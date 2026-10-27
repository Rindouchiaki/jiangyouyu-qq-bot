@echo off
rem One-click deploy: install / configure everything, then start. Safe to run again.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1" -Start %*
echo.
pause
