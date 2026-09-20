@echo off
call %~dp0\..\..\.venv\Scripts\activate.bat
cd %~dp0\..\..\
@REM python -m ddrcv.apps.driver_ddr --choose-camera --debug
python -m ddrcv.apps.driver_ddr --choose-camera
pause