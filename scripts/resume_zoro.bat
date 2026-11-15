@echo off
title ZORO RESUME AUTHORIZATION
color 0A
echo ========================================================
echo         PROJECT ZORO -- RESUME AUTHORIZATION
echo ========================================================
echo.
echo Clearing emergency halt lock...
echo.

python "%~dp0emergency_kill.py" --resume

echo.
pause
