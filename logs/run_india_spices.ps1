# India Spices and Seasonings Market -- India-headquartered spice / masala / seasoning makers and brand owners
# (sample report groups Manufacturer + Brand). 10 browsers (slots 41-50), discover to ~160, keep every verified company (owner 2026-10-20), India state-wise. Resumable.
Set-Location (Split-Path -Parent $PSScriptRoot)
$m = 'India Spices and Seasonings Market'
$log = 'logs\run_india_spices.log'
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') start: $m (10 browsers)" | Out-File -FilePath $log -Append -Encoding utf8
& '.\.venv\Scripts\python.exe' 'logs\run_market.py' $m --country india --keep 1000 --discover-to 160 --browsers 10 --slot-start 41 --state-wise 2>&1 |
    Out-File -FilePath $log -Append -Encoding utf8
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') end: $m exit=$LASTEXITCODE" | Out-File -FilePath $log -Append -Encoding utf8

