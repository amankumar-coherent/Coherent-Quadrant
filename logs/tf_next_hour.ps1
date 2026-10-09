# Trade Finance: after the found candidates are verified and the next country sweep starts,
# let it run 60 minutes, then stop it, keep everything, verify the last finds and build the report.
Set-Location 'C:\Users\aman.kumar\Downloads\Coherent-Quadrant'
$log = 'logs\run_trade_finance.log'
$base = (Get-Content $log | Select-String -Pattern 'country by country').Count
while ((Get-Content $log | Select-String -Pattern 'country by country').Count -le $base) { Start-Sleep 30 }
Start-Sleep 3600
Get-CimInstance Win32_Process | Where-Object {
  ($_.Name -eq 'python.exe' -and ($_.CommandLine -like '*run_trade_finance*' -or $_.CommandLine -like '*parallel_topup*' -or ($_.CommandLine -like '*discover_verify_rounds*' -and $_.CommandLine -like '*Trade Finance*'))) -or
  ($_.Name -eq 'powershell.exe' -and $_.CommandLine -like '*run_trade_finance.ps1*') -or
  ($_.Name -in 'chrome.exe','chromium.exe' -and $_.CommandLine -match 'ai_mode_batch_4[1-5]') } |
  ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }
Start-Sleep 5
$env:PYTHONIOENCODING = 'utf-8'
$P = 'output\chatgpt_expand\global_trade_finance_market_global\_pipeline'
& '.\.venv\Scripts\python.exe' 'scripts\parallel_topup.py' --market 'Global Trade Finance Market' --country global --keep 330 --merge-only 2>&1 |
  Out-File 'logs\tf_next_hour.log' -Append -Encoding utf8
Remove-Item "$P\verify_only_done" -ErrorAction SilentlyContinue
'country sweep stopped after one more hour (owner request)' | Out-File "$P\country_topup_done" -Encoding utf8
Start-Process powershell.exe -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','C:\Users\aman.kumar\Downloads\Coherent-Quadrant\logs\run_trade_finance.ps1' -WorkingDirectory 'C:\Users\aman.kumar\Downloads\Coherent-Quadrant'
"stopped at $(Get-Date -Format HH:mm), merged, relaunched for final verify + report" | Out-File 'logs\tf_next_hour.log' -Append -Encoding utf8
