# Global Data Center Market -- technology, equipment, software & infrastructure solution providers only.
# Global, 20 browsers (slots 41-60), cap 200 in the report (discovery aims for ~267 to cover removals). Resumable.
Set-Location (Split-Path -Parent $PSScriptRoot)
$m = 'Global Data Center Market'
$log = 'logs\run_datacenter.log'
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') start: $m (global, 20 browsers)" | Out-File -FilePath $log -Append -Encoding utf8
& '.\.venv\Scripts\python.exe' 'logs\run_market.py' $m --country global --keep 200 --browsers 20 --slot-start 41 --global-focus --discover-to 200 2>&1 |
    Out-File -FilePath $log -Append -Encoding utf8
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') end: $m exit=$LASTEXITCODE" | Out-File -FilePath $log -Append -Encoding utf8
