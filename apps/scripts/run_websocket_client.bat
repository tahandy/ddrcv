@echo off
call %~dp0\..\..\.venv\Scripts\activate.bat
cd %~dp0\..\..\
python -m sandbox.websocket_client --uri ws://localhost:9000
pause