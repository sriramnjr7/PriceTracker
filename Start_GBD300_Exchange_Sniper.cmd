@echo off
title Flipkart GBD-300 Black Exchange Sniper
color 0A
cd /d "%~dp0"
echo ======================================================================
echo    FLIPKART CASIO G-SHOCK GBD-300-1DR (BLACK) EXCHANGE SNIPER
echo ======================================================================
echo.
echo Polling Flipkart for Black 1DR restock every 20s...
echo Audit Log: All check entries written to gbd300_exchange_sniper.log
echo When in-stock:
echo   - Windows Native Desktop Notification banner
echo   - Your Order Details exchange page will auto-open in your browser
echo   - Telegram emergency notification will be dispatched
echo.
py -3 gbd300_exchange_sniper.py
pause
