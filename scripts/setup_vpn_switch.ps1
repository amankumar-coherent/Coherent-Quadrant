# One-time setup for the automatic IP switch on a Google block (ip_rotate.py).
#
# Run ONCE from an Administrator PowerShell:
#   powershell -ExecutionPolicy Bypass -File scripts\setup_vpn_switch.ps1 -Configs C:\Users\<you>\vpn\proton_wg
#
# It registers a scheduled task that runs with Administrator rights and switches WireGuard
# to the next config. The pipeline (not elevated) starts that task when Google blocks it,
# so the pipeline itself never needs an Administrator terminal.
param(
    [Parameter(Mandatory = $true)][string]$Configs,
    [string]$TaskName = "CoherentQuadrant_VPN_Switch"
)
$ErrorActionPreference = "Stop"

$wg = "C:\Program Files\WireGuard\wireguard.exe"
if (-not (Test-Path $wg)) {
    throw "WireGuard is not installed. Install it from https://www.wireguard.com/install/ and run this again."
}
$confs = @(Get-ChildItem -Path $Configs -Filter *.conf)
if ($confs.Count -eq 0) { throw "No *.conf files in $Configs" }

$repo = Split-Path -Parent $PSScriptRoot
$cmd = Join-Path $repo "scripts\vpn_switch_task.cmd"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"`"$cmd`" `"$Configs`"`""
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $action -Principal $principal -Settings $settings -Force | Out-Null

Write-Host "Registered task '$TaskName' for $($confs.Count) WireGuard config(s) in $Configs"
Write-Host "Add this line to .env to turn the switch on:"
Write-Host "  GOOGLE_AI_MODE_WIREGUARD_CONFIGS=$Configs"
