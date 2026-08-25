@echo off
REM Start Google AI scraper on port 15561 (bypasses PowerShell execution policy)
cd /d "%~dp0.."
set PYTHONPATH=%CD%\google-ai-scraper-main\google-ai-scraper-main\server
start "google-ai-scraper-15561" /MIN "%CD%\.venv\Scripts\python.exe" -m uvicorn google_ai_scraper.app:app --host 127.0.0.1 --port 15561
timeout /t 4 /nobreak >nul
curl -s http://127.0.0.1:15561/health
echo.
echo If extension_connected is false: set Chrome extension Server URL to http://localhost:15561 and refresh.
