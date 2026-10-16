@echo off
rem Builds dist\PCAwakeMonitor.exe (needs Python on PATH). Always asks for admin rights.
python -m pip install --upgrade pyinstaller || exit /b 1
python -m PyInstaller --onefile --noconsole --uac-admin --name PCAwakeMonitor monitor.py
echo.
echo Done: dist\PCAwakeMonitor.exe
