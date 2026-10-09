# Accounts Payable Automation run, launched from PowerShell (resumes from its last saved step).
Set-Location 'C:\Users\aman.kumar\Downloads\Coherent-Quadrant'
& '.\.venv\Scripts\python.exe' 'logs\run_ap_automation.py' 2>&1 |
    Out-File -FilePath 'logs\run_ap_automation.log' -Append -Encoding utf8
"exit=$LASTEXITCODE" | Out-File -FilePath 'logs\run_ap_automation.log' -Append -Encoding utf8
