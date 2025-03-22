@echo off
call %~dp0\..\..\.venv\Scripts\activate.bat
cd %~dp0\..\camera_preview
python -m camera_preview
pause