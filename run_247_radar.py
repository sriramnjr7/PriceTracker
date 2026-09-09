"""24/7 Autonomous Deal Radar & Telegram Interactive Assistant Daemon.

Runs continuous multi-platform deal monitoring and listens for Telegram
user commands (/track, /list, /status, and natural language tracking).
"""

import asyncio
import logging
import os
import sys
from datetime import datetime

workspace_dir = r"c:\Users\srira\Downloads\Antigravity\PriceTracker"
if workspace_dir not in sys.path:
    sys.path.insert(0, workspace_dir)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import settings
from radar import StealRadar
from telegram_bot import TelegramAssistant
from tracker import Tracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("radar_daemon.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("radar_daemon")


async def casio_deal_radar_loop(radar: StealRadar, interval_seconds: int = 90):
    """Dedicated deal radar loop for Casio Bhawar & Flipkart (70%+ OFF & GBD-300)."""
    cycle_count = 0
    while True:
        cycle_count += 1
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n[{now_str}] ⚡ Starting Casio (Bhawar & Flipkart 70%+ / G300) Scan #{cycle_count}...")
        try:
            alerts = await radar.scan_all(only_platforms=["casio", "flipkart"])
            print(f"[{now_str}] ✅ Casio Scan #{cycle_count} completed. ({alerts} alert(s) dispatched)")
        except Exception as exc:
            logger.error("Error during Casio scan #%s: %s", cycle_count, exc)

        print(f"⚡ Sleeping {interval_seconds}s until next Casio scan...\n")
        await asyncio.sleep(interval_seconds)


async def manual_tracker_loop(tracker: Tracker, interval_seconds: int = 300):
    """Checks custom products manually added by the user via Telegram Bot."""
    cycle_count = 0
    while True:
        cycle_count += 1
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n[{now_str}] 📋 Checking Manual Telegram Tracked Products Cycle #{cycle_count}...")
        try:
            tracked_alerts = await tracker.run_once()
            print(f"[{now_str}] ✅ Manual Track Cycle #{cycle_count} completed. ({tracked_alerts} custom alert(s))")
        except Exception as exc:
            logger.error("Error during manual tracker cycle #%s: %s", cycle_count, exc)

        print(f"💤 Sleeping {interval_seconds}s until next manual tracker pass...\n")
        await asyncio.sleep(interval_seconds)


async def main():
    radar = StealRadar(settings)
    await radar.init()

    tracker = Tracker(radar.db, radar.notifier, settings)

    tg_bot = TelegramAssistant(settings, db=radar.db)
    await tg_bot.init()

    print("\n" + "=" * 70)
    print("🚀 CASIO (BHARAWAR & FLIPKART) & TELEGRAM DEAL HUNTER STARTED")
    print("🎯 Target 1: Casio Store Bhawar (70%+ Clearance & GBD-300 Watcher)")
    print("🎯 Target 2: Flipkart Casio Deals (70%+ Brand Facet)")
    print("🎯 Target 3: Manual Telegram User Tracked Products")
    print("📱 Telegram 2-Way Bot: ACTIVE (@my_steal_radar_bot)")
    print("⏰ Casio Deal Sweep: Every 90s | Manual Tracking Pass: Every 300s")
    print("=" * 70 + "\n")

    # Run Casio deals hunter, manual Telegram tracker, and interactive bot listener concurrently
    try:
        await asyncio.gather(
            casio_deal_radar_loop(radar, interval_seconds=90),
            manual_tracker_loop(tracker, interval_seconds=300),
            tg_bot.listen_loop(),
        )
    except (KeyboardInterrupt, SystemExit):
        print("\n🛑 24/7 Daemon stopped by user.")
    finally:
        tg_bot.stop()
        await radar.close()


if __name__ == "__main__":
    asyncio.run(main())
