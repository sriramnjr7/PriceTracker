"""Swiggy Instamart Quick-Commerce scraper.

Extracts product title, selling price, and stock availability from Swiggy Instamart.
"""

from __future__ import annotations

import json
import re
from bs4 import BeautifulSoup
from .base import BaseScraper, ScrapeResult


class InstamartScraper(BaseScraper):
    platform = "instamart"
    prefer_js = True

    title_selectors = (
        "h1[data-testid='item-name']",
        "h1[class*='item-name']",
        "h1[class*='ItemName']",
        "h1",
        "h2",
    )

    price_selectors = (
        "span[data-testid='item-price']",
        "div[data-testid='item-price']",
        "[class*='item-price']",
        "[class*='ItemPrice']",
        "[class*='Price']",
    )

    out_of_stock_keywords = (
        "out of stock",
        "currently unavailable",
        "item unavailable",
    )

    def parse(self, html: str, url: str) -> ScrapeResult:
        soup = BeautifulSoup(html, "html.parser")
        
        # 1. Try __NEXT_DATA__ JSON
        next_data_el = soup.find("script", id="__NEXT_DATA__")
        if next_data_el and next_data_el.string:
            try:
                data = json.loads(next_data_el.string)
                page_props = data.get("props", {}).get("pageProps", {})
                item = page_props.get("item") or page_props.get("productDetails", {})
                if item:
                    title = item.get("name") or item.get("display_name")
                    price_info = item.get("price", {})
                    price = price_info.get("offer_price") or price_info.get("store_price") or price_info.get("mrp")
                    if not price and isinstance(price_info, (int, float)):
                        price = price_info
                    if price and price > 1000:
                        price = price / 100.0
                    available = item.get("in_stock", True)
                    if title and price:
                        return ScrapeResult(
                            title=title,
                            price=float(price),
                            in_stock=available,
                            platform=self.platform,
                            url=url,
                        )
            except Exception:
                pass

        res = super().parse(html, url)
        if not res.title:
            match = re.search(r"/item/([^/?]+)", url)
            if match:
                res.title = match.group(1).replace("-", " ").title()
        return res
