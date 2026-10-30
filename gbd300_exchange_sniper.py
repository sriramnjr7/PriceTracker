"""Flipkart GBD-300 Black (1DR) Order Exchange Sniper & Audio Alarm.

Purpose:
1. Continuously polls Flipkart for CASIO G-Shock GBD-300-1DR (Black) stock.
2. The instant Black is back in stock:
   - Sounds a loud emergency audio alarm on your PC speakers (winsound).
   - Automatically opens your default logged-in browser directly to your Flipkart Order Details page.
   - Fires a high-priority Telegram alert.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
import webbrowser
from datetime import datetime

# Windows audio alarm
try:
    import winsound
except ImportError:
    winsound = None

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
CHECK_INTERVAL_SECONDS = 20  # Fast, stealth polling frequency

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ExchangeSniper")


def play_alarm():
    """Play a loud emergency siren on PC speakers to wake/alert you immediately."""
    if winsound:
        try:
            for _ in range(5):
                winsound.Beep(1200, 300)
                winsound.Beep(1800, 300)
        except Exception:
            pass
    else:
        # Fallback system bell
        print("\a\a\a\a\a")


async def send_emergency_telegram(price: float, url: str):
    """Dispatch high-priority alert to your Telegram."""
    token = getattr(settings, "telegram_bot_token", None) or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = getattr(settings, "telegram_chat_id", None) or os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.warning("Telegram credentials not configured; skipping Telegram alert.")
        return

    msg = (
        "🚨🚨🚨 <b>CASIO GBD-300-1DR (BLACK) IS IN STOCK!</b> 🚨🚨🚨\n\n"
        "⚡ <b>ACTION REQUIRED NOW:</b>\n"
        "The Black GBD-300 is live on Flipkart. Open your order exchange flow immediately before it sells out!\n\n"
        f"💰 <b>Live Price:</b> ₹{price:,.0f}\n\n"
        f"👉 <a href='{FLIPKART_ORDER_URL}'><b>CLICK HERE TO OPEN YOUR ORDER & EXCHANGE</b></a>\n"
        f"🔗 <a href='{url}'>View Product Page</a>"
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
                logger.info("Telegram emergency alert dispatched successfully!")
            else:
                logger.warning("Telegram dispatch returned %s: %s", resp.status_code, resp.text)
    except Exception as exc:
        logger.error("Failed to send Telegram alert: %s", exc)


async def run_exchange_sniper():
    """Main polling loop."""
    scraper = FlipkartScraper(settings)
    print("\n" + "=" * 70)
    print("🚀 FLIPKART GBD-300-1DR (BLACK) EXCHANGE SNIPER ACTIVE")
    print("=" * 70)
    print(f"🎯 Target Item : CASIO GBD-300-1DR (Black - PID: {TARGET_PID})")
    print(f"📦 Your Order  : OD439015405806274100")
    print(f"⏱️ Check Cadence: Every {CHECK_INTERVAL_SECONDS} seconds")
    print(f"🚨 On In-Stock : Rings PC audio alarm + Opens Order Page in Browser + Telegram Alert")
    print("=" * 70 + "\n")

    consecutive_checks = 0

    while True:
        consecutive_checks += 1
        now_str = datetime.now().strftime("%H:%M:%S")

        try:
            res = await scraper.scrape(TARGET_URL)

            if res.in_stock:
                price = res.price or 11725.0
                print("\n" + "!" * 70)
                print(f"🚨 [{now_str}] IN STOCK DETECTED! Price: ₹{price:,.0f}")
                print("!" * 70)

                # 1. Open default browser directly to order details exchange page
                logger.info("Popping open browser to Flipkart Order Details...")
                webbrowser.open(FLIPKART_ORDER_URL)

                # 2. Fire high-priority Telegram alert
                await send_emergency_telegram(price, TARGET_URL)

                # 3. Sound loud PC alarm
                print("\n🔔 SOUNDING EMERGENCY AUDIO ALARM...")
                for _ in range(3):
                    play_alarm()
                    await asyncio.sleep(0.5)

                print("\n✅ Order page opened in your browser. Complete the exchange now!")
                print("Sleeping for 10 minutes to prevent alert flood...")
                await asyncio.sleep(600)
            else:
                price_disp = f"₹{res.price:,.0f}" if res.price else "N/A"
                print(f"[{now_str}] Check #{consecutive_checks}: Out of Stock (Last Price: {price_disp}) | Next check in {CHECK_INTERVAL_SECONDS}s...", end="\r")

        except Exception as exc:
            logger.warning("[%s] Check failed (will retry): %s", now_str, exc)

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    try:
        asyncio.run(run_exchange_sniper())
    except KeyboardInterrupt:
        print("\n\n🛑 Sniper stopped by user.")
