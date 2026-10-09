# After the 10-market fire update batch: re-run the checks-only update for the 3 markets that got
# placeholder-HQ companies added (only those companies are asked), then refresh the Final folders.
Set-Location 'C:\Users\aman.kumar\Downloads\Coherent-Quadrant'
while (-not (Select-String -Path 'logs\run_fire_india_10.log' -Pattern '^exit=' -Quiet)) { Start-Sleep 30 }
$env:GOOGLE_AI_MODE_QUERY_DELAY = '10'
$env:PYTHONIOENCODING = 'utf-8'
foreach ($m in 'disaster_response','electrical_fire_safety','emergency_communications') {
  Remove-Item "output\chatgpt_expand\$($m)_industry_analysis_india\_pipeline\report_update_done" -ErrorAction SilentlyContinue
}
& '.\.venv\Scripts\python.exe' 'scripts\run_markets_parallel.py' --markets-file 'queries\fire_india_hq_recheck.txt' --workers 3 --slot-start 46 --top-n 20 -- --max-discover-rounds 0 --update-report auto 2>&1 |
    Out-File -FilePath 'logs\run_fire_hq_recheck.log' -Append -Encoding utf8
& '.\.venv\Scripts\python.exe' 'logs\build_final_folders.py' 2>&1 | Out-File -FilePath 'logs\run_fire_hq_recheck.log' -Append -Encoding utf8
"exit=$LASTEXITCODE" | Out-File -FilePath 'logs\run_fire_hq_recheck.log' -Append -Encoding utf8
