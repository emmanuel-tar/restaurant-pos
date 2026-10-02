@echo off
REM Always run from the folder this script lives in, on any machine/drive.
cd /d "%~dp0"

REM Use the project's virtualenv explicitly so the correct Django is loaded.
set "PYTHON=%~dp0.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo ERROR: Virtual environment not found at "%PYTHON%".
    echo Create it with:  python -m venv .venv
    echo Then install deps: .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

start "" http://127.0.0.1:8000/login/

"%PYTHON%" manage.py runserver

pause
