@echo off
call %~dp0\..\..\.venv\Scripts\activate.bat
cv2_enumerate_cameras.exe
pause