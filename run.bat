@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================
echo   奇迹暖暖自动化 - Qdd
echo ================================
echo.
python run.py
echo.
pause
