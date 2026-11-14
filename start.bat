@echo off
rem Tanso Juliss - Windows launcher. Double-click to run. Close: Ctrl+C or close this window.
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"
echo.
pause
