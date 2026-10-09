# Resume the last 2 fire India checks-only updates (Life Safety, Smoke Control Systems) on fresh browsers 46-47,
# chart refill to 20 if needed, then refresh Desktop\Final Fire Quadrant.
Set-Location 'C:\Users\aman.kumar\Downloads\Coherent-Quadrant'
$env:GOOGLE_AI_MODE_QUERY_DELAY = '10'
$env:PYTHONIOENCODING = 'utf-8'
& '.\.venv\Scripts\python.exe' 'scripts\run_markets_parallel.py' --markets-file 'queries\fire_india_last2.txt' --workers 2 --slot-start 46 --top-n 20 -- --max-discover-rounds 0 --update-report auto --refill-chart 2>&1 |
    Out-File -FilePath 'logs\run_fire_india_10.log' -Append -Encoding utf8
& '.\.venv\Scripts\python.exe' 'logs\build_final_folders.py' 2>&1 | Out-File -FilePath 'logs\run_fire_india_10.log' -Append -Encoding utf8
"BATCH_FINISHED exit=$LASTEXITCODE" | Out-File -FilePath 'logs\run_fire_india_10.log' -Append -Encoding utf8
