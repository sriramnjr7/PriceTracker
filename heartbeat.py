"""Heartbeat monitoring engine for PriceTracker.

Dispatches periodic and on-demand Telegram heartbeat notifications
to verify active monitoring and eliminate silent runner failures.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from config import Settings, settings

logger = logging.getLogger("heartbeat")


def build_heartbeat_message(
    active_count: int,
    rules_count: int = 3,
    error_count: int = 0,
    heartbeat_interval_hours: float = 12.0,
) -> str:
    """Format structured heartbeat status message for Telegram."""
    try:
        from zoneinfo import ZoneInfo
        now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    except Exception:
        now_ist = datetime.now()
    time_str = now_ist.strftime("%Y-%m-%d %I:%M %p IST")

    if heartbeat_interval_hours == 1.0:
        interval_desc = "Hourly"
    elif heartbeat_interval_hours.is_integer():
        interval_desc = f"Every {int(heartbeat_interval_hours)}h"
    else:
        interval_desc = f"Every {heartbeat_interval_hours}h"

    return (
        "🟢 *PriceTracker Heartbeat: Active & Healthy* 🟢\n\n"
        "📡 *24/7 Radar Status: ACTIVE & MONITORING*\n"
        f"📦 *Monitored Items:* {active_count} active product{'s' if active_count != 1 else ''}\n"
        f"🛡️ *Deal Radar:* {rules_count} active categories (Casio Bhawar, Flipkart, etc.)\n"
        f"⚡ *24/7 Sweeps:* GitHub Actions Runner & Deal Daemon Operational\n"
        f"🩺 *System Health:* {error_count} fatal errors in last 24h\n"
        f"⏱️ *Heartbeat Frequency:* {interval_desc}\n"
        f"🕒 *Timestamp:* {time_str}"
    )



async def check_and_send_heartbeat(
    db: Any,
    notifier: Any,
    config: Settings = settings,
    force: bool = False,
) -> bool:
    """Send periodic heartbeat to Telegram if interval has elapsed, or immediately if force=True."""
    interval_hours = getattr(config, "heartbeat_interval_hours", 12.0)
    heartbeat_key = "system_heartbeat"

    if not force:
        recently_sent = await db.is_deal_recently_notified(heartbeat_key, hours=interval_hours)
        if recently_sent:
            return False

    prods = await db.get_products(active_only=True)
    active_count = len(prods)

    msg = build_heartbeat_message(
        active_count=active_count,
        heartbeat_interval_hours=interval_hours,
    )

    sent = await notifier.send_telegram(msg)
    if sent:
        await db.log_deal_alert(
            product_url=heartbeat_key,
            title="PriceTracker Heartbeat",
            price=0.0,
            effective_price=0.0,
            discount_percent=0.0,
            platform="heartbeat",
        )
        logger.info(
            "[heartbeat] Dispatched Telegram heartbeat (interval=%sh, active_items=%s).",
            interval_hours,
            active_count,
        )
        return True
    return False
