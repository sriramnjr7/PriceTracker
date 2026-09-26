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

import asyncio
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
        """Check active products concurrently with rate-limiting (max 3 at a time)."""
        products = await self.db.get_products(active_only=True)
        if not products:
            logger.info("No active products tracked.")
            return 0

        sem = asyncio.Semaphore(6)

        async def _safe_check(p) -> bool:
            async with sem:
                try:
                    return await self.check_product(p)
                except Exception as exc:
                    logger.warning("Error checking product %s: %s", getattr(p, "id", "?"), exc)
                    return False

        results = await asyncio.gather(*(_safe_check(p) for p in products), return_exceptions=False)
        return sum(1 for r in results if r)

    async def check_product(self, product) -> bool:
        """Scrape + persist one product or collection; send an alert if triggered."""
        # 1. Specialized handling for Casio Collection deal scans (only true collection URLs)
        if product.platform == "casio" and "/collections/" in product.url and "/products/" not in product.url:
            return await self._check_casio_collection(product)

        # 2. Specialized handling for Flipkart Multi-Variant products (e.g. Crocs LiteRide 360 or all-colors/all-sizes tracking)
        if product.platform == "flipkart" and (
            "(all colors" in (product.title or "").lower()
            or "literide" in product.url.lower()
            or "variants" in (product.title or "").lower()
        ):
            return await self._check_flipkart_variants(product)

        # 3. Specialized handling for Casio Myntra Catalog sweeps
        if product.platform == "myntra" and ("/watches" in product.url or "category: casio" in (product.title or "").lower()):
            return await self._check_myntra_casio(product)

        # 4. Specialized handling for Casio Flipkart Catalog sweeps
        if product.platform == "flipkart" and (
            "category: casio" in (product.title or "").lower()
            or ("casio" in product.url.lower() and "/watches" in product.url)
        ):
            return await self._check_flipkart_casio(product)

        # 5. Standard single product check
        try:
            scraper = get_scraper(product.platform, self.config)
            result = await scraper.scrape(product.url)
        except (ScrapeError, ValueError) as exc:
            logger.warning("Skipping product %s: %s", product.id, exc)
            return False

        if result.price is None or not result.in_stock:
            # Item is unlisted / out of stock / 404
            title_to_set = result.title or None
            await self.db.update_price(product.id, None, title=title_to_set)
            return False

        should_notify, drop_percent = self._should_notify(
            product, product.current_price, result.price
        )
        await self.db.update_price(product.id, result.price, title=result.title or None)

        if not should_notify:
            return False

        is_restock = product.current_price is None
        target_text = self._target_text(product)
        old_price: Optional[float] = (
            product.current_price if product.current_price is not None else product.initial_price
        )
        if await self.notifier.notify(
            product, old_price, result.price, drop_percent, target_text, is_restock=is_restock
        ):
            await self.db.set_last_notified(product.id, result.price)
            logger.info(
                "Alert sent for product %s at INR %s (restock=%s)",
                product.id,
                result.price,
                is_restock,
            )
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
        category_name = handle.replace("-", " ").title()
        best_price = min((d["price"] for d in deals), default=product.current_price)
        active_count = len(deals)
        updated_title = f"[Category: {category_name}] ({active_count} active deal{'s' if active_count != 1 else ''} currently)"
        await self.db.update_price(product.id, best_price, title=updated_title)

        if not deals:
            logger.info("[casio] Collection %s: 0 deals matching >= %s%% discount", handle, min_discount)
            return False
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

    async def _check_myntra_casio(self, product) -> bool:
        """Scan Myntra for genuine Casio deals matching target discount (>= 60%)."""
        scraper = get_scraper("myntra", self.config)
        min_discount = product.percentage_drop_target or 60.0

        deals = await scraper.scan_deals(
            query="watches",
            min_discount=min_discount,
            custom_url=product.url,
            brand="Casio",
        )
        best_price = min((d["price"] for d in deals), default=None)

        if deals:
            best_deal = max(deals, key=lambda d: d.get("discount_percent", 0))
            clean_name = best_deal["title"][:35]
            updated_title = f"[Category: Casio Myntra] Best: {clean_name} ({best_deal['discount_percent']:.0f}% OFF)"
            await self.db.update_price(product.id, best_price, title=updated_title)
        else:
            updated_title = "[Category: Casio Myntra] (0 active deals currently)"
            await self.db.update_price(product.id, None, title=updated_title)

        if not deals:
            logger.info("[myntra] 0 Casio deals matching >= %s%% discount", min_discount)
            return False

        notified_any = False
        for deal in deals:
            if product.target_price is not None and deal["price"] > product.target_price:
                continue

            if await self.db.is_deal_recently_notified(deal["url"], minutes=20, current_price=deal["price"]):
                continue

            deal_msg = (
                f"🚨 *Casio Myntra STEAL DEAL ({deal['discount_percent']:.0f}% OFF!)* 🚨\n"
                f"📦 *Watch:* {deal['title']}\n"
                f"📉 *Deal Price:* ₹{deal['price']:g} (MRP: ₹{deal['mrp']:g})\n"
                f"🎯 *Discount:* {deal['discount_percent']:.1f}% OFF (Target: >={min_discount}%)\n"
                f"🛒 *Buy Now:* {deal['url']}"
            )
            logger.info("[myntra] Found %s%% Casio deal: %s at INR %s", deal["discount_percent"], deal["title"], deal["price"])
            if await self.notifier.send_message(deal_msg):
                notified_any = True
                await self.db.log_deal_alert(
                    product_url=deal["url"],
                    title=deal["title"],
                    price=deal["price"],
                    effective_price=deal["price"],
                    discount_percent=deal["discount_percent"],
                    platform="myntra",
                )

        if notified_any and deals:
            await self.db.set_last_notified(product.id, deals[0]["price"])
        return notified_any

    async def _check_flipkart_casio(self, product) -> bool:
        """Scan Flipkart for genuine Casio deals matching target discount (>= 60%)."""
        scraper = get_scraper("flipkart", self.config)
        min_discount = product.percentage_drop_target or 60.0

        deals = await scraper.scan_deals(
            query="watches",
            min_discount=min_discount,
            custom_url=product.url,
            brand="Casio",
        )
        best_price = min((d["price"] for d in deals), default=None)

        if deals:
            best_deal = max(deals, key=lambda d: d.get("discount_percent", 0))
            clean_name = best_deal["title"][:35]
            updated_title = f"[Category: Casio Flipkart] Best: {clean_name} ({best_deal['discount_percent']:.0f}% OFF)"
            await self.db.update_price(product.id, best_price, title=updated_title)
        else:
            updated_title = "[Category: Casio Flipkart] (0 active deals currently)"
            await self.db.update_price(product.id, None, title=updated_title)

        if not deals:
            logger.info("[flipkart] 0 Casio deals matching >= %s%% discount", min_discount)
            return False

        notified_any = False
        for deal in deals:
            if product.target_price is not None and deal["price"] > product.target_price:
                continue

            if await self.db.is_deal_recently_notified(deal["url"], minutes=20, current_price=deal["price"]):
                continue

            deal_msg = (
                f"🚨 *Casio Flipkart STEAL DEAL ({deal['discount_percent']:.0f}% OFF!)* 🚨\n"
                f"📦 *Watch:* {deal['title']}\n"
                f"📉 *Deal Price:* ₹{deal['price']:g} (MRP: ₹{deal['mrp']:g})\n"
                f"🎯 *Discount:* {deal['discount_percent']:.1f}% OFF (Target: >={min_discount}%)\n"
                f"🛒 *Buy Now:* {deal['url']}"
            )
            logger.info("[flipkart] Found %s%% Casio deal: %s at INR %s", deal["discount_percent"], deal["title"], deal["price"])
            if await self.notifier.send_message(deal_msg):
                notified_any = True
                await self.db.log_deal_alert(
                    product_url=deal["url"],
                    title=deal["title"],
                    price=deal["price"],
                    effective_price=deal["price"],
                    discount_percent=deal["discount_percent"],
                    platform="flipkart",
                )

        if notified_any and deals:
            await self.db.set_last_notified(product.id, deals[0]["price"])
        return notified_any

    async def _check_flipkart_variants(self, product) -> bool:
        """Inspect all colorways and sizes for a Flipkart multi-variant product."""
        from scrapers.flipkart import FlipkartScraper

        scraper = FlipkartScraper(self.config)
        report = await scraper.check_product_variants(product.url)

        model_title = report.get("model_title") or product.title or "CROCS LiteRide 360 Clog"
        clean_model = model_title.split("(")[0].strip() if "(" in model_title else model_title

        in_stock_variants = report.get("in_stock_variants", [])
        lowest_price = report.get("lowest_price")

        if not in_stock_variants:
            updated_title = f"{clean_model} (All Colors & Sizes - Out of Stock)"
            await self.db.update_price(product.id, None, title=updated_title)
            logger.info(
                "[flipkart] Multi-variant product %s: all %s colorways & sizes currently out of stock.",
                product.id,
                report.get("total_colors_checked", 0),
            )
            return False

        updated_title = f"{clean_model} ({len(in_stock_variants)} variant{'s' if len(in_stock_variants) != 1 else ''} In Stock)"
        await self.db.update_price(product.id, lowest_price, title=updated_title)

        notified_any = False
        target_price = product.target_price or 2500.0

        for variant in in_stock_variants:
            v_price = variant["price"]
            v_color = variant["color"]
            v_sizes = ", ".join(variant["sizes"]) if variant["sizes"] else "Standard"
            v_url = variant["url"]
            v_mrp = variant.get("mrp") or v_price

            if v_price > target_price:
                logger.info("[flipkart] Variant %s (%s) price INR %s exceeds target INR %s", v_color, v_sizes, v_price, target_price)
                continue

            # 60-minute alert de-duplication
            if await self.db.is_deal_recently_notified(v_url, minutes=60, current_price=v_price):
                continue

            discount_pct = round(((v_mrp - v_price) / v_mrp) * 100.0, 1) if v_mrp > v_price else 0.0
            price_display = f"₹{v_price:,.0f}" if v_price.is_integer() else f"₹{v_price:,.2f}"
            mrp_display = f"₹{v_mrp:,.0f}" if v_mrp.is_integer() else f"₹{v_mrp:,.2f}"
            target_display = f"₹{target_price:,.0f}" if target_price.is_integer() else f"₹{target_price:,.2f}"

            alert_msg = (
                f"🚨 *CROCS LITERIDE 360 IN-STOCK DEAL!* 🚨\n"
                f"📦 *Model:* {clean_model}\n"
                f"🎨 *Color:* {v_color}\n"
                f"📏 *Available Sizes:* {v_sizes}\n"
                f"📉 *Deal Price:* {price_display}" + (f" (MRP: {mrp_display} | {discount_pct:.1f}% OFF)" if discount_pct > 0 else "") + "\n"
                f"🎯 *Target Price:* Below {target_display}\n"
                f"🛒 *Buy Now:* {v_url}"
            )

            logger.info("[flipkart] IN-STOCK VARIANT TRIGGERED: %s (%s) at INR %s", v_color, v_sizes, v_price)
            if await self.notifier.send_message(alert_msg):
                notified_any = True
                await self.db.log_deal_alert(
                    product_url=v_url,
                    title=f"{clean_model} - {v_color} (Size: {v_sizes})",
                    price=v_price,
                    effective_price=v_price,
                    discount_percent=discount_pct,
                    platform="flipkart",
                )

        if notified_any and lowest_price is not None:
            await self.db.set_last_notified(product.id, lowest_price)

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

        # 1. Back-in-stock alert: Product was previously out-of-stock (old_price is None)
        # and has now returned to stock at or below target threshold.
        if old_price is None:
            return True, drop_percent

        # 2. Recovery from non-deal price: If price was previously above target (regular price),
        # this is a fresh drop back into target range, not a bounce within the deal.
        if product.target_price is not None and old_price > product.target_price:
            return True, drop_percent

        # 3. Anti-spam: don't re-alert at the same or a higher price within the same deal window.
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