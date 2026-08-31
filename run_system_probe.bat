@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "NETLOGIN_PYTHON=%~dp0.venv\Scripts\python.exe"
set "NETLOGIN_SCRIPT=%~dp0my_login.py"
set "PROBE_LOG=%~dp0system_probe_log.txt"
set "RUN_ID=%~1"

>>"%PROBE_LOG%" echo [SystemProbeStart] run_id=%RUN_ID% date=%date% time=%time%
"%NETLOGIN_PYTHON%" "%NETLOGIN_SCRIPT%" --probe-only >>"%PROBE_LOG%" 2>&1
set "PROBE_EXIT=%ERRORLEVEL%"
>>"%PROBE_LOG%" echo [SystemProbeEnd] run_id=%RUN_ID% exit_code=%PROBE_EXIT% date=%date% time=%time%
>>"%PROBE_LOG%" echo ------------------------------------------------
exit /b %PROBE_EXIT%
