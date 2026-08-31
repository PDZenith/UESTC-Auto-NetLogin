import argparse
import ipaddress
import msvcrt
import os
import select
import socket
import socketserver
import sys
import threading
import time
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

import requests
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service


BASE_DIR = Path(__file__).resolve().parent
DRIVER_PATH = BASE_DIR / "webdriver" / "chromedriver-win64" / "chromedriver.exe"
BINARY_PATH = BASE_DIR / "webdriver" / "chrome-headless-shell-win64" / "chrome-headless-shell.exe"
CACHE_FILE = BASE_DIR / "state" / "last_known_ip.txt"
LEGACY_CACHE_FILE = BASE_DIR / "last_known_ip.txt"
LOCK_FILE = BASE_DIR / ".netlogin.lock"

CONNECTIVITY_PROBES = (
    ("http://www.msftconnecttest.com/connecttest.txt", 200, "Microsoft Connect Test"),
    ("http://connect.rom.miui.com/generate_204", 204, None),
)
WIFI_IP = "10.253.0.213"
WIRED_IP = "10.253.0.237"
WIFI_DOMAIN = "wifi.uestc.edu.cn"
WIRED_DOMAIN = "aaa.uestc.edu.cn"
WIFI_PORTAL_PATH = "/srun_portal_pc?ac_id=0&theme=pro"
WIRED_PORTAL_PATH = "/srun_portal_pc?ac_id=1&theme=pro"
FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")
LOGIN_BUTTON_LOCATORS = (
    (By.ID, "login-account"),
    (By.CSS_SELECTOR, '.login-domain[mode="@dx-uestc"]'),
)


class ExitCode(IntEnum):
    OK = 0
    CONFIG_ERROR = 10
    BROWSER_ERROR = 20
    NO_COMPATIBLE_PORTAL = 30
    CAPTCHA_REQUIRED = 40
    CREDENTIAL_REJECTED = 41
    LOGIN_NOT_RESTORED = 42
    UNEXPECTED_ERROR = 50


class ConfigError(RuntimeError):
    pass


class PortalRouteUnavailable(RuntimeError):
    pass


@dataclass
class RuntimeConfig:
    connectivity_probes: tuple[tuple[str, int, Optional[str]], ...] = CONNECTIVITY_PROBES
    connectivity_timeout: float = 3.0
    preflight_attempts: int = 2
    preflight_interval_seconds: float = 2.0
    portal_wait_seconds: float = 10.0
    portal_poll_seconds: float = 0.25
    verify_attempts: int = 9
    verify_interval_seconds: float = 5.0
    probe_attempts: int = 1
    retry_delays: tuple[float, ...] = (5.0, 15.0)
    page_load_timeout: float = 15.0
    source_probe_timeout: float = 3.0
    preferred_portal_mode: str = "wired"
    cache_file: Path = CACHE_FILE
    legacy_cache_file: Path = LEGACY_CACHE_FILE
    portal_urls: Optional[tuple[str, ...]] = None


def log(event: str, **fields: object) -> None:
    safe_fields = " ".join(f"{key}={value}" for key, value in fields.items())
    suffix = f" {safe_fields}" if safe_fields else ""
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {event}{suffix}", flush=True)


def disable_environment_proxies() -> None:
    for name in (
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
    ):
        os.environ[name] = ""
    os.environ["no_proxy"] = "*"
    os.environ["NO_PROXY"] = "*"


class InstanceLock:
    def __init__(self, path: Path = LOCK_FILE):
        self.path = path
        self.handle = None
        self.acquired = False

    def __enter__(self) -> "InstanceLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        self.handle.seek(0, os.SEEK_END)
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            self.acquired = True
        except OSError:
            self.acquired = False
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.handle is None:
            return
        if self.acquired:
            self.handle.seek(0)
            try:
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        self.handle.close()


def create_http_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    return session


def check_internet(session: requests.Session, config: RuntimeConfig) -> bool:
    for url, expected_status, expected_body in config.connectivity_probes:
        try:
            response = session.get(
                url,
                timeout=config.connectivity_timeout,
                allow_redirects=True,
            )
        except requests.RequestException:
            continue
        if response.status_code != expected_status:
            continue
        if expected_body is None or response.text.strip() == expected_body:
            return True
    return False


def confirm_internet(
    session: requests.Session,
    config: RuntimeConfig,
    sleeper: Callable[[float], None],
) -> bool:
    for attempt in range(config.preflight_attempts):
        if check_internet(session, config):
            return True
        if attempt < config.preflight_attempts - 1:
            log("connectivity_recheck", attempt=attempt + 1, total=config.preflight_attempts)
            sleeper(config.preflight_interval_seconds)
    return False


def load_credentials() -> tuple[str, str]:
    try:
        from config import PASSWORD, USER_ID
    except (ImportError, AttributeError) as exc:
        raise ConfigError("config.py is missing USER_ID or PASSWORD") from exc
    if not isinstance(USER_ID, str) or not USER_ID.strip():
        raise ConfigError("USER_ID is empty or invalid")
    if not isinstance(PASSWORD, str) or not PASSWORD:
        raise ConfigError("PASSWORD is empty or invalid")
    return USER_ID, PASSWORD


def is_usable_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if address.version != 4 or address in FAKE_IP_NETWORK:
        return False
    return not (address.is_loopback or address.is_multicast or address.is_unspecified)


def read_cached_ip(path: Path) -> Optional[str]:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value if is_usable_ip(value) else None


def write_cached_ip(path: Path, value: str) -> bool:
    if not is_usable_ip(value):
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
        return True
    except OSError as exc:
        log("cache_write_failed", error=type(exc).__name__)
        return False


def resolve_real_ipv4(domain: str) -> Optional[str]:
    try:
        value = socket.gethostbyname(domain)
    except OSError:
        return None
    return value if is_usable_ip(value) else None


def build_portal_urls(config: RuntimeConfig) -> list[str]:
    if config.portal_urls is not None:
        return list(dict.fromkeys(config.portal_urls))

    def portal_url(value: str, path: Optional[str] = None) -> str:
        known_path = {
            WIFI_IP: WIFI_PORTAL_PATH,
            WIRED_IP: WIRED_PORTAL_PATH,
        }.get(value)
        return f"http://{value}{path or known_path or '/'}"

    endpoints = {
        "wired": (WIRED_IP, WIRED_DOMAIN, WIRED_PORTAL_PATH),
        "wifi": (WIFI_IP, WIFI_DOMAIN, WIFI_PORTAL_PATH),
    }
    mode_order = (
        ("wired", "wifi")
        if config.preferred_portal_mode.lower() == "wired"
        else ("wifi", "wired")
    )

    urls = [
        portal_url(endpoints[mode][0], endpoints[mode][2]) for mode in mode_order
    ]

    cached = read_cached_ip(config.cache_file) or read_cached_ip(config.legacy_cache_file)
    if cached:
        urls.append(portal_url(cached))

    for mode in mode_order:
        _, domain, path = endpoints[mode]
        resolved = resolve_real_ipv4(domain)
        if resolved:
            urls.append(portal_url(resolved, path))
    return list(dict.fromkeys(urls))


def validate_browser_resources(
    binary_path: Path = BINARY_PATH, driver_path: Path = DRIVER_PATH
) -> Optional[str]:
    missing = [str(path) for path in (binary_path, driver_path) if not path.is_file()]
    return ", ".join(missing) if missing else None


def local_ipv4_candidates() -> list[str]:
    try:
        records = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return []
    candidates = []
    for record in records:
        value = record[4][0]
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            continue
        if (
            address.version != 4
            or address in FAKE_IP_NETWORK
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_unspecified
        ):
            continue
        candidates.append(value)
    return list(dict.fromkeys(candidates))


def probe_portal_from_source(source_ip: str, host: str, timeout: float) -> bool:
    connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    connection.settimeout(timeout)
    try:
        connection.bind((source_ip, 0))
        connection.connect((host, 80))
        connection.sendall(
            f"GET / HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode(
                "ascii"
            )
        )
        response = connection.recv(4096)
        return response.startswith(b"HTTP/")
    except OSError:
        return False
    finally:
        connection.close()


def select_portal_source_ip(
    urls: list[str],
    timeout: float,
    *,
    candidates: Optional[list[str]] = None,
    probe: Callable[[str, str, float], bool] = probe_portal_from_source,
) -> Optional[str]:
    source_candidates = candidates if candidates is not None else local_ipv4_candidates()
    usable_sources = []
    for value in dict.fromkeys(source_candidates):
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            continue
        if (
            address.version == 4
            and address not in FAKE_IP_NETWORK
            and not address.is_loopback
            and not address.is_link_local
            and not address.is_multicast
            and not address.is_unspecified
        ):
            usable_sources.append(value)
    usable_sources.sort(key=lambda value: not ipaddress.ip_address(value).is_global)

    hosts = []
    for url in urls:
        host = urlparse(url).hostname or ""
        if is_usable_ip(host):
            hosts.append(host)
    for source_ip in usable_sources:
        for host in dict.fromkeys(hosts):
            if probe(source_ip, host, timeout):
                return source_ip
    return None


class _PortalProxyServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


class _PortalProxyHandler(socketserver.BaseRequestHandler):
    max_header_bytes = 64 * 1024

    def _send_error(self, status: int, reason: str) -> None:
        try:
            body = f"{status} {reason}\n".encode("ascii")
            self.request.sendall(
                f"HTTP/1.1 {status} {reason}\r\n"
                f"Content-Length: {len(body)}\r\n"
                "Connection: close\r\n\r\n".encode("ascii")
                + body
            )
        except OSError:
            pass

    def _relay(self, upstream: socket.socket) -> None:
        sockets = (self.request, upstream)
        while True:
            readable, _, _ = select.select(sockets, (), (), self.server.io_timeout)
            if not readable:
                return
            for source in readable:
                try:
                    data = source.recv(65536)
                except OSError:
                    return
                if not data:
                    return
                destination = upstream if source is self.request else self.request
                try:
                    destination.sendall(data)
                except OSError:
                    return

    def handle(self) -> None:
        request_data = b""
        while b"\r\n\r\n" not in request_data:
            chunk = self.request.recv(8192)
            if not chunk:
                return
            request_data += chunk
            if len(request_data) > self.max_header_bytes:
                self._send_error(431, "Request Header Fields Too Large")
                return

        header_data, body = request_data.split(b"\r\n\r\n", 1)
        header_lines = header_data.split(b"\r\n")
        try:
            method, target, version = header_lines[0].decode("ascii").split(" ", 2)
        except (UnicodeDecodeError, ValueError):
            self._send_error(400, "Bad Request")
            return

        if method.upper() == "CONNECT":
            host_text, separator, port_text = target.rpartition(":")
            if not separator:
                self._send_error(400, "Bad Request")
                return
            host = host_text.lower()
            try:
                port = int(port_text)
            except ValueError:
                self._send_error(400, "Bad Request")
                return
            outbound_data = body
        else:
            parsed = urlparse(target)
            host = (parsed.hostname or "").lower()
            try:
                port = parsed.port or (443 if parsed.scheme == "https" else 80)
            except ValueError:
                self._send_error(400, "Bad Request")
                return
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            filtered_headers = [
                line
                for line in header_lines[1:]
                if not line.lower().startswith((b"proxy-connection:", b"connection:"))
            ]
            outbound_data = (
                f"{method} {path} {version}\r\n".encode("ascii")
                + b"\r\n".join(filtered_headers)
                + b"\r\nConnection: close\r\n\r\n"
                + body
            )

        if host not in self.server.allowed_hosts or port not in self.server.allowed_ports:
            log("proxy_target_denied", host=host or "missing", port=port)
            self._send_error(403, "Forbidden")
            return

        upstream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        upstream.settimeout(self.server.connect_timeout)
        try:
            upstream.bind((self.server.source_ip, 0))
            upstream.connect((host, port))
            if method.upper() == "CONNECT":
                self.request.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            if outbound_data:
                upstream.sendall(outbound_data)
            upstream.settimeout(None)
            self._relay(upstream)
        except OSError as exc:
            log(
                "proxy_upstream_failed",
                host=host or "missing",
                port=port,
                error=type(exc).__name__,
            )
            self._send_error(502, "Bad Gateway")
        finally:
            upstream.close()


class SourceBoundPortalProxy:
    def __init__(
        self,
        source_ip: str,
        allowed_hosts: set[str],
        allowed_ports: set[int] | None = None,
        *,
        connect_timeout: float = 10.0,
        io_timeout: float = 20.0,
    ):
        self.source_ip = source_ip
        self.allowed_hosts = {host.lower() for host in allowed_hosts}
        self.allowed_ports = allowed_ports or {80, 443, 8800}
        self.connect_timeout = connect_timeout
        self.io_timeout = io_timeout
        self._server = None
        self._thread = None

    @property
    def url(self) -> str:
        if self._server is None:
            raise RuntimeError("portal proxy has not been started")
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def start(self) -> "SourceBoundPortalProxy":
        if self._server is not None:
            return self
        server = _PortalProxyServer(("127.0.0.1", 0), _PortalProxyHandler)
        server.source_ip = self.source_ip
        server.allowed_hosts = self.allowed_hosts
        server.allowed_ports = self.allowed_ports
        server.connect_timeout = self.connect_timeout
        server.io_timeout = self.io_timeout
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self._server = server
        self._thread = thread
        return self

    def stop(self) -> None:
        if self._server is None:
            return
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        server.shutdown()
        server.server_close()
        if thread is not None:
            thread.join(timeout=2)

    def __enter__(self) -> "SourceBoundPortalProxy":
        return self.start()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()


def build_chrome_options(proxy_url: Optional[str] = None) -> Options:
    chrome_options = Options()
    chrome_options.binary_location = str(BINARY_PATH)
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    if proxy_url:
        chrome_options.add_argument(f"--proxy-server={proxy_url}")
    chrome_options.add_argument("--ignore-certificate-errors")
    chrome_options.add_argument("--window-size=1920,1080")
    return chrome_options


class ProxyManagedDriver:
    def __init__(self, driver, proxy: SourceBoundPortalProxy):
        self._driver = driver
        self._proxy = proxy

    def __getattr__(self, name):
        return getattr(self._driver, name)

    def quit(self) -> None:
        try:
            self._driver.quit()
        finally:
            self._proxy.stop()


def create_driver(config: RuntimeConfig):
    urls = build_portal_urls(config)
    source_ip = select_portal_source_ip(urls, config.source_probe_timeout)
    if source_ip is None:
        raise PortalRouteUnavailable("no source-bound route reached a campus portal")
    allowed_hosts = {
        host for url in urls if (host := (urlparse(url).hostname or "")) and is_usable_ip(host)
    }
    proxy = SourceBoundPortalProxy(
        source_ip=source_ip,
        allowed_hosts=allowed_hosts,
        connect_timeout=config.page_load_timeout,
        io_timeout=config.page_load_timeout,
    ).start()
    log("source_bound_proxy_started", source_ip=source_ip, listen=proxy.url)
    chrome_options = build_chrome_options(proxy.url)
    service = Service(executable_path=str(DRIVER_PATH))
    try:
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.set_page_load_timeout(config.page_load_timeout)
        return ProxyManagedDriver(driver, proxy)
    except Exception:
        proxy.stop()
        raise


def visible_element(driver, element_id: str):
    try:
        elements = driver.find_elements(By.ID, element_id)
    except WebDriverException:
        return None
    for element in elements:
        try:
            if element.is_displayed():
                return element
        except WebDriverException:
            continue
    return None


def visible_login_button(driver):
    for by, value in LOGIN_BUTTON_LOCATORS:
        try:
            elements = driver.find_elements(by, value)
        except WebDriverException:
            continue
        for element in elements:
            try:
                if element.is_displayed():
                    return element
            except WebDriverException:
                continue
    return None


def portal_diagnostics(driver) -> dict[str, str]:
    try:
        parsed = urlparse(getattr(driver, "current_url", ""))
        current_url = (
            f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if parsed.scheme and parsed.netloc
            else "unavailable"
        )
    except Exception:
        current_url = "unavailable"

    try:
        ready_state = str(driver.execute_script("return document.readyState"))
    except Exception:
        ready_state = "unavailable"

    def element_state(by: str, value: str) -> str:
        try:
            elements = driver.find_elements(by, value)
        except Exception:
            return "error"
        if not elements:
            return "missing"
        try:
            return "visible" if elements[0].is_displayed() else "hidden"
        except Exception:
            return "error"

    return {
        "current_url": current_url,
        "ready_state": ready_state,
        "username": element_state(By.ID, "username"),
        "password": element_state(By.ID, "password"),
        "login_button": element_state(By.ID, "login-account"),
        "campus_login_button": element_state(
            By.CSS_SELECTOR, '.login-domain[mode="@dx-uestc"]'
        ),
        "logout": element_state(By.ID, "logout"),
        "captcha": element_state(By.ID, "captcha"),
    }


def wait_for_compatible_portal(
    driver,
    url: str,
    config: RuntimeConfig,
    sleeper: Callable[[float], None],
):
    try:
        driver.get(url)
    except WebDriverException as exc:
        log("portal_open_failed", url=url, error=type(exc).__name__)
        return None

    deadline = time.monotonic() + config.portal_wait_seconds
    while True:
        username = visible_element(driver, "username")
        password = visible_element(driver, "password")
        login_button = visible_login_button(driver)
        if username is not None and password is not None and login_button is not None:
            return "login", (username, password, login_button)
        if visible_element(driver, "logout") is not None:
            return "authenticated", None
        if time.monotonic() >= deadline:
            log("portal_incompatible", url=url, **portal_diagnostics(driver))
            return None
        sleeper(config.portal_poll_seconds)


def select_portal(
    driver,
    urls: list[str],
    config: RuntimeConfig,
    sleeper: Callable[[float], None],
    *,
    cache_selection: bool = True,
):
    for url in urls:
        fields = wait_for_compatible_portal(driver, url, config, sleeper)
        if fields is not None:
            host = urlparse(url).hostname or ""
            if cache_selection and is_usable_ip(host):
                write_cached_ip(config.cache_file, host)
            log("portal_selected", url=url, state=fields[0])
            return url, fields
    return None


def visible_auth_error(driver) -> Optional[str]:
    keywords = ("密码", "错误", "失败", "不存在", "欠费", "停机", "锁定", "拒绝")
    for element_id in ("notice-title", "login_msg", "error-message"):
        element = visible_element(driver, element_id)
        if element is None:
            continue
        try:
            text = " ".join(element.text.split())
        except WebDriverException:
            continue
        if text and any(keyword in text for keyword in keywords):
            return text[:120]
    return None


def run_login(
    *,
    probe_only: bool = False,
    config: Optional[RuntimeConfig] = None,
    session=None,
    driver_factory: Callable[[RuntimeConfig], object] = create_driver,
    sleeper: Callable[[float], None] = time.sleep,
    credentials_loader: Callable[[], tuple[str, str]] = load_credentials,
) -> int:
    config = config or RuntimeConfig()
    session = session or create_http_session()
    online = confirm_internet(session, config, sleeper)
    log("connectivity_checked", online=online, probe_only=probe_only)

    if online and not probe_only:
        log("already_online")
        return int(ExitCode.OK)

    missing = validate_browser_resources()
    if missing:
        log("browser_resources_missing", paths=missing)
        return int(ExitCode.BROWSER_ERROR)

    credentials: Optional[tuple[str, str]] = None
    if not probe_only:
        try:
            credentials = credentials_loader()
        except ConfigError as exc:
            log("configuration_error", detail=str(exc))
            return int(ExitCode.CONFIG_ERROR)

    driver = None
    try:
        driver = driver_factory(config)
        urls = build_portal_urls(config)
        selection = None
        for attempt in range(config.probe_attempts):
            log("portal_probe_attempt", attempt=attempt + 1, total=config.probe_attempts)
            selection = select_portal(
                driver,
                urls,
                config,
                sleeper,
                cache_selection=not probe_only,
            )
            if selection is not None:
                break
            if attempt < config.probe_attempts - 1:
                delay = config.retry_delays[min(attempt, len(config.retry_delays) - 1)]
                log("portal_probe_retry", delay_seconds=delay)
                sleeper(delay)

        if selection is None:
            log("no_compatible_portal")
            return int(ExitCode.NO_COMPATIBLE_PORTAL)

        url, (portal_state, portal_fields) = selection
        if probe_only:
            log("probe_succeeded", online=online, portal=url, portal_state=portal_state)
            return int(ExitCode.OK)

        if portal_state == "authenticated":
            log("portal_authenticated_but_connectivity_unavailable", portal=url)
            return int(ExitCode.LOGIN_NOT_RESTORED)

        assert portal_fields is not None
        username_input, password_input, login_button = portal_fields

        captcha = visible_element(driver, "captcha")
        if captcha is not None:
            log("captcha_required", portal=url)
            return int(ExitCode.CAPTCHA_REQUIRED)

        assert credentials is not None
        user_id, password = credentials
        username_input.clear()
        username_input.send_keys(user_id)
        password_input.clear()
        password_input.send_keys(password)
        login_button.click()
        log("login_submitted", portal=url)

        for attempt in range(config.verify_attempts):
            if check_internet(session, config):
                log("internet_restored", verify_attempt=attempt + 1)
                return int(ExitCode.OK)
            rejection = visible_auth_error(driver)
            if rejection:
                log("credentials_rejected", detail=rejection)
                return int(ExitCode.CREDENTIAL_REJECTED)
            if attempt < config.verify_attempts - 1:
                sleeper(config.verify_interval_seconds)

        log("login_not_restored", verify_attempts=config.verify_attempts)
        return int(ExitCode.LOGIN_NOT_RESTORED)
    except PortalRouteUnavailable as exc:
        log("portal_route_unavailable", detail=str(exc))
        return int(ExitCode.NO_COMPATIBLE_PORTAL)
    except WebDriverException as exc:
        log("browser_error", error=type(exc).__name__)
        return int(ExitCode.BROWSER_ERROR)
    except Exception as exc:
        log("unexpected_error", error=type(exc).__name__)
        return int(ExitCode.UNEXPECTED_ERROR)
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


def parse_args(argv: Optional[list[str]] = None):
    parser = argparse.ArgumentParser(description="UESTC unattended network login watchdog")
    parser.add_argument(
        "--probe-only",
        action="store_true",
        help="Check connectivity and portal compatibility without submitting credentials.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    disable_environment_proxies()
    args = parse_args(argv)
    log("script_started", probe_only=args.probe_only)
    try:
        with InstanceLock() as lock:
            if not lock.acquired:
                log("already_running")
                return int(ExitCode.OK)
            result = run_login(probe_only=args.probe_only)
    except Exception as exc:
        log("lock_or_startup_error", error=type(exc).__name__)
        result = int(ExitCode.UNEXPECTED_ERROR)
    log("script_finished", exit_code=result)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
