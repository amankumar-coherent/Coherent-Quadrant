# U.S. Entresto Market -- companies marketing finished sacubitril/valsartan (branded ENTRESTO + FDA-approved
# generics) in the U.S., companies HEADQUARTERED in the U.S. only. 10 browsers (slots 41-50), cap 120 (a small market: ends when exhausted). Resumable.
Set-Location (Split-Path -Parent $PSScriptRoot)
$m = 'U.S. Entresto Market'
$log = 'logs\run_entresto.log'
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') start: $m (10 browsers)" | Out-File -FilePath $log -Append -Encoding utf8
& '.\.venv\Scripts\python.exe' 'logs\run_market.py' $m --country global --keep 120 --browsers 10 --slot-start 41 --global-focus --discover-to 120 2>&1 |
    Out-File -FilePath $log -Append -Encoding utf8
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') end: $m exit=$LASTEXITCODE" | Out-File -FilePath $log -Append -Encoding utf8


