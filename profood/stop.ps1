# Stop the ProFood queue and its browsers. Everything is saved; profood\start.ps1 resumes.
#     powershell -ExecutionPolicy Bypass -File profood\stop.ps1
$root = Split-Path -Parent $PSScriptRoot
Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^(python|powershell|conhost)\.exe$' -and $_.ProcessId -ne $PID -and
    ($_.CommandLine -match 'profood\\run_queue\.py' -or $_.CommandLine -match 'run_market\.py|run_quadrant_pipeline\.py|parallel_topup\.py|discover_verify_rounds\.py' -and $_.CommandLine -match [regex]::Escape($root))
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep 3
Get-CimInstance Win32_Process -Filter "name='python.exe'" | Where-Object { $_.CommandLine -match [regex]::Escape($root) } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Get-CimInstance Win32_Process -Filter "name='chrome.exe'" | Where-Object { $_.CommandLine -match 'ai_mode_batch_4[1-5]' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Write-Host "ProFood queue stopped. Resume with: powershell -ExecutionPolicy Bypass -File profood\start.ps1"
