"""Multi-channel notification engine (Telegram Bot, WhatsApp CallMeBot, Windows Toast).

Dispatches instant alerts across Telegram, WhatsApp, and Desktop without delay.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)


def _fmt_price(value: Optional[float]) -> str:
    return f"₹{value:g}" if value is not None else "?"


def build_message(
    title: str,
    old_price: Optional[float],
    new_price: Optional[float],
    drop_percent: Optional[float],
    target_text: str,
    buy_url: str,
) -> str:
    """Render the standard alert template (markdown bold + emoji)."""
    drop_line = f"({drop_percent:.0f}% OFF!)" if drop_percent else ""
    return (
        "🚨 *PRICE DROP ALERT!* 🚨\n"
        f"📦 *Product:* {title}\n"
        f"📉 *Old Price:* {_fmt_price(old_price)} ➡️ "
        f"*New Price:* {_fmt_price(new_price)} {drop_line}\n"
        f"🎯 *Target:* {target_text}\n"
        f"🛒 *Buy Now:* {buy_url}"
    )


class Notifier:
    def __init__(self, config=settings) -> None:
        self.config = config

    async def shorten_url(self, url: str) -> str:
        """Try TinyURL's free API; fall back to the raw product link."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    "https://tinyurl.com/api-create.php", params={"url": url}
                )
            if response.status_code == 200 and response.text.strip().startswith("http"):
                return response.text.strip()
        except httpx.HTTPError as exc:
            logger.warning("URL shortening failed, using original link: %s", exc)
        return url

    async def send_telegram(self, text: str) -> bool:
        """Dispatch instant alert via Telegram Bot API with plain text fallback."""
        token = self.config.telegram_bot_token
        chat_id = self.config.telegram_chat_id
        if not token or not chat_id:
            return False

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False,
        }
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                logger.info("Telegram alert dispatched to chat %s", chat_id)
                return True
            elif resp.status_code == 400:
                # Markdown entity parse error (e.g. unescaped underscores/brackets in URL/title)
                logger.warning("Telegram Markdown parse error, retrying plain text: %s", resp.text)
                payload.pop("parse_mode", None)
                async with httpx.AsyncClient(timeout=20) as client:
                    resp2 = await client.post(url, json=payload)
                if resp2.status_code == 200:
                    logger.info("Telegram plain text alert dispatched to chat %s", chat_id)
                    return True
                logger.error("Telegram plain text retry failed (HTTP %s): %s", resp2.status_code, resp2.text)
            else:
                logger.error("Telegram API returned HTTP %s: %s", resp.status_code, resp.text)
        except Exception as exc:
            logger.error("Telegram dispatch error: %s", exc)
        return False

    async def send_whatsapp(self, text: str) -> bool:
        """Dispatch a message via CallMeBot. Returns True on success."""
        phone, key = self.config.whatsapp_phone, self.config.whatsapp_api_key
        if not phone or not key:
            return False
        params = {"phone": phone, "apikey": key, "text": text}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(self.config.callmebot_url, params=params)
            body = response.text.strip()
            if response.status_code == 200 and "message sent" in body.lower():
                logger.info("WhatsApp alert dispatched to %s", phone)
                return True
            logger.error("CallMeBot rejected message (HTTP %s): %s", response.status_code, body[:300])
        except httpx.HTTPError as exc:
            logger.error("CallMeBot unreachable: %s", exc)
        return False

    async def send_message(self, text: str) -> bool:
        """Multi-channel message dispatch. Sends to Telegram, WhatsApp, or logs to terminal."""
        sent_tg = await self.send_telegram(text)
        sent_wa = await self.send_whatsapp(text)
        return sent_tg or sent_wa

    async def notify(
        self,
        product,
        old_price: Optional[float],
        new_price: float,
        drop_percent: Optional[float],
        target_text: str,
    ) -> bool:
        """Build + send an alert for a product whose threshold was hit."""
        buy_url = await self.shorten_url(product.url)
        message = build_message(
            title=product.title or product.url,
            old_price=old_price if old_price is not None else product.initial_price,
            new_price=new_price,
            drop_percent=drop_percent,
            target_text=target_text,
            buy_url=buy_url,
        )
        return await self.send_message(message)