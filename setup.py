import os
import zipfile
import io
import requests
import subprocess
import sys

# Chrome for Testing v133 (Stable) 下载链接
CHROME_URL = "https://storage.googleapis.com/chrome-for-testing-public/133.0.6943.53/win64/chrome-headless-shell-win64.zip"
DRIVER_URL = "https://storage.googleapis.com/chrome-for-testing-public/133.0.6943.53/win64/chromedriver-win64.zip"

BASE_DIR = os.getcwd()
WEBDRIVER_DIR = os.path.join(BASE_DIR, "webdriver")

def install_libs():
    print("[1/3] Installing libraries...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])

def download_drivers():
    print("[2/3] Downloading Chrome Drivers...")
    if not os.path.exists(WEBDRIVER_DIR): os.makedirs(WEBDRIVER_DIR)
    
    def dl(url):
        print(f" -> Downloading {url.split('/')[-1]}...")
        r = requests.get(url)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        z.extractall(WEBDRIVER_DIR)
    
    try:
        dl(CHROME_URL)
        dl(DRIVER_URL)
        print(" -> Drivers ready.")
    except Exception as e:
        print(f"Error: {e}")

def create_config():
    print("[3/3] User Configuration")
    if os.path.exists("config.py"):
        print(" -> config.py already exists. Skipping.")
        return
    
    uid = input("请输入学号 (Student ID): ")
    pwd = input("请输入密码 (Password): ")
    
    with open("config.py", "w", encoding="utf-8") as f:
        f.write(f'USER_ID = "{uid}"\n')
        f.write(f'PASSWORD = "{pwd}"\n')
    print(" -> config.py created.")

if __name__ == "__main__":
    print("=== UESTC AutoLogin Setup ===")
    install_libs()
    download_drivers()
    create_config()
    print("\n安装完成！请参考 README 配置任务计划程序。")