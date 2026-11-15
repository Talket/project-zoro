@echo off
title ZORO EMERGENCY KILL
color 0C
echo ========================================================
echo         PROJECT ZORO -- EMERGENCY HARD KILL SWITCH
echo ========================================================
echo.
echo Terminating ZORO process tree and setting emergency halt lock...
echo.

python "%~dp0emergency_kill.py" --kill --reason "Double-click emergency kill shortcut"

echo.
pause
