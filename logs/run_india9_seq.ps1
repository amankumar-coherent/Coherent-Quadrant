# 9 India drone / geospatial markets, ONE AT A TIME on 10 browsers (slots 41-50), owner 2026-10-14.
# Each market resumes from its saved work; when it ends the next one starts automatically.
# Order: most advanced first. Cap 120, India only.
Set-Location (Split-Path -Parent $PSScriptRoot)
$order = @(
    'AI in Geospatial Imaging & Remote Sensing Market',
    'Drone Surveying & LiDAR Mapping Market',
    'Geospatial Analytics / GIS Market',
    'Commercial Drone Services Market',
    'Telecom Tower Inspection & Maintenance Market',
    'Digital Twin Market - Infrastructure, Utilities & Smart Cities',
    'Drone-Based Infrastructure Inspection Market',
    'Power Line, Utility Asset & Vegetation Management Drone Market',
    'Precision Agriculture & Agricultural Drone Market'
)
$queue = 'logs\india9_seq.log'
foreach ($m in $order) {
    $tag = ($m -replace '[^A-Za-z0-9]+', '_').Trim('_').ToLower()
    $log = "logs\india9_$tag.log"
    "=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') start: $m (india, 10 browsers, slots 41-50)" | Out-File -FilePath $log -Append -Encoding utf8
    "$(Get-Date -Format 'HH:mm:ss') START $m" | Out-File -FilePath $queue -Append -Encoding utf8
    & '.\.venv\Scripts\python.exe' 'logs\run_market.py' $m --country india --keep 120 --browsers 10 --slot-start 41 --global-focus --discover-to 120 2>&1 |
        Out-File -FilePath $log -Append -Encoding utf8
    "$(Get-Date -Format 'HH:mm:ss') END   $m exit=$LASTEXITCODE" | Out-File -FilePath $queue -Append -Encoding utf8
}
"$(Get-Date -Format 'HH:mm:ss') ALL DONE" | Out-File -FilePath $queue -Append -Encoding utf8
