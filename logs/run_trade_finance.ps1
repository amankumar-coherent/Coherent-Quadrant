# Global Trade Finance Market (technology & network providers): resumable run, launched from PowerShell.
Set-Location (Split-Path -Parent $PSScriptRoot)
& '.\.venv\Scripts\python.exe' 'logs\run_trade_finance.py' 2>&1 |
    Out-File -FilePath 'logs\run_trade_finance.log' -Append -Encoding utf8
"exit=$LASTEXITCODE" | Out-File -FilePath 'logs\run_trade_finance.log' -Append -Encoding utf8
