@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0.."
where py >nul 2>nul
if errorlevel 1 goto failed
if not exist ".product-venv\Scripts\python.exe" py -3 -m venv .product-venv
if errorlevel 1 goto failed
".product-venv\Scripts\python.exe" -m pip install -r product\requirements.lock.txt
if errorlevel 1 goto failed
".product-venv\Scripts\python.exe" -m pip install .
if errorlevel 1 goto failed
".product-venv\Scripts\python.exe" product\research_session.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo Native research setup failed. Please retain the error above.
pause
exit /b 1
