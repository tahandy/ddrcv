@echo off
setlocal
cd /d "%~dp0"
py -3.12 -c "import sys; assert sys.version_info[:2] == (3,12)" >nul 2>&1
if errorlevel 1 goto failed
if not exist ".venv\Scripts\python.exe" py -3.12 -m venv .venv
if errorlevel 1 goto failed
.venv\Scripts\python.exe -c "import sys; assert sys.version_info[:2] == (3,12), 'Existing .venv must use Python 3.12'"
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip install -r requirements-desktop.txt
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip install --no-deps -e .
if errorlevel 1 goto failed
.venv\Scripts\python.exe -B -m ddrcv.desktop --check
if errorlevel 1 goto failed
echo Setup complete. Launch with launch_desktop.vbs (no console).
pause
exit /b 0
:failed
echo Setup failed. Python 3.12 and Microsoft Edge WebView2 Runtime are required. Read the error above.
pause
exit /b 1
