@echo off
call %~dp0\..\..\.venv\Scripts\activate.bat
cd %~dp0\..\obs
python -m run sdvx %~dp0\obs_config.json
pause