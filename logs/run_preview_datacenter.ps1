# PREVIEW of the 2026-10-15 pipeline changes (per-part supporting points, research panel, "As per our findings").
# Runs on a COPY of Global Data Center Market in output\chatgpt_expand_preview\ -- the delivered report in
# output\chatgpt_expand\ is not touched (EXPAND_OUTPUT_FOLDER redirects every step).
Set-Location (Split-Path -Parent $PSScriptRoot)
$env:EXPAND_OUTPUT_FOLDER = 'chatgpt_expand_preview'
$env:PYTHONIOENCODING = 'utf-8'
$log = 'logs\run_preview_datacenter.log'
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') start: preview Global Data Center Market" | Out-File -FilePath $log -Append -Encoding utf8
& '.\.venv\Scripts\python.exe' 'scripts\run_quadrant_pipeline.py' --market 'Global Data Center Market' --country global --keep 200 --slots 41-60 --evidence-slots 41-60 --max-discover-rounds 0 2>&1 |
    Out-File -FilePath $log -Append -Encoding utf8
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') end: preview exit=$LASTEXITCODE" | Out-File -FilePath $log -Append -Encoding utf8
