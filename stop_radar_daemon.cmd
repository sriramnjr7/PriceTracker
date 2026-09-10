@echo off
title Stop PriceTracker Radar Daemon
color 0C
cls

echo ======================================================================
echo              STOPPING PRICETRACKER RADAR DAEMON
echo ======================================================================
echo.

wmic process where "commandline like '%%run_247_radar.py%%'" call terminate >nul 2>&1
powershell -Command "Get-CimInstance Win32_Process -Filter \"CommandLine like '%%run_247_radar.py%%'\" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1

echo [OK] Any running PriceTracker radar processes have been terminated.
echo.
timeout /t 3
exit
