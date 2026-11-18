@echo off
rem Elevated half of the IP switch (vendor_intel.scraping.ip_rotate): run by the scheduled
rem task that scripts\setup_vpn_switch.ps1 registers. Moves WireGuard to the next config.
rem %1 = folder of WireGuard *.conf files.
cd /d "%~dp0.."
set PYTHONPATH=src
set IP_ROTATE_IN_TASK=1
set GOOGLE_AI_MODE_WIREGUARD_CONFIGS=%~1
".venv\Scripts\python.exe" -m vendor_intel.scraping.ip_rotate wg-next >> "logs\vpn_switch.log" 2>&1
