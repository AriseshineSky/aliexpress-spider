@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

title AliExpress Spider

echo.
echo ============================================
echo   AliExpress Spider - Setup and Run
echo ============================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo .venv not found. Running installer...
    call "%~dp0scripts\install.bat"
    if errorlevel 1 (
        echo.
        echo Install failed. Try: scripts\reinstall.bat
        pause
        exit /b 1
    )
)

REM Headed browser: visible window, wait for manual captcha, do not exit immediately on block
set "USER_DATA=%USERPROFILE%\.aliexpress-spider\browser"
set "CRAWL_OPTS=--headed --no-exit-on-block --captcha-wait 120 --user-data-dir !USER_DATA! --output-dir %~dp0data"

echo.
echo --------------------------------------------
echo Starting crawl (headed browser). Output: data\
echo Profile: !USER_DATA!
echo If captcha appears, solve it in the browser window.
echo --------------------------------------------
echo.

".venv\Scripts\python.exe" -m aliexpress_spider crawl !CRAWL_OPTS!
set CRAWL_EXIT=!ERRORLEVEL!

echo.
if "!CRAWL_EXIT!"=="0" goto crawl_ok
if "!CRAWL_EXIT!"=="2" goto crawl_blocked
echo Crawl failed with exit code: !CRAWL_EXIT!
goto end

:crawl_ok
echo Crawl finished successfully.
goto end

:crawl_blocked
echo Blocked by AliExpress anti-bot page.
echo Run verify.bat to pass captcha, then run this script again.
goto end

:end
echo.
pause
exit /b !CRAWL_EXIT!
