"""Vercel Serverless Entrypoint for PriceTracker.

Provides:
- GET  /                      : Executive Glassmorphism Tracking Dashboard UI
- GET  /api/status            : JSON Engine Health Status
- GET  /api/dashboard/data    : Dashboard telemetry, product cards & deal radar log
- POST /api/products          : Enroll new product into 24/7 tracking
- POST /api/products/{id}/check : Instant live scrape of a single item
- POST /api/products/{id}/toggle: Pause/resume tracking for an item
- DELETE /api/products/{id}   : Delete product from tracking
- POST /api/sweep             : 1-click deal radar & price sweep
- POST /api/telegram          : Telegram Webhook for real-time manual link tracking & commands
- GET  /api/cron              : 24/7 Periodic deal & price drop scanner (Casio Bhawar & Flipkart)
- GET  /api/set-webhook       : 1-Click Telegram Webhook configuration
"""

from __future__ import annotations

import logging
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
import httpx
from pydantic import BaseModel

# Ensure project root is in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from config import settings
from database import get_database
from notifier import Notifier
from radar import StealRadar
from scrapers import extract_fallback_title, get_scraper, normalize_product_url, resolve_platform
from telegram_bot import TelegramAssistant
from tracker import Tracker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("vercel_api")

app = FastAPI(
    title="SriTrack // Executive PriceTracker Engine",
    description="Autonomous Casio Bhawar + Flipkart deal hunter & Real-time Tracking Dashboard",
    version="2.1.0",
)

DASHBOARD_HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_dashboard_html() -> str:
    """Read the standalone HTML dashboard template."""
    if os.path.exists(DASHBOARD_HTML_PATH):
        try:
            with open(DASHBOARD_HTML_PATH, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as exc:
            logger.error("Error reading dashboard.html: %s", exc)
    return "<html><body style='background:#060911;color:#fff;font-family:sans-serif;padding:40px;'><h2>SriTrack Engine Online</h2><p>Dashboard template missing or loading...</p></body></html>"


def is_browser_request(request: Request) -> bool:
    """Check if the incoming request accepts HTML."""
    accept = request.headers.get("accept", "").lower()
    return "text/html" in accept


def extract_path(request: Request, full_path: str = "") -> str:
    """Extract clean lower-cased path segment from query params, headers, or url."""
    raw = (
        request.query_params.get("_vercel_path")
        or request.headers.get("x-vercel-matched-path")
        or request.headers.get("x-matched-path")
        or request.headers.get("x-forwarded-uri")
        or request.headers.get("x-invoke-path")
        or full_path
        or request.url.path
        or ""
    )
    # Strip any query parameters appended in rewrite headers
    clean = raw.split("?")[0].strip("/").lower()
    return clean


class AddProductPayload(BaseModel):
    url: str
    target_price: float


# ==========================================
# CORE DASHBOARD & STATUS ROUTES
# ==========================================

@app.get("/")
@app.get("/dashboard")
@app.get("/api")
@app.get("/api/")
@app.get("/api/index")
@app.get("/api/index.py")
@app.get("/index.py")
async def root(request: Request):
    """Serve Dashboard HTML to browsers or status JSON to API callers."""
    clean = extract_path(request)

    # Route based on rewritten target if applicable
    if "cron" in clean:
        return await cron_sweep(request)
    elif "set-webhook" in clean or "set_webhook" in clean:
        return await set_telegram_webhook(request)
    elif "telegram" in clean:
        return await telegram_webhook(request)
    elif clean == "api/dashboard/data":
        return await get_dashboard_data()
    elif clean == "api/status":
        return await get_status()

    # If requested by a browser or accessing root/dashboard, return HTML
    if is_browser_request(request) or not clean or clean in ("dashboard", "index", "index.py", "api", "api/index", "api/index.py"):
        return HTMLResponse(content=get_dashboard_html(), status_code=200)

    return await get_status()


@app.get("/api/status")
async def get_status():
    """Health check and status telemetry JSON."""
    db = get_database(settings)
    await db.initialize()
    try:
        products = await db.get_products(active_only=True)
    finally:
        await db.close()

    return {
        "status": "online",
        "service": "SriTrack Executive Serverless Engine",
        "timestamp": _now(),
        "database": "Supabase PostgreSQL" if os.getenv("SUPABASE_URL") else "SQLite",
        "active_monitored_products": len(products),
        "focus": "Casio Bhawar + Flipkart (>= 70% OFF & GBD-300) + Amazon/Flipkart EDYELL C5S (< ₹1,300)",
        "endpoints": {
            "dashboard_ui": "GET /",
            "dashboard_data": "GET /api/dashboard/data",
            "add_product": "POST /api/products",
            "telegram_webhook": "POST /api/telegram",
            "cron_deal_scanner": "GET /api/cron",
            "setup_webhook": "GET /api/set-webhook",
        },
    }


def _format_datetime(dt: Any) -> Optional[str]:
    if not dt:
        return None
    if hasattr(dt, "isoformat"):
        return dt.isoformat()
    return str(dt)


@app.get("/api/dashboard/data")
async def get_dashboard_data():
    """Aggregate dashboard telemetry, tracked products list, and recent deals."""
    db = get_database(settings)
    await db.initialize()
    try:
        products = await db.get_products(active_only=False)
        recent_deals = await db.get_recent_deal_alerts(limit=25)
        active_count = sum(1 for p in products if p.is_active)

        last_sweep = None
        for p in products:
            if p.last_checked and (last_sweep is None or str(p.last_checked) > str(last_sweep)):
                last_sweep = p.last_checked

        stats = {
            "active_count": active_count,
            "total_count": len(products),
            "last_sweep_time": _format_datetime(last_sweep),
            "deal_radar_status": "ONLINE",
            "database": "Supabase PostgreSQL" if os.getenv("SUPABASE_URL") else "SQLite",
        }

        prods_data = [
            {
                "id": p.id,
                "title": p.title,
                "url": p.url,
                "platform": p.platform,
                "initial_price": p.initial_price,
                "current_price": p.current_price,
                "target_price": p.target_price,
                "is_active": p.is_active,
                "last_checked": _format_datetime(p.last_checked),
                "created_at": _format_datetime(getattr(p, "created_at", None)),
            }
            for p in products
        ]

        return {
            "status": "success",
            "stats": stats,
            "products": prods_data,
            "recent_deals": recent_deals,
        }
    finally:
        await db.close()


# ==========================================
# PRODUCT MANAGEMENT REST APIS
# ==========================================

@app.post("/api/products")
async def api_add_product(payload: AddProductPayload):
    """Enroll a new URL into 24/7 price tracking with canonical URL normalization."""
    import asyncio
    raw_url = payload.url.strip()
    target_price = payload.target_price

    platform = await resolve_platform(raw_url)
    if not platform:
        raise HTTPException(
            status_code=400,
            detail="Unsupported URL. Supported: Amazon, Flipkart, Casio Bhawar, Myntra, Ajio, Blinkit, Zepto, BigBasket."
        )

    clean_url = normalize_product_url(raw_url, platform)

    db = get_database(settings)
    await db.initialize()
    try:
        current_price = target_price
        title = extract_fallback_title(raw_url, platform)

        # Fast preview scrape with 5.0s timeout so the web console returns immediately
        try:
            scraper = get_scraper(platform, settings)
            res = await asyncio.wait_for(scraper.scrape(clean_url), timeout=5.0)
            if res.price and res.price > 0:
                current_price = res.price
            if res.title:
                title = res.title
        except Exception as exc:
            logger.info("Fast preview scrape deferred for %s: %s", clean_url, exc)

        prod_id = await db.add_product(
            url=clean_url,
            platform=platform,
            target_price=target_price,
            initial_price=current_price,
            title=title,
        )

        return {
            "status": "success",
            "id": prod_id,
            "title": title,
            "platform": platform,
            "current_price": current_price,
            "target_price": target_price,
            "url": clean_url,
        }
    finally:
        await db.close()


@app.post("/api/products/{product_id}/check")
async def check_single_product(product_id: int):
    """Perform on-demand live scrape and evaluation for a single item."""
    db = get_database(settings)
    await db.initialize()
    try:
        product = await db.get_product(product_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        notifier = Notifier(settings)
        tracker = Tracker(db, notifier, settings)
        await tracker.check_product(product)

        updated = await db.get_product(product_id)
        return {
            "status": "success",
            "id": product_id,
            "price": updated.current_price if updated else None,
            "last_checked": updated.last_checked.isoformat() if updated and updated.last_checked else None,
        }
    finally:
        await db.close()


@app.post("/api/products/{product_id}/toggle")
async def toggle_single_product(product_id: int):
    """Toggle tracking status (pause/resume) for a product."""
    db = get_database(settings)
    await db.initialize()
    try:
        product = await db.get_product(product_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        new_status = not product.is_active
        await db.set_active(product_id, new_status)
        return {"status": "success", "id": product_id, "is_active": new_status}
    finally:
        await db.close()


@app.delete("/api/products/{product_id}")
async def delete_single_product(product_id: int):
    """Remove a product from 24/7 tracking."""
    db = get_database(settings)
    await db.initialize()
    try:
        success = await db.remove_product(product_id)
        return {"status": "success", "id": product_id, "deleted": success}
    finally:
        await db.close()


@app.post("/api/sweep")
async def manual_deal_sweep():
    """Trigger an immediate full clearance scan (Casio & Flipkart) and product checks."""
    db = get_database(settings)
    await db.initialize()
    try:
        radar = StealRadar(settings, db=db)
        await radar.init()
        casio_alerts = await radar.scan_all(only_platforms=["casio", "flipkart"])

        tracker = Tracker(db, radar.notifier, settings)
        manual_alerts = await tracker.run_once()
        await radar.close()

        return {
            "status": "success",
            "casio_alerts": casio_alerts,
            "manual_alerts": manual_alerts,
            "total_dispatched": casio_alerts + manual_alerts,
        }
    finally:
        await db.close()


# ==========================================
# TELEGRAM & CRON SWEEPER
# ==========================================

@app.post("/telegram")
@app.post("/api/telegram")
@app.post("/api/index.py/telegram")
async def telegram_webhook(request: Request):
    """Receive and dispatch incoming Telegram messages in real-time via Webhook."""
    try:
        update: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    message = update.get("message")
    if not message:
        return {"ok": True, "note": "No message field in update"}

    logger.info("Received Telegram message: %s", message.get("text", "")[:40])

    db = get_database(settings)
    await db.initialize()
    assistant = TelegramAssistant(settings, db=db)

    try:
        await assistant.handle_message(message)
    except Exception as exc:
        logger.error("Error processing Telegram message: %s", exc)
        chat = message.get("chat", {})
        if chat.get("id"):
            await assistant.send_reply(chat["id"], f"⚠️ Error processing request: {exc}")
    finally:
        await db.close()

    return {"ok": True}


@app.get("/cron")
@app.get("/api/cron")
@app.get("/api/index.py/cron")
async def cron_sweep(request: Request):
    """Execute scheduled deal hunter & manual product price checking."""
    cron_secret = os.getenv("CRON_SECRET")
    if cron_secret:
        auth_header = request.headers.get("Authorization", "")
        query_secret = request.query_params.get("secret", "")
        if auth_header != f"Bearer {cron_secret}" and query_secret != cron_secret:
            raise HTTPException(status_code=401, detail="Unauthorized cron trigger")

    logger.info("Starting /api/cron sweep...")
    db = get_database(settings)
    await db.initialize()

    radar = StealRadar(settings, db=db)
    await radar.init()
    casio_alerts = await radar.scan_all(only_platforms=["casio", "flipkart"])

    tracker = Tracker(db, radar.notifier, settings)
    manual_alerts = await tracker.run_once()

    await radar.close()

    return {
        "status": "success",
        "timestamp": _now(),
        "casio_deal_alerts": casio_alerts,
        "manual_tracked_alerts": manual_alerts,
        "total_dispatched": casio_alerts + manual_alerts,
    }


@app.get("/set-webhook")
@app.get("/api/set-webhook")
@app.get("/api/index.py/set-webhook")
async def set_telegram_webhook(request: Request, url: Optional[str] = None):
    """Register this Vercel deployment URL with Telegram's Bot API."""
    token = settings.telegram_bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise HTTPException(status_code=400, detail="TELEGRAM_BOT_TOKEN environment variable is not set.")

    if url:
        webhook_url = url.rstrip("/")
    else:
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
        scheme = request.headers.get("x-forwarded-proto") or "https"
        if not host:
            raise HTTPException(status_code=400, detail="Could not determine host. Provide ?url=https://your-domain.vercel.app")
        webhook_url = f"{scheme}://{host}/api/telegram"

    telegram_api = f"https://api.telegram.org/bot{token}/setWebhook"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(telegram_api, json={"url": webhook_url})
        data = resp.json()

    return {
        "action": "setWebhook",
        "webhook_url": webhook_url,
        "telegram_response": data,
    }


# ==========================================
# CATCH-ALL REWRITE ROUTER
# ==========================================

@app.api_route("/{full_path:path}", methods=["GET", "POST", "DELETE", "PUT", "PATCH", "HEAD", "OPTIONS"])
async def catch_all(request: Request, full_path: str):
    """Fallback router ensuring Vercel rewrites dispatch to the right handler."""
    clean = extract_path(request, full_path)
    method = request.method.upper()

    # 1. Telegram Webhook
    if "telegram" in clean:
        return await telegram_webhook(request)

    # 2. Cron Sweeper
    if "cron" in clean:
        return await cron_sweep(request)

    # 3. Setup Webhook
    if "set-webhook" in clean or "set_webhook" in clean:
        return await set_telegram_webhook(request)

    # 4. Immediate Sweep
    if clean in ("api/sweep", "sweep"):
        return await manual_deal_sweep()

    # 5. Dashboard Data
    if clean in ("api/dashboard/data", "dashboard/data"):
        return await get_dashboard_data()

    # 6. Status JSON
    if clean in ("api/status", "status"):
        return await get_status()

    # 7. Products Sub-routes
    prod_check_match = re.search(r"products/(\d+)/check", clean)
    if prod_check_match:
        return await check_single_product(int(prod_check_match.group(1)))

    prod_toggle_match = re.search(r"products/(\d+)/toggle", clean)
    if prod_toggle_match:
        return await toggle_single_product(int(prod_toggle_match.group(1)))

    prod_id_match = re.search(r"products/(\d+)$", clean)
    if prod_id_match:
        pid = int(prod_id_match.group(1))
        if method == "DELETE":
            return await delete_single_product(pid)

    if clean in ("api/products", "products"):
        if method == "POST":
            data = await request.json()
            payload = AddProductPayload(**data)
            return await api_add_product(payload)
        return await get_dashboard_data()

    # 8. Root or Dashboard HTML fallback
    if method == "GET" and (is_browser_request(request) or clean in ("", "dashboard", "index", "index.py", "api", "api/index", "api/index.py")):
        return HTMLResponse(content=get_dashboard_html(), status_code=200)

    return JSONResponse(
        status_code=404,
        content={"detail": "Not Found", "received_path": full_path, "matched_path": clean},
    )



