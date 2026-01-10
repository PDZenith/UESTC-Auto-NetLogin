import os
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

# 尝试导入配置，如果不存在则提示
try:
    from config import USER_ID, PASSWORD
except ImportError:
    print("[Fatal] config.py not found! Please run setup.py first.")
    exit(1)

# ================= 配置区域 =================
# 1. 强制禁用代理 (核心抗干扰)
os.environ['http_proxy'] = ''
os.environ['https_proxy'] = ''
os.environ['all_proxy'] = ''
os.environ['no_proxy'] = '*'

# 2. 目标地址 (IP直连，绕过DNS)
TARGET_URL = "http://198.18.0.35/"

# 3. 路径配置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DRIVER_PATH = os.path.join(BASE_DIR, "webdriver", "chromedriver-win64", "chromedriver.exe")
BINARY_PATH = os.path.join(BASE_DIR, "webdriver", "chrome-headless-shell-win64", "chrome-headless-shell.exe")
# ===========================================

def login():
    print("[Info] Script Started.")
    
    if not os.path.exists(BINARY_PATH):
        print(f"[Error] Browser not found at: {BINARY_PATH}")
        print("Please run setup.py to download drivers.")
        return

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
        
        # 重试机制
        max_retries = 20
        page_loaded = False
        
        print(f"[Info] Target: {TARGET_URL}")
        for i in range(max_retries):
            try:
                print(f"[Connect] Attempt {i+1}/{max_retries}...")
                driver.get(TARGET_URL)
                print("[Connect] Page loaded successfully!")
                page_loaded = True
                break
            except Exception as e:
                time.sleep(3)
        
        if not page_loaded:
            print("[Fatal] Network unreachable.")
            return

        time.sleep(3)
        print(f"[Info] Title: {driver.title}")

        # 查找输入框
        user_input = None
        pwd_input = None
        
        # 兼容多种页面结构的 ID
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
            # 尝试点击多种登录按钮
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

    except Exception as e:
        print(f"[Fatal Error] {e}")
    finally:
        if driver: driver.quit()
        print("[Done] End.")

if __name__ == "__main__":
    login()