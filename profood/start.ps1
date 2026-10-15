# ProFood India -- 75 Coherent Quadrant markets, one command:
#     powershell -ExecutionPolicy Bypass -File profood\start.ps1
# First time on a machine it installs everything (setup.bat). Then it starts the
# queue in the background (no window to keep open) and returns. Re-running it
# resumes: finished markets are skipped, every market continues from saved work.
# Extra options go straight to the queue, e.g.  profood\start.ps1 --only FP-01,FP-02
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "First run on this machine: installing (setup.bat) ..."
    & cmd /c setup.bat
    if (-not (Test-Path ".venv\Scripts\python.exe")) { Write-Host "setup.bat failed -- see its output above."; exit 1 }
}
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
$key = Select-String -Path ".env" -Pattern "^DEEPSEEK_API_KEY=(\S+)" | Select-Object -First 1
if (-not $key -or $key.Matches[0].Groups[1].Value -match 'PASTE') {
    Write-Host "Put your DeepSeek key in .env (DEEPSEEK_API_KEY=...) and run this again."
    exit 1
}
$running = Get-CimInstance Win32_Process -Filter "name='python.exe'" |
    Where-Object { $_.CommandLine -match 'profood\\run_queue\.py' -and $_.CommandLine -notmatch '--status' }
if ($running) { Write-Host "The ProFood queue is already running (pid $($running[0].ProcessId))."; exit 0 }

New-Item -ItemType Directory -Force -Path "logs\profood" | Out-Null
$extra = ($args -join ' ')
$cmd = "& '.\.venv\Scripts\python.exe' 'profood\run_queue.py' $extra *>> 'logs\profood\console.log'"
# conhost --headless: no window; closing a terminal cannot stop the run.
$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine      = "conhost.exe --headless powershell.exe -NoProfile -ExecutionPolicy Bypass -Command `"$cmd`""
    CurrentDirectory = $root
}
Write-Host "ProFood queue started in the background (pid $($r.ProcessId))."
Write-Host "Progress:  .venv\Scripts\python.exe profood\run_queue.py --status"
Write-Host "Live log:  logs\profood\queue.log   (one log per market in logs\profood\)"
Write-Host "Stop:      powershell -ExecutionPolicy Bypass -File profood\stop.ps1"
