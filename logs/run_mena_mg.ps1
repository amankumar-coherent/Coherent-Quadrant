# MENA Magnesium Glycinate Market -- brand owners / finished-product makers of magnesium glycinate supplements
# sold in MENA (B2C). 10 browsers (slots 41-50), cap 120, MENA countries asked first. Resumable.
Set-Location (Split-Path -Parent $PSScriptRoot)
$m = 'MENA Magnesium Glycinate Market'
$log = 'logs\run_mena_mg.log'
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') start: $m (10 browsers)" | Out-File -FilePath $log -Append -Encoding utf8
& '.\.venv\Scripts\python.exe' 'logs\run_market.py' $m --country global --keep 120 --browsers 10 --slot-start 41 --global-focus --discover-to 120 2>&1 |
    Out-File -FilePath $log -Append -Encoding utf8
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') end: $m exit=$LASTEXITCODE" | Out-File -FilePath $log -Append -Encoding utf8
