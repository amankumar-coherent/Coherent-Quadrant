# Global Empty Capsules Market (empty capsule manufacturers): resumable run, launched from PowerShell.
Set-Location (Split-Path -Parent $PSScriptRoot)
& '.\.venv\Scripts\python.exe' 'logs\run_empty_capsules.py' 2>&1 |
    Out-File -FilePath 'logs\run_empty_capsules.log' -Append -Encoding utf8
"exit=$LASTEXITCODE" | Out-File -FilePath 'logs\run_empty_capsules.log' -Append -Encoding utf8
