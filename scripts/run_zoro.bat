@echo off
title PROJECT ZORO
color 0B
echo ========================================================
echo                 STARTING PROJECT ZORO
echo ========================================================
echo.

cd /d "%~dp0.."

REM Check if Ollama daemon is running, start it in background if not
tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I /N "ollama.exe">NUL
if "%ERRORLEVEL%"=="1" (
    echo [Project ZORO] Starting local Ollama AI daemon in background...
    start /B "" "ollama" serve >nul 2>&1
    timeout /t 2 /nobreak >nul
)

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "scripts\supervisor.py"
) else (
    python "scripts\supervisor.py"
)

echo.
pause
