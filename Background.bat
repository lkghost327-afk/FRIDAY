@echo off
setlocal
cd /d "%~dp0"
call "%~dp0_runtime.bat"
if not exist "%ASSISTANT_RUNTIME%\Scripts\python.exe" (
  echo Run Setup.bat first.
  pause
  exit /b 1
)
start "" "%ASSISTANT_RUNTIME%\Scripts\pythonw.exe" "%~dp0friday_app.py" --background
