@echo off
setlocal
cd /d "%~dp0"
call "%~dp0_runtime.bat"
if not exist "%ASSISTANT_RUNTIME%\Scripts\python.exe" (
  py -3.12 -m venv "%ASSISTANT_RUNTIME%"
  if errorlevel 1 (
    echo Install Python 3.12 from python.org, then run Setup.bat again.
    pause
    exit /b 1
  )
)
"%ASSISTANT_RUNTIME%\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
  echo Installation failed. Check the error above and your internet connection.
  pause
  exit /b 1
)
echo Setup complete. Run Start.bat to open the assistant.
"%ASSISTANT_RUNTIME%\Scripts\python.exe" setup_wake.py
if errorlevel 1 echo Local wake download failed. Run Setup.bat again to retry. Online wake still works.
pause
