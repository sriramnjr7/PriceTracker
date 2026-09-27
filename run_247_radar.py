"""24/7 Autonomous Deal Radar & Telegram Interactive Assistant Daemon.

Runs continuous multi-platform deal monitoring and listens for Telegram
user commands (/track, /list, /status, and natural language tracking).
"""

import asyncio
import logging
import os
import re
import sys
from datetime import datetime
import httpx

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
            alerts = await radar.scan_all(only_platforms=["casio", "flipkart", "myntra"])
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


async def supabase_log_shipper_loop(interval_seconds: int = 15):
    """Continuously flush new radar daemon log entries to Supabase so Vercel UI sees them in real-time."""
    supabase_url = getattr(settings, "supabase_url", None) or os.getenv("SUPABASE_URL", "").rstrip("/")
    supabase_key = getattr(settings, "supabase_key", None) or os.getenv("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        return

    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
    }

    log_path = "radar_daemon.log"
    last_pos = 0
    if os.path.exists(log_path):
        try:
            last_pos = max(0, os.path.getsize(log_path) - 80000)
        except Exception:
            last_pos = 0

    pat_std = re.compile(
        r"^(?P<timestamp>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}[,\.]\d{3})\s+\[(?P<level>[A-Z]+)\]\s+(?P<logger>[^:]+):\s+(?P<message>.*)$"
    )
    pat_bracket = re.compile(
        r"^\[(?P<timestamp>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\]\s+(?P<message>.*)$"
    )

    while True:
        try:
            await asyncio.sleep(interval_seconds)
            if not os.path.exists(log_path):
                continue

            current_size = os.path.getsize(log_path)
            if current_size < last_pos:
                last_pos = 0

            if current_size == last_pos:
                continue

            read_bytes = min(current_size - last_pos, 200000)
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(last_pos)
                chunk = f.read(read_bytes)
                last_pos = f.tell()

            lines = [l.strip() for l in chunk.splitlines() if l.strip()]
            if not lines:
                continue

            batch = []
            for l in lines[-60:]:
                m1 = pat_std.match(l)
                m2 = pat_bracket.match(l)
                if m1:
                    d = m1.groupdict()
                    batch.append({
                        "name": "DAEMON_LOG",
                        "category": d["level"].upper(),
                        "platforms": d["logger"].strip()[:50],
                        "query": d["message"][:1000],
                        "negative_keywords": l[:1500],
                        "is_active": False,
                    })
                elif m2:
                    d = m2.groupdict()
                    lvl = "WARNING" if "warn" in l.lower() else "INFO"
                    batch.append({
                        "name": "DAEMON_LOG",
                        "category": lvl,
                        "platforms": "radar",
                        "query": d["message"][:1000],
                        "negative_keywords": l[:1500],
                        "is_active": False,
                    })

            if batch:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    await client.post(f"{supabase_url}/rest/v1/custom_radar_rules", headers=headers, json=batch)

        except Exception as exc:
            logger.debug("Supabase log shipper tick error: %s", exc)


VIP_WATCHES = [
    {
        "id": 58,
        "name": "CASIO G-SHOCK GBD-H2000-1A9 G-SQUAD",
        "url": "https://casiostore.bhawar.com/products/casio-g-shock-gbd-h2000-1a9-g-squad-digital-sports-watch",
        "target_price": 14000.0,
        "default_price": 13499.0,
        "mrp": 44995,
        "tag": "gbd-h2000",
    },
    {
        "id": 5,
        "name": "CASIO G-SHOCK GBD-300-9DR",
        "url": "https://casiostore.bhawar.com/products/casio-g-shock-gbd-300-9dr-watch",
        "target_price": 4000.0,
        "default_price": 3495.0,
        "mrp": 11495,
        "tag": "gbd-300-9dr",
    },
]


async def ship_vip_log_to_supabase(watch: dict, status_str: str, price: float, http_code: int, detail: str = ""):
    """Instantly flush a structured VIP probe log into Supabase for Vercel/UI live view."""
    supabase_url = getattr(settings, "supabase_url", None) or os.getenv("SUPABASE_URL", "").rstrip("/")
    supabase_key = getattr(settings, "supabase_key", None) or os.getenv("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        return
    now_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload = [
        {
            "name": "VIP_LOG",
            "category": status_str,
            "platforms": watch.get("tag", "vip"),
            "query": f"{watch['name']} -> {status_str} (Price: ₹{price:g}, Target: ₹{watch['target_price']:g})",
            "negative_keywords": f"{now_stamp} [VIP SNIPER] {watch['name']} -> {status_str} [HTTP {http_code}] (Price: ₹{price:g} / Target: ₹{watch['target_price']:g}) {detail}".strip(),
            "is_active": False,
        },
        {
            "name": "DAEMON_LOG",
            "category": "CRITICAL" if status_str == "IN_STOCK" else "INFO",
            "platforms": "vip.sniper",
            "query": f"[VIP WATCH] {watch['name']} -> {status_str} (Target: ₹{watch['target_price']:g})",
            "negative_keywords": f"{now_stamp} [INFO] vip.sniper: {watch['name']} -> {status_str} (Price: ₹{price:g}, Target: ₹{watch['target_price']:g}, HTTP {http_code})",
            "is_active": False,
        },
    ]
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            await client.post(f"{supabase_url}/rest/v1/custom_radar_rules", headers=headers, json=payload)
    except Exception as exc:
        logger.debug("Failed to ship VIP log to Supabase: %s", exc)


async def probe_vip_watches(tracker: Tracker) -> int:
    """Perform a single instantaneous probe of all VIP target watches (GBD-H2000 & GBD-300-9DR).
    
    Zero deduplication: dispatches Telegram alert on every cycle while either watch is in stock.
    Returns the count of alerts dispatched.
    """
    import httpx
    from scrapers import get_scraper

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    alerts_sent = 0

    for watch in VIP_WATCHES:
        target_url = watch["url"]
        js_url = f"{target_url}.js"
        in_stock = False
        deal_price = watch["default_price"]
        r_status = 0
        detail_msg = ""

        try:
            async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
                r = await client.get(js_url, headers=headers)
                r_status = r.status_code
                if r.status_code == 200:
                    try:
                        data = r.json()
                        is_avail = bool(data.get("available", False))
                        variants = data.get("variants", [])
                        if is_avail or any(bool(v.get("available", False)) for v in variants):
                            in_stock = True
                            for v in variants:
                                if v.get("price"):
                                    p_val = float(v["price"]) / 100.0 if float(v["price"]) > 100000 else float(v["price"])
                                    if p_val > 0:
                                        deal_price = p_val
                                        break
                        detail_msg = f"Available: {is_avail}"
                    except Exception as parse_e:
                        detail_msg = f"JSON parse note: {parse_e}"
                elif r.status_code == 404:
                    r_html = await client.get(target_url, headers=headers)
                    r_status = r_html.status_code
                    if r_html.status_code == 200 and "404" not in r_html.text[:300].lower():
                        in_stock = True
                        detail_msg = "Product un-redirected HTML 200"
                    else:
                        detail_msg = "Unlisted / Awaiting restock drop"

            status_str = "IN_STOCK" if in_stock else "OUT_OF_STOCK"

            if in_stock:
                logger.info("🚨🚨 [VIP SNIPER] %s IS IN STOCK! Deal Price: ₹%s (Target: ₹%s)", watch["name"], deal_price, watch["target_price"])
            else:
                logger.info("[VIP SNIPER] %s -> OUT OF STOCK (Target: ₹%s | Price: ₹%s | HTTP %s)", watch["name"], watch["target_price"], deal_price, r_status)

            # Ship VIP log to Supabase for instant real-time telemetry on both local & server runs
            await ship_vip_log_to_supabase(watch, status_str, deal_price, r_status, detail_msg)

            if in_stock:
                try:
                    scraper = get_scraper("casio", tracker.config)
                    res = await scraper.scrape(target_url)
                    if res.price and res.price > 0:
                        deal_price = res.price
                except Exception:
                    pass

                alert_msg = (
                    "🚨🚨 *URGENT VIP DEAL RESTOCK!* 🚨🚨\n"
                    f"📦 *Watch:* {watch['name']}\n"
                    "🔥 *STATUS: IN STOCK RIGHT NOW!*\n"
                    f"💰 *Deal Price:* ₹{deal_price:g} (MRP: ₹{watch['mrp']:,})\n"
                    f"🎯 *Target:* ₹{watch['target_price']:g} (Target Met!)\n"
                    f"🛒 *ORDER INSTANTLY:* {target_url}\n"
                    "⚡ *Caught via 60-Second Priority VIP Sniper*\n"
                    "⚠️ *Zero-dedupe mode: Alerting every 60s while in stock!*"
                )
                await tracker.notifier.send_telegram(alert_msg)
                alerts_sent += 1

                try:
                    products = await tracker.db.get_products()
                    vip_prod = next((p for p in products if watch["tag"] in (p.url or "").lower()), None)
                    if vip_prod:
                        await tracker.db.update_price(vip_prod.id, deal_price, title=f"{watch['name']} (IN STOCK!)")
                    await tracker.db.log_deal_alert(
                        product_url=target_url,
                        title=f"{watch['name']} (VIP IN STOCK)",
                        price=deal_price,
                        effective_price=deal_price,
                        discount_percent=round((1 - deal_price / watch["mrp"]) * 100, 1),
                        platform="casio",
                    )
                except Exception as db_err:
                    logger.debug("[VIP Sniper] DB update error: %s", db_err)

        except Exception as exc:
            logger.debug("[VIP Sniper] %s error: %s", watch["name"], exc)

    return alerts_sent


async def vip_casio_sniper_loop(tracker: Tracker, interval_seconds: int = 60):
    """Ultra-high-frequency 60-second sniper loop for Casio GBD-H2000 and GBD-300-9DR restocks."""
    cycle = 0
    while True:
        cycle += 1
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await probe_vip_watches(tracker)
        if cycle % 10 == 1 or cycle <= 3:
            print(f"[{now_str}] 🎯 [VIP Sniper #{cycle}] GBD-H2000 & GBD-300-9DR probed. Both 1-min priority guards live.")
        await asyncio.sleep(interval_seconds)


async def running_shoes_radar_loop(interval_seconds: int = 600):
    """Dedicated background harvester loop for Performance Running Shoes (Nike, Adidas, Asics, Puma, NB, Skechers)."""
    from running_shoes_radar import shoes_radar
    cycle_count = 0
    while True:
        cycle_count += 1
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not shoes_radar.is_active():
            logger.info("Running Shoes Radar is switched OFF in UI. Skipping background cycle #%s.", cycle_count)
        else:
            print(f"\n[{now_str}] 👟 Starting Running Shoes Radar Harvest Cycle #{cycle_count}...")
            try:
                res = await shoes_radar.sweep()
                new_deals = res.get("new_deals_found", 0)
                alerts = res.get("alerts_dispatched", 0)
                print(f"[{now_str}] ✅ Running Shoes Cycle #{cycle_count} completed: {new_deals} deals found, {alerts} Telegram alerts dispatched.")
            except Exception as exc:
                logger.error("Error during running shoes cycle #%s: %s", cycle_count, exc)

        await asyncio.sleep(interval_seconds)


async def run_single_pass() -> int:
    """Execute a single complete sweep (Casio Bhawar + Flipkart deals + manual products)."""
    print("\n⚡ [PriceTracker] Executing Single Sweep (GitHub Actions / Scheduled Runner)...")
    radar = StealRadar(settings)
    await radar.init()
    try:
        try:
            casio_alerts = await asyncio.wait_for(
                radar.scan_all(only_platforms=["casio", "flipkart", "myntra"]),
                timeout=90.0,
            )
            print(f"✅ Deal Radar scan completed: {casio_alerts} deal alert(s) dispatched.")
        except asyncio.TimeoutError:
            print("⚠️ Deal Radar scan timed out after 90s — continuing to tracked products.")
            casio_alerts = 0

        tracker = Tracker(radar.db, radar.notifier, settings)

        # Priority 1: Instant VIP restock probe (GBD-H2000 & GBD-300-9DR with zero dedupe)
        vip_alerts = await probe_vip_watches(tracker)

        try:
            tracked_alerts = await asyncio.wait_for(
                tracker.run_once(),
                timeout=120.0,
            )
            print(f"✅ Tracked products check completed: {tracked_alerts} alert(s) dispatched.")
        except asyncio.TimeoutError:
            print("⚠️ Tracked products check timed out after 120s.")
            tracked_alerts = 0

        total = casio_alerts + tracked_alerts + vip_alerts
        print(f"🎯 Total alerts sent: {total}\n")

        # Check Running Shoes Radar if active
        try:
            from running_shoes_radar import shoes_radar
            if shoes_radar.is_active():
                print("👟 Checking Running Shoes Radar (Myntra, Flipkart, Tata CLiQ, Ajio)...")
                shoe_res = await asyncio.wait_for(shoes_radar.sweep(), timeout=60.0)
                shoe_alerts = shoe_res.get("alerts_dispatched", 0)
                total += shoe_alerts
                print(f"✅ Running Shoes check completed: {shoe_alerts} alert(s) dispatched.")
            else:
                print("ℹ️ Running Shoes Radar is switched OFF in config/UI. Skipping.")
        except Exception as shoe_exc:
            logger.error("Error during running shoes single pass: %s", shoe_exc)

        # Check and dispatch periodic Telegram heartbeat if due
        try:
            from heartbeat import check_and_send_heartbeat
            await check_and_send_heartbeat(radar.db, radar.notifier, settings)
        except Exception as hb_exc:
            logger.debug("Heartbeat check error: %s", hb_exc)

        return total
    finally:
        await radar.close()


async def run_cloud_runner(duration_seconds: int = 240) -> int:
    """Execute continuous cloud runner pass (ideal for GitHub Actions 5-minute scheduled runs).
    
    Probes VIP watches every 60 seconds throughout the execution window, while
    running standard deal sweeps in parallel, ensuring 24/7 sub-minute cloud vigilance.
    """
    print(f"\n⚡ [PriceTracker Cloud Runner] Starting {duration_seconds}s active surveillance window...")
    radar = StealRadar(settings)
    await radar.init()
    try:
        tracker = Tracker(radar.db, radar.notifier, settings)
        loop = asyncio.get_running_loop()
        start_time = loop.time()
        stop_event = asyncio.Event()
        total_alerts = 0
        vip_alerts_total = 0

        # Dedicated 60-Second VIP Sniper Loop running concurrently in the background
        async def _vip_sniper_loop():
            nonlocal vip_alerts_total
            pass_num = 0
            while not stop_event.is_set():
                pass_num += 1
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"[{now_str}] 🎯 [Cloud Runner VIP Sniper Pass #{pass_num}] Probing GBD-H2000 & GBD-300-9DR...")
                try:
                    v_alerts = await probe_vip_watches(tracker)
                    vip_alerts_total += v_alerts
                except Exception as e:
                    logger.error("VIP sniper probe error: %s", e)

                # Wait exactly 60 seconds (or wake up immediately if stop_event is set)
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=60.0)
                except asyncio.TimeoutError:
                    pass

        vip_task = asyncio.create_task(_vip_sniper_loop())

        # In parallel: Perform catalog sweeps and deal checks
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            tracked_alerts = await asyncio.wait_for(tracker.run_once(), timeout=120.0)
            total_alerts += tracked_alerts
            print(f"[{now_str}] ✅ Tracked products check completed: {tracked_alerts} alert(s) dispatched.")
        except Exception as e:
            logger.error("Cloud sweep tracked items error: %s", e)

        try:
            casio_alerts = await asyncio.wait_for(
                radar.scan_all(only_platforms=["casio", "flipkart", "myntra"]),
                timeout=90.0,
            )
            total_alerts += casio_alerts
            print(f"[{now_str}] ✅ Deal Radar scan completed: {casio_alerts} alert(s) dispatched.")
        except Exception as e:
            logger.error("Cloud sweep radar error: %s", e)

        try:
            from running_shoes_radar import shoes_radar
            if shoes_radar.is_active():
                shoe_res = await asyncio.wait_for(shoes_radar.sweep(), timeout=60.0)
                total_alerts += shoe_res.get("alerts_dispatched", 0)
        except Exception as e:
            logger.debug("Cloud shoe sweep: %s", e)

        try:
            from heartbeat import check_and_send_heartbeat
            await check_and_send_heartbeat(radar.db, radar.notifier, settings)
        except Exception as hb_exc:
            logger.debug("Heartbeat check error: %s", hb_exc)

        # Maintain active VIP vigilance every 60s for the entire duration_seconds surveillance window
        elapsed = loop.time() - start_time
        remaining = duration_seconds - elapsed - 5
        if remaining > 0:
            print(f"⏳ Cloud Runner maintaining active sub-minute VIP vigilance for {int(remaining)}s remaining...")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                pass

        stop_event.set()
        await vip_task
        total_alerts += vip_alerts_total

        print(f"\n✅ [Cloud Runner] Surveillance window concluded. Total alerts dispatched: {total_alerts}")
        return total_alerts
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
                tracked_alerts = await tracker.run_once()
                print(f"[{now_str}] ✅ Tracked items check: {tracked_alerts} alert(s).")
                total_alerts += tracked_alerts
            except Exception as exc:
                logger.error("Error checking tracked items in pass #%s: %s", i, exc)

            try:
                casio_alerts = await radar.scan_all(only_platforms=["casio", "flipkart"])
                print(f"[{now_str}] ✅ Deal Radar scan: {casio_alerts} deal alert(s).")
                total_alerts += casio_alerts
            except Exception as exc:
                logger.error("Error in deal radar scan pass #%s: %s", i, exc)

            try:
                from running_shoes_radar import shoes_radar
                if shoes_radar.is_active():
                    shoe_res = await shoes_radar.sweep()
                    shoe_alerts = shoe_res.get("alerts_dispatched", 0)
                    total_alerts += shoe_alerts
                    print(f"[{now_str}] ✅ Running Shoes scan: {shoe_alerts} alert(s).")
            except Exception as shoe_exc:
                logger.error("Error during running shoes sweep pass: %s", shoe_exc)
            
            # Check periodic heartbeat
            try:
                from heartbeat import check_and_send_heartbeat
                await check_and_send_heartbeat(radar.db, radar.notifier, settings)
            except Exception as hb_exc:
                logger.debug("Heartbeat check error: %s", hb_exc)


            if i < repeats:
                print(f"⏳ Sleeping {interval_seconds}s until next pass in this runner...")
                await asyncio.sleep(interval_seconds)

        print(f"\n🎯 [PriceTracker Runner] All {repeats} passes completed. Total alerts sent: {total_alerts}\n")
        return total_alerts
    finally:
        await radar.close()


async def main():
    if "--runner" in sys.argv:
        duration = 240
        for i, arg in enumerate(sys.argv):
            if arg == "--duration" and i + 1 < len(sys.argv) and sys.argv[i + 1].isdigit():
                duration = int(sys.argv[i + 1])
        await run_cloud_runner(duration_seconds=duration)
        return

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
    shoes_interval = 600
    for arg in sys.argv[1:]:
        if arg.isdigit():
            manual_interval = int(arg)
            casio_interval = min(90, int(arg))

    print("\n" + "=" * 70)
    print("🚀 PRICETRACKER 24/7 AUTONOMOUS DEAL & PRICE RADAR STARTED")
    print("🎯 Target 1: Casio Store Bhawar (70%+ Silent Deals & GBD-300 Watcher)")
    print("🎯 Target 2: Flipkart Casio Deals (70%+ Brand Facet)")
    print("🎯 Target 3: Tracked Products (Crocs LiteRide 360 All Variants / User Items)")
    print("🎯 Target 4: Running Shoes Radar (Myntra, Flipkart, Tata CLiQ, Ajio - 56 Whitelist Models)")
    print("🎯 VIP Sniper: Casio G-Shock GBD-H2000-1A9 (70% Member Restock) -> Every 60s")
    print("📱 Telegram 2-Way Bot: ACTIVE")
    print(f"⏰ VIP Sniper: Every 60s | Casio: Every {casio_interval}s | Tracked Items: Every {manual_interval}s | Shoes: Every {shoes_interval}s")
    print("=" * 70 + "\n")

    # Run VIP sniper, Casio deals hunter, manual Telegram tracker, running shoes harvester, and interactive bot listener concurrently
    try:
        await asyncio.gather(
            vip_casio_sniper_loop(tracker, interval_seconds=60),
            casio_deal_radar_loop(radar, interval_seconds=casio_interval),
            manual_tracker_loop(tracker, interval_seconds=manual_interval),
            running_shoes_radar_loop(interval_seconds=shoes_interval),
            supabase_log_shipper_loop(interval_seconds=15),
            tg_bot.listen_loop(),
        )
    except (KeyboardInterrupt, SystemExit):
        print("\n🛑 24/7 Daemon stopped by user.")
    finally:
        tg_bot.stop()
        await radar.close()


if __name__ == "__main__":
    asyncio.run(main())
