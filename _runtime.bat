@echo off
set "PYTHONDONTWRITEBYTECODE=1"
set "ASSISTANT_RUNTIME=%LOCALAPPDATA%\FanAssistants\FRIDAY\runtime"
if not exist "%ASSISTANT_RUNTIME%\Scripts\python.exe" if exist "%LOCALAPPDATA%\FanAssistants\shared-runtime\Scripts\python.exe" set "ASSISTANT_RUNTIME=%LOCALAPPDATA%\FanAssistants\shared-runtime"
