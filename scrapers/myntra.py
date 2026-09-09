"""Myntra scraper (JS-rendered with deal scanning).

Supports single product tracking, anti-bot TLS bypass, and clearance deal search.
"""

from __future__ import annotations

import logging
import re
from typing import Any, List, Optional
from urllib.parse import quote_plus
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from .base import BaseScraper, ScrapeResult

logger = logging.getLogger(__name__)


class MyntraScraper(BaseScraper):
    platform = "myntra"
    prefer_js = True

    title_selectors = (
        "h1[class*='pdp-title']",
        ".pdp-title",
        "h1[class*='product-name']",
        "h1",
    )

    price_selectors = (
        ".pdp-price strong",
        ".pdp-price",
        "[class*='pdp-price']",
        "span[class*='price']",
    )

    out_of_stock_keywords = (
        "out of stock",
        "sold out",
        "currently unavailable",
        "not available",
    )

    async def scan_deals(
        self,
        query: str,
        min_discount: float = 50.0,
        max_price: Optional[float] = None,
        min_mrp: Optional[float] = None,
        negative_keywords: Optional[List[str]] = None,
        custom_url: Optional[str] = None,
    ) -> List[dict[str, Any]]:
        """Search Myntra for deals matching discount, price ceiling, and negative filters."""
        if custom_url:
            url = custom_url
        else:
            disc_tier = int(min_discount) if min_discount >= 10 else 10
            url = f"https://www.myntra.com/{quote_plus(query)}?f=Discount:{disc_tier}.0_100.0"

        deals: List[dict[str, Any]] = []
        negative_set = [k.lower() for k in (negative_keywords or [])]

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    channel="chrome",
                    headless=self.config.headless,
                    args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                )
                context = await browser.new_context(
                    user_agent=self._random_user_agent(),
                    locale="en-IN",
                    timezone_id="Asia/Kolkata",
                )
                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                await page.wait_for_timeout(3500)
                html = await page.content()
                await context.close()
                await browser.close()

                soup = BeautifulSoup(html, "html.parser")
                cards = soup.select("li.product-base, div.product-base")
                if not cards:
                    # Fallback to search any product links
                    cards = [a.parent for a in soup.find_all("a", href=True) if "/buy" in a["href"]]

                for card in cards:
                    link_el = card.find("a", href=True) if card.name != "a" else card
                    if not link_el or not link_el.get("href"):
                        continue

                    href = link_el["href"]
                    clean_url = "https://www.myntra.com/" + href.lstrip("/")

                    brand_el = card.select_one(".product-brand")
                    prod_el = card.select_one(".product-product")
                    brand_txt = brand_el.get_text(strip=True) if brand_el else ""
                    prod_txt = prod_el.get_text(strip=True) if prod_el else ""
                    title = f"{brand_txt} {prod_txt}".strip() or clean_url.split("/")[-3].replace("-", " ").title()

                    title_lower = title.lower()
                    if any(neg in title_lower for neg in negative_set):
                        continue

                    price_el = card.select_one(".product-discountedPrice, .product-price")
                    if not price_el:
                        continue
                    selling_price = self.clean_price(price_el.get_text(strip=True))
                    if selling_price is None or selling_price <= 0:
                        continue

                    mrp_el = card.select_one(".product-strike")
                    mrp_val = self.clean_price(mrp_el.get_text(strip=True)) if mrp_el else selling_price
                    mrp_val = mrp_val or selling_price

                    if min_mrp is not None and mrp_val < min_mrp:
                        continue

                    if mrp_val > selling_price and mrp_val > 0:
                        discount_percent = round(((mrp_val - selling_price) / mrp_val) * 100.0, 1)
                    else:
                        discount_percent = 0.0

                    if discount_percent < min_discount and (max_price is None or selling_price > max_price):
                        continue

                    if max_price is not None and selling_price > max_price:
                        continue

                    deals.append({
                        "title": title,
                        "price": selling_price,
                        "effective_price": selling_price,
                        "mrp": mrp_val,
                        "discount_percent": discount_percent,
                        "coupon_text": None,
                        "platform": "myntra",
                        "url": clean_url,
                        "in_stock": True,
                    })
        except Exception as exc:
            logger.warning("[myntra] deal scan error for query '%s': %s", query, exc)

        return deals