"""GenesisPC (genesispc.in) Scraper.

Supports single product tracking, variant price selection, and stock checks
for PC components, mechanical keyboards, and gaming controllers.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, List, Optional
from urllib.parse import urlparse, parse_qs

import httpx
from bs4 import BeautifulSoup

from .base import BaseScraper, ScrapeResult

logger = logging.getLogger(__name__)


class GenesisPCScraper(BaseScraper):
    platform: str = "genesispc"
    prefer_js: bool = False

    title_selectors: tuple[str, ...] = (
        "h1.product-title",
        "h1.product__title",
        ".product_title",
        "h1",
    )
    price_selectors: tuple[str, ...] = (
        ".price--on-sale .price-item--sale",
        ".price-item--sale",
        ".price__sale .price-item--sale",
        ".price-item--regular",
        ".price .price-item",
        "span.price-item",
    )
    out_of_stock_keywords: tuple[str, ...] = (
        "sold out",
        "out of stock",
        "currently unavailable",
    )

    async def scrape(self, url: str) -> ScrapeResult:
        """Scrape GenesisPC product using Shopify JSON endpoint for maximum speed and accuracy."""
        clean = url.strip()
        parsed = urlparse(clean)
        path = parsed.path.rstrip("/")
        m = re.search(r"/products/([a-zA-Z0-9_-]+)", path)
        handle = m.group(1) if m else ""
        
        # Check variant ID if present in query
        qs = parse_qs(parsed.query)
        target_variant_id = qs.get("variant", [None])[0]

        headers = {
            "User-Agent": self._random_user_agent(),
            "Accept": "application/json, text/html, */*",
        }

        # 1. Fast Shopify Product JSON endpoint
        if handle:
            json_url = f"https://www.genesispc.in/products/{handle}.json"
            try:
                async with httpx.AsyncClient(timeout=10, follow_redirects=True, headers=headers) as client:
                    r = await client.get(json_url)
                    if r.status_code == 200:
                        data = r.json().get("product", {})
                        title = data.get("title", handle.replace("-", " ").title())
                        variants = data.get("variants", [])
                        
                        chosen_variant = None
                        if target_variant_id:
                            for v in variants:
                                if str(v.get("id")) == str(target_variant_id):
                                    chosen_variant = v
                                    break
                        if not chosen_variant and variants:
                            # Prefer first available variant, otherwise first variant
                            chosen_variant = next((v for v in variants if v.get("available")), variants[0])

                        if chosen_variant:
                            price = float(chosen_variant.get("price", 0))
                            in_stock = bool(chosen_variant.get("available", False))
                            v_title = chosen_variant.get("title", "")
                            if v_title and v_title.lower() != "default title":
                                full_title = f"{title} ({v_title})"
                            else:
                                full_title = title

                            return ScrapeResult(
                                title=full_title,
                                price=price if price > 0 else None,
                                in_stock=in_stock,
                                platform=self.platform,
                                url=clean,
                            )
            except Exception as exc:
                logger.debug("[genesispc] JSON endpoint error: %s; falling back to HTML", exc)

        # 2. HTML Scrape Fallback
        async with httpx.AsyncClient(timeout=12, follow_redirects=True, headers=headers) as client:
            resp = await client.get(clean)
            if resp.status_code == 200:
                result = self.parse(resp.text, str(resp.url))
                result.platform = self.platform
                if not result.title and handle:
                    result.title = handle.replace("-", " ").title()
                return result

        return ScrapeResult(
            title=handle.replace("-", " ").title() if handle else "GenesisPC Item",
            price=None,
            in_stock=False,
            platform=self.platform,
            url=clean,
        )

    def _extract_stock(self, soup: BeautifulSoup) -> bool:
        """Check button state specifically instead of whole body text."""
        btn = soup.select_one('button[name="add"], .product-form__submit, .add-to-cart')
        if btn:
            if btn.has_attr("disabled"):
                return False
            btn_text = btn.get_text(" ", strip=True).lower()
            if any(k in btn_text for k in self.out_of_stock_keywords):
                return False
            return True
        return super()._extract_stock(soup)
