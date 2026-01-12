import os
import time
import socket
import sys
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

# 尝试导入配置
try:
    from config import USER_ID, PASSWORD
except ImportError:
    print("[Fatal] config.py not found! Please run setup.py first.")
    sys.exit(1)

# ================= 配置区域 =================
# 1. 强制禁用代理 (核心抗干扰)
os.environ['http_proxy'] = ''
os.environ['https_proxy'] = ''
os.environ['all_proxy'] = ''
os.environ['no_proxy'] = '*'

# 2. 路径配置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DRIVER_PATH = os.path.join(BASE_DIR, "webdriver", "chromedriver-win64", "chromedriver.exe")
BINARY_PATH = os.path.join(BASE_DIR, "webdriver", "chrome-headless-shell-win64", "chrome-headless-shell.exe")
CACHE_FILE = os.path.join(BASE_DIR, "last_known_ip.txt")
# ===========================================

class SmartIPManager:
    def __init__(self):
        # 1. 有线网真实 IP (aaa.uestc.edu.cn)
        self.wired_ip = "10.253.0.237"
        
        # 2. 无线网真实 IP (wifi.uestc.edu.cn)
        self.wifi_ip = "10.253.0.213"
        
        self.wired_domain = "aaa.uestc.edu.cn"
        self.wifi_domain = "wifi.uestc.edu.cn"

    def get_best_url(self):
        """
        决策优先级：缓存 -> 有线IP -> 无线IP -> 有线DNS -> 无线DNS
        """
        # 1. 读缓存
        cached_ip = self._read_cache()
        if cached_ip:
            print(f"[IP-Manager] Checking Cached IP: {cached_ip}")
            if self._check_port(cached_ip):
                print(f"[IP-Manager] Cache {cached_ip} is ALIVE.")
                return f"http://{cached_ip}/"

        # 2. 试有线 IP (绝大多数情况走这里)
        print(f"[IP-Manager] Checking Wired IP: {self.wired_ip}")
        if self._check_port(self.wired_ip):
            print("[IP-Manager] Wired IP is ALIVE.")
            self._write_cache(self.wired_ip)
            return f"http://{self.wired_ip}/"
            
        # 3. 试无线 IP (备用)
        print(f"[IP-Manager] Checking WiFi IP: {self.wifi_ip}")
        if self._check_port(self.wifi_ip):
            print("[IP-Manager] WiFi IP is ALIVE.")
            self._write_cache(self.wifi_ip)
            return f"http://{self.wifi_ip}/"

        # 4. 试有线 DNS (防止学校换IP)
        print("[IP-Manager] IPs unreachable. Trying Wired DNS...")
        ip = self._resolve(self.wired_domain)
        if ip and self._check_port(ip):
            self._write_cache(ip)
            return f"http://{ip}/"

        # 5. 试无线 DNS
        print("[IP-Manager] Wired DNS failed. Trying WiFi DNS...")
        ip = self._resolve(self.wifi_domain)
        if ip and self._check_port(ip):
            self._write_cache(ip)
            return f"http://{ip}/"

        # 全挂了，回退到有线默认
        return f"http://{self.wired_ip}/"

    def _check_port(self, ip):
        try:
            socket.create_connection((ip, 80), timeout=1).close()
            return True
        except: return False

    def _resolve(self, domain):
        try:
            socket.setdefaulttimeout(3)
            return socket.gethostbyname(domain)
        except: return None

    def _read_cache(self):
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, 'r') as f: return f.read().strip()
            except: pass
        return None

    def _write_cache(self, ip):
        try:
            with open(CACHE_FILE, 'w') as f: f.write(ip)
        except: pass

def login():
    print(f"[Info] Script Started at {time.ctime()}")
    
    if not os.path.exists(BINARY_PATH):
        print(f"[Error] Browser not found.")
        print("Please run setup.py first.")
        return

    # 智能获取目标地址
    ip_manager = SmartIPManager()
    target_url = ip_manager.get_best_url()
    
    chrome_options = Options()
    chrome_options.binary_location = BINARY_PATH
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--ignore-certificate-errors")
    chrome_options.add_argument("--window-size=1920,1080")

    service = Service(executable_path=DRIVER_PATH)

    driver = None
    try:
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        print(f"[Info] Target URL: {target_url}")
        
        # 页面加载重试
        page_loaded = False
        for i in range(15):
            try:
                print(f"[Connect] Attempt {i+1}...")
                driver.get(target_url)
                if driver.title:
                    print(f"[Connect] Title: {driver.title}")
                    page_loaded = True
                    break
            except:
                time.sleep(2)
        
        if not page_loaded:
            print("[Fatal] Webpage unreachable.")
            return

        time.sleep(2)

        # 查找输入框 (兼容有线和无线页面的不同ID)
        user_input = None
        pwd_input = None
        
        possible_user_ids = ["username", "userId", "user_name", "edit_account", "username_text"]
        possible_pwd_ids = ["password", "pwd", "password_text", "edit_password", "password_text"]

        for uid in possible_user_ids:
            try:
                user_input = driver.find_element(By.ID, uid)
                break
            except: continue
        
        for pid in possible_pwd_ids:
            try:
                pwd_input = driver.find_element(By.ID, pid)
                break
            except: continue

        if user_input and pwd_input:
            print("[Action] Inputting credentials...")
            user_input.clear()
            user_input.send_keys(USER_ID)
            pwd_input.clear()
            pwd_input.send_keys(PASSWORD)

            print("[Action] Clicking Login...")
            clicked = False
            try:
                driver.find_element(By.ID, "login-account").click()
                clicked = True
            except:
                try:
                    driver.find_element(By.CLASS_NAME, "login-btn").click()
                    clicked = True
                except:
                    tags = driver.find_elements(By.TAG_NAME, "a") + driver.find_elements(By.TAG_NAME, "button")
                    for tag in tags:
                        if "登录" in tag.text or "Login" in tag.text:
                            tag.click()
                            clicked = True
                            break
            
            if clicked:
                print("[Success] Login clicked.")
                time.sleep(5)
            else:
                pwd_input.submit()
        else:
            print("[Error] Input fields not found.")
            print(f"Source: {driver.page_source[:200]}")

    except Exception as e:
        print(f"[Fatal Error] {e}")
    finally:
        if driver: driver.quit()
        print("[Done] End.")

if __name__ == "__main__":
    login()
