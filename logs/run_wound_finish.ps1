# Owner's order 2026-10-12: Medical Films verifies its pending companies (no more discovery),
# then the pending re-runs of NPWT and Advanced Wound Care, then the Medical Films pipeline.
Set-Location (Split-Path -Parent $PSScriptRoot)
$steps = @(
    @('Global Medical Films Market', '--discovery-only'),
    @('Global Negative Pressure Wound Therapy (NPWT) Devices Market', ''),
    @('Global Advanced Wound Care Market', ''),
    @('Global Medical Films Market', '')
)
foreach ($s in $steps) {
    $m = $s[0]; $extra = @(); if ($s[1]) { $extra = @($s[1]) }
    "=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') start: $m $($s[1])" | Out-File -FilePath 'logs\run_wound_markets.log' -Append -Encoding utf8
    & '.\.venv\Scripts\python.exe' 'logs\run_market.py' $m --keep 150 --browsers 20 @extra 2>&1 |
        Out-File -FilePath 'logs\run_wound_markets.log' -Append -Encoding utf8
    "=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') end: $m $($s[1]) exit=$LASTEXITCODE" | Out-File -FilePath 'logs\run_wound_markets.log' -Append -Encoding utf8
}
