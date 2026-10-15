# 9 drone / geospatial markets, INDIA ONLY (owner 2026-10-14): one browser per market (slots 41-49),
# cap 120 verified, companies headquartered in India, discovery India-wide then state by state. Resumable.
Set-Location (Split-Path -Parent $PSScriptRoot)
$markets = Get-Content 'logs\india9_markets.json' -Raw | ConvertFrom-Json
$slot = 41
foreach ($m in $markets) {
    $tag = ($m -replace '[^A-Za-z0-9]+', '_').Trim('_').ToLower()
    $log = "logs\india9_$tag.log"
    "=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') start: $m (india, slot $slot)" | Out-File -FilePath $log -Append -Encoding utf8
    $cmd = "& '.\.venv\Scripts\python.exe' 'logs\run_market.py' '$m' --country india --keep 120 --browsers 1 --slot-start $slot --global-focus --discover-to 120 2>&1 | Out-File -FilePath '$log' -Append -Encoding utf8"
    Start-Process powershell.exe -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $cmd -WindowStyle Hidden
    $slot++
    Start-Sleep -Seconds 20   # stagger browser launches
}
