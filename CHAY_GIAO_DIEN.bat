@echo off
chcp 65001 >nul
cd /d "%~dp0"
python gui.py
if errorlevel 1 (
    echo.
    echo Khong khoi dong duoc. Hay cai Python va chay: python -m pip install -r requirements.txt
    pause
)
