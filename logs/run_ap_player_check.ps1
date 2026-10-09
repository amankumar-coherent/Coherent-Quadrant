# Accounts Payable Automation: re-verify all report companies are Solution Providers (AI Mode, read-only, resumable).
Set-Location 'C:\Users\aman.kumar\Downloads\Coherent-Quadrant'
$env:GOOGLE_AI_MODE_QUERY_DELAY = '10'
& '.\.venv\Scripts\python.exe' 'scripts\recheck_player_type.py' --market 'Accounts Payable Automation Market' --country global --browsers 10 --slot-start 41 2>&1 |
    Out-File -FilePath 'logs\run_ap_player_check.log' -Append -Encoding utf8
"exit=$LASTEXITCODE" | Out-File -FilePath 'logs\run_ap_player_check.log' -Append -Encoding utf8
