# Start Google AI scraper on port 15561 for this project's Chrome profile.
param([int]$Port = 15561)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$serverDir = Join-Path $root "google-ai-scraper-main\google-ai-scraper-main\server"
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $serverDir)) { throw "Scraper server not found: $serverDir" }
if (-not (Test-Path $py)) { throw "Missing .venv python" }

Write-Host "Starting scraper on port $Port ..." -ForegroundColor Cyan
$env:PYTHONPATH = $serverDir
Start-Process -FilePath $py -ArgumentList @(
    "-m", "uvicorn", "google_ai_scraper.app:app",
    "--host", "127.0.0.1", "--port", "$Port"
) -WorkingDirectory $serverDir -WindowStyle Minimized

Start-Sleep -Seconds 4
try {
    $h = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 5
    Write-Host ($h | ConvertTo-Json -Compress) -ForegroundColor Green
    if (-not $h.extension_connected) {
        Write-Host "Server is up. In THIS Chrome: extension URL = http://localhost:$Port then click the extension refresh icon." -ForegroundColor Yellow
    }
} catch {
    Write-Host "Server starting - retry health: http://127.0.0.1:$Port/health" -ForegroundColor Yellow
}
