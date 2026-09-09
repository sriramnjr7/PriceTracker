"""Blinkit Quick-Commerce scraper.

Extracts product title, selling price, MRP, and stock availability from Blinkit.
"""

from __future__ import annotations

import re
from bs4 import BeautifulSoup
from .base import BaseScraper, ScrapeResult


class BlinkitScraper(BaseScraper):
    platform = "blinkit"
    prefer_js = True

    title_selectors = (
        "h1[class*='tw-text']",
        "h1",
        "div[class*='ProductDetails__Title']",
        "div.tw-text-300",
        ".ProductTitle",
    )

    price_selectors = (
        "div[class*='ProductPrice'] div",
        "div.tw-text-400",
        "span[class*='Price']",
        "div[class*='price']",
    )

    out_of_stock_keywords = (
        "out of stock",
        "unavailable in your area",
        "currently unavailable",
        "sold out",
    )

    def parse(self, html: str, url: str) -> ScrapeResult:
        res = super().parse(html, url)
        # If title is just a unit/measurement, extract clean product name from URL
        match = re.search(r"/prn/([^/?]+)", url)
        if match:
            url_name = match.group(1).replace("-", " ").title()
            if not res.title or len(res.title) < 5 or any(k in res.title.lower() for k in ["ltr", "kg", " g", " ml", "pack"]):
                res.title = f"{url_name} ({res.title})" if res.title else url_name
        return res

    def _extract_price(self, soup: BeautifulSoup) -> float | None:
        for s in self.price_selectors:
            for el in soup.select(s):
                txt = el.get_text(" ", strip=True)
                if "₹" in txt or "Rs" in txt:
                    val = self.clean_price(txt)
                    if val is not None:
                        return val
        return super()._extract_price(soup)
