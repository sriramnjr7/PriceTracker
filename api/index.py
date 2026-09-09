"""Vercel Serverless Entrypoint for PriceTracker.

Provides:
- POST /api/telegram : Telegram Webhook for real-time manual link tracking & commands
- GET  /api/cron     : 24/7 Periodic deal & price drop scanner (Casio Bhawar & Flipkart + manual items)
- GET  /api/set-webhook : 1-Click Telegram Webhook configuration
- GET  /             : Health and status dashboard
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
import httpx

# Ensure project root is in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from config import settings
from database import get_database
from radar import StealRadar
from telegram_bot import TelegramAssistant
from tracker import Tracker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("vercel_api")

app = FastAPI(
    title="PriceTracker Vercel Serverless Engine",
    description="Autonomous Casio Bhawar + Flipkart deal hunter & Telegram interactive bot",
    version="2.0.0",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.get("/")
@app.get("/api")
@app.get("/api/")
@app.get("/api/index")
@app.get("/api/index.py")
@app.get("/index.py")
async def root(request: Request):
    """Health check and status dashboard."""
    db = get_database(settings)
    await db.initialize()
    products = await db.get_products(active_only=True)
    await db.close()

    # If Vercel rewrote an endpoint to /api/index.py, inspect original path from headers:
    orig_path = (
        request.headers.get("x-vercel-matched-path")
        or request.headers.get("x-matched-path")
        or request.headers.get("x-forwarded-uri")
        or request.headers.get("x-invoke-path")
        or ""
    )

    if "cron" in orig_path.lower():
        return await cron_sweep(request)
    elif "set-webhook" in orig_path.lower():
        return await set_telegram_webhook(request)

    return {
        "status": "online",
        "service": "PriceTracker Vercel Serverless Engine",
        "timestamp": _now(),
        "database": "Supabase PostgreSQL" if os.getenv("SUPABASE_URL") else "SQLite",
        "active_monitored_products": len(products),
        "focus": "Casio Bhawar + Flipkart (>= 70% OFF & GBD-300) + Telegram Manual Tracker",
        "endpoints": {
            "telegram_webhook": "POST /api/telegram",
            "cron_deal_scanner": "GET /api/cron",
            "setup_webhook": "GET /api/set-webhook",
        },
        "debug_info": {
            "x_matched_path": request.headers.get("x-matched-path"),
            "x_vercel_matched_path": request.headers.get("x-vercel-matched-path"),
            "x_forwarded_uri": request.headers.get("x-forwarded-uri"),
            "path": request.scope.get("path"),
        },
    }


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
    """Execute scheduled deal hunter & manual product price checking.

    Can be triggered by Vercel Cron or an external 1-minute pinger (cron-job.org).
    """
    # Optional authorization check
    cron_secret = os.getenv("CRON_SECRET")
    if cron_secret:
        auth_header = request.headers.get("Authorization", "")
        query_secret = request.query_params.get("secret", "")
        if auth_header != f"Bearer {cron_secret}" and query_secret != cron_secret:
            raise HTTPException(status_code=401, detail="Unauthorized cron trigger")

    logger.info("Starting /api/cron sweep...")
    db = get_database(settings)
    await db.initialize()

    # 1. Scan Casio Bhawar & Flipkart 70%+ deals and GBD-300 watcher
    radar = StealRadar(settings, db=db)
    await radar.init()
    casio_alerts = await radar.scan_all(only_platforms=["casio", "flipkart"])

    # 2. Check active user-submitted products from Supabase
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

    # Determine target webhook URL
    if url:
        webhook_url = url.rstrip("/")
    else:
        # Infer base URL from Host header
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


@app.api_route("/{full_path:path}", methods=["GET", "POST", "HEAD", "OPTIONS"])
async def catch_all(request: Request, full_path: str):
    """Fallback catch-all route ensuring Vercel rewrites never trigger accidental 404s."""
    raw_path = (
        request.headers.get("x-vercel-matched-path")
        or request.headers.get("x-matched-path")
        or request.headers.get("x-forwarded-uri")
        or full_path
    )
    clean = raw_path.strip("/").lower()

    if clean in ("", "api", "api/", "index", "index.py", "api/index", "api/index.py"):
        return await root(request)
    elif "cron" in clean:
        return await cron_sweep(request)
    elif "telegram" in clean:
        return await telegram_webhook(request)
    elif "set-webhook" in clean or "set_webhook" in clean:
        return await set_telegram_webhook(request)

    return JSONResponse(
        status_code=404,
        content={"detail": "Not Found", "received_path": full_path, "matched_path": raw_path},
    )


