@echo off
rem Start everything in the background (hidden windows). Add -Status to only show status.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-all-here.ps1" %*
echo.
pause
