@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo Error: .venv not found. Run scripts\install.bat first.
  exit /b 1
)
".venv\Scripts\python.exe" -m aliexpress_spider verify --user-data-dir "%USERPROFILE%\.aliexpress-spider\browser" --timeout 300 %*
endlocal
