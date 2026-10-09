@echo off
cd /d C:\Users\aman.kumar\Downloads\Coherent-Quadrant
set PYTHONIOENCODING=utf-8
.venv\Scripts\python.exe scripts\run_quadrant_pipeline.py --market "Connected Fleet Mobility Solutions Market" --country "united kingdom" --slots 41-50 --keep 250 --max-discover-rounds 0 >> logs\uk_connected_fleet_run.log 2>&1
echo exit=%ERRORLEVEL% >> logs\uk_connected_fleet_run.log
