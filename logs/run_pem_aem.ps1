# PEM & AEM Electrolyzers for Green Hydrogen Projects Market -- INDIA only, 10 browsers (slots 41-50), cap 200, state by state. Resumable.
Set-Location (Split-Path -Parent $PSScriptRoot)
$m = 'PEM & AEM Electrolyzers for Green Hydrogen Projects Market'
$log = 'logs\run_pem_aem.log'
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') start: $m (india, 10 browsers)" | Out-File -FilePath $log -Append -Encoding utf8
& '.\.venv\Scripts\python.exe' 'logs\run_market.py' $m --country india --keep 200 --browsers 10 --slot-start 41 --global-focus --state-wise --discover-to 200 2>&1 |
    Out-File -FilePath $log -Append -Encoding utf8
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') end: $m exit=$LASTEXITCODE" | Out-File -FilePath $log -Append -Encoding utf8
