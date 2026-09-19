@echo off
setlocal
if exist "%~dp0..\..\.venv\Scripts\pythonw.exe" (
    start "" "%~dp0..\..\.venv\Scripts\pythonw.exe" "%~dp0ffmpeg_record_gui.py"
    exit /b
)
where pyw >nul 2>nul
if not errorlevel 1 (
    start "" pyw -3 "%~dp0ffmpeg_record_gui.py"
    exit /b
)
echo Python with Tkinter is required. Install standard Windows Python or use the existing DDRCV environment.
pause
