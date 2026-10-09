@echo off
cd /d C:\Users\aman.kumar\Downloads\Coherent-Quadrant
for %%M in ("Drone Charging Industry Analysis" "Drone Propulsion Industry Analysis" "Anti-Drone Systems Industry Analysis" "Drone AI Industry Analysis" "Drone LiDAR Industry Analysis" "Drone Cybersecurity Industry Analysis") do (
  echo [rerun] START %%~M >> logs\rerun_6.log
  .venv\Scripts\python.exe scripts\run_quadrant_pipeline.py --market %%M --country india --slots 51 --top-n 20 --keep 120 --max-discover-rounds 0 > logs\rerun_6_current.log 2>&1
  findstr /C:"[PASS]" logs\rerun_6_current.log | find /C "[PASS]" > logs\rerun_6_pass.txt
  for /f %%P in (logs\rerun_6_pass.txt) do echo [rerun] END %%~M exit=!ERRORLEVEL! pass=%%P >> logs\rerun_6.log
  findstr /C:"[FAIL]" logs\rerun_6_current.log >> logs\rerun_6.log
  type logs\rerun_6_current.log >> logs\parallel\rerun_6_all.log
)
echo [rerun] ALL DONE >> logs\rerun_6.log
