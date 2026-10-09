@echo off
cd /d C:\Users\aman.kumar\Downloads\Coherent-Quadrant
.venv\Scripts\python.exe scripts\run_markets_parallel.py --markets-file queries\drone_fire_33.txt --workers 10 --keep 120 -- --max-discover-rounds 0 >> logs\run_drone_fire_33.log 2>&1
echo exit=%ERRORLEVEL% >> logs\run_drone_fire_33.log
