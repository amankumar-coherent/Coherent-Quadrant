# Waits for the fire checks-only batch, then runs the second pass (HQ-added companies + chart refill to 20).
Set-Location 'C:\Users\aman.kumar\Downloads\Coherent-Quadrant'
$env:GOOGLE_AI_MODE_QUERY_DELAY = '10'
$env:PYTHONIOENCODING = 'utf-8'
& '.\.venv\Scripts\python.exe' 'logs\fire_second_pass.py' 2>&1 | Out-File -FilePath 'logs\run_fire_second_pass.log' -Append -Encoding utf8
"exit=$LASTEXITCODE" | Out-File -FilePath 'logs\run_fire_second_pass.log' -Append -Encoding utf8
