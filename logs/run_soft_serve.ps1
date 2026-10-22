# Global Soft Serve Ice Cream Machines Market -- manufacturers of commercial soft-serve machines (client brief
# 2026-10-21). 20 browsers (slots 41-60), global, discover to ~300 (owner 2026-10-21), keep every verified company. Resumable.
Set-Location (Split-Path -Parent $PSScriptRoot)
$m = 'Global Soft Serve Ice Cream Machines Market'
$log = 'logs\run_soft_serve.log'
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') start: $m (20 browsers)" | Out-File -FilePath $log -Append -Encoding utf8
& '.\.venv\Scripts\python.exe' 'logs\run_market.py' $m --country global --keep 1000 --discover-to 300 --browsers 20 --slot-start 41 --global-focus 2>&1 |
    Out-File -FilePath $log -Append -Encoding utf8
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') end: $m exit=$LASTEXITCODE" | Out-File -FilePath $log -Append -Encoding utf8



