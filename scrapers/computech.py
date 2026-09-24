"""Computech Store (computechstore.in) PC Hardware & Peripherals Scraper.

Parses product price, stock availability, and metadata using Schema.org Product
JSON-LD data with HTML microdata fallbacks.
"""

from __future__ import annotations

import json
import logging
from typing import Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from .base import BaseScraper, ScrapeResult

logger = logging.getLogger(__name__)


class ComputechScraper(BaseScraper):
    platform: str = "computech"
    prefer_js: bool = False

    title_selectors: tuple[str, ...] = (
        "h1.product_title",
        "h1.product-title",
        ".product_title",
        "h1",
    )
    price_selectors: tuple[str, ...] = (
        ".price ins .amount",
        ".price .amount",
        "p.price",
        "span.amount",
    )
    out_of_stock_keywords: tuple[str, ...] = (
        "out of stock",
        "sold out",
        "currently unavailable",
        "unavailable",
    )

    async def scrape(self, url: str) -> ScrapeResult:
        """Scrape Computech Store product page."""
        clean_url = url.split("?")[0].rstrip("/") + "/"
        parsed = urlparse(clean_url)
        slug = [s for s in parsed.path.split("/") if s][-1] if parsed.path else "product"
        fallback_title = slug.replace("-", " ").title()

        html = await self._static_fetch(clean_url)
        if not html:
            html = await self._js_fetch(clean_url)

        if not html:
            return ScrapeResult(
                title=fallback_title,
                price=None,
                in_stock=False,
                platform=self.platform,
                url=clean_url,
            )

        soup = BeautifulSoup(html, "html.parser")
        title: Optional[str] = None
        price: Optional[float] = None
        in_stock: bool = True

        # 1. Parse Schema.org Product JSON-LD (primary authoritative source)
        for s in soup.find_all("script", type="application/ld+json"):
            if not s.string:
                continue
            try:
                data = json.loads(s.string)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") == "Product":
                        title = item.get("name")
                        offers = item.get("offers")
                        if isinstance(offers, list) and offers:
                            offers = offers[0]
                        if isinstance(offers, dict):
                            avail = str(offers.get("availability", "")).lower()
                            if "outofstock" in avail:
                                in_stock = False
                            elif "instock" in avail:
                                in_stock = True

                            p_val = offers.get("price")
                            if not p_val and "priceSpecification" in offers:
                                ps = offers["priceSpecification"]
                                if isinstance(ps, list) and ps:
                                    p_val = ps[0].get("price")
                            if p_val:
                                try:
                                    price = float(str(p_val).replace(",", "").strip())
                                except ValueError:
                                    pass
                        break
            except Exception:
                pass
            if title and price:
                break

        # 2. HTML Fallbacks
        if not title:
            title = self._extract_title(soup) or fallback_title

        if price is None:
            price = self._extract_price(soup)

        # Double check stock keywords in text
        text_lower = soup.get_text(" ", strip=True).lower()
        if any(kw in text_lower for kw in self.out_of_stock_keywords):
            in_stock = False

        return ScrapeResult(
            title=title,
            price=price if in_stock else None,
            in_stock=in_stock,
            platform=self.platform,
            url=clean_url,
        )
