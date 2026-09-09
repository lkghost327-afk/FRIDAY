@echo off
setlocal
cd /d "%~dp0"
call "%~dp0_runtime.bat"
if not exist "%ASSISTANT_RUNTIME%\Scripts\python.exe" (
  echo Run Setup.bat first.
  pause
  exit /b 1
)
"%ASSISTANT_RUNTIME%\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 exit /b 1
"%ASSISTANT_RUNTIME%\Scripts\python.exe" build_exe.py
pause
