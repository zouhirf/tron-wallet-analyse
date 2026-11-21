@echo off
cd /d "%~dp0"
if not exist venv (
    echo Eerste keer: virtuele omgeving maken en pakketten installeren...
    python -m venv venv
    venv\Scripts\python -m pip install --upgrade pip >nul
    venv\Scripts\python -m pip install -r requirements.txt
)
venv\Scripts\python gui.py
if errorlevel 1 pause
