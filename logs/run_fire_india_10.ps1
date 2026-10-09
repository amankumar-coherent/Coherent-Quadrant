# The 10 fire markets from Desktop\Fire Market Quadrant: checks-only update of the original India report
# (active / acquired / real + house wording), chart refilled to 20 from each report's own long tail.
# 5 browsers (slots 46-50), resumable; refreshes Desktop\Final Fire Quadrant at the end.
Set-Location 'C:\Users\aman.kumar\Downloads\Coherent-Quadrant'
$env:GOOGLE_AI_MODE_QUERY_DELAY = '10'
$env:PYTHONIOENCODING = 'utf-8'
& '.\.venv\Scripts\python.exe' 'scripts\run_markets_parallel.py' --markets-file 'queries\fire_india_10.txt' --workers 5 --slot-start 46 --top-n 20 -- --max-discover-rounds 0 --update-report auto --refill-chart 2>&1 |
    Out-File -FilePath 'logs\run_fire_india_10.log' -Append -Encoding utf8
& '.\.venv\Scripts\python.exe' 'logs\build_final_folders.py' 2>&1 | Out-File -FilePath 'logs\run_fire_india_10.log' -Append -Encoding utf8
"BATCH_FINISHED exit=$LASTEXITCODE" | Out-File -FilePath 'logs\run_fire_india_10.log' -Append -Encoding utf8
