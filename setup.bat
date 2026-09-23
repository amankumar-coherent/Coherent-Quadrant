@echo off
cd /d "%~dp0"
echo Vendor Intelligence - setup
python --version >nul 2>&1 || (echo Install Python 3.11+ from python.org & pause & exit /b 1)
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
.venv\Scripts\python.exe -m pip install --upgrade pip -q
.venv\Scripts\python.exe -m pip install -r requirements.txt
REM Bundled Chromium for Google AI Mode -- it loads the CAPTCHA solver in extensions\captcha-raptor
.venv\Scripts\python.exe -m patchright install chromium
if not exist .env copy .env.example .env
echo.
echo LIVE mode: edit .env using .env.example and env.live.template
echo Preflight: .venv\Scripts\python.exe scripts\preflight_search.py
echo.
echo Ready. Run:
echo   run.bat "Give me the best laptop companies in India"
pause
