"""Hugging Face Space Entrypoint for SriTrack Deal Radar.

Runs 24/7 continuous price tracking & Casio/Flipkart deal radar in a background
daemon thread while serving an executive Gradio monitoring dashboard on port 7860.
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any

# Ensure workspace root is in sys.path
workspace_dir = os.path.dirname(os.path.abspath(__file__))
if workspace_dir not in sys.path:
    sys.path.insert(0, workspace_dir)

import gradio as gr
from config import settings
from database import get_database
from notifier import Notifier
from radar import StealRadar
from tracker import Tracker


def _format_time(dt: Any) -> str:
    if not dt:
        return "Never"
    s = str(dt).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(s)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        diff_sec = (datetime.now(timezone.utc) - parsed).total_seconds()
        if diff_sec < 60:
            return f"{int(diff_sec)}s ago"
        elif diff_sec < 3600:
            return f"{int(diff_sec // 60)}m ago"
        else:
            return f"{int(diff_sec // 3600)}h ago"
    except Exception:
        return str(dt)[:19]


async def fetch_dashboard_stats():
    """Query Supabase for latest product status and deal alerts."""
    db = get_database(settings)
    await db.initialize()
    try:
        products = await db.get_products(active_only=False)
        deals = await db.get_recent_deal_alerts(limit=15)

        prod_rows = []
        for p in products:
            price_display = f"₹{p.current_price:,.0f}" if p.current_price else "Checking..."
            target_display = f"₹{p.target_price:,.0f}" if p.target_price else "None"
            status_badge = "🟢 Active" if p.is_active else "⏸️ Paused"
            prod_rows.append([
                p.id,
                p.platform.upper(),
                p.title[:45] + ("..." if len(p.title) > 45 else ""),
                price_display,
                target_display,
                status_badge,
                _format_time(p.last_checked),
            ])

        deal_rows = []
        for d in deals:
            deal_rows.append([
                d.get("platform", "casio").upper(),
                d.get("title", "Deal Item")[:45],
                f"₹{float(d.get('effective_price') or d.get('price') or 0):,.0f}",
                f"{float(d.get('discount_percent') or 0):.0f}% OFF",
                _format_time(d.get("notified_at")),
            ])

        last_check = max([str(p.last_checked) for p in products if p.last_checked], default="None")
        summary_md = f"### ⚡ SriTrack 24/7 Cloud Daemon (Hugging Face)\n" \
                     f"- **Deal Radar**: `ONLINE` (Scanning Casio & Flipkart every 90s)\n" \
                     f"- **Tracked Products**: `{len(products)} active items`\n" \
                     f"- **Last Sweep Executed**: `{_format_time(last_check)}`\n" \
                     f"- **Telegram Alerts**: `CONNECTED`\n"

        return summary_md, prod_rows, deal_rows
    finally:
        await db.close()


def get_ui_data():
    return asyncio.run(fetch_dashboard_stats())


async def trigger_manual_sweep():
    """Trigger an immediate deal radar & product check on demand."""
    db = get_database(settings)
    await db.initialize()
    try:
        radar = StealRadar(settings, db=db)
        await radar.init()
        casio_alerts = await radar.scan_all(only_platforms=["casio", "flipkart"])
        tracker = Tracker(db, radar.notifier, settings)
        tracked_alerts = await tracker.run_once()
        await radar.close()
        return f"✅ Sweep completed! Dispatched {casio_alerts + tracked_alerts} deal alert(s)."
    except Exception as exc:
        return f"⚠️ Sweep error: {exc}"
    finally:
        await db.close()


def on_manual_sweep_click():
    result = asyncio.run(trigger_manual_sweep())
    summary, prods, deals = get_ui_data()
    return result, summary, prods, deals


# -------------------------------------------------------------
# BACKGROUND DAEMON RUNNER (Loops every 90s for Casio, 120s for items)
# -------------------------------------------------------------
def run_background_daemon():
    """Executes continuous price monitoring 24/7 inside the Hugging Face container."""
    print("🚀 [HuggingFace] Starting SriTrack 24/7 background radar daemon...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _daemon_loop():
        # Wait 10s on boot for container networking to stabilize
        await asyncio.sleep(10)
        from run_247_radar import casio_deal_radar_loop, manual_tracker_loop
        radar = StealRadar(settings)
        await radar.init()
        tracker = Tracker(radar.db, radar.notifier, settings)

        try:
            await asyncio.gather(
                casio_deal_radar_loop(radar, interval_seconds=90),
                manual_tracker_loop(tracker, interval_seconds=120),
            )
        finally:
            await radar.close()

    try:
        loop.run_until_complete(_daemon_loop())
    except Exception as exc:
        print(f"❌ Daemon loop error: {exc}")


# Start background daemon thread
daemon_thread = threading.Thread(target=run_background_daemon, daemon=True)
daemon_thread.start()


# -------------------------------------------------------------
# GRADIO INTERFACE
# -------------------------------------------------------------
theme = gr.themes.Soft(
    primary_hue="blue",
    secondary_hue="slate",
    neutral_hue="slate",
)

with gr.Blocks(theme=theme, title="SriTrack 24/7 Deal Radar") as demo:
    gr.Markdown("# 🚀 SriTrack // Autonomous Deal Radar & Price Intelligence")
    
    with gr.Row():
        status_box = gr.Markdown(value="Loading telemetry...")

    with gr.Row():
        sweep_btn = gr.Button("⚡ Trigger Immediate Live Sweep", variant="primary")
        sweep_output = gr.Label(label="Sweep Status", value="Ready")

    gr.Markdown("### 📋 24/7 Tracked Products")
    products_table = gr.Dataframe(
        headers=["ID", "Platform", "Product Title", "Current Price", "Target", "Status", "Last Checked"],
        datatype=["number", "str", "str", "str", "str", "str", "str"],
        interactive=False,
        wrap=True,
    )

    gr.Markdown("### 🎯 Recent 70%+ Steal Deals & Glitches")
    deals_table = gr.Dataframe(
        headers=["Platform", "Deal Title", "Deal Price", "Discount", "Detected At"],
        datatype=["str", "str", "str", "str", "str"],
        interactive=False,
        wrap=True,
    )

    # Initial data load
    demo.load(fn=get_ui_data, inputs=None, outputs=[status_box, products_table, deals_table])

    # Button click
    sweep_btn.click(
        fn=on_manual_sweep_click,
        inputs=None,
        outputs=[sweep_output, status_box, products_table, deals_table],
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    demo.launch(server_name="0.0.0.0", server_port=port)
