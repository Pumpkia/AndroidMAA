@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================
echo   QQ 自动登录 - Qdd
echo ================================
echo.
python run.py
echo.
pause
