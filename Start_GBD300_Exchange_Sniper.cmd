@echo off
title Flipkart GBD-300 Black Exchange Sniper
color 0A
cd /d "%~dp0"
echo ======================================================================
echo    FLIPKART CASIO G-SHOCK GBD-300-1DR (BLACK) EXCHANGE SNIPER
echo ======================================================================
echo.
echo Polling Flipkart for Black 1DR restock...
echo When in-stock:
echo   - PC Audio Alarm will ring
echo   - Your Order Details exchange page will auto-open in your browser
echo   - Telegram emergency notification will be sent
echo.
py -3 gbd300_exchange_sniper.py
pause
