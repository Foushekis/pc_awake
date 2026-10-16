@echo off
rem Builds dist\PCAwakeMonitor.exe. Always asks for admin rights.
rem Uses the "py" launcher if present, otherwise "python".
where py >nul 2>nul && (set PY=py) || (set PY=python)
%PY% -m pip install --upgrade pyinstaller || exit /b 1
%PY% -m PyInstaller --onefile --noconsole --uac-admin --name PCAwakeMonitor monitor.py || exit /b 1
echo.
echo Done: dist\PCAwakeMonitor.exe
