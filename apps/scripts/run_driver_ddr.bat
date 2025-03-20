@echo off
call %~dp0\..\..\.venv\Scripts\activate.bat
cd %~dp0\..\..\
@REM python -m ddrcv.apps.driver_ddr_tbd5 --choose-camera --debug
python -m ddrcv.apps.driver_ddr_tbd5 --choose-camera
pause