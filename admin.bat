@echo off
REM Universal CRM: administration menu (git versions, DB backups, start/stop). Double-click to run.
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0admin.ps1"
