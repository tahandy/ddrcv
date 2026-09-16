@echo off
setlocal
cd /d "%~dp0"
py -3.12 -c "import sys; assert sys.version_info[:2] == (3,12)" >nul 2>&1
if errorlevel 1 (
  echo Python 3.12 is required. Install 64-bit Python 3.12 with the Python launcher, then run this script again.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv
  if errorlevel 1 goto failed
)
.venv\Scripts\python.exe -c "import sys; assert sys.version_info[:2] == (3,12), 'Existing .venv is not Python 3.12. Move it aside before creating a new one.'"
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip install -r requirements-workbench.txt
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip install --no-deps -e .
if errorlevel 1 goto failed
if exist "..\ddr_score_render\setup.py" (
  .venv\Scripts\python.exe -m pip install --no-deps -e "..\ddr_score_render"
  if errorlevel 1 goto failed
) else (
  echo Optional renderer not found. Place ddr_score_render next to this folder, or choose its location in the panel.
)
.venv\Scripts\python.exe -B -m ddrcv.workbench --check
if errorlevel 1 goto failed
echo Setup complete. Run launch_workbench.bat to open the rehearsal panel.
pause
exit /b 0
:failed
echo Setup failed. Read the error above. Existing settings have been preserved.
pause
exit /b 1
