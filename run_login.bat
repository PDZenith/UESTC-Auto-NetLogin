@echo off
cd /d %~dp0

timeout /t 5 /nobreak >nul

echo [Start] %date% %time% >> run_log.txt

where python >nul 2>nul
if %errorlevel% equ 0 (
    set PYTHON_CMD=python
    goto :EXECUTE
)

where py >nul 2>nul
if %errorlevel% equ 0 (
    set PYTHON_CMD=py
    goto :EXECUTE
)

if exist "C:\Python39\python.exe" (
    set PYTHON_CMD="C:\Python39\python.exe"
    goto :EXECUTE
)

if exist "D:\Program Files\Anaconda\python.exe" (
    set PYTHON_CMD="D:\Program Files\Anaconda\python.exe"
    goto :EXECUTE
)
if exist "C:\ProgramData\Anaconda3\python.exe" (
    set PYTHON_CMD="C:\ProgramData\Anaconda3\python.exe"
    goto :EXECUTE
)


echo [Fatal Error] Python not found in PATH or common locations. >> run_log.txt
echo Please edit 'run_login.bat' and set absolute path to python.exe manually. >> run_log.txt
goto :END


:EXECUTE
echo [Info] Using Interpreter: %PYTHON_CMD% >> run_log.txt
%PYTHON_CMD% auto_login.py >> run_log.txt 2>&1

:END
echo [End] Finished >> run_log.txt
echo ------------------------------------------------ >> run_log.txt