@echo off
cd /d C:\Users\aman.kumar\Downloads\Coherent-Quadrant
.venv\Scripts\python.exe logs\run_ap_automation.py >> logs\run_ap_automation.log 2>&1
echo exit=%ERRORLEVEL% >> logs\run_ap_automation.log
