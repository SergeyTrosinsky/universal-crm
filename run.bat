@echo off
REM Universal CRM: start Docker containers + Cloudflare tunnel (double-click to run).
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"
echo.
pause
