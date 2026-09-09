"""Monitoring loop: scrape -> persist -> evaluate thresholds -> notify.

The tracker is deliberately stateless between runs: every pass reads the
active products from the DB, scrapes each one, appends the new price to
``price_logs``, then decides whether an alert is warranted.

Alert logic (``_should_notify``):

* A product is "triggered" when its price is at/below ``target_price`` OR the
  drop from the last observed price is >= ``percentage_drop_target``.
* Anti-spam: we only alert on NEW lows. Once a price has been notified, we
  don't re-alert until the price falls further (guarding against small
  price bounces around the threshold).
"""

from __future__ import annotations

import logging
from typing import Optional

from config import settings
from database import Database
from notifier import Notifier
from scrapers import ScrapeError, get_scraper

logger = logging.getLogger(__name__)


class Tracker:
    def __init__(self, database: Database, notifier: Notifier, config=settings) -> None:
        self.db = database
        self.notifier = notifier
        self.config = config

    async def run_once(self) -> int:
        """Check every active product once. Returns how many alerts were sent."""
        products = await self.db.get_products(active_only=True)
        if not products:
            logger.info("No active products tracked.")
            return 0
        sent = 0
        for product in products:
            if await self.check_product(product):
                sent += 1
        return sent

    async def check_product(self, product) -> bool:
        """Scrape + persist one product or collection; send an alert if triggered."""
        # 1. Specialized handling for Casio Collection deal scans
        if product.platform == "casio" and "/collections/" in product.url:
            return await self._check_casio_collection(product)

        # 2. Standard single product check
        try:
            scraper = get_scraper(product.platform, self.config)
            result = await scraper.scrape(product.url)
        except (ScrapeError, ValueError) as exc:
            logger.warning("Skipping product %s: %s", product.id, exc)
            return False

        if result.price is None:
            # Item is unlisted / out of stock / 404
            if result.title:
                await self.db.update_price(product.id, None, title=result.title)
            return False

        await self.db.update_price(product.id, result.price, title=result.title or None)

        should_notify, drop_percent = self._should_notify(
            product, product.current_price, result.price
        )
        if not should_notify:
            return False

        target_text = self._target_text(product)
        old_price: Optional[float] = (
            product.current_price if product.current_price is not None else product.initial_price
        )
        if await self.notifier.notify(product, old_price, result.price, drop_percent, target_text):
            await self.db.set_last_notified(product.id, result.price)
            logger.info("Alert sent for product %s at INR %s", product.id, result.price)
            return True
        return False

    async def _check_casio_collection(self, product) -> bool:
        """Scan a Casio collection for deals matching target discount or target price."""
        from scrapers.casio import CasioScraper
        import re

        scraper = CasioScraper(self.config)
        match = re.search(r"/collections/([^/?]+)", product.url)
        handle = match.group(1) if match else "g-shock"
        min_discount = product.percentage_drop_target or 70.0

        deals = await scraper.scan_collection_deals(handle, min_discount=min_discount)
        if not deals:
            logger.info("[casio] Collection %s: 0 deals matching >= %s%% discount", handle, min_discount)
            return False

        category_name = handle.replace("-", " ").upper()
        notified_any = False
        for deal in deals:
            # Check price threshold if set
            if product.target_price is not None and deal["price"] > product.target_price:
                continue

            # 20-minute de-duplication check
            if await self.db.is_deal_recently_notified(deal["url"], minutes=20, current_price=deal["price"]):
                continue

            deal_msg = (
                f"🚨 *{category_name} STEAL DEAL ({deal['discount_percent']:.0f}% OFF!)* 🚨\n"
                f"📦 *Watch:* {deal['title']}\n"
                f"📉 *Deal Price:* ₹{deal['price']:g} (MRP: ₹{deal['mrp']:g})\n"
                f"🎯 *Discount:* {deal['discount_percent']:.1f}% OFF (Target: >={min_discount}%)\n"
                f"🛒 *Buy Now:* {deal['url']}"
            )
            logger.info("[casio] Found %s%% deal: %s at INR %s", deal['discount_percent'], deal['title'], deal['price'])
            if await self.notifier.send_message(deal_msg):
                notified_any = True
                await self.db.log_deal_alert(
                    product_url=deal["url"],
                    title=deal["title"],
                    price=deal["price"],
                    effective_price=deal["price"],
                    discount_percent=deal["discount_percent"],
                    platform="casio",
                )

        if notified_any:
            await self.db.set_last_notified(product.id, deals[0]["price"])
        return notified_any

    @staticmethod
    def _target_text(product) -> str:
        """Human-readable target for the WhatsApp message."""
        if product.target_price is not None:
            return f"\u20B9{product.target_price:g}"
        if product.percentage_drop_target is not None:
            return f"{product.percentage_drop_target:g}% drop"
        return "\u2014"

    @staticmethod
    def _should_notify(product, old_price: Optional[float], new_price: float):
        """Return (should_alert, drop_percent)."""
        drop_percent = 0.0
        if old_price and old_price > 0:
            drop_percent = (old_price - new_price) / old_price * 100.0

        triggered = False
        if product.target_price is not None and new_price <= product.target_price:
            triggered = True
        if (
            product.percentage_drop_target is not None
            and drop_percent >= product.percentage_drop_target
        ):
            triggered = True
        if not triggered:
            return False, drop_percent

        # Anti-spam: don't re-alert at the same or a higher price.
        last_notified = product.last_notified_price
        if last_notified is not None and new_price >= last_notified:
            return False, drop_percent
        return True, drop_percent

    async def run_forever(self) -> None:
        """Start the APScheduler loop and poll at the configured interval."""
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.interval import IntervalTrigger

        scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")
        scheduler.add_job(
            self.run_once,
            IntervalTrigger(
                seconds=self.config.poll_interval_seconds,
                jitter=self.config.scheduler_jitter_seconds,
            ),
            id="poll",
            max_instances=1,  # never overlap two passes
            coalesce=True,    # if a pass ran late, skip the missed run
        )
        scheduler.start()
        logger.info(
            "Scheduler started; polling every %ss. Press Ctrl+C to stop.",
            self.config.poll_interval_seconds,
        )
        await self.run_once()  # immediate first pass
        try:
            import asyncio

            await asyncio.Event().wait()  # idle until interrupted
        except (KeyboardInterrupt, asyncio.CancelledError):
            logger.info("Shutting down scheduler...")
        finally:
            scheduler.shutdown(wait=False)