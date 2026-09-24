"""Telegram 2-Way Interactive Tracking Assistant & Natural Language Intent Listener.

Allows users to manage tracked products, add URLs, and type natural language
requests (e.g. "track if iphone 15 comes under 50k") directly from Telegram.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from typing import Any, Optional

import httpx

from config import Settings, settings
from database import Database, Product, get_database
from gemini_validator import GeminiDealValidator
from scrapers import (
    get_scraper,
    detect_platform,
    resolve_platform,
    resolve_platform_and_url,
    normalize_product_url,
    extract_fallback_title,
)

logger = logging.getLogger("telegram_bot")


class TelegramAssistant:
    """Asynchronous 2-Way Telegram Bot Controller."""

    def __init__(self, config: Settings = settings, db: Optional[Any] = None):
        self.config = config
        self.db = db or get_database(config)
        self.token = config.telegram_bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = str(config.telegram_chat_id or os.getenv("TELEGRAM_CHAT_ID", ""))
        self.ai = GeminiDealValidator(config)
        self.offset = 0
        self._is_running = False

    async def init(self) -> None:
        await self.db.initialize()

    async def send_reply(self, chat_id: str | int, text: str) -> bool:
        """Send formatted reply to a Telegram chat with plain text fallback."""
        if not self.token:
            return False
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False,
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(url, json=payload)
            if r.status_code == 200:
                return True
            if r.status_code == 400:
                payload.pop("parse_mode", None)
                async with httpx.AsyncClient(timeout=15) as client:
                    r2 = await client.post(url, json=payload)
                return r2.status_code == 200
            return False
        except Exception as e:
            logger.error("Error sending Telegram reply: %s", e)
            return False

    async def handle_url_tracking(self, chat_id: str | int, url: str, target_price: Optional[float]) -> None:
        """Handle direct product URL tracking with canonical normalization."""
        platform, resolved_url = await resolve_platform_and_url(url)
        if not platform:
            await self.send_reply(chat_id, "⚠️ Could not identify the retailer from this link. Supported: Amazon (amzn.in), Flipkart (fkrt.co), EliteHubs, Computech, GameLoot, Myntra, Ajio, BigBasket, Blinkit, Zepto, Swiggy, Casio.")
            return

        norm_url = normalize_product_url(resolved_url, platform)

        # Check if already tracked in DB to avoid duplicate insertion or redundant scraping
        try:
            products = await self.db.get_products(active_only=False)
            existing = next((p for p in products if p.url == norm_url), None)
        except Exception:
            existing = None

        if existing:
            if target_price is not None and target_price != existing.target_price:
                await self.db.add_product(
                    url=norm_url,
                    platform=platform,
                    target_price=target_price,
                    initial_price=existing.initial_price,
                    title=existing.title,
                )
                curr_display = f"₹{existing.current_price:g}" if existing.current_price else "Pending check"
                await self.send_reply(
                    chat_id,
                    f"🎯 *Target Price Updated!*\n\n"
                    f"🆔 *ID:* #{existing.id}\n"
                    f"📦 *Product:* {existing.title}\n"
                    f"🏪 *Platform:* {platform.title()}\n"
                    f"💰 *Current Price:* {curr_display}\n"
                    f"🎯 *New Target:* ₹{target_price:g}\n\n"
                    f"Your alert target has been successfully updated!"
                )
                return
            else:
                curr_display = f"₹{existing.current_price:g}" if existing.current_price else "Pending check"
                target_display = f"₹{existing.target_price:g}" if existing.target_price else "Auto"
                await self.send_reply(
                    chat_id,
                    f"ℹ️ *Already Tracked!*\n\n"
                    f"🆔 *ID:* #{existing.id}\n"
                    f"📦 *Product:* {existing.title}\n"
                    f"🏪 *Platform:* {platform.title()}\n"
                    f"💰 *Current Price:* {curr_display}\n"
                    f"🎯 *Alert Target:* {target_display}\n\n"
                    f"This product is already active in your radar!"
                )
                return

        await self.send_reply(chat_id, f"🔍 Inspecting product on *{platform.title()}*...")
        try:
            scraper = get_scraper(platform, self.config)
            # Bound scraping to 6.0 seconds so serverless / webhook never exceeds timeout
            try:
                res = await asyncio.wait_for(scraper.scrape(norm_url), timeout=6.0)
            except (asyncio.TimeoutError, Exception) as scrape_exc:
                logger.warning("[%s] Initial fast scrape timed out or failed (%s); queueing background verification", platform, scrape_exc)
                fallback_title = extract_fallback_title(resolved_url, platform)
                target = target_price or 1.0
                prod_id = await self.db.add_product(
                    url=norm_url,
                    platform=platform,
                    target_price=target,
                    initial_price=None,
                    title=fallback_title,
                )
                target_display = f"₹{target:g}" if target_price else "Auto (on first price check)"
                await self.send_reply(
                    chat_id,
                    f"✅ *Tracking Added!*\n\n"
                    f"🆔 *ID:* #{prod_id}\n"
                    f"📦 *Product:* {fallback_title}\n"
                    f"🏪 *Platform:* {platform.title()}\n"
                    f"🎯 *Alert Target:* {target_display}\n\n"
                    f"⏳ *Note:* The retailer page is taking longer to verify. Product has been registered and live price verification will complete in the background shortly!"
                )
                return

            is_out_of_stock = (res.price is None or res.price <= 0 or not res.in_stock)
            title = res.title or extract_fallback_title(resolved_url, platform)

            if is_out_of_stock:
                current_price = None
                target = target_price
            else:
                current_price = res.price
                target = target_price if target_price is not None else round(current_price * 0.8, 2)

            prod_id = await self.db.add_product(
                url=norm_url,
                platform=platform,
                target_price=target,
                initial_price=current_price,
                title=title,
            )

            if is_out_of_stock:
                target_display = f"₹{target:g}" if target else "Any Restock"
                await self.send_reply(
                    chat_id,
                    f"✅ *Restock Tracker Added!*\n\n"
                    f"🆔 *ID:* #{prod_id}\n"
                    f"📦 *Product:* {title}\n"
                    f"🏪 *Platform:* {platform.title()}\n"
                    f"📊 *Status:* 🔴 *Currently Out of Stock*\n"
                    f"🎯 *Target:* {target_display}\n\n"
                    f"🔔 You will receive an instant Telegram alert the moment this item returns to stock!"
                )
            else:
                await self.send_reply(
                    chat_id,
                    f"✅ *Tracking Added Successfully!*\n\n"
                    f"🆔 *ID:* #{prod_id}\n"
                    f"📦 *Product:* {title}\n"
                    f"🏪 *Platform:* {platform.title()}\n"
                    f"💰 *Current Price:* ₹{current_price:g}\n"
                    f"🎯 *Alert Target:* ₹{target:g}\n\n"
                    f"You will receive an instant alert when the price drops to or below your target!"
                )
        except Exception as exc:
            logger.error("Error adding product from Telegram: %s", exc)
            await self.send_reply(chat_id, f"❌ Error adding product: {exc}")

    async def handle_natural_language_tracking(self, chat_id: str | int, text: str) -> None:
        """Parse natural language request using AI and search platforms for matching hardware/groceries."""
        await self.send_reply(chat_id, "🤖 *Analyzing request with AI & searching e-commerce platforms...*")

        parsed = await self.ai.parse_tracking_intent(text)
        query = parsed.get("query") or text
        target_price = parsed.get("target_price")
        brand = parsed.get("brand")

        found_products = []
        text_lower = text.lower()

        # Check Quick Commerce (Zepto) if specified or grocery tokens
        if any(w in text_lower for w in ("zepto", "grocery", "milk", "butter", "paneer", "egg", "bread", "quick commerce", "qcommerce")):
            try:
                zepto = get_scraper("zepto", self.config)
                z_deals = await zepto.scan_deals(query=query, min_discount=0.0)
                if z_deals:
                    found_products.extend(z_deals[:2])
            except Exception as e:
                logger.debug("Zepto NL search error: %s", e)

        # Check Amazon for the top genuine item
        if not found_products:
            try:
                amz = get_scraper("amazon", self.config)
                deals = await amz.scan_deals(query=query, min_discount=10.0, brand=brand)
                if deals:
                    found_products.extend(deals[:2])
            except Exception:
                pass

        # Check Flipkart if needed
        if not found_products:
            try:
                fk = get_scraper("flipkart", self.config)
                fk_deals = await fk.scan_deals(query=query, min_discount=10.0, brand=brand)
                if fk_deals:
                    found_products.extend(fk_deals[:2])
            except Exception:
                pass

        if not found_products:
            # Add as a custom sniper radar rule if no instant search card was returned
            rule_target = target_price or 50000.0
            await self.db.add_custom_rule(
                name=f"Telegram: {query[:30]}",
                category="Telegram Requests",
                query=query,
                platforms=["amazon", "flipkart"],
                min_discount=25.0,
                max_price=rule_target,
                negative_keywords=["case", "cover", "strap", "tempered glass", "cable"],
            )
            await self.send_reply(
                chat_id,
                f"🎯 *Custom Sniper Rule Created!*\n\n"
                f"🔍 *Query:* {query}\n"
                f"💰 *Target Price Floor:* <= ₹{rule_target:g}\n"
                f"🏪 *Platforms Monitored:* Amazon, Flipkart\n\n"
                f"The 24/7 radar will continuously scan for this item and alert you the moment it drops below your target!"
            )
            return

        # Add top matched product to tracker
        top_item = found_products[0]
        sp = top_item.get("effective_price", top_item["price"])
        target = target_price if target_price is not None else round(sp * 0.8, 2)

        prod_id = await self.db.add_product(
            url=top_item["url"],
            platform=top_item.get("platform", "online"),
            target_price=target,
            initial_price=sp,
            title=top_item["title"],
        )

        await self.send_reply(
            chat_id,
            f"✅ *Auto-Discovered & Tracking Active!*\n\n"
            f"🆔 *ID:* #{prod_id}\n"
            f"📦 *Product:* {top_item['title']}\n"
            f"🏪 *Platform:* {top_item.get('platform', 'Retailer').title()}\n"
            f"💰 *Current Price:* ₹{sp:g} (MRP: ₹{top_item.get('mrp', sp):g})\n"
            f"🎯 *Target Price:* ₹{target:g}\n"
            f"🛒 *Link:* {top_item['url']}\n\n"
            f"We are monitoring this 24/7 and will push an instant alert when it hits your target!"
        )

    async def handle_command_list(self, chat_id: str | int) -> None:
        """List all active tracked products."""
        prods = await self.db.get_products(active_only=True)
        if not prods:
            await self.send_reply(chat_id, "📭 No custom products currently tracked.\n\nSend a link or type e.g. `track if iphone 15 comes under 50k` to start tracking!")
            return

        lines = ["📋 *Currently Tracked Products:*\n"]
        for p in prods:
            lines.append(
                f"• *[#{p.id}]* {p.title[:35]}\n"
                f"  💰 Current: ₹{p.current_price:g} ➡️ Target: *₹{p.target_price:g}*\n"
                f"  🔗 [Open on {p.platform.title()}]({p.url})\n"
            )
        lines.append("\n_To remove any item, send /remove <ID> (e.g. /remove 1)_")
        await self.send_reply(chat_id, "\n".join(lines))

    async def handle_command_remove(self, chat_id: str | int, text: str) -> None:
        """Remove a product by ID."""
        match = re.search(r"/remove\s+(\d+)", text)
        if not match:
            await self.send_reply(chat_id, "⚠️ Usage: `/remove <product_id>` (e.g. `/remove 1`)")
            return
        pid = int(match.group(1))
        await self.db.remove_product(pid)
        await self.send_reply(chat_id, f"🗑️ Tracked product #{pid} has been removed.")

    async def handle_message(self, message: dict[str, Any]) -> None:
        """Dispatch incoming Telegram message to appropriate handler."""
        chat = message.get("chat", {})
        chat_id = chat.get("id")
        text = (message.get("text") or "").strip()

        if not text or not chat_id:
            return

        # 1. /start or /help
        if text in {"/start", "/help"}:
            await self.send_reply(
                chat_id,
                "👋 *Welcome to Universal Deal Radar & Price Hunter!*\n\n"
                "🎯 *How to Track Anything:*\n"
                "1️⃣ *Direct Link:* Send any product URL with a price, e.g.:\n"
                "   `https://www.amazon.in/dp/B000GAYQJ0 1500`\n\n"
                "2️⃣ *Natural Language:* Just type what you want, e.g.:\n"
                "   • `track if iphone 15 comes under 50k`\n"
                "   • `alert me when Sony XM5 headphones drop below 20000`\n"
                "   • `track Samsung S24 Ultra under 90k`\n\n"
                "⚡ *Commands:*\n"
                "• `/list` : View all tracked products\n"
                "• `/remove <id>` : Stop tracking a product\n"
                "• `/status` : Check 24/7 radar health\n"
            )
            return

        # 2. /list
        if text.startswith("/list"):
            await self.handle_command_list(chat_id)
            return

        # 3. /remove
        if text.startswith("/remove"):
            await self.handle_command_remove(chat_id, text)
            return

        # 4. /status, /ping, /heartbeat
        if text.startswith(("/status", "/ping", "/heartbeat")):
            prods = await self.db.get_products(active_only=True)
            from heartbeat import build_heartbeat_message
            interval_h = getattr(self.config, "heartbeat_interval_hours", 12.0)
            hb_msg = build_heartbeat_message(active_count=len(prods), heartbeat_interval_hours=interval_h)
            await self.send_reply(chat_id, hb_msg)
            return


        # 5. Direct URL check
        url_match = re.search(r"(https?://[^\s]+)", text)
        if url_match:
            raw_url = url_match.group(1).rstrip("),.]\"'")
            # Check if target price specified after link
            remainder = text.replace(url_match.group(1), "").strip()
            price_match = re.search(r"(\d+(?:,\d+)?(?:\.\d+)?)", remainder)
            target_price = float(price_match.group(1).replace(",", "")) if price_match else None
            await self.handle_url_tracking(chat_id, raw_url, target_price)
            return

        # 6. Natural language tracking request
        await self.handle_natural_language_tracking(chat_id, text)

    async def listen_loop(self) -> None:
        """Continuous long-polling loop listening for user messages in Telegram."""
        if not self.token:
            logger.warning("Telegram Bot token not configured; listener disabled.")
            return

        self._is_running = True
        logger.info("Telegram 2-Way Interactive Bot Listener started.")

        async with httpx.AsyncClient(timeout=35) as client:
            while self._is_running:
                url = f"https://api.telegram.org/bot{self.token}/getUpdates"
                params = {"offset": self.offset, "timeout": 20}
                try:
                    r = await client.get(url, params=params)
                    if r.status_code == 200:
                        data = r.json()
                        updates = data.get("result", [])
                        for update in updates:
                            self.offset = update["update_id"] + 1
                            if "message" in update:
                                async def _safe_dispatch(msg):
                                    try:
                                        await self.handle_message(msg)
                                    except Exception as e:
                                        logger.error("Error processing Telegram message: %s", e)
                                        chat = msg.get("chat", {})
                                        if chat.get("id"):
                                            await self.send_reply(chat["id"], f"⚠️ Error processing request: {e}")

                                asyncio.create_task(_safe_dispatch(update["message"]))
                    elif r.status_code == 409:
                        logger.info("Telegram Webhook is currently active on Vercel. Local long-polling listener disabled to prevent conflicts (Vercel receives messages).")
                        self._is_running = False
                        break
                except Exception as exc:
                    logger.debug("Telegram polling error: %s", exc)
                    await asyncio.sleep(2)

                await asyncio.sleep(0.5)

    def stop(self) -> None:
        self._is_running = False
