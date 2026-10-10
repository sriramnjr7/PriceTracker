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

    async def run_once(self, products: Optional[list[Product]] = None, limit: Optional[int] = None) -> int:
        """Check active products concurrently with rate-limiting (max 3 at a time)."""
        if products is None:
            products = await self.db.get_products(active_only=True)
        if not products:
            logger.info("No active products tracked.")
            return 0

        # Prioritize VIP targets first, then sort by oldest/least-recently checked (fair round-robin)
        def _sweep_priority(p):
            url_l = (getattr(p, "url", "") or "").lower()
            is_vip = 0 if ("gbd-h2000" in url_l or "gbd-300-9dr" in url_l) else 1
            lc = getattr(p, "last_checked", None)
            lc_str = str(lc) if lc else ""
            return (is_vip, lc_str)

        products = sorted(products, key=_sweep_priority)
        if limit and limit > 0:
            products = products[:limit]

        sem = asyncio.Semaphore(3)

        async def _safe_check(p, delay: float = 0.0) -> bool:
            if delay > 0:
                await asyncio.sleep(delay)
            async with sem:
                try:
                    return await self.check_product(p)
                except Exception as exc:
                    err_msg = str(exc).strip() or repr(exc)
                    logger.warning("Error checking product %s: %s", getattr(p, "id", "?"), err_msg)
                    try:
                        if hasattr(self.db, "update_last_checked"):
                            await self.db.update_last_checked(getattr(p, "id"))
                    except Exception:
                        pass
                    return False

        tasks = [_safe_check(p, idx * 0.25) for idx, p in enumerate(products)]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return sum(1 for r in results if r)

    async def check_product(self, product) -> bool:
        """Scrape + persist one product or collection; send an alert if triggered."""
        # 1. Specialized handling for Casio Collection deal scans (only true collection URLs)
        if product.platform == "casio" and "/collections/" in product.url and "/products/" not in product.url:
            return await self._check_casio_collection(product)

        # 2. Specialized handling for Amazon Multi-Variant products (e.g. 8Bitdo joysticks, twister, or all-colors tracking)
        if product.platform == "amazon" and (
            "(all colors" in (product.title or "").lower()
            or "twister" in product.url.lower()
            or "variants" in (product.title or "").lower()
            or "joystick" in (product.title or "").lower()
            or "8bitdo" in (product.title or "").lower()
        ):
            return await self._check_amazon_variants(product)

        # 3. Specialized handling for Flipkart Multi-Variant products (e.g. Crocs LiteRide 360, Skechers size-filtered, or all-colors/all-sizes tracking)
        if product.platform == "flipkart" and (
            "(all colors" in (product.title or "").lower()
            or "literide" in product.url.lower()
            or "variants" in (product.title or "").lower()
            or "size " in (product.title or "").lower()
            or "sizes " in (product.title or "").lower()
            or "size 8" in (product.title or "").lower()
            or "skechers" in (product.title or "").lower()
            or "skechers" in product.url.lower()
        ):
            return await self._check_flipkart_variants(product)

        # 4. Specialized handling for Casio Myntra Catalog sweeps
        if product.platform == "myntra" and ("/watches" in product.url or "category: casio" in (product.title or "").lower()):
            return await self._check_myntra_casio(product)

        # 5. Specialized handling for Casio Flipkart Catalog sweeps
        if product.platform == "flipkart" and (
            "category: casio" in (product.title or "").lower()
            or ("casio" in product.url.lower() and "/watches" in product.url)
        ):
            return await self._check_flipkart_casio(product)

        # 6. Standard single product check
        try:
            scraper = get_scraper(product.platform, self.config)
            result = await scraper.scrape(product.url)
        except (ScrapeError, ValueError, Exception) as exc:
            err_msg = str(exc).strip() or repr(exc)
            logger.warning("Skipping product %s: %s", product.id, err_msg)
            try:
                if hasattr(self.db, "update_last_checked"):
                    await self.db.update_last_checked(product.id)
            except Exception:
                pass
            return False

        if result.price is None or not result.in_stock:
            # Item is unlisted / out of stock / 404
            title_to_set = result.title or None
            await self.db.update_price(product.id, None, title=title_to_set)
            return False

        # 1. Variant specification consistency guard (e.g. 1 TB SSD vs 250 GB pill)
        if not self._is_variant_consistent(product.title or "", product.url or "", result.title or ""):
            logger.warning(
                "Variant specification mismatch for product %s ('%s' vs extracted '%s'). Setting out of stock.",
                product.id, product.title, result.title
            )
            await self.db.update_price(product.id, None, title=product.title)
            return False

        # 2. Single-Tick Anomaly Confirmation Guard:
        # Detect sudden plunges (>= 50% drop from current price or >= 55% drop from initial price on restock)
        is_extreme_drop = False
        if product.current_price and product.current_price > 0:
            tick_drop = (product.current_price - result.price) / product.current_price * 100.0
            if tick_drop >= 50.0:
                is_extreme_drop = True
        elif product.initial_price and product.initial_price > 0:
            restock_drop = (product.initial_price - result.price) / product.initial_price * 100.0
            if restock_drop >= 55.0:
                is_extreme_drop = True

        if is_extreme_drop:
            logger.warning(
                "Suspected extreme single-tick drop for '%s' (Price: INR %s vs Current: %s, Initial: %s). Running confirmation probe...",
                product.title, result.price, product.current_price, product.initial_price
            )
            try:
                recheck_scraper = get_scraper(product.platform, self.config)
                recheck = await recheck_scraper.scrape(product.url)
                if not recheck.in_stock or recheck.price is None or abs(recheck.price - result.price) > 5.0:
                    logger.warning(
                        "Re-probe failed to confirm drop for '%s' (probe 1: %s, probe 2: %s, in_stock: %s). Suppressing false alert.",
                        product.title, result.price, getattr(recheck, "price", None), getattr(recheck, "in_stock", None)
                    )
                    if recheck.in_stock and recheck.price:
                        result = recheck
                    else:
                        await self.db.update_price(product.id, None, title=result.title or None)
                        return False
            except Exception as recheck_exc:
                logger.warning("Re-probe exception for %s: %s", product.id, recheck_exc)

        should_notify, drop_percent = self._should_notify(
            product, product.current_price, result.price
        )
        await self.db.update_price(product.id, result.price, title=result.title or None)

        if not should_notify:
            return False

        # Urgent VIP Notification format for GBD-H2000 & GBD-300-9DR (only when target price is met)
        url_lower = (product.url or "").lower()
        if ("gbd-h2000" in url_lower or "gbd-300-9dr" in url_lower) and product.target_price and result.price <= product.target_price:
            mrp_text = "₹44,995" if "gbd-h2000" in url_lower else "₹11,495"
            vip_msg = (
                "🚨🚨 *URGENT VIP DEAL RESTOCK!* 🚨🚨\n"
                f"📦 *Watch:* {result.title or product.title}\n"
                "🔥 *STATUS: IN STOCK RIGHT NOW!*\n"
                f"💰 *Deal Price:* ₹{result.price:g} (MRP: {mrp_text})\n"
                f"🎯 *Target:* ₹{product.target_price:g} (Target Met!)\n"
                f"🛒 *ORDER INSTANTLY:* {product.url}\n"
                "⚡ *Caught via 60-Second Priority VIP Sniper*\n"
                "⚠️ *Zero-dedupe mode: Alerting continuously while in stock at target price!*"
            )
            if await self.notifier.send_telegram(vip_msg):
                await self.db.set_last_notified(product.id, result.price)
                await self.db.log_deal_alert(
                    product_url=product.url,
                    title=result.title or product.title,
                    price=result.price,
                    effective_price=result.price,
                    discount_percent=drop_percent or 70.0,
                    platform="casio",
                )
                logger.info("[VIP Sniper] Dispatched URGENT alert for %s at INR %s", product.title, result.price)
                return True

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

    async def _check_amazon_variants(self, product) -> bool:
        """Inspect all colorways and styles for an Amazon multi-variant (Twister) product."""
        from scrapers.amazon import AmazonScraper

        scraper = AmazonScraper(self.config)
        report = await scraper.check_product_variants(product.url)

        model_title = report.get("model_title") or product.title or "8Bitdo Controller"
        clean_model = model_title.split("(")[0].strip() if "(" in model_title else model_title

        in_stock_variants = report.get("in_stock_variants", [])
        lowest_price = report.get("lowest_price")

        if not in_stock_variants:
            updated_title = f"{clean_model} (All Colors - Out of Stock)"
            await self.db.update_price(product.id, None, title=updated_title)
            logger.info(
                "[amazon] Multi-variant product %s: all %s colorways currently out of stock.",
                product.id,
                report.get("total_variants_checked", 0),
            )
            return False

        updated_title = f"{clean_model} ({len(in_stock_variants)} variant{'s' if len(in_stock_variants) != 1 else ''} In Stock)"
        await self.db.update_price(product.id, lowest_price, title=updated_title)

        notified_any = False
        target_price = product.target_price or 2600.0

        for variant in in_stock_variants:
            v_price = variant["price"]
            v_color = variant["color"]
            v_url = variant["url"]
            v_mrp = variant.get("mrp") or v_price

            if target_price is not None and v_price > target_price:
                logger.info("[amazon] Variant %s price INR %s exceeds target INR %s", v_color, v_price, target_price)
                continue

            # 60-minute alert de-duplication
            if await self.db.is_deal_recently_notified(v_url, minutes=60, current_price=v_price):
                continue

            discount_pct = round(((v_mrp - v_price) / v_mrp) * 100.0, 1) if v_mrp > v_price else 0.0
            price_display = f"₹{v_price:,.0f}" if v_price.is_integer() else f"₹{v_price:,.2f}"
            mrp_display = f"₹{v_mrp:,.0f}" if v_mrp.is_integer() else f"₹{v_mrp:,.2f}"
            target_display = f"₹{target_price:,.0f}" if target_price.is_integer() else f"₹{target_price:,.2f}"

            alert_header = f"{clean_model.upper()} IN-STOCK DEAL!"
            if "8bitdo" in clean_model.lower():
                alert_header = "8BITDO JOYSTICK IN-STOCK DEAL!"

            alert_msg = (
                f"🚨 *{alert_header}* 🚨\n"
                f"📦 *Model:* {clean_model}\n"
                f"🎨 *Color:* {v_color}\n"
                f"📉 *Deal Price:* {price_display}" + (f" (MRP: {mrp_display} | {discount_pct:.1f}% OFF)" if discount_pct > 0 else "") + "\n"
                f"🎯 *Target Price:* Below {target_display}\n"
                f"🛒 *Buy Now:* {v_url}"
            )

            logger.info("[amazon] IN-STOCK VARIANT TRIGGERED: %s at INR %s", v_color, v_price)
            if await self.notifier.send_message(alert_msg):
                notified_any = True
                await self.db.log_deal_alert(
                    product_url=v_url,
                    title=f"{clean_model} - {v_color}",
                    price=v_price,
                    effective_price=v_price,
                    discount_percent=discount_pct,
                    platform="amazon",
                )

        if notified_any and lowest_price is not None:
            await self.db.set_last_notified(product.id, lowest_price)

        return notified_any

    async def _check_flipkart_variants(self, product) -> bool:
        """Inspect all colorways and sizes for a Flipkart multi-variant product."""
        import re
        from scrapers.flipkart import FlipkartScraper

        scraper = FlipkartScraper(self.config)
        report = await scraper.check_product_variants(product.url)

        model_title = report.get("model_title") or product.title or "CROCS LiteRide 360 Clog"
        clean_model = model_title.split("(")[0].strip() if "(" in model_title else model_title

        # Check if specific target size(s) are specified in product.title (e.g. "Size 8", "Sizes 8 & 9", "Size 8, 9", "Size 8 and 9")
        target_sizes: list[str] = []
        m_sizes = re.search(r"\bsizes?\s*[:\s-]?\s*([0-9\s,\.&/and]+)\b", (product.title or ""), re.IGNORECASE)
        if m_sizes:
            raw_nums = re.findall(r"\b([0-9]+(?:\.[0-9]+)?)\b", m_sizes.group(1))
            target_sizes = [n.strip() for n in raw_nums if n.strip()]
        if not target_sizes:
            m_single = re.search(r"\b(?:uk|us)?\s*size\s*[:\s-]?\s*([0-9]+(?:\.[0-9]+)?)\b", (product.title or ""), re.IGNORECASE)
            if m_single:
                target_sizes = [m_single.group(1).strip()]

        in_stock_variants = report.get("in_stock_variants", [])

        # Filter by target sizes if specified
        if target_sizes:
            def matches_target_sizes(v):
                v_sizes = [s.strip().lower() for s in v.get("sizes", [])]
                for ts in target_sizes:
                    ts_clean = ts.strip().lower()
                    if any(
                        s == ts_clean
                        or s == f"uk{ts_clean}"
                        or s == f"us{ts_clean}"
                        or s == f"uk {ts_clean}"
                        or s == f"us {ts_clean}"
                        or s.startswith(f"{ts_clean} ")
                        or s.endswith(f" {ts_clean}")
                        for s in v_sizes
                    ):
                        return True
                return False
            in_stock_variants = [v for v in in_stock_variants if matches_target_sizes(v)]

        lowest_price = min((v["price"] for v in in_stock_variants), default=None)
        size_prefix = "Size" if len(target_sizes) == 1 else "Sizes"
        sizes_label = " & ".join(target_sizes) if len(target_sizes) <= 2 else ", ".join(target_sizes)

        if not in_stock_variants:
            if target_sizes:
                updated_title = f"{clean_model} ({size_prefix} {sizes_label} - All Colors Out of Stock)"
            else:
                updated_title = f"{clean_model} (All Colors & Sizes - Out of Stock)"
            await self.db.update_price(product.id, None, title=updated_title)
            logger.info(
                "[flipkart] Multi-variant product %s: all %s colorways currently out of stock (target sizes: %s).",
                product.id,
                report.get("total_colors_checked", 0),
                sizes_label or "any",
            )
            return False

        if target_sizes:
            updated_title = f"{clean_model} ({size_prefix} {sizes_label} - {len(in_stock_variants)} color{'s' if len(in_stock_variants) != 1 else ''} In Stock)"
        else:
            updated_title = f"{clean_model} ({len(in_stock_variants)} variant{'s' if len(in_stock_variants) != 1 else ''} In Stock)"
        await self.db.update_price(product.id, lowest_price, title=updated_title)

        notified_any = False
        target_price = product.target_price

        for variant in in_stock_variants:
            v_price = variant["price"]
            v_color = variant["color"]
            v_sizes = ", ".join(variant["sizes"]) if variant["sizes"] else "Standard"
            v_url = variant["url"]
            v_mrp = variant.get("mrp") or v_price

            if target_price is not None and v_price > target_price:
                logger.info("[flipkart] Variant %s (%s) price INR %s exceeds target INR %s", v_color, v_sizes, v_price, target_price)
                continue

            # 60-minute alert de-duplication
            if await self.db.is_deal_recently_notified(v_url, minutes=60, current_price=v_price):
                continue

            discount_pct = round(((v_mrp - v_price) / v_mrp) * 100.0, 1) if v_mrp > v_price else 0.0
            price_display = f"₹{v_price:,.0f}" if v_price.is_integer() else f"₹{v_price:,.2f}"
            mrp_display = f"₹{v_mrp:,.0f}" if v_mrp.is_integer() else f"₹{v_mrp:,.2f}"

            if "crocs" in clean_model.lower() and "literide" in clean_model.lower():
                alert_header = "CROCS LITERIDE 360 IN-STOCK DEAL!"
            else:
                alert_header = f"{clean_model.upper()} IN-STOCK DEAL!"

            if target_price is not None:
                target_display = f"₹{target_price:,.0f}" if target_price.is_integer() else f"₹{target_price:,.2f}"
                target_line = f"🎯 *Target Price:* Below {target_display}\n"
            elif target_sizes:
                target_line = f"🎯 *Target:* In-Stock Alert ({size_prefix} {sizes_label})\n"
            else:
                target_line = f"🎯 *Target:* In-Stock Alert\n"

            alert_msg = (
                f"🚨 *{alert_header}* 🚨\n"
                f"📦 *Model:* {clean_model}\n"
                f"🎨 *Color:* {v_color}\n"
                f"📏 *Available Sizes:* {v_sizes}\n"
                f"📉 *Deal Price:* {price_display}" + (f" (MRP: {mrp_display} | {discount_pct:.1f}% OFF)" if discount_pct > 0 else "") + "\n"
                + target_line +
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
    def _is_variant_consistent(target_title: str, target_url: str, scraped_title: str) -> bool:
        """Check if target capacity/size specification matches scraped title."""
        import re
        target_combined = f"{target_title} {target_url}".lower()
        scraped_lower = (scraped_title or "").lower()

        capacities = ("1 tb", "2 tb", "4 tb", "250 gb", "256 gb", "500 gb", "512 gb", "128 gb", "64 gb", "32 gb", "16 gb", "8 gb")
        expected_cap = None
        for cap in capacities:
            cap_clean = cap.replace(" ", "")
            cap_dash = cap.replace(" ", "-")
            if re.search(r"\b" + re.escape(cap) + r"\b", target_combined) or \
               re.search(r"\b" + re.escape(cap_clean) + r"\b", target_combined) or \
               re.search(r"\b" + re.escape(cap_dash) + r"\b", target_combined):
                expected_cap = cap
                break

        if expected_cap and scraped_lower:
            for other_cap in capacities:
                if other_cap == expected_cap:
                    continue
                other_clean = other_cap.replace(" ", "")
                other_dash = other_cap.replace(" ", "-")
                if re.search(r"\b" + re.escape(other_cap) + r"\b", scraped_lower) or \
                   re.search(r"\b" + re.escape(other_clean) + r"\b", scraped_lower) or \
                   re.search(r"\b" + re.escape(other_dash) + r"\b", scraped_lower):
                    if not (re.search(r"\b" + re.escape(expected_cap) + r"\b", scraped_lower) or \
                            re.search(r"\b" + re.escape(expected_cap.replace(" ", "")) + r"\b", scraped_lower)):
                        return False
        return True

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

        # VIP items bypass anti-spam deduplication completely (alert repeatedly while in stock as requested):
        url_lower = (product.url or "").lower()
        if "gbd-h2000" in url_lower or "gbd-300-9dr" in url_lower:
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