@echo off
title Flipkart Edifice Glitch Sniper (15s Loop)
cd /d "%~dp0"
echo ======================================================================
echo    STARTING CASIO EDIFICE (EFS-S650DC) PRICING GLITCH SNIPER
echo    Cadence: Every 15s ^| Threshold: ^<= Rs 1,500 (MRP Rs 17,995)
echo ======================================================================
echo.
python edifice_glitch_sniper.py
pause
