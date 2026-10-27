@echo off
rem Stop everything (QQ itself is left running).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-all-here.ps1" -Stop %*
echo.
pause
