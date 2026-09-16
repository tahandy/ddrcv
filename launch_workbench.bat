@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup_workbench.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -B -m ddrcv.workbench
if errorlevel 1 pause
