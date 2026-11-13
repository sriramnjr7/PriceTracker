@echo off
title Flipkart One-Time Login Session Builder
cd /d "%~dp0"
echo ======================================================================
echo    FLIPKART ONE-TIME LOGIN SESSION BUILDER
echo ======================================================================
echo.
echo  A visible Chrome window will open.
echo  1. Enter your mobile number and OTP to log into your account (Sriram).
echo  2. Ensure your delivery pincode is active.
echo  3. Return to this window and press ENTER to save your session cookies.
echo.
echo ======================================================================
python login_flipkart.py
echo.
echo Session export complete! You can now launch Start_Local_Multi_Sniper.cmd
pause

