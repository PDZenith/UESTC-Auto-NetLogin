from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading

import pytest
import requests
from selenium.common.exceptions import WebDriverException

import my_login


class FakeResponse:
    def __init__(self, online: bool):
        self.status_code = 200
        self.text = "Microsoft Connect Test" if online else "captive portal"


class FakeSession:
    def __init__(self, states):
        self.states = deque(states)
        self.last = states[-1] if states else False
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        if self.states:
            self.last = self.states.popleft()
        return FakeResponse(self.last)


class RoutedSession:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        status_code, text = self.responses[url]
        response = FakeResponse(False)
        response.status_code = status_code
        response.text = text
        return response


class FakeElement:
    def __init__(self, *, displayed=True, text=""):
        self.displayed = displayed
        self.text = text
        self.value = None
        self.clicked = False

    def is_displayed(self):
        return self.displayed

    def clear(self):
        self.value = ""

    def send_keys(self, value):
        self.value = value

    def click(self):
        self.clicked = True


class FakeDriver:
    def __init__(self, pages):
        self.pages = pages
        self.current = None
        self.visited = []
        self.quit_called = False

    def get(self, url):
        self.visited.append(url)
        page = self.pages.get(url)
        if page == "error":
            raise WebDriverException("simulated connection failure")
        self.current = page or {}

    def find_elements(self, by, element_id):
        value = self.current.get(element_id) if isinstance(self.current, dict) else None
        return [value] if value is not None else []

    def quit(self):
        self.quit_called = True


class DiagnosticDriver(FakeDriver):
    current_url = "http://10.253.0.213/srun_portal_pc?secret=not-logged"

    def execute_script(self, script):
        if "document.readyState" in script:
            return "complete"
        raise AssertionError(f"unexpected diagnostic script: {script}")


def login_page(*, captcha=False, error_text=""):
    page = {
        "username": FakeElement(),
        "password": FakeElement(),
        "login-account": FakeElement(),
    }
    if captcha:
        page["captcha"] = FakeElement(displayed=True)
    if error_text:
        page["notice-title"] = FakeElement(displayed=True, text=error_text)
    return page


def domain_login_page(*, captcha=False, error_text=""):
    page = {
        "username": FakeElement(),
        "password": FakeElement(),
        '.login-domain[mode="@dx-uestc"]': FakeElement(),
    }
    if captcha:
        page["captcha"] = FakeElement(displayed=True)
    if error_text:
        page["notice-title"] = FakeElement(displayed=True, text=error_text)
    return page


def runtime_config(tmp_path: Path, urls=("http://10.253.0.237/", "http://10.253.0.213/")):
    return my_login.RuntimeConfig(
        connectivity_probes=(("http://test/connecttest.txt", 200, "Microsoft Connect Test"),),
        connectivity_timeout=0.01,
        preflight_attempts=1,
        preflight_interval_seconds=0,
        portal_wait_seconds=0,
        portal_poll_seconds=0,
        verify_attempts=1,
        verify_interval_seconds=0,
        probe_attempts=1,
        retry_delays=(0,),
        page_load_timeout=1,
        cache_file=tmp_path / "last_known_ip.txt",
        legacy_cache_file=tmp_path / "legacy_last_known_ip.txt",
        portal_urls=urls,
    )


def test_already_online_skips_browser_and_credentials(tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("offline-only dependency was used")

    code = my_login.run_login(
        config=runtime_config(tmp_path),
        session=FakeSession([True]),
        driver_factory=forbidden,
        credentials_loader=forbidden,
    )
    assert code == my_login.ExitCode.OK


def test_transient_connectivity_failure_is_rechecked_before_login(tmp_path):
    config = runtime_config(tmp_path)
    config.preflight_attempts = 3
    session = FakeSession([False, True])

    def forbidden(*args, **kwargs):
        raise AssertionError("login path was entered after a transient failure")

    code = my_login.run_login(
        config=config,
        session=session,
        driver_factory=forbidden,
        credentials_loader=forbidden,
        sleeper=lambda seconds: None,
    )
    assert code == my_login.ExitCode.OK
    assert session.calls == 2


def test_default_offline_preflight_uses_two_short_rounds():
    config = my_login.RuntimeConfig()
    session = FakeSession([False, False, False, False])
    sleeps = []

    online = my_login.confirm_internet(session, config, sleeps.append)

    assert not online
    assert config.connectivity_timeout == 3.0
    assert session.calls == 4
    assert sleeps == [2.0]


def test_secondary_204_probe_prevents_login_when_primary_is_captive(tmp_path):
    config = runtime_config(tmp_path)
    config.connectivity_probes = (
        ("http://primary/check", 200, "Microsoft Connect Test"),
        ("http://secondary/generate_204", 204, None),
    )
    session = RoutedSession(
        {
            "http://primary/check": (200, "captive portal"),
            "http://secondary/generate_204": (204, ""),
        }
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("login path was entered while the secondary probe was online")

    code = my_login.run_login(
        config=config,
        session=session,
        driver_factory=forbidden,
        credentials_loader=forbidden,
    )
    assert code == my_login.ExitCode.OK
    assert session.calls == ["http://primary/check", "http://secondary/generate_204"]


def test_all_two_endpoint_checks_must_fail_for_three_rounds_before_portal(tmp_path):
    config = runtime_config(tmp_path, ("http://10.253.0.213/",))
    config.connectivity_probes = (
        ("http://primary/check", 200, "Microsoft Connect Test"),
        ("http://secondary/generate_204", 204, None),
    )
    config.preflight_attempts = 3
    session = FakeSession([False] * 6)
    driver_started = []

    def driver_factory(_config):
        driver_started.append(True)
        return FakeDriver({"http://10.253.0.213/": {}})

    code = my_login.run_login(
        config=config,
        session=session,
        driver_factory=driver_factory,
        credentials_loader=lambda: ("user", "secret"),
        sleeper=lambda seconds: None,
    )
    assert code == my_login.ExitCode.NO_COMPATIBLE_PORTAL
    assert session.calls == 6
    assert driver_started == [True]


def test_probe_only_checks_portal_without_credentials(tmp_path):
    wifi = login_page()
    driver = FakeDriver({"http://10.253.0.213/": wifi})
    config = runtime_config(tmp_path, ("http://10.253.0.213/",))

    def forbidden():
        raise AssertionError("credentials were read")

    code = my_login.run_login(
        probe_only=True,
        config=config,
        session=FakeSession([True]),
        driver_factory=lambda config: driver,
        credentials_loader=forbidden,
    )
    assert code == my_login.ExitCode.OK
    assert not wifi["login-account"].clicked
    assert driver.quit_called
    assert not config.cache_file.exists()


def test_probe_only_accepts_portal_authenticated_state(tmp_path):
    authenticated = {"logout": FakeElement(displayed=True)}
    driver = FakeDriver({"http://10.253.0.213/": authenticated})
    code = my_login.run_login(
        probe_only=True,
        config=runtime_config(tmp_path, ("http://10.253.0.213/",)),
        session=FakeSession([True]),
        driver_factory=lambda config: driver,
        credentials_loader=lambda: (_ for _ in ()).throw(AssertionError()),
    )
    assert code == my_login.ExitCode.OK


def test_authenticated_portal_never_logs_out_or_resubmits_when_public_check_fails(tmp_path):
    logout = FakeElement(displayed=True)
    driver = FakeDriver({"http://10.253.0.213/": {"logout": logout}})
    code = my_login.run_login(
        config=runtime_config(tmp_path, ("http://10.253.0.213/",)),
        session=FakeSession([False]),
        driver_factory=lambda config: driver,
        credentials_loader=lambda: ("user", "secret"),
    )
    assert code == my_login.ExitCode.LOGIN_NOT_RESTORED
    assert not logout.clicked


def test_incompatible_wired_falls_back_to_wifi_and_restores_internet(tmp_path):
    wired = {"username": FakeElement(), "password": FakeElement()}
    wifi = login_page()
    driver = FakeDriver(
        {
            "http://10.253.0.237/": wired,
            "http://10.253.0.213/": wifi,
        }
    )
    code = my_login.run_login(
        config=runtime_config(tmp_path),
        session=FakeSession([False, True]),
        driver_factory=lambda config: driver,
        credentials_loader=lambda: ("test-user", "test-password"),
    )
    assert code == my_login.ExitCode.OK
    assert driver.visited == ["http://10.253.0.237/", "http://10.253.0.213/"]
    assert wifi["username"].value == "test-user"
    assert wifi["password"].value == "test-password"
    assert wifi["login-account"].clicked
    assert (tmp_path / "last_known_ip.txt").read_text() == "10.253.0.213"


def test_default_wired_flow_submits_to_wired_portal_before_wifi(tmp_path, monkeypatch):
    wired_url = "http://10.253.0.237/srun_portal_pc?ac_id=1&theme=pro"
    wifi_url = "http://10.253.0.213/srun_portal_pc?ac_id=0&theme=pro"
    wired = login_page()
    driver = FakeDriver({wired_url: wired, wifi_url: login_page()})
    config = runtime_config(tmp_path)
    config.portal_urls = None
    monkeypatch.setattr(my_login, "resolve_real_ipv4", lambda _domain: None)

    code = my_login.run_login(
        config=config,
        session=FakeSession([False, True]),
        driver_factory=lambda _config: driver,
        credentials_loader=lambda: ("simulated-user", "simulated-password"),
        sleeper=lambda _seconds: None,
    )

    assert code == my_login.ExitCode.OK
    assert driver.visited == [wired_url]
    assert wired["username"].value == "simulated-user"
    assert wired["password"].value == "simulated-password"
    assert wired["login-account"].clicked
    assert config.cache_file.read_text(encoding="utf-8") == "10.253.0.237"


def test_wired_domain_login_button_is_accepted_and_clicked(tmp_path):
    page = domain_login_page()
    button = page['.login-domain[mode="@dx-uestc"]']

    code = my_login.run_login(
        config=runtime_config(tmp_path, ("http://10.253.0.237/",)),
        session=FakeSession([False, True]),
        driver_factory=lambda config: FakeDriver(
            {"http://10.253.0.237/": page}
        ),
        credentials_loader=lambda: ("student-id", "secret"),
    )

    assert code == my_login.ExitCode.OK
    assert button.clicked
    assert page["username"].value == "student-id"
    assert page["password"].value == "secret"


def test_login_submit_without_connectivity_returns_42(tmp_path):
    page = login_page()
    code = my_login.run_login(
        config=runtime_config(tmp_path, ("http://10.253.0.213/",)),
        session=FakeSession([False, False]),
        driver_factory=lambda config: FakeDriver({"http://10.253.0.213/": page}),
        credentials_loader=lambda: ("user", "secret"),
    )
    assert code == my_login.ExitCode.LOGIN_NOT_RESTORED
    assert page["login-account"].clicked


def test_captcha_stops_before_submit(tmp_path):
    page = login_page(captcha=True)
    code = my_login.run_login(
        config=runtime_config(tmp_path, ("http://10.253.0.213/",)),
        session=FakeSession([False]),
        driver_factory=lambda config: FakeDriver({"http://10.253.0.213/": page}),
        credentials_loader=lambda: ("user", "secret"),
    )
    assert code == my_login.ExitCode.CAPTCHA_REQUIRED
    assert not page["login-account"].clicked


def test_explicit_credential_error_is_not_retried_or_logged_with_password(tmp_path, capsys):
    page = login_page(error_text="密码错误")
    code = my_login.run_login(
        config=runtime_config(tmp_path, ("http://10.253.0.213/",)),
        session=FakeSession([False, False]),
        driver_factory=lambda config: FakeDriver({"http://10.253.0.213/": page}),
        credentials_loader=lambda: ("student-id", "TOP-SECRET-PASSWORD"),
    )
    output = capsys.readouterr().out
    assert code == my_login.ExitCode.CREDENTIAL_REJECTED
    assert "TOP-SECRET-PASSWORD" not in output


def test_no_compatible_or_reachable_portal_returns_30(tmp_path):
    pages = {
        "http://10.253.0.237/": "error",
        "http://10.253.0.213/": {},
    }
    code = my_login.run_login(
        config=runtime_config(tmp_path),
        session=FakeSession([False]),
        driver_factory=lambda config: FakeDriver(pages),
        credentials_loader=lambda: ("user", "secret"),
    )
    assert code == my_login.ExitCode.NO_COMPATIBLE_PORTAL


def test_portal_diagnostics_report_structure_without_query_or_page_source():
    hidden_login = FakeElement(displayed=False)
    driver = DiagnosticDriver(
        {
            "http://portal/": {
                "username": FakeElement(),
                "password": FakeElement(),
                "login-account": hidden_login,
            }
        }
    )
    driver.get("http://portal/")

    details = my_login.portal_diagnostics(driver)

    assert details == {
        "current_url": "http://10.253.0.213/srun_portal_pc",
        "ready_state": "complete",
        "username": "visible",
        "password": "visible",
        "login_button": "hidden",
        "campus_login_button": "missing",
        "logout": "missing",
        "captcha": "missing",
    }


def test_default_portal_probe_exits_after_one_cycle_for_next_scheduled_run(tmp_path):
    urls = ("http://10.253.0.237/", "http://10.253.0.213/")
    config = runtime_config(tmp_path, urls)
    config.probe_attempts = my_login.RuntimeConfig().probe_attempts
    driver = FakeDriver({url: {} for url in urls})

    code = my_login.run_login(
        config=config,
        session=FakeSession([False]),
        driver_factory=lambda _config: driver,
        credentials_loader=lambda: ("user", "secret"),
        sleeper=lambda _seconds: None,
    )

    assert code == my_login.ExitCode.NO_COMPATIBLE_PORTAL
    assert driver.visited == list(urls)


def test_invalid_configuration_returns_10_before_browser_start(tmp_path):
    def invalid_credentials():
        raise my_login.ConfigError("simulated invalid config")

    code = my_login.run_login(
        config=runtime_config(tmp_path),
        session=FakeSession([False]),
        driver_factory=lambda config: (_ for _ in ()).throw(AssertionError()),
        credentials_loader=invalid_credentials,
    )
    assert code == my_login.ExitCode.CONFIG_ERROR


def test_fake_ip_cache_is_rejected_and_never_written(tmp_path):
    cache = tmp_path / "last_known_ip.txt"
    cache.write_text("198.18.0.138", encoding="utf-8")
    assert my_login.read_cached_ip(cache) is None
    assert not my_login.write_cached_ip(cache, "198.18.0.139")
    assert cache.read_text(encoding="utf-8") == "198.18.0.138"


def test_known_portals_use_direct_form_urls_instead_of_meta_refresh(tmp_path, monkeypatch):
    config = my_login.RuntimeConfig(
        cache_file=tmp_path / "last_known_ip.txt",
        legacy_cache_file=tmp_path / "legacy_last_known_ip.txt",
    )
    config.cache_file.write_text("10.253.0.213", encoding="utf-8")
    monkeypatch.setattr(my_login, "resolve_real_ipv4", lambda _domain: None)

    urls = my_login.build_portal_urls(config)

    assert urls[:2] == [
        "http://10.253.0.237/srun_portal_pc?ac_id=1&theme=pro",
        "http://10.253.0.213/srun_portal_pc?ac_id=0&theme=pro",
    ]
    assert "http://10.253.0.213/" not in urls
    assert "http://10.253.0.237/" not in urls


def test_wifi_mode_can_be_selected_explicitly(tmp_path, monkeypatch):
    config = my_login.RuntimeConfig(
        preferred_portal_mode="wifi",
        cache_file=tmp_path / "last_known_ip.txt",
        legacy_cache_file=tmp_path / "legacy_last_known_ip.txt",
    )
    monkeypatch.setattr(my_login, "resolve_real_ipv4", lambda _domain: None)

    urls = my_login.build_portal_urls(config)

    assert urls[:2] == [
        "http://10.253.0.213/srun_portal_pc?ac_id=0&theme=pro",
        "http://10.253.0.237/srun_portal_pc?ac_id=1&theme=pro",
    ]


def test_missing_browser_resource_is_reported(tmp_path):
    missing = my_login.validate_browser_resources(
        tmp_path / "missing-chrome.exe", tmp_path / "missing-driver.exe"
    )
    assert "missing-chrome.exe" in missing
    assert "missing-driver.exe" in missing


def test_file_lock_allows_only_one_holder(tmp_path):
    lock_path = tmp_path / "watchdog.lock"
    with my_login.InstanceLock(lock_path) as first:
        assert first.acquired
        with my_login.InstanceLock(lock_path) as second:
            assert not second.acquired
    with my_login.InstanceLock(lock_path) as third:
        assert third.acquired


def test_batch_uses_project_python_and_propagates_exit_code():
    content = (my_login.BASE_DIR / "run_login.bat").read_text(encoding="utf-8")
    assert ".venv\\Scripts\\python.exe" in content
    assert "%*" in content
    assert "exit /b %NETLOGIN_EXIT%" in content
    assert "D:\\Program Files\\Anaconda\\python.exe" not in content


def test_source_bound_proxy_uses_selected_local_ip_for_upstream_connection():
    class RecordingHandler(BaseHTTPRequestHandler):
        client_ip = None

        def do_GET(self):
            type(self).client_ip = self.client_address[0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"portal-ok")

        def log_message(self, format, *args):
            pass

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), RecordingHandler)
    upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    upstream_thread.start()
    upstream_port = upstream.server_address[1]

    try:
        with my_login.SourceBoundPortalProxy(
            source_ip="127.0.0.2",
            allowed_hosts={"127.0.0.1"},
            allowed_ports={upstream_port},
        ) as proxy:
            response = requests.get(
                f"http://127.0.0.1:{upstream_port}/portal",
                proxies={"http": proxy.url},
                timeout=2,
            )
        assert response.status_code == 200
        assert response.text == "portal-ok"
        assert RecordingHandler.client_ip == "127.0.0.2"
    finally:
        upstream.shutdown()
        upstream.server_close()


def test_source_bound_proxy_rejects_hosts_outside_portal_allowlist():
    with my_login.SourceBoundPortalProxy(
        source_ip="127.0.0.2",
        allowed_hosts={"10.253.0.213", "10.253.0.237"},
    ) as proxy:
        response = requests.get(
            "http://127.0.0.1/not-the-portal",
            proxies={"http": proxy.url},
            timeout=2,
        )
    assert response.status_code == 403


def test_source_bound_proxy_allows_only_required_portal_service_ports_by_default():
    proxy = my_login.SourceBoundPortalProxy(
        source_ip="127.0.0.2",
        allowed_hosts={"10.253.0.213", "10.253.0.237"},
    )
    assert proxy.allowed_ports == {80, 443, 8800}


def test_chrome_options_use_local_source_bound_proxy_without_global_bypass():
    options = my_login.build_chrome_options("http://127.0.0.1:43123")
    assert "--proxy-server=http://127.0.0.1:43123" in options.arguments
    assert "--no-proxy-server" not in options.arguments
    assert "--proxy-bypass-list=*" not in options.arguments


def test_portal_source_selection_rejects_tun_fake_ip_and_prefers_working_global_ip():
    probed = []

    def probe(source_ip, host, timeout):
        probed.append((source_ip, host))
        return source_ip == "211.83.106.230" and host == "10.253.0.213"

    selected = my_login.select_portal_source_ip(
        ["http://10.253.0.213/", "http://10.253.0.237/"],
        timeout=0.1,
        candidates=["198.18.0.1", "192.168.191.1", "211.83.106.230"],
        probe=probe,
    )
    assert selected == "211.83.106.230"
    assert all(source != "198.18.0.1" for source, _ in probed)
    assert probed[0] == ("211.83.106.230", "10.253.0.213")


def test_missing_source_bound_portal_route_returns_30_without_credentials(tmp_path):
    def unavailable_driver(_config):
        raise my_login.PortalRouteUnavailable("simulated TUN interception")

    def forbidden_credentials():
        raise AssertionError("credentials were read without a usable portal route")

    code = my_login.run_login(
        probe_only=True,
        config=runtime_config(tmp_path, ("http://10.253.0.213/",)),
        session=FakeSession([False]),
        driver_factory=unavailable_driver,
        credentials_loader=forbidden_credentials,
    )
    assert code == my_login.ExitCode.NO_COMPATIBLE_PORTAL


def test_driver_quit_also_closes_the_ephemeral_loopback_proxy(monkeypatch, tmp_path):
    created = {}

    class FakeChrome:
        def __init__(self, *, service, options):
            created["options"] = options
            self.quit_called = False

        def set_page_load_timeout(self, timeout):
            created["timeout"] = timeout

        def quit(self):
            self.quit_called = True

    monkeypatch.setattr(
        my_login, "build_portal_urls", lambda config: ["http://10.253.0.213/"]
    )
    monkeypatch.setattr(
        my_login, "select_portal_source_ip", lambda urls, timeout: "127.0.0.2"
    )
    monkeypatch.setattr(my_login.webdriver, "Chrome", FakeChrome)

    config = runtime_config(tmp_path, ("http://10.253.0.213/",))
    driver = my_login.create_driver(config)
    proxy_argument = next(
        value
        for value in created["options"].arguments
        if value.startswith("--proxy-server=")
    )
    proxy_url = proxy_argument.split("=", 1)[1]
    proxy_port = int(proxy_url.rsplit(":", 1)[1])

    driver.quit()

    assert driver._driver.quit_called
    with pytest.raises(OSError):
        __import__("socket").create_connection(("127.0.0.1", proxy_port), timeout=0.2)
