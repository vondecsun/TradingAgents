@echo off
setlocal
set PRODUCT_LOCAL_TEST_LOGIN=true
set PRODUCT_HOST=127.0.0.1
cd /d "%~dp0"
call "%~dp0product\setup-research-windows.bat"
