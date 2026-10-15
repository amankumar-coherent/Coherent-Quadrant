# Global Lactoferrin Market (lactoferrin producers), 200 companies, 10 browsers (slots 41-50). Resumable.
Set-Location (Split-Path -Parent $PSScriptRoot)
$log = 'logs\run_lactoferrin.log'
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') start: Global Lactoferrin Market" | Out-File -FilePath $log -Append -Encoding utf8
& '.\.venv\Scripts\python.exe' 'logs\run_market.py' 'Global Lactoferrin Market' --keep 200 --browsers 10 2>&1 |
    Out-File -FilePath $log -Append -Encoding utf8
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') end: Global Lactoferrin Market exit=$LASTEXITCODE" | Out-File -FilePath $log -Append -Encoding utf8
