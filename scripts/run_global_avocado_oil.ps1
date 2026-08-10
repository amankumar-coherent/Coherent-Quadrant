# Run main quality pipeline + Coherent Quadrant for Global Avocado Oil (Docker).
# Prerequisites:
#   1. Copy .env.example → .env and paste an LLM API key (USE_MOCK_DATA=false, QUADRANT_ENABLED=true)
#   2. Docker Desktop running
#
# Usage (from repo root, PowerShell):
#   .\scripts\run_global_avocado_oil.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if (-not (Test-Path ".env")) {
  Write-Error ".env missing. Run: Copy-Item .env.example .env  then paste an LLM API key."
}

New-Item -ItemType Directory -Force -Path "output\pipeline", "output\quadrant" | Out-Null

Write-Host "==> Starting postgres + searxng…"
docker compose up -d --build postgres searxng

Write-Host "==> Waiting for SearXNG on :8080…"
$ready = $false
for ($i = 1; $i -le 30; $i++) {
  try {
    Invoke-WebRequest -Uri "http://127.0.0.1:8080" -UseBasicParsing -TimeoutSec 2 | Out-Null
    $ready = $true
    break
  } catch {
    Start-Sleep -Seconds 2
  }
}
if (-not $ready) {
  Write-Warning "SearXNG not responding yet — pipeline will fall back to DDGS/Bing HTML."
}

Write-Host "==> Pipeline + Quadrant: Avocado Oil Market (global)"
docker compose run --rm --entrypoint "" `
  -e SEARXNG_BASE_URL=http://searxng:8080 `
  -e QUADRANT_ENABLED=true `
  -e USE_MOCK_DATA=false `
  app `
  python run_pipeline.py `
    --input-json queries/briefs/global_avocado_oil.json `
    --global `
    --live `
    --profile quality

Write-Host ""
Write-Host "==> Done. Look for:"
Write-Host "  output\pipeline\pipeline_avocado_oil_market_global.*"
Write-Host "  output\quadrant\*avocado*oil*_quadrant.json"
Get-ChildItem -Path "output\quadrant" -ErrorAction SilentlyContinue | Format-Table Name, Length, LastWriteTime
Get-ChildItem -Path "output\pipeline" -Filter "*avocado*" -ErrorAction SilentlyContinue | Format-Table Name, Length, LastWriteTime
