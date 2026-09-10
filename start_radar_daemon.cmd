@echo off
title PriceTracker 24/7 Deal & Price Radar
color 0B
cls

echo ======================================================================
echo          PRICETRACKER 24/7 AUTONOMOUS DEAL & PRICE RADAR
echo ======================================================================
echo  Casio Silent Deals (70%%+ OFF): Every 90 seconds
echo  G-Shock & Edifice Deals (50%%+): Every 90 seconds
echo  Tracked Products (Crocs LiteRide 360 / Flipkart / Amazon): Active
echo  Telegram Bot: Active
echo ======================================================================
echo.

cd /d "%~dp0"
if not exist "run_247_radar.py" (
    cd /d "c:\Users\srira\Downloads\Antigravity\PriceTracker"
)

echo Checking Python environment...
py -3 --version >nul 2>&1
if %errorlevel% equ 0 (
    set PY_CMD=py -3
) else (
    python --version >nul 2>&1
    if %errorlevel% equ 0 (
        set PY_CMD=python
    ) else (
        echo [ERROR] Python was not found in PATH!
        echo Please make sure Python 3.11+ is installed.
        pause
        exit /b 1
    )
)

echo Starting radar daemon with %PY_CMD%...
echo.
%PY_CMD% run_247_radar.py

echo.
echo Daemon stopped.
pause
