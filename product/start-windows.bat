@echo off
setlocal
cd /d "%~dp0.."
where py >nul 2>nul
if errorlevel 1 (
 echo Python 3.11+ is required. Install it from python.org, then reopen this file.
 pause
 exit /b 1
)
if not exist ".product-venv\Scripts\python.exe" (
 py -3 -m venv .product-venv
 if errorlevel 1 goto failed
)
".product-venv\Scripts\python.exe" -c "import sys; assert sys.version_info >= (3,11), 'Python 3.11+ required'"
if errorlevel 1 goto failed
".product-venv\Scripts\python.exe" -m pip install -r product\requirements.lock.txt
if errorlevel 1 goto failed
".product-venv\Scripts\python.exe" product\launch.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo Startup failed. Copy the error above for diagnosis. This window stays open.
pause
exit /b 1
