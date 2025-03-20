@echo off
REM Use PowerShell to get the current date and time in the format YYYY-MM-dd_HH-mm-ss
for /f "delims=" %%a in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH-mm-ss"') do set datetime=%%a

echo Recording to file %datetime%.mkv...
C:\code\ffmpeg\bin\ffmpeg -f dshow -framerate 30 -video_size 1280x720 -i video="USB Video":audio="Digital Audio Interface (USB Digital Audio)" "%datetime%.mkv"

pause
