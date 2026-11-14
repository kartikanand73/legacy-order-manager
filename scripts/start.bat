@echo off
cd /d "%~dp0\.."
py app.py --init
if errorlevel 1 exit /b 1
py app.py
