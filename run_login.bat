@echo off
cd /d %~dp0

:: 等待网卡初始化
timeout /t 5 /nobreak

:: 记录日志
echo [Start] %date% %time% >> run_log.txt

:: 尝试运行脚本
:: 如果你的 python 不在系统路径中，请修改下面的 "python" 为绝对路径
:: 例如: "D:\Program Files\Anaconda\python.exe"
python auto_login.py >> run_log.txt 2>&1

echo [End] Finished >> run_log.txt

echo ------------------------------------------------ >> run_log.txt
