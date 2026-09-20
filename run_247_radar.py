"""24/7 Autonomous Deal Radar & Telegram Interactive Assistant Daemon.

Runs continuous multi-platform deal monitoring and listens for Telegram
user commands (/track, /list, /status, and natural language tracking).
"""

import asyncio
import logging
import os
import sys
from datetime import datetime

workspace_dir = os.path.dirname(os.path.abspath(__file__))
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


async def run_single_pass() -> int:
    """Execute a single complete sweep (Casio Bhawar + Flipkart deals + manual products)."""
    print("\n⚡ [PriceTracker] Executing Single Sweep (GitHub Actions / Scheduled Runner)...")
    radar = StealRadar(settings)
    await radar.init()
    try:
        try:
            casio_alerts = await asyncio.wait_for(
                radar.scan_all(only_platforms=["casio", "flipkart"]),
                timeout=90.0,
            )
            print(f"✅ Deal Radar scan completed: {casio_alerts} deal alert(s) dispatched.")
        except asyncio.TimeoutError:
            print("⚠️ Deal Radar scan timed out after 90s — continuing to tracked products.")
            casio_alerts = 0

        tracker = Tracker(radar.db, radar.notifier, settings)
        try:
            tracked_alerts = await asyncio.wait_for(
                tracker.run_once(),
                timeout=120.0,
            )
            print(f"✅ Tracked products check completed: {tracked_alerts} alert(s) dispatched.")
        except asyncio.TimeoutError:
            print("⚠️ Tracked products check timed out after 120s.")
            tracked_alerts = 0

        total = casio_alerts + tracked_alerts
        print(f"🎯 Total alerts sent: {total}\n")

        # Check and dispatch periodic Telegram heartbeat if due
        try:
            from heartbeat import check_and_send_heartbeat
            await check_and_send_heartbeat(radar.db, radar.notifier, settings)
        except Exception as hb_exc:
            logger.debug("Heartbeat check error: %s", hb_exc)

        return total
    finally:
        await radar.close()


async def run_repeating_sweep(repeats: int = 3, interval_seconds: int = 110) -> int:
    """Execute multiple consecutive sweeps within a single runner invocation (e.g. 3 passes every ~2 mins)."""
    total_alerts = 0
    radar = StealRadar(settings)
    await radar.init()
    try:
        tracker = Tracker(radar.db, radar.notifier, settings)
        for i in range(1, repeats + 1):
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"\n[{now_str}] ⚡ [PriceTracker Runner] Starting Pass {i}/{repeats}...")
            try:
                casio_alerts = await radar.scan_all(only_platforms=["casio", "flipkart"])
                print(f"[{now_str}] ✅ Deal Radar scan: {casio_alerts} deal alert(s).")
                tracked_alerts = await tracker.run_once()
                print(f"[{now_str}] ✅ Tracked items check: {tracked_alerts} alert(s).")
                total_alerts += casio_alerts + tracked_alerts
                
                # Check periodic heartbeat
                try:
                    from heartbeat import check_and_send_heartbeat
                    await check_and_send_heartbeat(radar.db, radar.notifier, settings)
                except Exception as hb_exc:
                    logger.debug("Heartbeat check error: %s", hb_exc)
            except Exception as exc:
                logger.error("Error during runner pass #%s: %s", i, exc)


            if i < repeats:
                print(f"⏳ Sleeping {interval_seconds}s until next pass in this runner...")
                await asyncio.sleep(interval_seconds)

        print(f"\n🎯 [PriceTracker Runner] All {repeats} passes completed. Total alerts sent: {total_alerts}\n")
        return total_alerts
    finally:
        await radar.close()


async def main():
    if "--once" in sys.argv:
        await run_single_pass()
        return

    if "--repeat" in sys.argv or "--interval" in sys.argv:
        repeats = 3
        interval = 110
        for i, arg in enumerate(sys.argv):
            if arg == "--repeat" and i + 1 < len(sys.argv) and sys.argv[i + 1].isdigit():
                repeats = int(sys.argv[i + 1])
            elif arg == "--interval" and i + 1 < len(sys.argv) and sys.argv[i + 1].isdigit():
                interval = int(sys.argv[i + 1])
        await run_repeating_sweep(repeats=repeats, interval_seconds=interval)
        return

    radar = StealRadar(settings)
    await radar.init()

    tracker = Tracker(radar.db, radar.notifier, settings)

    tg_bot = TelegramAssistant(settings, db=radar.db)
    await tg_bot.init()

    manual_interval = 120
    casio_interval = 90
    for arg in sys.argv[1:]:
        if arg.isdigit():
            manual_interval = int(arg)
            casio_interval = min(90, int(arg))

    print("\n" + "=" * 70)
    print("🚀 PRICETRACKER 24/7 AUTONOMOUS DEAL & PRICE RADAR STARTED")
    print("🎯 Target 1: Casio Store Bhawar (70%+ Silent Deals & GBD-300 Watcher)")
    print("🎯 Target 2: Flipkart Casio Deals (70%+ Brand Facet)")
    print("🎯 Target 3: Tracked Products (Crocs LiteRide 360 All Variants / User Items)")
    print("📱 Telegram 2-Way Bot: ACTIVE")
    print(f"⏰ Casio Deal Sweep: Every {casio_interval}s | Tracked Items Sweep: Every {manual_interval}s")
    print("=" * 70 + "\n")

    # Run Casio deals hunter, manual Telegram tracker, and interactive bot listener concurrently
    try:
        await asyncio.gather(
            casio_deal_radar_loop(radar, interval_seconds=casio_interval),
            manual_tracker_loop(tracker, interval_seconds=manual_interval),
            tg_bot.listen_loop(),
        )
    except (KeyboardInterrupt, SystemExit):
        print("\n🛑 24/7 Daemon stopped by user.")
    finally:
        tg_bot.stop()
        await radar.close()


if __name__ == "__main__":
    asyncio.run(main())
