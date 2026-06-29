@echo off
setlocal
cd /d "%~dp0.."
echo ==> aliexpress-spider installer (Windows)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
if errorlevel 1 exit /b 1
endlocal
