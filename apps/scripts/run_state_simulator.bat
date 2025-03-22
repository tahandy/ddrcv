@echo off
call %~dp0\..\..\.venv\Scripts\activate.bat
cd %~dp0\..\state_simulator
python -m run
pause