@echo off
cd /d C:\Users\aman.kumar\Downloads\Coherent-Quadrant
.venv\Scripts\python.exe scripts\run_quadrant_pipeline.py --market "Drone Charging Industry Analysis" --country india --slots 51 --top-n 20 --keep 120 --max-discover-rounds 0 >> logs\parallel\drone_charging_industry_analysis_india.log 2>&1
echo exit=%ERRORLEVEL% >> logs\parallel\drone_charging_industry_analysis_india.log
