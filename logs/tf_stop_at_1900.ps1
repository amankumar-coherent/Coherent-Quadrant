# Trade Finance: stop the country sweep at 19:00, keep everything it found, verify it, then build the report.
Set-Location 'C:\Users\aman.kumar\Downloads\Coherent-Quadrant'
while ((Get-Date) -lt (Get-Date -Hour 19 -Minute 0 -Second 0)) { Start-Sleep 30 }
# 1. stop the running Trade Finance launcher, top-up and its 5 browsers (slots 41-45)
Get-CimInstance Win32_Process | Where-Object {
  ($_.Name -eq 'python.exe' -and ($_.CommandLine -like '*run_trade_finance*' -or $_.CommandLine -like '*parallel_topup*' -or ($_.CommandLine -like '*discover_verify_rounds*' -and $_.CommandLine -like '*Trade Finance*'))) -or
  ($_.Name -eq 'powershell.exe' -and $_.CommandLine -like '*run_trade_finance.ps1*') -or
  ($_.Name -in 'chrome.exe','chromium.exe' -and $_.CommandLine -match 'ai_mode_batch_4[1-5]') } |
  ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }
Start-Sleep 5
$env:PYTHONIOENCODING = 'utf-8'
$P = 'output\chatgpt_expand\global_trade_finance_market_global\_pipeline'
# 2. keep what the browsers verified
& '.\.venv\Scripts\python.exe' 'scripts\parallel_topup.py' --market 'Global Trade Finance Market' --country global --keep 330 --merge-only 2>&1 |
  Out-File 'logs\tf_stop_at_1900.log' -Append -Encoding utf8
# 3. the next launch verifies every found-but-unchecked candidate, skips further discovery, builds the report
Remove-Item "$P\verify_only_done" -ErrorAction SilentlyContinue
'country sweep stopped at 19:00 by owner request (1 hour)' | Out-File "$P\country_topup_done" -Encoding utf8
Start-Process powershell.exe -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','C:\Users\aman.kumar\Downloads\Coherent-Quadrant\logs\run_trade_finance.ps1' -WorkingDirectory 'C:\Users\aman.kumar\Downloads\Coherent-Quadrant'
"stopped at $(Get-Date -Format HH:mm), merged, relaunched for verify + report" | Out-File 'logs\tf_stop_at_1900.log' -Append -Encoding utf8
