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

import asyncio
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
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
from running_shoes_radar import shoes_radar
from collection_data import collection_mgr

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


class UpdateTargetPricePayload(BaseModel):
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
    elif "running-shoes" in clean or "running_shoes" in clean:
        if "toggle-shoe" in clean and method == "POST":
            return await api_toggle_single_shoe(request)
        elif "toggle-brand" in clean and method == "POST":
            return await api_toggle_shoe_brand(request)
        elif "toggle" in clean and method == "POST":
            return await api_toggle_running_shoes(request)
        elif "sweep" in clean and method == "POST":
            return await api_sweep_running_shoes()
        return await api_get_running_shoes_status()
    elif "logs" in clean:
        if method == "DELETE" or "clear" in clean:
            return await api_clear_logs()
        limit = int(request.query_params.get("limit", 250))
        level = request.query_params.get("level")
        search = request.query_params.get("search")
        return await api_get_logs(limit=limit, level=level, search=search)
    elif "sweep" in clean and method == "POST":
        return await manual_deal_sweep()
    elif re.search(r"products/(\d+)/check", clean) and method == "POST":
        match = re.search(r"products/(\d+)/check", clean)
        return await check_single_product(int(match.group(1)))
    elif re.search(r"products/(\d+)/toggle", clean) and method == "POST":
        match = re.search(r"products/(\d+)/toggle", clean)
        return await toggle_single_product(int(match.group(1)))
    elif re.search(r"products/(\d+)/target-price", clean) and method == "POST":
        match = re.search(r"products/(\d+)/target-price", clean)
        data = await request.json()
        payload = UpdateTargetPricePayload(**data)
        return await api_update_product_target_price(int(match.group(1)), payload)
    elif re.search(r"products/(\d+)$", clean) and method == "PATCH":
        match = re.search(r"products/(\d+)$", clean)
        data = await request.json()
        payload = UpdateTargetPricePayload(**data)
        return await api_update_product_target_price(int(match.group(1)), payload)
    elif re.search(r"products/(\d+)$", clean) and method == "DELETE":
        match = re.search(r"products/(\d+)$", clean)
        return await delete_single_product(int(match.group(1)))
    elif "assets/collection" in clean or "collection/asset" in clean:
        filename = clean.split("/")[-1]
        return await serve_collection_asset(filename)
    elif "collection" in clean:
        if clean in ("my-collection", "collection", "my_collection") or is_browser_request(request):
            return HTMLResponse(
                content=get_dashboard_html(),
                status_code=200,
                headers={"Cache-Control": "public, max-age=60, s-maxage=300, stale-while-revalidate=600"},
            )
        if "reset" in clean and method == "POST":
            return await api_reset_collection()
        archive_match = re.search(r"collection/([^/]+)/archive", clean)
        if archive_match and method == "POST":
            return await api_archive_collection_item(archive_match.group(1))
        item_match = re.search(r"collection/([^/]+)$", clean)
        if item_match:
            item_id = item_match.group(1)
            if method in ("PUT", "PATCH"):
                return await api_update_collection_item(item_id, request)
            elif method == "DELETE":
                return await api_delete_collection_item(item_id)
        if method == "POST":
            return await api_add_collection_item(request)
        return await api_get_collection()
    elif clean in ("api/products", "products"):
        if method == "POST":
            data = await request.json()
            payload = AddProductPayload(**data)
            return await api_add_product(payload)
        return await get_dashboard_data()

    # If requested by a browser or accessing root/dashboard/my-collection, return HTML with CDN caching
    if is_browser_request(request) or not clean or clean in ("dashboard", "index", "index.py", "api", "api/index", "api/index.py", "my-collection", "collection", "my_collection"):
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
        daemon_info = get_daemon_quick_status()

        last_sweep = None
        for p in products:
            if p.last_checked and (last_sweep is None or str(p.last_checked) > str(last_sweep)):
                last_sweep = p.last_checked

        for d in recent_deals:
            n_at = d.get("notified_at")
            if n_at and (last_sweep is None or str(n_at) > str(last_sweep)):
                last_sweep = n_at

        if daemon_info.get("seconds_since_activity") is not None:
            sec = daemon_info["seconds_since_activity"]
            daemon_dt = datetime.now(timezone.utc) - timedelta(seconds=sec)
            if last_sweep is None or daemon_dt.isoformat() > str(last_sweep):
                last_sweep = daemon_dt

        shoes_cfg = shoes_radar.load_config()
        shoes_deals = shoes_radar.load_cached_deals()

        stats = {
            "active_count": active_count,
            "total_count": len(products),
            "last_sweep_time": _format_datetime(last_sweep),
            "deal_radar_status": "ONLINE",
            "database": "Supabase PostgreSQL" if os.getenv("SUPABASE_URL") else "SQLite",
            "daemon": daemon_info,
            "running_shoes_radar": {
                "is_active": shoes_radar.is_active(),
                "deals_count": len(shoes_deals),
                "last_sweep": shoes_cfg.get("last_sweep"),
            },
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
            headers={"Cache-Control": "no-cache, no-store, must-revalidate, max-age=0"},
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
            detail="Unsupported URL. Supported: Amazon, Flipkart, Casio Bhawar, EliteHubs, Computech, GameLoot, Myntra, Ajio, Blinkit, Zepto, BigBasket."
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
        price_disp = f"₹{updated.current_price:g}" if (updated and updated.current_price) else "Out of Stock"
        title_disp = (updated.title or product.title or f"Product #{product_id}")[:40]
        await aemit_daemon_log("INFO", "tracker", f"Live check #{product_id} ({title_disp}) -> {price_disp}")
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


@app.patch("/api/products/{product_id}")
@app.post("/api/products/{product_id}/target-price")
@app.patch("/api/index.py/api/products/{product_id}")
@app.post("/api/index.py/api/products/{product_id}/target-price")
async def api_update_product_target_price(product_id: int, payload: UpdateTargetPricePayload):
    """Update target alert price for an existing monitored product."""
    if payload.target_price <= 0:
        raise HTTPException(status_code=400, detail="Target price must be greater than zero")

    db = get_database(settings)
    await db.initialize()
    try:
        product = await db.get_product(product_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        ok = await db.update_target_price(product_id, payload.target_price)
        if not ok:
            raise HTTPException(status_code=500, detail="Failed to update target price")

        updated = await db.get_product(product_id)
        return {
            "status": "success",
            "id": product_id,
            "target_price": updated.target_price if updated else payload.target_price,
            "current_price": updated.current_price if updated else None,
        }
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


async def aemit_daemon_log(level: str, logger_name: str, message: str) -> None:
    """Asynchronously append log entry to local log file and Supabase cloud log stream."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_line = f"[{now_str}] [{level.upper()}] {logger_name}: {message}\n"

    # 1. Local disk if present/writable
    candidates = [
        os.path.join(root_dir, "radar_daemon.log"),
        os.path.join(os.getcwd(), "radar_daemon.log"),
        "radar_daemon.log",
    ]
    log_file = next((c for c in candidates if os.path.exists(c)), None)
    if log_file:
        try:
            with open(log_file, "a", encoding="utf-8", errors="ignore") as f:
                f.write(formatted_line)
        except Exception:
            pass

    # 2. Supabase Cloud Stream
    sb_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    sb_key = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if sb_url and sb_key:
        try:
            sb_headers = {
                "apikey": sb_key,
                "Authorization": f"Bearer {sb_key}",
                "Content-Type": "application/json",
            }
            sb_payload = [
                {
                    "name": "DAEMON_LOG",
                    "category": level.upper(),
                    "platforms": logger_name,
                    "query": message,
                    "negative_keywords": f"{now_str} [{level.upper()}] {logger_name}: {message}",
                }
            ]
            async with httpx.AsyncClient(timeout=3.5) as client:
                await client.post(f"{sb_url}/rest/v1/custom_radar_rules", headers=sb_headers, json=sb_payload)
        except Exception as exc:
            logger.debug("aemit_daemon_log Supabase note: %s", exc)


def emit_daemon_log(level: str, logger_name: str, message: str) -> None:
    """Synchronously append log entry to local log file and Supabase cloud log stream."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_line = f"[{now_str}] [{level.upper()}] {logger_name}: {message}\n"

    candidates = [
        os.path.join(root_dir, "radar_daemon.log"),
        os.path.join(os.getcwd(), "radar_daemon.log"),
        "radar_daemon.log",
    ]
    log_file = next((c for c in candidates if os.path.exists(c)), None)
    if log_file:
        try:
            with open(log_file, "a", encoding="utf-8", errors="ignore") as f:
                f.write(formatted_line)
        except Exception:
            pass

    sb_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    sb_key = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if sb_url and sb_key:
        try:
            sb_headers = {
                "apikey": sb_key,
                "Authorization": f"Bearer {sb_key}",
                "Content-Type": "application/json",
            }
            sb_payload = [
                {
                    "name": "DAEMON_LOG",
                    "category": level.upper(),
                    "platforms": logger_name,
                    "query": message,
                    "negative_keywords": f"{now_str} [{level.upper()}] {logger_name}: {message}",
                }
            ]
            with httpx.Client(timeout=3.0) as client:
                client.post(f"{sb_url}/rest/v1/custom_radar_rules", headers=sb_headers, json=sb_payload)
        except Exception as exc:
            logger.debug("emit_daemon_log Supabase note: %s", exc)


@app.post("/api/sweep")
async def manual_deal_sweep():
    """Trigger an immediate full clearance scan (Casio & Flipkart) and product checks."""
    await aemit_daemon_log("INFO", "deal.sweep", "Manual sweep launched across Casio, Flipkart, and Amazon...")
    db = get_database(settings)
    await db.initialize()
    try:
        radar = StealRadar(settings, db=db)
        await radar.init()

        tracker = Tracker(db, radar.notifier, settings)
        manual_alerts = 0
        try:
            manual_alerts = await tracker.run_once()
        except Exception as e:
            logger.error("Manual sweep tracker error: %s", e)
            await aemit_daemon_log("ERROR", "tracker", f"Tracker check error: {e}")

        casio_alerts = 0
        try:
            casio_alerts = await radar.scan_all(only_platforms=["casio", "flipkart", "myntra"])
        except Exception as e:
            logger.error("Manual sweep radar error: %s", e)
            await aemit_daemon_log("ERROR", "radar", f"Radar clearance scan error: {e}")

        await radar.close()
        total_dispatched = casio_alerts + manual_alerts
        await aemit_daemon_log(
            "INFO",
            "deal.sweep",
            f"Sweep cycle finished: {casio_alerts} Casio clearance alerts, {manual_alerts} product alerts dispatched.",
        )

        return {
            "status": "success",
            "casio_alerts": casio_alerts,
            "manual_alerts": manual_alerts,
            "total_dispatched": total_dispatched,
        }
    finally:
        await db.close()


# ==========================================
# RUNNING SHOES RADAR REST APIS
# ==========================================

@app.get("/api/running-shoes/status")
@app.get("/api/index.py/api/running-shoes/status")
async def api_get_running_shoes_status():
    """Fetch real-time telemetry, configuration, and detected deals for running shoes."""
    cfg = shoes_radar.load_config()
    deals = shoes_radar.load_cached_deals()
    tracked_shoes = shoes_radar.get_tracked_catalog()
    return JSONResponse(
        content={
            "status": "online",
            "is_active": shoes_radar.is_active(),
            "last_sweep": cfg.get("last_sweep"),
            "min_price": cfg.get("min_price", 4000),
            "max_price": cfg.get("max_price", 5999),
            "target_sizes": cfg.get("target_sizes", ["UK 9.5", "UK 10", "UK 10.5", "UK 11"]),
            "total_deals": len(deals),
            "total_tracked": len(tracked_shoes),
            "deals": deals,
            "tracked_shoes": tracked_shoes,
            "whitelist_brands": ["Saucony", "Reebok", "Hoka", "Brooks", "Puma", "Nike", "Adidas", "Asics", "New Balance", "Skechers", "On Running"],
            "enabled_brands": cfg.get("enabled_brands", {
                "Saucony": True,
                "Reebok": True,
                "Hoka": True,
                "Brooks": True,
                "Puma": True,
                "Nike": True,
                "Adidas": True,
                "Asics": True,
                "New Balance": True,
                "Skechers": True,
                "On Running": True,
            }),
        },
        headers={"Cache-Control": "no-cache"},
    )


@app.post("/api/running-shoes/toggle")
@app.post("/api/index.py/api/running-shoes/toggle")
async def api_toggle_running_shoes(request: Request):
    """Switch Running Shoes Harvester ON or OFF."""
    target = None
    try:
        body = await request.json()
        if "active" in body:
            target = bool(body["active"])
    except Exception:
        pass
    if target is None:
        target = not shoes_radar.is_active()

    new_state = shoes_radar.set_active(target)
    state_str = "ACTIVE (Monitoring 24/7)" if new_state else "PAUSED"
    await aemit_daemon_log("INFO", "running_shoes", f"Running shoes harvester master switch toggled -> {state_str}")
    return JSONResponse(content={"status": "success", "is_active": new_state})


@app.post("/api/running-shoes/toggle-brand")
@app.post("/api/index.py/api/running-shoes/toggle-brand")
async def api_toggle_shoe_brand(request: Request):
    """Enable or disable tracking searches for a specific shoe brand."""
    try:
        body = await request.json()
        brand = body.get("brand")
        enabled = body.get("enabled", True)
        if not brand:
            raise HTTPException(status_code=400, detail="Brand parameter required")
        updated_brands = shoes_radar.toggle_brand(brand, enabled)
        st_text = "ENABLED" if enabled else "DISABLED"
        await aemit_daemon_log("INFO", "running_shoes", f"Brand filter updated: {brand} -> {st_text}")
        return JSONResponse(
            content={
                "status": "success",
                "brand": brand,
                "enabled": enabled,
                "enabled_brands": updated_brands,
            }
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/running-shoes/toggle-shoe")
@app.post("/api/index.py/api/running-shoes/toggle-shoe")
async def api_toggle_single_shoe(request: Request):
    """Enable or disable tracking for a specific shoe model."""
    try:
        body = await request.json()
        shoe_key = body.get("shoe_key")
        active = body.get("active")
        if not shoe_key:
            raise HTTPException(status_code=400, detail="shoe_key parameter required")
        new_active = shoes_radar.toggle_shoe(shoe_key, active)
        st_text = "TRACKING" if new_active else "PAUSED"
        await aemit_daemon_log("INFO", "running_shoes", f"Shoe silhouette '{shoe_key}' set to {st_text}")
        return JSONResponse(
            content={"status": "success", "shoe_key": shoe_key, "is_active": new_active}
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/running-shoes/sweep")
@app.post("/api/index.py/api/running-shoes/sweep")
async def api_sweep_running_shoes():
    """Trigger an immediate live harvest sweep across Myntra, Flipkart, Tata CLiQ, and Ajio."""
    await aemit_daemon_log("INFO", "running_shoes", "Running shoes harvest initiated across Myntra, Flipkart, Tata CLiQ & Ajio...")
    res = await shoes_radar.sweep()
    new_found = res.get("new_deals_found", 0) if isinstance(res, dict) else 0
    scanned = res.get("total_scanned", 0) if isinstance(res, dict) else 0
    await aemit_daemon_log("INFO", "running_shoes", f"Harvest complete: {new_found} new deals detected ({scanned} shoes scanned).")
    return JSONResponse(content=res)


# ==========================================
# MY COLLECTION // PERSONAL INVENTORY & ARCHIVE
# ==========================================

@app.get("/api/collection")
@app.get("/api/index.py/api/collection")
async def api_get_collection():
    """Get all items in personal collection along with computed statistics."""
    stats = collection_mgr.get_summary_stats()
    items = collection_mgr.get_all_items()
    return JSONResponse(
        content={
            "status": "success",
            "stats": stats,
            "items": items,
        },
        headers={"Cache-Control": "no-cache, no-store, must-revalidate, max-age=0"},
    )


@app.post("/api/collection")
@app.post("/api/index.py/api/collection")
async def api_add_collection_item(request: Request):
    """Add a new item to personal collection."""
    try:
        data = await request.json()
        item = collection_mgr.add_item(data)
        return JSONResponse(content={"status": "success", "item": item}, status_code=201)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.put("/api/collection/{item_id}")
@app.patch("/api/collection/{item_id}")
@app.put("/api/index.py/api/collection/{item_id}")
@app.patch("/api/index.py/api/collection/{item_id}")
async def api_update_collection_item(item_id: str, request: Request):
    """Update an item in personal collection."""
    try:
        data = await request.json()
        item = collection_mgr.update_item(item_id, data)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        return JSONResponse(content={"status": "success", "item": item})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/collection/{item_id}/archive")
@app.post("/api/index.py/api/collection/{item_id}/archive")
async def api_archive_collection_item(item_id: str):
    """Toggle archive status for a collection item."""
    item = collection_mgr.archive_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return JSONResponse(content={"status": "success", "item": item})


@app.delete("/api/collection/{item_id}")
@app.delete("/api/index.py/api/collection/{item_id}")
async def api_delete_collection_item(item_id: str):
    """Delete an item from personal collection."""
    success = collection_mgr.delete_item(item_id)
    if not success:
        raise HTTPException(status_code=404, detail="Item not found")
    return JSONResponse(content={"status": "success", "deleted": True, "id": item_id})


@app.post("/api/collection/reset")
@app.post("/api/index.py/api/collection/reset")
async def api_reset_collection():
    """Reset collection to verified initial 17 items."""
    items = collection_mgr.reset_to_defaults()
    stats = collection_mgr.get_summary_stats()
    return JSONResponse(content={"status": "success", "stats": stats, "items": items})


@app.get("/assets/collection/{filename}")
@app.get("/api/collection/asset/{filename}")
@app.get("/api/index.py/assets/collection/{filename}")
@app.get("/api/index.py/api/collection/asset/{filename}")
async def serve_collection_asset(filename: str):
    """Serve local mockup assets for collection items."""
    clean_name = os.path.basename(filename)
    asset_dir = os.path.join(root_dir, "assets", "collection")
    filepath = os.path.join(asset_dir, clean_name)
    if os.path.exists(filepath):
        ext = os.path.splitext(clean_name)[1].lower()
        content_types = {
            ".webp": "image/webp",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".svg": "image/svg+xml",
        }
        media_type = content_types.get(ext, "image/jpeg")
        return FileResponse(filepath, media_type=media_type, headers={"Cache-Control": "public, max-age=86400"})
    raise HTTPException(status_code=404, detail="Asset not found")



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
        # Strict 12.0s timeout guarantees Vercel NEVER returns a 504 Gateway Timeout (maxDuration is 15s)
        await asyncio.wait_for(assistant.handle_message(message), timeout=12.0)
    except asyncio.TimeoutError:
        logger.warning(
            "Telegram webhook processing timed out after 12.0s for update_id %s; returning 200 OK to prevent Telegram retry loop",
            update_id,
        )
        chat = message.get("chat", {})
        text = (message.get("text") or "").strip()
        url_match = re.search(r"(https?://[^\s]+)", text)
        if url_match:
            try:
                from scrapers import detect_platform, extract_fallback_title, normalize_product_url
                raw_u = url_match.group(1).rstrip("),.]\"'")
                plat = detect_platform(raw_u, safe=True) or "online"
                clean_u = normalize_product_url(raw_u, plat)
                fb_title = extract_fallback_title(raw_u, plat)
                m_target = re.search(r"(?:under|below|target|price|₹|rs\.?)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)", text.replace(url_match.group(1), ""), re.I)
                target_val = float(m_target.group(1).replace(",", "")) if m_target else None
                await db.add_product(
                    url=clean_u,
                    platform=plat,
                    target_price=target_val,
                    initial_price=None,
                    title=fb_title,
                )
            except Exception as ins_exc:
                logger.debug("Emergency fallback DB insertion error: %s", ins_exc)

        if chat.get("id"):
            try:
                await assistant.send_reply(
                    chat["id"],
                    "⏳ *Processing Request...*\n\nThe retailer page is taking longer to verify. Product has been registered in your radar and live verification will complete in the background!"
                )
            except Exception:
                pass
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
                await aemit_daemon_log("INFO", "cron", f"Vercel cron pulse heartbeat: {len(products)} monitored products are fresh.")
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

        tot = casio_alerts + manual_alerts
        await aemit_daemon_log("INFO", "cron", f"Vercel cron sweep pulse executed: {len(products)} products checked, {tot} alerts generated.")

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
# SYSTEM LOGS & TELEMETRY CONTROLLER
# ==========================================

def get_daemon_quick_status() -> dict[str, Any]:
    """Lightweight check of radar daemon heartbeat and file update activity."""
    candidates = [
        os.path.join(root_dir, "radar_daemon.log"),
        os.path.join(os.getcwd(), "radar_daemon.log"),
        "radar_daemon.log",
    ]
    log_file = next((c for c in candidates if os.path.exists(c)), None)
    local_info = None
    if log_file:
        try:
            stat = os.stat(log_file)
            seconds_ago = int(time.time() - stat.st_mtime)
            is_running = seconds_ago <= 180
            status_text = "ACTIVE" if is_running else ("IDLE" if seconds_ago <= 600 else "STOPPED")
            local_info = {
                "is_running": is_running,
                "status_text": status_text,
                "seconds_since_activity": seconds_ago,
                "has_log_file": True,
                "size_mb": round(stat.st_size / (1024 * 1024), 2),
                "last_activity_time": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            }
            if is_running:
                return local_info
        except Exception:
            pass

    # Cloud / Supabase check (e.g. GitHub Actions cloud runner activity)
    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    supabase_key = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if supabase_url and supabase_key:
        try:
            headers = {"apikey": supabase_key, "Authorization": f"Bearer {supabase_key}"}
            with httpx.Client(timeout=3.5) as client:
                r = client.get(
                    f"{supabase_url}/rest/v1/price_logs?select=timestamp&order=timestamp.desc&limit=1",
                    headers=headers,
                )
                if r.status_code == 200 and r.json():
                    p_ts = r.json()[0]["timestamp"]
                    dt = datetime.fromisoformat(p_ts.replace("Z", "+00:00"))
                    now = datetime.now(timezone.utc)
                    sec_ago = max(0, int((now - dt).total_seconds()))
                    is_run = sec_ago <= 360  # GitHub Actions 5-min runner
                    cloud_info = {
                        "is_running": is_run,
                        "status_text": "ACTIVE" if is_run else ("IDLE" if sec_ago <= 600 else "STOPPED"),
                        "seconds_since_activity": sec_ago,
                        "has_log_file": False,
                        "size_mb": 0.0,
                        "last_activity_time": p_ts,
                    }
                    if is_run or local_info is None or sec_ago < local_info.get("seconds_since_activity", 999999):
                        return cloud_info
        except Exception:
            pass

    if local_info is not None:
        return local_info

    return {
        "is_running": False,
        "status_text": "OFFLINE",
        "seconds_since_activity": None,
        "has_log_file": False,
        "size_mb": 0.0,
    }


VIP_WATCHES_DEF = [
    {
        "id": 58,
        "name": "CASIO G-SHOCK GBD-H2000-1A9 G-SQUAD",
        "short_name": "GBD-H2000-1A9",
        "url": "https://casiostore.bhawar.com/products/casio-g-shock-gbd-h2000-1a9-g-squad-digital-sports-watch",
        "target_price": 14000.0,
        "default_price": 13499.0,
        "mrp": 44995,
        "tag": "gbd-h2000",
    },
    {
        "id": 5,
        "name": "CASIO G-SHOCK GBD-300-9DR",
        "short_name": "GBD-300-9DR",
        "url": "https://casiostore.bhawar.com/products/casio-g-shock-gbd-300-9dr-watch",
        "target_price": 4000.0,
        "default_price": 3495.0,
        "mrp": 11495,
        "tag": "gbd-300-9dr",
    },
]


def get_vip_logs_and_telemetry() -> dict[str, Any]:
    """Retrieve dedicated VIP Steal Checker logs and live state for GBD-H2000 and GBD-300."""
    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    supabase_key = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    vip_entries: list[dict[str, Any]] = []

    # 1. Fetch from Supabase cloud
    if supabase_url and supabase_key:
        try:
            headers = {"apikey": supabase_key, "Authorization": f"Bearer {supabase_key}"}
            with httpx.Client(timeout=4.0) as client:
                resp = client.get(
                    f"{supabase_url}/rest/v1/custom_radar_rules?name=eq.VIP_LOG&order=id.desc&limit=60",
                    headers=headers,
                )
                if resp.status_code == 200:
                    for row in resp.json():
                        ts = (row.get("created_at") or "")[:19].replace("T", " ")
                        raw = row.get("negative_keywords") or row.get("query") or ""
                        category = (row.get("category") or "OUT_OF_STOCK").upper()
                        vip_entries.append({
                            "id": row.get("id"),
                            "timestamp": ts,
                            "level": "VIP",
                            "logger": "vip.casio",
                            "category": category,
                            "tag": row.get("platforms") or "vip",
                            "message": row.get("query") or "",
                            "raw": raw,
                        })
        except Exception as exc:
            logger.debug("Supabase VIP log read error: %s", exc)

    # 2. Also check local radar_daemon.log for any lines matching VIP sniper
    candidates = [
        os.path.join(root_dir, "radar_daemon.log"),
        os.path.join(os.getcwd(), "radar_daemon.log"),
        "radar_daemon.log",
    ]
    log_file = next((c for c in candidates if os.path.exists(c)), None)
    if log_file:
        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()[-400:]
            for line in reversed(lines):
                line_str = line.strip()
                if any(k in line_str for k in ("[VIP SNIPER]", "vip.sniper", "gbd-h2000", "gbd-300", "[VIP WATCH]")):
                    ts = line_str[:19] if (len(line_str) >= 19 and line_str[4] == "-") else ""
                    tag = "gbd-h2000" if "gbd-h2000" in line_str.lower() else ("gbd-300-9dr" if "gbd-300" in line_str.lower() else "vip")
                    cat = "IN_STOCK" if "IN STOCK" in line_str else "OUT_OF_STOCK"
                    # Deduplicate with already collected entries
                    if not any(e["raw"] == line_str for e in vip_entries):
                        vip_entries.append({
                            "id": len(vip_entries) + 1,
                            "timestamp": ts,
                            "level": "VIP",
                            "logger": "vip.sniper",
                            "category": cat,
                            "tag": tag,
                            "message": line_str,
                            "raw": line_str,
                        })
        except Exception as exc:
            logger.debug("Local VIP log scan note: %s", exc)

    # Sort newest first
    vip_entries.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
    vip_entries = vip_entries[:60]

    # Synthesize watch status
    watches = []
    for w in VIP_WATCHES_DEF:
        tag = w["tag"]
        recent_probe = next((e for e in vip_entries if tag in e.get("tag", "").lower() or tag in e.get("raw", "").lower() or w["short_name"].lower() in e.get("raw", "").lower()), None)

        in_stock = False
        last_price = w["default_price"]
        http_code = 200
        last_time = "Recent check"
        detail = "60-second ultra-high frequency priority guard active"

        if recent_probe:
            last_time = recent_probe.get("timestamp") or last_time
            in_stock = recent_probe.get("category") == "IN_STOCK"
            raw_text = recent_probe.get("raw") or ""
            if "HTTP 404" in raw_text:
                http_code = 404
                detail = "HTTP 404 (Unlisted / Waiting Drop)"
            elif "HTTP 200" in raw_text:
                http_code = 200
                detail = "Shopify API 200 OK (available: false)"
            if "Price: ₹" in raw_text:
                try:
                    p_str = raw_text.split("Price: ₹")[1].split()[0].replace(",", "")
                    last_price = float(p_str)
                except Exception:
                    pass

        watches.append({
            "id": w["id"],
            "name": w["name"],
            "short_name": w["short_name"],
            "tag": w["tag"],
            "url": w["url"],
            "target_price": w["target_price"],
            "mrp": w["mrp"],
            "price": last_price,
            "in_stock": in_stock,
            "status": "IN_STOCK" if in_stock else "OUT_OF_STOCK",
            "status_badge": "RESTOCKED! IN STOCK" if in_stock else "OUT OF STOCK",
            "last_checked": last_time,
            "http_status": http_code,
            "detail": detail,
        })

    return {
        "status": "success",
        "watches": watches,
        "logs": vip_entries,
    }


async def probe_vip_watches_live() -> dict[str, Any]:
    """Execute instantaneous real-time probe of both Casio VIP watches."""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    watches_res = []
    new_logs = []

    sb_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    sb_key = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
        for w in VIP_WATCHES_DEF:
            target_url = w["url"]
            js_url = f"{target_url}.js"
            in_stock = False
            deal_price = w["default_price"]
            r_status = 0
            detail = ""

            try:
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
                        detail = f"Shopify API HTTP 200 (Available: {is_avail})"
                    except Exception as e:
                        detail = f"JSON parse note: {e}"
                elif r.status_code == 404:
                    r_html = await client.get(target_url, headers=headers)
                    r_status = r_html.status_code
                    if r_html.status_code == 200 and "404" not in r_html.text[:300].lower():
                        in_stock = True
                        detail = "HTML Page 200 OK (Product Un-hidden)"
                    else:
                        detail = "HTTP 404 (Unlisted / Waiting Drop)"
                else:
                    detail = f"HTTP {r.status_code}"
            except Exception as exc:
                detail = f"Probe connection error: {exc}"

            status_str = "IN_STOCK" if in_stock else "OUT_OF_STOCK"
            raw_log = f"{now_str} [VIP SNIPER] {w['name']} -> {status_str} [HTTP {r_status}] (Price: ₹{deal_price:g} / Target: ₹{w['target_price']:g}) {detail}".strip()

            watch_obj = {
                "id": w["id"],
                "name": w["name"],
                "short_name": w["short_name"],
                "tag": w["tag"],
                "url": w["url"],
                "target_price": w["target_price"],
                "mrp": w["mrp"],
                "price": deal_price,
                "in_stock": in_stock,
                "status": status_str,
                "status_badge": "RESTOCKED! IN STOCK" if in_stock else "OUT OF STOCK",
                "last_checked": now_str,
                "http_status": r_status,
                "detail": detail,
            }
            watches_res.append(watch_obj)

            log_entry = {
                "timestamp": now_str,
                "level": "VIP",
                "logger": "vip.sniper",
                "category": status_str,
                "tag": w["tag"],
                "message": f"{w['name']} -> {status_str} (Price: ₹{deal_price:g}, Target: ₹{w['target_price']:g})",
                "raw": raw_log,
            }
            new_logs.append(log_entry)

            # Ship to Supabase
            if sb_url and sb_key:
                try:
                    sb_headers = {"apikey": sb_key, "Authorization": f"Bearer {sb_key}", "Content-Type": "application/json"}
                    sb_payload = [
                        {
                            "name": "VIP_LOG",
                            "category": status_str,
                            "platforms": w["tag"],
                            "query": log_entry["message"],
                            "negative_keywords": raw_log,
                        },
                        {
                            "name": "DAEMON_LOG",
                            "category": "CRITICAL" if in_stock else "INFO",
                            "platforms": "vip.sniper",
                            "query": f"[VIP WATCH] {w['name']} -> {status_str} (Target: ₹{w['target_price']:g})",
                            "negative_keywords": f"{now_str} [INFO] vip.sniper: {w['name']} -> {status_str} (Price: ₹{deal_price:g}, Target: ₹{w['target_price']:g}, HTTP {r_status})",
                        },
                    ]
                    await client.post(f"{sb_url}/rest/v1/custom_radar_rules", headers=sb_headers, json=sb_payload)
                except Exception as sb_err:
                    logger.debug("Live probe Supabase upload note: %s", sb_err)

    return {
        "status": "success",
        "timestamp": now_str,
        "watches": watches_res,
        "logs": new_logs,
    }


def _fetch_supabase_logs_and_status(limit: int = 100, level: Optional[str] = None, search: Optional[str] = None) -> dict[str, Any]:
    """Retrieve synced daemon logs and activity from Supabase cloud database for serverless environments."""
    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    supabase_key = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not supabase_url or not supabase_key:
        return {
            "status": "serverless_active",
            "daemon": {
                "is_running": True,
                "status_text": "SERVERLESS RUNNER",
                "seconds_since_activity": 0,
                "file_size_mb": 0.0,
                "counts": {"total": 0, "errors": 0, "warnings": 0, "info": 0},
                "note": "Radar daemon runs locally or via scheduled GitHub Actions runner.",
            },
            "logs": [],
            "recent_issues": [],
            "vip": get_vip_logs_and_telemetry(),
        }

    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
    }

    parsed_entries: list[dict[str, Any]] = []
    total_errors = 0
    total_warnings = 0
    total_info = 0
    seconds_ago = None
    is_running = False

    try:
        with httpx.Client(timeout=6.0) as client:
            # 1. Fetch synced daemon logs
            resp = client.get(
                f"{supabase_url}/rest/v1/custom_radar_rules?name=eq.DAEMON_LOG&order=id.desc&limit=300",
                headers=headers,
            )
            rows = resp.json() if resp.status_code == 200 else []

            # 2. Fetch latest price logs for telemetry & backup activity
            resp_p = client.get(
                f"{supabase_url}/rest/v1/price_logs?select=timestamp,price,products(title,platform)&order=timestamp.desc&limit=30",
                headers=headers,
            )
            price_rows = resp_p.json() if resp_p.status_code == 200 else []

            # Determine latest activity
            latest_iso = None
            if rows and rows[0].get("created_at"):
                latest_iso = rows[0]["created_at"]
            if price_rows and price_rows[0].get("timestamp"):
                p_ts = price_rows[0]["timestamp"]
                if not latest_iso or p_ts > latest_iso:
                    latest_iso = p_ts

            if latest_iso:
                try:
                    dt = datetime.fromisoformat(latest_iso.replace("Z", "+00:00"))
                    now = datetime.now(timezone.utc)
                    seconds_ago = max(0, int((now - dt).total_seconds()))
                    is_running = seconds_ago <= 300
                except Exception:
                    seconds_ago = 5
                    is_running = True

            # Convert synced daemon logs (stored newest first; reverse to ascending order for terminal)
            for row in reversed(rows):
                lvl = (row.get("category") or "INFO").upper()
                ts_raw = row.get("created_at", "")
                ts_clean = ts_raw[:19].replace("T", " ") if ts_raw else ""
                logger_name = row.get("platforms") or "daemon"
                msg = row.get("query") or ""
                raw_line = row.get("negative_keywords") or msg

                if lvl in ("ERROR", "CRITICAL"):
                    total_errors += 1
                elif lvl in ("WARNING", "WARN"):
                    total_warnings += 1
                else:
                    total_info += 1

                parsed_entries.append({
                    "id": row.get("id", len(parsed_entries) + 1),
                    "timestamp": ts_clean,
                    "level": lvl,
                    "logger": logger_name,
                    "message": msg,
                    "raw": raw_line,
                })

            # If no DAEMON_LOG entries exist, fallback to synthesized price check logs
            if not parsed_entries and price_rows:
                for prow in reversed(price_rows):
                    p_info = prow.get("products") or {}
                    title = p_info.get("title") or "Tracked Product"
                    plat = p_info.get("platform") or "online"
                    price = prow.get("price")
                    p_ts = prow.get("timestamp", "")[:19].replace("T", " ")
                    msg = f"[{plat}] {title} -> INR {price} (in stock)"
                    total_info += 1
                    parsed_entries.append({
                        "id": len(parsed_entries) + 1,
                        "timestamp": p_ts,
                        "level": "INFO",
                        "logger": "tracker",
                        "message": msg,
                        "raw": f"{p_ts} [INFO] tracker: {msg}",
                    })

    except Exception as exc:
        logger.warning("Error fetching cloud logs from Supabase: %s", exc)

    if is_running:
        status_text = "ACTIVE & STREAMING"
    elif seconds_ago is not None and seconds_ago <= 1800:
        status_text = "STANDBY / CLOUD SYNCED"
        is_running = True
    else:
        status_text = "STANDBY (Serverless Runner)"
        is_running = False

    # Extract recent issues (errors + warnings), newest first
    recent_issues = [
        e for e in parsed_entries
        if e["level"] in ("ERROR", "CRITICAL", "WARNING", "WARN")
    ]
    recent_issues.reverse()
    recent_issues = recent_issues[:50]

    # Filter by level
    filtered = parsed_entries
    if level:
        lvl_k = level.lower().strip()
        if lvl_k in ("error", "errors"):
            filtered = [e for e in filtered if e["level"] in ("ERROR", "CRITICAL")]
        elif lvl_k in ("warning", "warn", "warnings"):
            filtered = [e for e in filtered if e["level"] in ("WARNING", "WARN")]
        elif lvl_k in ("warning_error", "issues", "problems"):
            filtered = [e for e in filtered if e["level"] in ("ERROR", "CRITICAL", "WARNING", "WARN")]
        elif lvl_k in ("info",):
            filtered = [e for e in filtered if e["level"] == "INFO"]
        elif lvl_k in ("vip", "vip_sniper"):
            filtered = [e for e in filtered if any(k in e["raw"].lower() for k in ("vip", "gbd-h2000", "gbd-300"))]

    if search:
        sq = search.lower().strip()
        filtered = [
            e for e in filtered
            if sq in e["message"].lower() or sq in e["logger"].lower() or sq in e["raw"].lower()
        ]

    limit_val = max(10, min(limit or 100, 1000))
    logs_slice = filtered[-limit_val:]

    return {
        "status": "success",
        "daemon": {
            "is_running": is_running,
            "status_text": status_text,
            "seconds_since_activity": seconds_ago,
            "file_size_mb": 0.0,
            "log_path": "supabase://custom_radar_rules (Cloud Stream)",
            "counts": {
                "total": len(parsed_entries),
                "errors": total_errors,
                "warnings": total_warnings,
                "info": total_info,
            },
        },
        "logs": logs_slice,
        "recent_issues": recent_issues,
        "vip": get_vip_logs_and_telemetry(),
    }


def get_parsed_logs(limit: int = 100, level: Optional[str] = None, search: Optional[str] = None) -> dict[str, Any]:
    """Parse recent entries from radar_daemon.log or fallback to Supabase cloud sync."""
    candidates = [
        os.path.join(root_dir, "radar_daemon.log"),
        os.path.join(os.getcwd(), "radar_daemon.log"),
        "radar_daemon.log",
    ]
    log_file = next((c for c in candidates if os.path.exists(c)), None)

    if not log_file:
        return _fetch_supabase_logs_and_status(limit=limit, level=level, search=search)

    try:
        stat = os.stat(log_file)
        mtime = stat.st_mtime
        now = time.time()
        seconds_ago = int(now - mtime)
        is_running = seconds_ago <= 180
        status_text = "ACTIVE & STREAMING" if is_running else ("STANDBY / IDLE" if seconds_ago <= 600 else "OFFLINE / STOPPED")

        # If local file is stale (> 10 mins without updates), verify if Supabase has newer activity
        if seconds_ago > 600:
            cloud_check = _fetch_supabase_logs_and_status(limit=limit, level=level, search=search)
            if cloud_check.get("daemon", {}).get("is_running") or (cloud_check.get("daemon", {}).get("seconds_since_activity") or 9999) < seconds_ago:
                return cloud_check

        # Read last 350KB chunk for rapid, low-memory response
        seek_bytes = min(stat.st_size, 350000)
        with open(log_file, "rb") as f:
            f.seek(stat.st_size - seek_bytes)
            chunk = f.read().decode("utf-8", errors="ignore")

        lines = chunk.splitlines()
        if seek_bytes < stat.st_size and lines:
            lines = lines[1:]  # Discard partial initial line

        pat_std = re.compile(
            r"^(?P<timestamp>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}[,\.]\d{3})\s+\[(?P<level>[A-Z]+)\]\s+(?P<logger>[^:]+):\s+(?P<message>.*)$"
        )
        pat_bracket_lvl = re.compile(
            r"^\[(?P<timestamp>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\]\s+(?P<level>[A-Z]+):\s+(?P<message>.*)$"
        )
        pat_bracket_msg = re.compile(
            r"^\[(?P<timestamp>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\]\s+(?P<message>.*)$"
        )

        parsed_entries: list[dict[str, Any]] = []
        total_errors = 0
        total_warnings = 0
        total_info = 0

        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            m1 = pat_std.match(line_str)
            m2 = pat_bracket_lvl.match(line_str)
            m3 = pat_bracket_msg.match(line_str)

            if m1:
                d = m1.groupdict()
                lvl = d["level"].upper()
                ts = d["timestamp"]
                logger_name = d["logger"].strip()
                msg = d["message"]
            elif m2:
                d = m2.groupdict()
                lvl = d["level"].upper()
                ts = d["timestamp"]
                logger_name = "system"
                msg = d["message"]
            elif m3:
                d = m3.groupdict()
                lvl = "INFO"
                ts = d["timestamp"]
                logger_name = "radar"
                msg = d["message"]
            else:
                low = line_str.lower()
                if any(k in low for k in ("error", "traceback", "exception", "failed", "critical")):
                    lvl = "ERROR"
                elif any(k in low for k in ("warn", "warning", "retry", "timeout")):
                    lvl = "WARNING"
                else:
                    lvl = "INFO"
                ts = ""
                logger_name = "stdout"
                msg = line_str

            if lvl in ("ERROR", "CRITICAL"):
                total_errors += 1
            elif lvl in ("WARNING", "WARN"):
                total_warnings += 1
            else:
                total_info += 1

            parsed_entries.append({
                "id": len(parsed_entries) + 1,
                "timestamp": ts,
                "level": lvl,
                "logger": logger_name,
                "message": msg,
                "raw": line_str,
            })

        # Extract recent issues (warnings + errors), newest first
        recent_issues = [
            e for e in parsed_entries
            if e["level"] in ("ERROR", "CRITICAL", "WARNING", "WARN")
        ]
        recent_issues.reverse()
        recent_issues = recent_issues[:50]

        filtered = parsed_entries
        if level:
            lvl_k = level.lower().strip()
            if lvl_k in ("error", "errors"):
                filtered = [e for e in filtered if e["level"] in ("ERROR", "CRITICAL")]
            elif lvl_k in ("warning", "warn", "warnings"):
                filtered = [e for e in filtered if e["level"] in ("WARNING", "WARN")]
            elif lvl_k in ("warning_error", "issues", "problems"):
                filtered = [e for e in filtered if e["level"] in ("ERROR", "CRITICAL", "WARNING", "WARN")]
            elif lvl_k in ("info",):
                filtered = [e for e in filtered if e["level"] == "INFO"]
            elif lvl_k in ("vip", "vip_sniper"):
                filtered = [e for e in filtered if any(k in e["raw"].lower() for k in ("vip", "gbd-h2000", "gbd-300"))]

        if search:
            sq = search.lower().strip()
            filtered = [
                e for e in filtered
                if sq in e["message"].lower() or sq in e["logger"].lower() or sq in e["raw"].lower()
            ]

        # Strictly show latest 100 logs by default
        limit_val = max(10, min(limit or 100, 1000))
        logs_slice = filtered[-limit_val:]

        return {
            "status": "success",
            "daemon": {
                "is_running": is_running,
                "status_text": status_text,
                "seconds_since_activity": seconds_ago,
                "file_size_mb": round(stat.st_size / (1024 * 1024), 2),
                "log_path": log_file,
                "counts": {
                    "total": len(parsed_entries),
                    "errors": total_errors,
                    "warnings": total_warnings,
                    "info": total_info,
                },
            },
            "logs": logs_slice,
            "recent_issues": recent_issues,
            "vip": get_vip_logs_and_telemetry(),
        }
    except Exception as exc:
        logger.error("Error parsing logs: %s", exc)
        return {
            "status": "error",
            "daemon": {"is_running": False, "status_text": "READ ERROR"},
            "message": str(exc),
            "logs": [],
            "recent_issues": [],
            "vip": get_vip_logs_and_telemetry(),
        }


@app.get("/api/logs")
async def api_get_logs(
    limit: int = Query(100, ge=1, le=1000),
    level: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
):
    """Retrieve structured parsed logs (latest 100), daemon status, and VIP sniper telemetry."""
    data = get_parsed_logs(limit=limit, level=level, search=search)
    return JSONResponse(
        content=data,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/api/logs/vip")
async def api_get_vip_logs():
    """Retrieve dedicated real-time VIP steal checker telemetry for GBD-H2000 & GBD-300."""
    vip_data = get_vip_logs_and_telemetry()
    return JSONResponse(
        content=vip_data,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.post("/api/logs/vip/probe")
async def api_probe_vip_now():
    """Trigger an instantaneous on-demand probe of both Casio VIP watches and return live status."""
    res = await probe_vip_watches_live()
    return JSONResponse(
        content=res,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.delete("/api/logs")
@app.post("/api/logs/clear")
async def api_clear_logs():
    """Truncate or reset radar_daemon.log and purge stale Supabase cloud log stream."""
    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    supabase_key = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    cleared_supabase = False

    if supabase_url and supabase_key:
        try:
            sb_headers = {
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Content-Type": "application/json",
            }
            async with httpx.AsyncClient(timeout=6.0) as client:
                # 1. Delete all existing DAEMON_LOG and VIP_LOG rows from Supabase
                await client.delete(
                    f"{supabase_url}/rest/v1/custom_radar_rules?name=in.(DAEMON_LOG,VIP_LOG)",
                    headers=sb_headers,
                )
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                # 2. Insert one clean initial reset log line so terminal displays fresh status
                reset_payload = [
                    {
                        "name": "DAEMON_LOG",
                        "category": "INFO",
                        "platforms": "system",
                        "query": "Radar log stream reset and cloud-synced by administrator.",
                        "negative_keywords": f"{now_str} [INFO] system: Radar log stream reset and cloud-synced by administrator.",
                    }
                ]
                await client.post(
                    f"{supabase_url}/rest/v1/custom_radar_rules",
                    headers=sb_headers,
                    json=reset_payload,
                )
                cleared_supabase = True
        except Exception as exc:
            logger.warning("Error clearing Supabase cloud logs: %s", exc)

    candidates = [
        os.path.join(root_dir, "radar_daemon.log"),
        os.path.join(os.getcwd(), "radar_daemon.log"),
        "radar_daemon.log",
    ]
    log_file = next((c for c in candidates if os.path.exists(c)), None)
    if log_file:
        try:
            with open(log_file, "r+", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
                keep_lines = lines[-50:] if len(lines) > 50 else lines
                f.seek(0)
                f.truncate()
                now_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"[{now_stamp}] [INFO] radar: Log stream reset by user from dashboard.\n")
                f.writelines(keep_lines)
        except Exception as exc:
            logger.error("Error truncating log file: %s", exc)

    return JSONResponse(
        content={
            "status": "ok",
            "message": "Log stream reset successfully; cloud and local buffers synchronized.",
            "cleared_supabase": cleared_supabase,
        }
    )


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

    # 7.5 Running Shoes Sub-routes
    if "running-shoes" in clean:
        if "toggle-shoe" in clean:
            return await api_toggle_single_shoe(request)
        if "toggle-brand" in clean:
            return await api_toggle_shoe_brand(request)
        if "toggle" in clean:
            return await api_toggle_running_shoes(request)
        if "sweep" in clean:
            return await api_sweep_running_shoes()
        if "status" in clean:
            return await api_get_running_shoes_status()

    # 7.8 Logs Sub-routes
    if "logs" in clean:
        if "vip/probe" in clean:
            return await api_probe_vip_now()
        if "vip" in clean:
            return await api_get_vip_logs()
        if method == "DELETE" or "clear" in clean:
            return await api_clear_logs()
        limit = int(request.query_params.get("limit", 100))
        level = request.query_params.get("level")
        search = request.query_params.get("search")
        return await api_get_logs(limit=limit, level=level, search=search)

    # 7.9 Collection Sub-routes
    if "assets/collection" in clean or "collection/asset" in clean:
        filename = clean.split("/")[-1]
        return await serve_collection_asset(filename)

    if "collection" in clean:
        if clean in ("my-collection", "collection", "my_collection") or is_browser_request(request):
            return HTMLResponse(content=get_dashboard_html(), status_code=200)
        if "reset" in clean and method == "POST":
            return await api_reset_collection()
        archive_match = re.search(r"collection/([^/]+)/archive", clean)
        if archive_match and method == "POST":
            return await api_archive_collection_item(archive_match.group(1))
        item_match = re.search(r"collection/([^/]+)$", clean)
        if item_match:
            item_id = item_match.group(1)
            if method in ("PUT", "PATCH"):
                return await api_update_collection_item(item_id, request)
            elif method == "DELETE":
                return await api_delete_collection_item(item_id)
        if method == "POST":
            return await api_add_collection_item(request)
        return await api_get_collection()

    # 8. Root or Dashboard HTML fallback
    if method == "GET" and (is_browser_request(request) or clean in ("", "dashboard", "index", "index.py", "api", "api/index", "api/index.py", "my-collection", "collection", "my_collection")):
        return HTMLResponse(content=get_dashboard_html(), status_code=200)

    return JSONResponse(
        status_code=404,
        content={"detail": "Not Found", "received_path": full_path, "matched_path": clean},
    )



