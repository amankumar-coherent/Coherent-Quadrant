# Global Antioxidants Market (rubber / polymer antioxidant additives), 200 companies, 10 browsers (slots 41-50). Resumable.
Set-Location (Split-Path -Parent $PSScriptRoot)
$log = 'logs\run_antioxidants.log'
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') start: Global Antioxidants Market" | Out-File -FilePath $log -Append -Encoding utf8
& '.\.venv\Scripts\python.exe' 'logs\run_market.py' 'Global Antioxidants Market' --keep 200 --browsers 10 2>&1 |
    Out-File -FilePath $log -Append -Encoding utf8
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') end: Global Antioxidants Market exit=$LASTEXITCODE" | Out-File -FilePath $log -Append -Encoding utf8
