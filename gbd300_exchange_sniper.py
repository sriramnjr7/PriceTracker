"""Flipkart GBD-300 Black (1DR) Order Exchange Sniper & Telemetry Logger.

Features:
1. Continuously polls Flipkart for CASIO G-Shock GBD-300-1DR (Black) stock.
2. Comprehensive Audit Logging: Logs every single check cycle with timestamp,
   price, in_stock status, and response latency to both console and
   `gbd300_exchange_sniper.log`.
3. Notification System (Silent & High-Priority):
   - Telegram Emergency Alert with direct 1-tap Order Exchange link.
   - Native Windows Desktop Notification (Toast).
   - Auto-opens default web browser directly to the Flipkart Order Details page.
   - (Zero audio / no sirens).
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import time
import webbrowser
from datetime import datetime
from logging.handlers import RotatingFileHandler

import httpx

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import settings
from scrapers.flipkart import FlipkartScraper

# =====================================================================
# CONFIGURATION
# =====================================================================
FLIPKART_ORDER_URL = (
    "https://www.flipkart.com/order_details?"
    "order_id=OD439015405806274100&item_id=439015405806274100&unit_id=439015405806274100000"
)
TARGET_PID = "WATH6HSUVHVMZVPW"  # GBD-300-1DR Black
TARGET_URL = (
    f"https://www.flipkart.com/casio-gbd-300-1dr-g-shock-digital-watch-men/p/"
    f"itmd46dfdac5b669?pid={TARGET_PID}"
)
CHECK_INTERVAL_SECONDS = 20  # Polling interval in seconds
LOG_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gbd300_exchange_sniper.log")

# =====================================================================
# LOGGING SETUP: Both Console & Rotating File for Every Entry
# =====================================================================
logger = logging.getLogger("ExchangeSniper")
logger.setLevel(logging.INFO)
logger.propagate = False

# Formatter
log_formatter = logging.Formatter(
    fmt="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# 1. Console Handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_formatter)
logger.addHandler(console_handler)

# 2. File Handler (Keeps up to 10 MB per file, max 5 backups)
file_handler = RotatingFileHandler(
    LOG_FILE_PATH,
    maxBytes=10 * 1024 * 1024,
    backupCount=5,
    encoding="utf-8",
)
file_handler.setFormatter(log_formatter)
logger.addHandler(file_handler)


# =====================================================================
# SILENT NOTIFICATION CHANNELS
# =====================================================================

def show_windows_toast(title: str, message: str) -> None:
    """Show a native Windows Toast notification banner via PowerShell (no audio, no pip dependencies)."""
    powershell_script = f"""
    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
    $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
    $textNodes = $template.GetElementsByTagName("text")
    $textNodes.Item(0).AppendChild($template.CreateTextNode("{title}")) | Out-Null
    $textNodes.Item(1).AppendChild($template.CreateTextNode("{message}")) | Out-Null
    $toast = [Windows.UI.Notifications.ToastNotification]::new($template)
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("SriTrack Sniper").Show($toast)
    """
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", powershell_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        logger.debug("Windows toast error: %s", exc)


async def send_telegram_alert(price: float, url: str) -> bool:
    """Dispatch high-priority alert to your Telegram with direct Order Exchange link."""
    token = getattr(settings, "telegram_bot_token", None) or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = getattr(settings, "telegram_chat_id", None) or os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.warning("Telegram credentials not configured; skipping Telegram dispatch.")
        return False

    msg = (
        "🚨🚨🚨 <b>CASIO GBD-300-1DR (BLACK) IS IN STOCK!</b> 🚨🚨🚨\n\n"
        "⚡ <b>ACTION REQUIRED NOW:</b>\n"
        "The Black GBD-300 has just been detected in stock on Flipkart.\n"
        "Open your order exchange flow immediately to claim the swap!\n\n"
        f"💰 <b>Live Price:</b> ₹{price:,.0f}\n"
        f"📦 <b>Order ID:</b> <code>OD439015405806274100</code>\n\n"
        f"👉 <a href='{FLIPKART_ORDER_URL}'><b>TAP HERE TO OPEN ORDER & EXCHANGE NOW</b></a>\n\n"
        f"🔗 <a href='{url}'>View Flipkart Product Listing</a>"
    )

    api_url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": msg,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(api_url, json=payload)
            if resp.status_code == 200:
                logger.info("Telegram emergency alert dispatched successfully to chat %s!", chat_id)
                return True
            else:
                logger.warning("Telegram dispatch returned %s: %s", resp.status_code, resp.text)
    except Exception as exc:
        logger.error("Failed to send Telegram alert: %s", exc)
    return False


# =====================================================================
# MAIN MONITORING & POLLING LOOP
# =====================================================================

async def run_exchange_sniper():
    """Main polling loop with comprehensive entry-by-entry logging."""
    scraper = FlipkartScraper(settings)

    logger.info("======================================================================")
    logger.info("FLIPKART GBD-300-1DR (BLACK) EXCHANGE SNIPER INITIALIZED")
    logger.info("Target Item   : CASIO GBD-300-1DR (Black - PID: %s)", TARGET_PID)
    logger.info("Flipkart Order: OD439015405806274100")
    logger.info("Check Cadence : Every %s seconds (Infinite loop - runs continuously 24/7)", CHECK_INTERVAL_SECONDS)
    logger.info("Audit Log File: %s", LOG_FILE_PATH)
    logger.info("Notifications : Telegram Alert + Windows Toast + Browser Auto-Open")
    logger.info("Audio Alarm   : DISABLED (Silent notifications only)")
    logger.info("======================================================================")

    check_count = 0

    while True:
        check_count += 1
        t_start = time.perf_counter()

        try:
            res = await scraper.scrape(TARGET_URL)
            latency_ms = round((time.perf_counter() - t_start) * 1000)

            status_str = "IN_STOCK" if res.in_stock else "OUT_OF_STOCK"
            price_val = res.price if res.price else 0.0
            price_str = f"₹{price_val:,.0f}" if price_val > 0 else "None"
            eff_val = getattr(res, "effective_price", None)
            eff_str = f"₹{eff_val:,.0f}" if eff_val else "N/A"

            # Log EVERY entry to both console and rotating log file
            logger.info(
                "CHECK #%-4d | Status: %-12s | Price: %-10s | Eff: %-10s | Latency: %4dms",
                check_count,
                status_str,
                price_str,
                eff_str,
                latency_ms,
            )

            # Trigger when IN_STOCK
            if res.in_stock:
                logger.critical("🚨🚨🚨 IN_STOCK DETECTED FOR GBD-300-1DR (BLACK)! PRICE: %s 🚨🚨🚨", price_str)

                # 1. Windows Native Toast Notification (Silent banner on desktop)
                show_windows_toast(
                    title="🚨 GBD-300 BLACK IS IN STOCK!",
                    message=f"Price: {price_str}. Opening your Flipkart order exchange page...",
                )

                # 2. Open default browser directly to order exchange page
                logger.info("Auto-opening default web browser to Flipkart Order Details...")
                webbrowser.open(FLIPKART_ORDER_URL)

                # 3. Send Telegram Alert
                await send_telegram_alert(price_val, TARGET_URL)

                logger.info("Exchange page opened in browser & Telegram alert sent. Pausing for 10 min to avoid alert spam...")
                await asyncio.sleep(600)

        except Exception as exc:
            latency_ms = round((time.perf_counter() - t_start) * 1000)
            logger.warning("CHECK #%-4d | ERROR: %s | Latency: %4dms", check_count, exc, latency_ms)

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    try:
        asyncio.run(run_exchange_sniper())
    except KeyboardInterrupt:
        logger.info("Exchange Sniper gracefully stopped by user.")
