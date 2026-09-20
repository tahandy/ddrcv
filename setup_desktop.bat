@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup.ps1" -App desktop %*
set "setup_result=%ERRORLEVEL%"
if not defined DDRCV_SETUP_NO_PAUSE pause
exit /b %setup_result%
