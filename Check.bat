@echo off
setlocal
cd /d "%~dp0"
call "%~dp0_runtime.bat"
if not exist "%ASSISTANT_RUNTIME%\Scripts\python.exe" (
  echo Run Setup.bat first.
  pause
  exit /b 1
)
"%ASSISTANT_RUNTIME%\Scripts\python.exe" -X utf8 "%~dp0friday_app.py" --check
pause
