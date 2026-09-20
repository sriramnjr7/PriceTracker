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
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query, Request
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
    title="PriceTracker // Deal Radar & Executive Tracking Engine",
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
    return "<html><body style='background:#060911;color:#fff;font-family:sans-serif;padding:40px;'><h2>PriceTracker Engine Online</h2><p>Dashboard template missing or loading...</p></body></html>"


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


class LoginPayload(BaseModel):
    email: Optional[str] = None
    password: str


@app.post("/api/auth/login")
@app.post("/auth/login")
async def api_auth_login(payload: LoginPayload):
    """Authenticate dashboard users server-side with constant-time comparison."""
    import hmac

    expected_pwd = getattr(settings, "dashboard_password", None) or os.getenv("DASHBOARD_PASSWORD", "8910")
    submitted_pwd = (payload.password or "").strip()

    if not hmac.compare_digest(submitted_pwd.encode("utf-8"), expected_pwd.strip().encode("utf-8")):
        raise HTTPException(status_code=401, detail="Invalid credentials. Please verify your password.")

    user_email = (payload.email or "").strip() or getattr(settings, "dashboard_email", None) or os.getenv("DASHBOARD_EMAIL", "sriramnjr7@gmail.com")
    return {
        "ok": True,
        "email": user_email,
    }


# ==========================================
# CORE DASHBOARD & STATUS ROUTES
# ==========================================

@app.api_route("/", methods=["GET", "POST", "HEAD", "OPTIONS"])
@app.api_route("/dashboard", methods=["GET", "POST", "HEAD", "OPTIONS"])
@app.api_route("/api", methods=["GET", "POST", "HEAD", "OPTIONS"])
@app.api_route("/api/", methods=["GET", "POST", "HEAD", "OPTIONS"])
@app.api_route("/api/index", methods=["GET", "POST", "HEAD", "OPTIONS"])
@app.api_route("/api/index.py", methods=["GET", "POST", "HEAD", "OPTIONS"])
@app.api_route("/index.py", methods=["GET", "POST", "HEAD", "OPTIONS"])
async def root(request: Request):
    """Serve Dashboard HTML to browsers or status JSON to API callers."""
    clean = extract_path(request)
    method = request.method.upper()

    # Route based on rewritten target if applicable
    if "auth" in clean:
        if method == "POST":
            data = await request.json()
            payload = LoginPayload(**data)
            return await api_auth_login(payload)
        elif method == "OPTIONS":
            return JSONResponse(content={"ok": True})
    elif "history" in clean:
        match = re.search(r"products/(\d+)/history", clean)
        if match:
            prod_id = int(match.group(1))
            rng = request.query_params.get("range") or request.query_params.get("timeframe") or "weekly"
            return await get_product_price_history(prod_id, timeframe=rng)
    elif "cron" in clean:
        return await cron_sweep(request)
    elif "trigger-runner" in clean or "trigger_runner" in clean:
        return await trigger_github_runner(request)
    elif "set-webhook" in clean or "set_webhook" in clean:
        return await set_telegram_webhook(request)
    elif "telegram" in clean:
        return await telegram_webhook(request)
    elif clean == "api/dashboard/data":
        return await get_dashboard_data()
    elif clean == "api/status":
        return await get_status()
    elif "sweep" in clean and method == "POST":
        return await manual_deal_sweep()
    elif re.search(r"products/(\d+)/check", clean) and method == "POST":
        match = re.search(r"products/(\d+)/check", clean)
        return await check_single_product(int(match.group(1)))
    elif re.search(r"products/(\d+)/toggle", clean) and method == "POST":
        match = re.search(r"products/(\d+)/toggle", clean)
        return await toggle_single_product(int(match.group(1)))
    elif clean in ("api/products", "products"):
        if method == "POST":
            data = await request.json()
            payload = AddProductPayload(**data)
            return await api_add_product(payload)
        return await get_dashboard_data()

    # If requested by a browser or accessing root/dashboard, return HTML with CDN caching
    if is_browser_request(request) or not clean or clean in ("dashboard", "index", "index.py", "api", "api/index", "api/index.py"):
        return HTMLResponse(
            content=get_dashboard_html(),
            status_code=200,
            headers={"Cache-Control": "public, max-age=60, s-maxage=300, stale-while-revalidate=600"},
        )

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

    return JSONResponse(
        content={
            "status": "online",
            "service": "PriceTracker Executive Serverless Engine",
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
        },
        headers={"Cache-Control": "public, max-age=15, s-maxage=30, stale-while-revalidate=60"},
    )


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

        return JSONResponse(
            content={
                "status": "success",
                "stats": stats,
                "products": prods_data,
                "recent_deals": recent_deals,
            },
            headers={"Cache-Control": "public, max-age=15, s-maxage=30, stale-while-revalidate=60"},
        )
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
        current_price = None
        title = extract_fallback_title(raw_url, platform)

        # Fast preview scrape with 10.0s timeout so the web console returns immediately
        try:
            scraper = get_scraper(platform, settings)
            res = await asyncio.wait_for(scraper.scrape(clean_url), timeout=10.0)
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

        # 1. Scrape live product URL directly
        scraper = get_scraper(product.platform, settings)
        try:
            result = await scraper.scrape(product.url)
        except Exception as exc:
            logger.error("Live scrape failed for %s (id=%s): %s", product.url, product_id, exc)
            raise HTTPException(
                status_code=502,
                detail=f"Live scrape failed for {product.platform}: {exc}"
            )

        # 2. Persist price update and fresh timestamp
        if result.price is not None:
            await db.update_price(product.id, result.price, title=result.title or None)
        elif result.title:
            await db.update_price(product.id, None, title=result.title)
        else:
            await db.update_price(product.id, product.current_price, title=product.title)

        # 3. Check notification threshold
        notifier = Notifier(settings)
        tracker = Tracker(db, notifier, settings)
        if result.price is not None:
            should_notify, drop_percent = tracker._should_notify(
                product, product.current_price, result.price
            )
            if should_notify:
                target_text = tracker._target_text(product)
                old_p = product.current_price or product.initial_price
                if await notifier.notify(product, old_p, result.price, drop_percent, target_text):
                    await db.set_last_notified(product.id, result.price)

        updated = await db.get_product(product_id)
        return {
            "status": "success",
            "id": product_id,
            "price": updated.current_price if updated else None,
            "last_checked": _format_datetime(updated.last_checked) if updated else None,
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


@app.get("/api/products/{product_id}/history")
@app.get("/products/{product_id}/history")
@app.get("/api/index.py/products/{product_id}/history")
@app.get("/api/index.py/api/products/{product_id}/history")
async def get_product_price_history(product_id: int, timeframe: str = Query(default="weekly", alias="range")):
    """Fetch structured price history with timeframe filtering (hourly, weekly, monthly, yearly)."""
    db = get_database(settings)
    await db.initialize()
    try:
        product = await db.get_product(product_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        raw_logs = await db.price_history(product_id, limit=500)
        # raw_logs is [(price, timestamp), ...] newest first
        now = datetime.now(timezone.utc)
        range_lower = (timeframe or "weekly").lower()

        if range_lower in ("hourly", "24h", "day"):
            cutoff = now - timedelta(hours=24)
            date_fmt = "%H:%M"
        elif range_lower in ("monthly", "30d", "month"):
            cutoff = now - timedelta(days=30)
            date_fmt = "%b %d"
        elif range_lower in ("yearly", "1y", "year", "all"):
            cutoff = now - timedelta(days=365)
            date_fmt = "%b %Y"
        else:  # default weekly / 7d
            cutoff = now - timedelta(days=7)
            date_fmt = "%a %H:%M"

        points = []
        for price, ts_str in reversed(raw_logs):
            try:
                clean_ts = ts_str.replace("Z", "+00:00")
                if "+" not in clean_ts and "-" not in clean_ts[10:]:
                    dt = datetime.fromisoformat(clean_ts).replace(tzinfo=timezone.utc)
                else:
                    dt = datetime.fromisoformat(clean_ts)
            except Exception:
                continue

            if dt >= cutoff:
                points.append({
                    "timestamp": dt.isoformat(),
                    "price": float(price),
                    "formatted_time": dt.strftime(date_fmt),
                })

        # If strict cutoff produced no points but raw logs exist, fallback to all available logs
        if not points and raw_logs:
            for price, ts_str in reversed(raw_logs):
                try:
                    clean_ts = ts_str.replace("Z", "+00:00")
                    if "+" not in clean_ts and "-" not in clean_ts[10:]:
                        dt = datetime.fromisoformat(clean_ts).replace(tzinfo=timezone.utc)
                    else:
                        dt = datetime.fromisoformat(clean_ts)
                    points.append({
                        "timestamp": dt.isoformat(),
                        "price": float(price),
                        "formatted_time": dt.strftime(date_fmt),
                    })
                except Exception:
                    continue

        # If points are still empty, use product's recorded prices
        if not points:
            ref_price = product.current_price or product.initial_price
            if ref_price:
                earlier = now - timedelta(days=7 if "week" in range_lower else 1)
                points.append({
                    "timestamp": earlier.isoformat(),
                    "price": float(ref_price),
                    "formatted_time": earlier.strftime(date_fmt),
                })
                points.append({
                    "timestamp": now.isoformat(),
                    "price": float(ref_price),
                    "formatted_time": now.strftime(date_fmt),
                })
        elif len(points) == 1:
            earlier = now - timedelta(hours=3)
            points.insert(0, {
                "timestamp": earlier.isoformat(),
                "price": points[0]["price"],
                "formatted_time": earlier.strftime(date_fmt),
            })

        # Downsample evenly to at most 60 points if history is very dense
        if len(points) > 60:
            step = len(points) / 58.0
            downsampled = [points[0]]
            for i in range(1, 57):
                idx = int(i * step)
                if 0 <= idx < len(points) and points[idx] not in downsampled:
                    downsampled.append(points[idx])
            if points[-1] not in downsampled:
                downsampled.append(points[-1])
            points = downsampled

        prices = [p["price"] for p in points if p.get("price") is not None]
        min_p = min(prices) if prices else (product.current_price or product.initial_price)
        max_p = max(prices) if prices else (product.current_price or product.initial_price)

        return JSONResponse(
            content={
                "status": "success",
                "product_id": product_id,
                "title": product.title,
                "platform": product.platform,
                "url": product.url,
                "range": range_lower,
                "current_price": product.current_price,
                "target_price": product.target_price,
                "initial_price": product.initial_price,
                "min_price": min_p,
                "max_price": max_p,
                "total_points": len(points),
                "points": points,
            }
        )
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
        casio_alerts = await radar.scan_all(only_platforms=["casio", "flipkart", "myntra"])

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

_PROCESSED_UPDATES: set[int] = set()
_PROCESSED_UPDATES_ORDER: list[int] = []
_MAX_PROCESSED_CACHE = 1000


def _record_and_check_duplicate(update_id: Optional[int]) -> bool:
    """Return True if update_id was already processed, else record it in a sliding window cache."""
    if update_id is None:
        return False
    if update_id in _PROCESSED_UPDATES:
        return True
    _PROCESSED_UPDATES.add(update_id)
    _PROCESSED_UPDATES_ORDER.append(update_id)
    if len(_PROCESSED_UPDATES_ORDER) > _MAX_PROCESSED_CACHE:
        oldest = _PROCESSED_UPDATES_ORDER.pop(0)
        _PROCESSED_UPDATES.discard(oldest)
    return False


@app.post("/telegram")
@app.post("/api/telegram")
@app.post("/api/index.py/telegram")
async def telegram_webhook(request: Request):
    """Receive and dispatch incoming Telegram messages in real-time via Webhook."""
    try:
        update: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    update_id = update.get("update_id")
    if _record_and_check_duplicate(update_id):
        logger.info("Ignoring duplicate Telegram update_id %s", update_id)
        return {"ok": True, "note": "duplicate update skipped"}

    message = update.get("message")
    if not message:
        return {"ok": True, "note": "No message field in update"}

    logger.info("Received Telegram message (update_id=%s): %s", update_id, message.get("text", "")[:40])

    db = get_database(settings)
    await db.initialize()
    assistant = TelegramAssistant(settings, db=db)

    try:
        # Strict 9.0s timeout guarantees Vercel NEVER returns a 504 Gateway Timeout (maxDuration is 15s)
        await asyncio.wait_for(assistant.handle_message(message), timeout=9.0)
    except asyncio.TimeoutError:
        logger.warning(
            "Telegram webhook processing timed out after 9.0s for update_id %s; returning 200 OK to prevent Telegram retry loop",
            update_id,
        )
    except Exception as exc:
        logger.error("Error processing Telegram message: %s", exc)
        chat = message.get("chat", {})
        if chat.get("id"):
            try:
                await assistant.send_reply(chat["id"], f"⚠️ Error processing request: {exc}")
            except Exception:
                pass
    finally:
        await db.close()

    # ALWAYS return 200 OK so Telegram acknowledges the update and never enters a retry loop
    return {"ok": True}


@app.get("/cron")
@app.get("/api/cron")
@app.get("/api/index.py/cron")
async def cron_sweep(request: Request):
    """Execute scheduled deal hunter & manual product price checking with Fluid CPU protection."""
    cron_secret = os.getenv("CRON_SECRET")
    if cron_secret:
        auth_header = request.headers.get("Authorization", "")
        query_secret = request.query_params.get("secret", "")
        if auth_header != f"Bearer {cron_secret}" and query_secret != cron_secret:
            raise HTTPException(status_code=401, detail="Unauthorized cron trigger")

    mode = request.query_params.get("mode", "auto")
    db = get_database(settings)
    await db.initialize()

    try:
        products = await db.get_products(active_only=True)
        # Vercel Free Plan Guard: If products were checked within the last 20 minutes,
        # skip expensive scraping to preserve the 4h Fluid CPU limit.
        if mode != "force":
            now_ts = datetime.now(timezone.utc)
            recent_sweep = False
            for p in products:
                if p.last_checked:
                    try:
                        dt = p.last_checked if isinstance(p.last_checked, datetime) else datetime.fromisoformat(str(p.last_checked).replace("Z", "+00:00"))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        if (now_ts - dt).total_seconds() < 1200:  # 20 minutes
                            recent_sweep = True
                            break
                    except Exception:
                        pass

            if recent_sweep:
                logger.info("Vercel /api/cron: Sweep was already executed recently. Skipping to preserve Fluid CPU.")
                return {
                    "status": "skipped",
                    "reason": "sweep_already_current",
                    "monitored_products": len(products),
                    "timestamp": _now(),
                }

        import asyncio

        async def _run_sweep():
            radar = StealRadar(settings, db=db)
            await radar.init()
            # Fast scan only Casio clearance (lightweight) on serverless
            casio_alerts = await radar.scan_all(only_platforms=["casio"])
            tracker = Tracker(db, radar.notifier, settings)
            manual_alerts = await tracker.run_once()
            await radar.close()
            return casio_alerts, manual_alerts

        # Enforce strict 12.0s timeout to protect Fluid CPU
        try:
            casio_alerts, manual_alerts = await asyncio.wait_for(_run_sweep(), timeout=12.0)
        except asyncio.TimeoutError:
            logger.warning("Vercel cron reached 12s execution limit; stopped to preserve Fluid CPU.")
            casio_alerts, manual_alerts = 0, 0

        return {
            "status": "success",
            "timestamp": _now(),
            "casio_deal_alerts": casio_alerts,
            "manual_tracked_alerts": manual_alerts,
            "total_dispatched": casio_alerts + manual_alerts,
        }
    finally:
        await db.close()


@app.get("/trigger-runner")
@app.get("/api/trigger-runner")
@app.post("/trigger-runner")
@app.post("/api/trigger-runner")
async def trigger_github_runner(request: Request):
    """Zero-overhead runner trigger for cron-job.org or external webhooks.
    Dispatches GitHub Actions workflow tracker-cron.yml in ~150ms of Fluid CPU time."""
    cron_secret = os.getenv("CRON_SECRET")
    if cron_secret:
        auth_header = request.headers.get("Authorization", "")
        query_secret = request.query_params.get("secret", "")
        if auth_header != f"Bearer {cron_secret}" and query_secret != cron_secret:
            raise HTTPException(status_code=401, detail="Unauthorized trigger request")

    github_token = (
        os.getenv("GITHUB_TOKEN")
        or request.query_params.get("token")
        or request.headers.get("X-GitHub-Token")
    )
    repo = os.getenv("GITHUB_REPO", "sriramnjr7/PriceTracker")
    workflow_id = os.getenv("GITHUB_WORKFLOW", "tracker-cron.yml")

    if not github_token:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": "GITHUB_TOKEN not configured in Vercel environment variables.",
                "hint": "Add GITHUB_TOKEN to Vercel Settings -> Environment Variables, or pass ?token=<PAT>.",
            },
        )

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {github_token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "PriceTracker-Vercel-Dispatcher",
    }
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow_id}/dispatches"

    async with httpx.AsyncClient(timeout=8.0) as client:
        try:
            resp = await client.post(url, json={"ref": "main"}, headers=headers)
            if resp.status_code == 204:
                return {
                    "status": "success",
                    "action": "dispatched",
                    "workflow": workflow_id,
                    "repo": repo,
                    "timestamp": _now(),
                    "note": "GitHub Actions sweep runner has been triggered. Zero Vercel Fluid CPU consumed for scraping!",
                }
            else:
                return JSONResponse(
                    status_code=resp.status_code,
                    content={
                        "status": "github_error",
                        "code": resp.status_code,
                        "details": resp.text,
                    },
                )
        except Exception as exc:
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": f"Failed to dispatch GitHub Action: {exc}"},
            )


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

    # 0. Auth Login
    if "auth" in clean:
        if method == "POST":
            data = await request.json()
            payload = LoginPayload(**data)
            return await api_auth_login(payload)
        elif method == "OPTIONS":
            return JSONResponse(content={"ok": True})

    # 1. Telegram Webhook
    if "telegram" in clean:
        return await telegram_webhook(request)

    # 2. Trigger Runner (GitHub Actions dispatcher)
    if "trigger-runner" in clean or "trigger_runner" in clean:
        return await trigger_github_runner(request)

    # 3. Cron Sweeper
    if "cron" in clean:
        return await cron_sweep(request)

    # 4. Setup Webhook
    if "set-webhook" in clean or "set_webhook" in clean:
        return await set_telegram_webhook(request)

    # 5. Immediate Sweep
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



