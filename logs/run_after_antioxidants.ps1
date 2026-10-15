# Queue (owner 2026-10-13): Global Lactoferrin Market starts when the Antioxidants run ends (same slots 41-50).
Set-Location (Split-Path -Parent $PSScriptRoot)
while (Get-CimInstance Win32_Process -Filter "name='powershell.exe'" | Where-Object { $_.CommandLine -match 'run_antioxidants\.ps1' }) {
    Start-Sleep -Seconds 60
}
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'logs\run_lactoferrin.ps1'
