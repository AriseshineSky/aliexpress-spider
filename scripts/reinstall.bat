@echo off
setlocal
cd /d "%~dp0.."
echo ==> Reinstall aliexpress-spider (clean .venv)
if exist .venv (
  echo Removing old .venv ...
  rmdir /s /q .venv
)
call "%~dp0install.bat"
endlocal
