@echo off
setlocal
cd /d "%~dp0"

title AliExpress Spider - Verify

if not exist ".venv\Scripts\python.exe" (
    echo Please run run.bat or scripts\install.bat first.
    pause
    exit /b 1
)

echo A browser window will open.
echo Complete AliExpress captcha or login, then run run.bat again.
echo.

call "%~dp0scripts\verify.bat"
set EXIT_CODE=%ERRORLEVEL%

echo.
pause
exit /b %EXIT_CODE%
