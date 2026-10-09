# Smoke Control Systems (fire India) checks-only update on 5 browsers (slots 51-55, no overlap with Trade Finance
# on 41-45,48-50), chart refill to 20 if needed, then refresh Desktop\Final Fire Quadrant.
Set-Location 'C:\Users\aman.kumar\Downloads\Coherent-Quadrant'
$env:GOOGLE_AI_MODE_QUERY_DELAY = '10'
$env:PYTHONIOENCODING = 'utf-8'
& '.\.venv\Scripts\python.exe' 'scripts\run_markets_parallel.py' --markets-file 'queries\fire_smoke_only.txt' --workers 5 --slots-per-market 5 --slot-start 51 --top-n 20 -- --max-discover-rounds 0 --update-report auto --refill-chart 2>&1 |
    Out-File -FilePath 'logs\run_fire_smoke.log' -Append -Encoding utf8
& '.\.venv\Scripts\python.exe' 'logs\build_final_folders.py' 2>&1 | Out-File -FilePath 'logs\run_fire_smoke.log' -Append -Encoding utf8
"BATCH_FINISHED exit=$LASTEXITCODE" | Out-File -FilePath 'logs\run_fire_smoke.log' -Append -Encoding utf8
