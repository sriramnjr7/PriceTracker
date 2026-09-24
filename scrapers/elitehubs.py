"""EliteHubs (elitehubs.com) PC Components & Hardware Scraper.

Handles single product tracking for PC hardware, SSDs, GPUs, and peripherals
via Shopify's high-speed client-side JSON/JS APIs and HTML fallback.
"""

from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from .base import BaseScraper, ScrapeResult

logger = logging.getLogger(__name__)


class EliteHubsScraper(BaseScraper):
    platform: str = "elitehubs"
    prefer_js: bool = False

    title_selectors: tuple[str, ...] = (
        "h1.product-meta__title",
        "h1.product__title",
        ".product-title h1",
        "h1",
    )
    price_selectors: tuple[str, ...] = (
        ".price-list .price--highlight",
        ".price-list .price",
        ".price--sale",
        ".product-form__info-item .price",
        ".price .money",
        "span.price",
    )
    out_of_stock_keywords: tuple[str, ...] = (
        "sold out",
        "out of stock",
        "currently unavailable",
        "unavailable",
    )

    async def scrape(self, url: str) -> ScrapeResult:
        """Fetch and parse an EliteHubs product page."""
        clean_url = url.split("?")[0].rstrip("/")
        handle_match = re.search(r"/products/([a-zA-Z0-9_-]+)", clean_url)
        handle = handle_match.group(1) if handle_match else ""
        fallback_title = handle.replace("-", " ").title() if handle else "EliteHubs Product"

        # 1. First try Shopify's authoritative .js client endpoint
        if handle:
            js_url = f"https://elitehubs.com/products/{handle}.js"
            try:
                async with httpx.AsyncClient(
                    follow_redirects=True,
                    timeout=8.0,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                ) as client:
                    r = await client.get(js_url)
                    if r.status_code == 200:
                        data = r.json()
                        title = data.get("title") or fallback_title
                        is_avail = bool(data.get("available", False))
                        variants = data.get("variants", [])
                        has_avail_variant = any(bool(v.get("available", False)) for v in variants)
                        in_stock = is_avail or has_avail_variant

                        # Shopify .js returns price in paise (cents)
                        raw_price = data.get("price")
                        if raw_price is None and variants:
                            raw_price = variants[0].get("price")

                        price = (float(raw_price) / 100.0) if raw_price is not None else None

                        return ScrapeResult(
                            title=title,
                            price=price if in_stock else None,
                            in_stock=in_stock,
                            platform=self.platform,
                            url=clean_url,
                        )
            except Exception as exc:
                logger.debug("[elitehubs] .js endpoint failed: %s; falling back to .json/HTML", exc)

        # 2. Try .json endpoint fallback
        if handle:
            json_url = f"https://elitehubs.com/products/{handle}.json"
            try:
                async with httpx.AsyncClient(
                    follow_redirects=True,
                    timeout=8.0,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                ) as client:
                    r = await client.get(json_url)
                    if r.status_code == 200:
                        prod = r.json().get("product", {})
                        title = prod.get("title") or fallback_title
                        variants = prod.get("variants", [])
                        in_stock = any(bool(v.get("available", False)) for v in variants) if variants else False
                        price = float(variants[0]["price"]) if variants and variants[0].get("price") else None
                        return ScrapeResult(
                            title=title,
                            price=price if in_stock else None,
                            in_stock=in_stock,
                            platform=self.platform,
                            url=clean_url,
                        )
            except Exception as exc:
                logger.debug("[elitehubs] .json endpoint failed: %s; falling back to HTML", exc)

        # 3. HTML scrape fallback via BaseScraper
        html = await self._static_fetch(clean_url)
        if html:
            res = self.parse(html, clean_url)
            if not res.title:
                res.title = fallback_title
            return res

        return ScrapeResult(
            title=fallback_title,
            price=None,
            in_stock=False,
            platform=self.platform,
            url=clean_url,
        )
