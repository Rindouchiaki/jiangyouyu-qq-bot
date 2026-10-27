@echo off
rem One-click update: git pull, bring dependencies to the locked versions, restart.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\update.ps1" %*
echo.
pause
