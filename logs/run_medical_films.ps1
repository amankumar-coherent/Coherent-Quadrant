# Global Medical Films Market (medical FILM manufacturers, owner 2026-10-13), no cap (all qualifying companies), 20 browsers. Resumable.
Set-Location (Split-Path -Parent $PSScriptRoot)
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') start: Global Medical Films Market (film makers)" | Out-File -FilePath 'logs\run_medical_films.log' -Append -Encoding utf8
& '.\.venv\Scripts\python.exe' 'logs\run_market.py' 'Global Medical Films Market' --keep 1000 --browsers 20 2>&1 |
    Out-File -FilePath 'logs\run_medical_films.log' -Append -Encoding utf8
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') end: Global Medical Films Market (film makers) exit=$LASTEXITCODE" | Out-File -FilePath 'logs\run_medical_films.log' -Append -Encoding utf8
