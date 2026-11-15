@echo off
title PROJECT ZORO
color 0B
echo ========================================================
echo                 STARTING PROJECT ZORO
echo ========================================================
echo.

cd /d "%~dp0.."

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "scripts\supervisor.py"
) else (
    python "scripts\supervisor.py"
)

echo.
pause
