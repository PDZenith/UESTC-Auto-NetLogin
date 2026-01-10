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
# 1. 强制禁用代理 (核心抗干扰，防止Clash残留)
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
    """
    智能 IP 管理器：
    实现 缓存 -> 经验值 -> DNS 的多级故障转移策略
    """
    def __init__(self):
        self.domain = "aaa.uestc.edu.cn"
        self.default_ip = "198.18.0.35"  # 2026年经验值
    
    def get_best_url(self):
        # 1. 获取候选 IP (优先读取缓存，没有则用默认值)
        candidate_ip = self._read_cache() or self.default_ip
        print(f"[IP-Manager] Candidate IP: {candidate_ip}")
        
        # 2. 快速检测候选 IP 是否存活 (TCP Connect)
        # 如果存活，直接使用，跳过耗时的 DNS
        if self._check_port_open(candidate_ip):
            print("[IP-Manager] IP is alive. Using Candidate.")
            return f"http://{candidate_ip}/"
        
        # 3. 如果候选 IP 不通，说明 IP 变了或缓存失效，尝试 DNS 解析
        print("[IP-Manager] Candidate unreachable. Trying DNS...")
        new_ip = self._resolve_dns()
        
        if new_ip:
            print(f"[IP-Manager] DNS Resolved: {new_ip}")
            # 如果解析出了新 IP，更新缓存
            if new_ip != candidate_ip:
                self._write_cache(new_ip)
            return f"http://{new_ip}/"
        
        # 4. 如果 DNS 也挂了，死马当活马医，回退到默认 IP
        print("[IP-Manager] DNS failed. Fallback to default.")
        return f"http://{self.default_ip}/"

    def _check_port_open(self, ip, port=80, timeout=1):
        """检测 IP 端口连通性"""
        try:
            sock = socket.create_connection((ip, port), timeout=timeout)
            sock.close()
            return True
        except:
            return False

    def _resolve_dns(self):
        """执行 DNS 解析"""
        try:
            # 刚开机 DNS 可能慢，给 3 秒超时
            socket.setdefaulttimeout(3)
            return socket.gethostbyname(self.domain)
        except Exception as e:
            print(f"[IP-Manager] DNS Error: {e}")
            return None

    def _read_cache(self):
        """读取缓存文件"""
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, 'r') as f:
                    return f.read().strip()
            except: pass
        return None

    def _write_cache(self, ip):
        """写入缓存文件"""
        try:
            with open(CACHE_FILE, 'w') as f:
                f.write(ip)
            print("[IP-Manager] Cache updated.")
        except: pass

def login():
    print(f"[Info] Script Started at {time.ctime()}")
    
    if not os.path.exists(BINARY_PATH):
        print(f"[Error] Browser not found at: {BINARY_PATH}")
        print("Please run setup.py to download drivers.")
        return

    # === 1. 获取动态目标地址 ===
    ip_manager = SmartIPManager()
    target_url = ip_manager.get_best_url()
    # ==========================

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
        
        # 页面加载重试机制
        max_retries = 20
        page_loaded = False
        
        print(f"[Info] Target URL: {target_url}")
        for i in range(max_retries):
            try:
                print(f"[Connect] Attempt {i+1}/{max_retries}...")
                driver.get(target_url)
                # 简单验证页面标题防止空加载
                if driver.title:
                    print(f"[Connect] Success! Title: {driver.title}")
                    page_loaded = True
                    break
            except Exception as e:
                # 即使 IP 通了，HTTP 请求也可能因为服务未就绪而失败
                time.sleep(2)
        
        if not page_loaded:
            print("[Fatal] Webpage unreachable.")
            return

        time.sleep(2) # 等待 DOM 渲染

        # 查找输入框逻辑
        user_input = None
        pwd_input = None
        
        possible_user_ids = ["username", "userId", "user_name", "edit_account"]
        possible_pwd_ids = ["password", "pwd", "password_text", "edit_password"]

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
                print("[Success] Login button clicked.")
                time.sleep(5)
            else:
                pwd_input.submit()
        else:
            print("[Error] Input fields not found.")
            print(f"Source snippet: {driver.page_source[:200]}")

    except Exception as e:
        print(f"[Fatal Error] {e}")
    finally:
        if driver: driver.quit()
        print("[Done] Script End.")

if __name__ == "__main__":
    login()