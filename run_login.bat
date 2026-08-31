@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "NETLOGIN_PYTHON=%~dp0.venv\Scripts\python.exe"
set "NETLOGIN_SCRIPT=%~dp0my_login.py"
set "NETLOGIN_LOG=%~dp0run_log.txt"

>>"%NETLOGIN_LOG%" echo [BatchStart] %date% %time% args=%*

if not exist "%NETLOGIN_PYTHON%" (
    >>"%NETLOGIN_LOG%" echo [BatchError] Python not found: %NETLOGIN_PYTHON%
    >>"%NETLOGIN_LOG%" echo [BatchEnd] exit_code=20
    exit /b 20
)

if not exist "%NETLOGIN_SCRIPT%" (
    >>"%NETLOGIN_LOG%" echo [BatchError] Script not found: %NETLOGIN_SCRIPT%
    >>"%NETLOGIN_LOG%" echo [BatchEnd] exit_code=10
    exit /b 10
)

"%NETLOGIN_PYTHON%" "%NETLOGIN_SCRIPT%" %* >>"%NETLOGIN_LOG%" 2>&1
set "NETLOGIN_EXIT=%ERRORLEVEL%"
>>"%NETLOGIN_LOG%" echo [BatchEnd] %date% %time% exit_code=%NETLOGIN_EXIT%
>>"%NETLOGIN_LOG%" echo ------------------------------------------------
exit /b %NETLOGIN_EXIT%
