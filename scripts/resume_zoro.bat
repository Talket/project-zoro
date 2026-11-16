@echo off
title ZORO RESUME AUTHORIZATION
color 0A
echo ========================================================
echo         PROJECT ZORO -- RESUME AUTHORIZATION
echo ========================================================
echo.
echo Clearing emergency halt lock...
echo.

if exist "%~dp0..\.venv\Scripts\python.exe" (
    "%~dp0..\.venv\Scripts\python.exe" "%~dp0emergency_kill.py" --resume
) else (
    python "%~dp0emergency_kill.py" --resume
)

echo.
pause
