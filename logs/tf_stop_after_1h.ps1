# Trade Finance: let the country-by-country sweep run 60 minutes, then stop its discovery workers.
# parallel_topup then merges what they found and run_trade_finance.py continues into the pipeline.
Set-Location 'C:\Users\aman.kumar\Downloads\Coherent-Quadrant'
$log = 'logs\run_trade_finance.log'
$base = (Get-Content $log | Select-String -Pattern 'country by country').Count
while ((Get-Content $log | Select-String -Pattern 'country by country').Count -le $base) { Start-Sleep 30 }
"[stopper] country sweep started $(Get-Date -Format HH:mm); stopping it in 60 minutes" | Out-File $log -Append -Encoding utf8
Start-Sleep 3600
Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*discover_verify_rounds*' -and $_.CommandLine -like '*Trade Finance*' } |
  ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }
Get-CimInstance Win32_Process | Where-Object { $_.Name -in 'chrome.exe','chromium.exe' -and $_.CommandLine -match 'ai_mode_batch_4[1-5]' } |
  ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }
"[stopper] country sweep stopped after 60 minutes $(Get-Date -Format HH:mm); merging and building the report" | Out-File $log -Append -Encoding utf8
