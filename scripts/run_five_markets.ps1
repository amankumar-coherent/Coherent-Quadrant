# Batch-run 5 Coherent Quadrant markets.
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\run_five_markets.ps1

param(
    [string]$ScraperUrl = "",
    [int]$TableCompanies = 300,
    [int]$ChartCompanies = 20,
    [switch]$SkipDeepCrawl
)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$py = Join-Path (Get-Location) ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    throw "Missing .venv - create/activate venv first"
}

$env:PYTHONPATH = "src"
$env:QUADRANT_SCORE_ALL_TABLE = "true"
$env:QUADRANT_CRAWL_MODE = "business"
$env:QUADRANT_CRAWL_MAX_PAGES = "60"
$env:QUADRANT_GEO_DISCOVERY = "true"
$env:AI_OVERVIEW_DEEPSEEK_CLEAN = "true"
$env:GOOGLE_AI_SCRAPER_ENABLED = "true"

$batchArgs = @(
    "scripts\run_markets_batch.py",
    "--table-companies", "$TableCompanies",
    "--max-companies", "$ChartCompanies"
)
if ($ScraperUrl) {
    $batchArgs += @("--scraper-url", $ScraperUrl)
}
if ($SkipDeepCrawl) {
    $batchArgs += "--skip-deep-crawl"
}

& $py @batchArgs
exit $LASTEXITCODE
