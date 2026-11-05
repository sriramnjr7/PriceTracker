"""Flipkart CASIO EDIFICE (EFS-S650DC-1ADF) Glitch Sniper & Telemetry Logger.

Features:
1. High-speed 15s polling for the ₹1,420 pricing glitch.
2. Silent & High-Priority Notifications:
   - Telegram Emergency Alert with direct 1-tap Buy link.
   - Native Windows Desktop Notification (Toast).
   - Auto-opens web browser directly to the product buy page.
3. Rotating file and console audit logging.
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
TARGET_PID = "WATHGXZJSNKU7ADE"
TARGET_URL = (
    f"https://www.flipkart.com/casio-efs-s650dc-1adf-edifice-analog-watch-men/p/"
    f"itm2c0ecbb8a88aa?pid={TARGET_PID}"
)
TARGET_PRICE_FLOOR = 1500.0  # Glitch price threshold (<= ₹1,500)
CHECK_INTERVAL_SECONDS = 15   # Fast 15s polling cadence
LOG_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "edifice_glitch_sniper.log")

# =====================================================================
# LOGGING SETUP
# =====================================================================
logger = logging.getLogger("EdificeGlitchSniper")
logger.setLevel(logging.INFO)
logger.propagate = False

log_formatter = logging.Formatter(
    fmt="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_formatter)
logger.addHandler(console_handler)

file_handler = RotatingFileHandler(
    LOG_FILE_PATH,
    maxBytes=10 * 1024 * 1024,
    backupCount=5,
    encoding="utf-8",
)
file_handler.setFormatter(log_formatter)
logger.addHandler(file_handler)


def show_windows_toast(title: str, message: str) -> None:
    """Show a native Windows Toast notification banner via PowerShell."""
    powershell_script = f"""
    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
    $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
    $textNodes = $template.GetElementsByTagName("text")
    $textNodes.Item(0).AppendChild($template.CreateTextNode("{title}")) | Out-Null
    $textNodes.Item(1).AppendChild($template.CreateTextNode("{message}")) | Out-Null
    $toast = [Windows.UI.Notifications.ToastNotification]::new($template)
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("SriTrack Glitch Sniper").Show($toast)
    """
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", powershell_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        logger.debug("Windows toast error: %s", exc)


async def send_telegram_alert(price: float, eff_price: float | None = None) -> None:
    """Dispatch immediate Telegram alert with 1-click Buy Now button."""
    bot_token = settings.telegram_bot_token
    chat_id = settings.telegram_chat_id
    if not bot_token or not chat_id:
        return

    price_str = f"₹{price:g}"
    eff_str = f"\n💳 *Effective Offer Price:* ₹{eff_price:g}" if eff_price and eff_price < price else ""

    text = (
        "🚨🚨🚨 *PRICING GLITCH RESTOCK ALERT!* 🚨🚨🚨\n\n"
        "⚡ *Item:* CASIO EDIFICE Solar Sapphire (EFS-S650DC-1ADF)\n"
        "🔥 *STATUS: IN STOCK RIGHT NOW!*\n"
        f"💰 *Glitch Price:* {price_str} *(MRP: ₹17,995 - 92% OFF!)*{eff_str}\n"
        "🎯 *Target Threshold:* <= ₹1,500 (TARGET MET!)\n\n"
        f"🛒 *BUY IMMEDIATELY:* {TARGET_URL}\n\n"
        "⚡ *Dispatched via Local Glitch Radar (15s cadence)*"
    )

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": {
            "inline_keyboard": [
                [{"text": "🛒 BUY NOW INSTANTLY", "url": TARGET_URL}]
            ]
        },
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                logger.info("⚡ [TELEGRAM] Glitch Alert dispatched successfully!")
            else:
                logger.error("[TELEGRAM] Failed to dispatch alert: %s", resp.text)
    except Exception as exc:
        logger.error("[TELEGRAM] Error sending Telegram alert: %s", exc)


async def run_sniper() -> None:
    scraper = FlipkartScraper(settings)
    check_num = 0

    print("=" * 70)
    print("🔥 CASIO EDIFICE GLITCH SNIPER (EFS-S650DC-1ADF)")
    print(f"🎯 Target Threshold : <= ₹{TARGET_PRICE_FLOOR:g} (MRP: ₹17,995)")
    print(f"⏱️ Cadence          : Every {CHECK_INTERVAL_SECONDS}s")
    print(f"📦 Product URL      : {TARGET_URL}")
    print(f"📄 Audit Log        : {LOG_FILE_PATH}")
    print("=" * 70)

    while True:
        check_num += 1
        t0 = time.monotonic()
        try:
            result = await scraper.scrape(TARGET_URL)
            latency_ms = int((time.monotonic() - t0) * 1000)

            price = result.price or 1420.0
            eff = getattr(result, "effective_price", None)
            in_stock = bool(result.in_stock)

            status_str = "IN_STOCK" if in_stock else "OUT_OF_STOCK"
            p_display = f"₹{price:,.0f}" if price else "N/A"
            eff_display = f"₹{eff:,.0f}" if eff else p_display

            logger.info(
                "CHECK #%-4d | Status: %-12s | Price: %-10s | Eff: %-10s | Latency: %4dms",
                check_num, status_str, p_display, eff_display, latency_ms
            )

            # Trigger condition: in stock AND price <= ₹1,500
            if in_stock and price <= TARGET_PRICE_FLOOR:
                logger.warning("🚨🚨🚨 GLITCH ACTIVE! Price: ₹%s <= ₹%s! TRIGGERING SNIPER!", price, TARGET_PRICE_FLOOR)

                # 1. Open browser directly to product page
                try:
                    webbrowser.open(TARGET_URL)
                except Exception as b_err:
                    logger.debug("Failed opening browser: %s", b_err)

                # 2. Windows Toast Notification
                show_windows_toast(
                    "🔥 EDIFICE GLITCH RESTOCKED!",
                    f"Price: ₹{price:g} (MRP: ₹17,995). Buy now!"
                )

                # 3. Telegram alert
                await send_telegram_alert(price, eff)

        except Exception as exc:
            latency_ms = int((time.monotonic() - t0) * 1000)
            logger.warning("CHECK #%-4d | Exception: %s | Latency: %4dms", check_num, exc, latency_ms)

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    try:
        asyncio.run(run_sniper())
    except KeyboardInterrupt:
        print("\nSniper stopped by user.")
