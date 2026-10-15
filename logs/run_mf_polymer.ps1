# Medical Films: polymer-focused discovery (helper market), merge, then the Medical Films pipeline.
Set-Location (Split-Path -Parent $PSScriptRoot)
$log = 'logs\run_wound_markets.log'
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') start: polymer search (helper)" | Out-File -FilePath $log -Append -Encoding utf8
& '.\.venv\Scripts\python.exe' 'logs\run_market.py' 'Global Medical-Grade Polymer Materials Market' --keep 150 --browsers 20 --discovery-only 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
& '.\.venv\Scripts\python.exe' 'logs\merge_polymer_helper.py' 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') start: Global Medical Films Market (pipeline)" | Out-File -FilePath $log -Append -Encoding utf8
& '.\.venv\Scripts\python.exe' 'logs\run_market.py' 'Global Medical Films Market' --keep 150 --browsers 20 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') end: Global Medical Films Market exit=$LASTEXITCODE" | Out-File -FilePath $log -Append -Encoding utf8
