# Three client markets one after another, each on 20 browsers (slots 41-60), 150 companies.
# Resumable: re-running skips everything already saved (finished markets take about a minute).
Set-Location (Split-Path -Parent $PSScriptRoot)
$markets = @(
    'Global Negative Pressure Wound Therapy (NPWT) Devices Market',
    'Global Advanced Wound Care Market',
    'Global Medical Films Market'
)
foreach ($m in $markets) {
    "=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') start: $m" | Out-File -FilePath 'logs\run_wound_markets.log' -Append -Encoding utf8
    & '.\.venv\Scripts\python.exe' 'logs\run_market.py' $m --keep 150 --browsers 20 2>&1 |
        Out-File -FilePath 'logs\run_wound_markets.log' -Append -Encoding utf8
    "=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') end: $m exit=$LASTEXITCODE" | Out-File -FilePath 'logs\run_wound_markets.log' -Append -Encoding utf8
}
