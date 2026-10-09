# Accounts Payable Automation: targeted suite-vendor discovery, then pipeline with Top 20 re-pick (resumable).
Set-Location 'C:\Users\aman.kumar\Downloads\Coherent-Quadrant'
& '.\.venv\Scripts\python.exe' 'logs\run_ap_erp_topup.py' 2>&1 |
    Out-File -FilePath 'logs\run_ap_automation.log' -Append -Encoding utf8
"exit=$LASTEXITCODE" | Out-File -FilePath 'logs\run_ap_automation.log' -Append -Encoding utf8
