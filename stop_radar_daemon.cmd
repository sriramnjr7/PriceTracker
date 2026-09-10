@echo off
title Stop SriTrack Radar Daemon
color 0C
cls

echo ======================================================================
echo                 STOPPING SRITRACK RADAR DAEMON
echo ======================================================================
echo.

wmic process where "commandline like '%%run_247_radar.py%%'" call terminate >nul 2>&1

echo [OK] Any running SriTrack radar processes have been terminated.
echo.
timeout /t 3
exit
