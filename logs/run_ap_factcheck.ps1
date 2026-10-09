# Accounts Payable Automation: AI Mode fact-check of the chart companies (read-only, resumable).
Set-Location 'C:\Users\aman.kumar\Downloads\Coherent-Quadrant'
& '.\.venv\Scripts\python.exe' 'logs\run_ap_factcheck.py' 2>&1 |
    Out-File -FilePath 'logs\run_ap_factcheck.log' -Append -Encoding utf8
"exit=$LASTEXITCODE" | Out-File -FilePath 'logs\run_ap_factcheck.log' -Append -Encoding utf8
