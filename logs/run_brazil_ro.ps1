# Brazil Reverse Osmosis Market: Brazil-headquartered companies only, 200 companies, 10 browsers (slots 41-50). Resumable.
Set-Location (Split-Path -Parent $PSScriptRoot)
$log = 'logs\run_brazil_ro.log'
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') start: Reverse Osmosis Market (brazil)" | Out-File -FilePath $log -Append -Encoding utf8
& '.\.venv\Scripts\python.exe' 'logs\run_market.py' 'Reverse Osmosis Market' --country brazil --keep 200 --browsers 10 2>&1 |
    Out-File -FilePath $log -Append -Encoding utf8
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') end: Reverse Osmosis Market (brazil) exit=$LASTEXITCODE" | Out-File -FilePath $log -Append -Encoding utf8
