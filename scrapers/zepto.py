"""Zepto Quick-Commerce scraper.

Extracts product title, selling price, MRP, and stock availability from Zepto.
"""

from __future__ import annotations

import json
import re
from typing import Any, List, Optional
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from .base import BaseScraper, ScrapeResult


class ZeptoScraper(BaseScraper):
    platform = "zepto"
    prefer_js = True

    title_selectors = (
        "h1[data-testid='pdp-product-name']",
        "h1[class*='product-title']",
        "h1",
        "h2",
    )

    price_selectors = (
        "h4[data-testid='pdp-selling-price']",
        "span[data-testid='pdp-selling-price']",
        "[data-testid*='selling-price']",
        "[class*='sellingPrice']",
        "[class*='Price']",
    )

    out_of_stock_keywords = (
        "out of stock",
        "currently unavailable",
        "sold out",
    )

    def parse(self, html: str, url: str) -> ScrapeResult:
        soup = BeautifulSoup(html, "html.parser")
        
        # 1. Try __NEXT_DATA__ JSON
        next_data_el = soup.find("script", id="__NEXT_DATA__")
        if next_data_el and next_data_el.string:
            try:
                data = json.loads(next_data_el.string)
                page_props = data.get("props", {}).get("pageProps", {})
                product = page_props.get("product") or page_props.get("productResponse", {})
                if product:
                    title = product.get("name") or product.get("title")
                    price = product.get("discountedSellingPrice") or product.get("sellingPrice") or product.get("mrp")
                    if price and price > 1000:  # Sometimes stored in paise
                        price = price / 100.0
                    available = product.get("availableQuantity", 1) > 0 and not product.get("outOfStock", False)
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
            match = re.search(r"/pn/([^/?]+)", url)
            if match:
                res.title = match.group(1).replace("-", " ").title()
        return res

    async def scan_deals(
        self,
        query: str,
        min_discount: float = 20.0,
        max_price: Optional[float] = None,
        min_mrp: Optional[float] = None,
        negative_keywords: Optional[List[str]] = None,
        custom_url: Optional[str] = None,
    ) -> List[dict[str, Any]]:
        """Search Zepto for deals matching discount, price ceiling, and negative filters."""
        url = custom_url or f"https://www.zeptonow.com/search?q={query}"
        deals: List[dict[str, Any]] = []
        loc = self.config.get_location()
        negative_set = [k.lower() for k in (negative_keywords or [])]

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    channel="chrome",
                    headless=self.config.headless,
                    args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                )
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
                    locale="en-IN",
                    geolocation={"latitude": loc["lat"], "longitude": loc["lon"]},
                    permissions=["geolocation"],
                )
                page = await context.new_page()
                await page.goto("https://www.zeptonow.com/", wait_until="domcontentloaded")
                await page.wait_for_timeout(2500)
                
                # Dismiss location modal if shown
                btn = await page.query_selector("button:has-text('Select Location'), button:has-text('Enable Location')")
                if btn:
                    await btn.click()
                    await page.wait_for_timeout(1500)

                await page.goto(url, wait_until="domcontentloaded")
                await page.wait_for_timeout(3500)
                soup = BeautifulSoup(await page.content(), "html.parser")
                await context.close()
                await browser.close()

                cards = soup.select("[data-testid*='product-card'], div[class*='ProductCard']")
                for card in cards:
                    card_text = card.get_text(" ", strip=True)
                    if any(neg in card_text.lower() for neg in negative_set):
                        continue

                    # Extract price tokens (e.g. ADD ₹386 ₹550 ₹164 OFF Product Name)
                    price_tokens = re.findall(r"(?:₹|Rs\.?)\s*([\d,]+(?:\.\d+)?)", card_text)
                    if len(price_tokens) < 2:
                        continue

                    sp = float(price_tokens[0].replace(",", ""))
                    mrp = float(price_tokens[1].replace(",", ""))

                    if min_mrp is not None and mrp < min_mrp:
                        continue

                    if max_price is not None and sp > max_price:
                        continue

                    disc = round(((mrp - sp) / mrp) * 100.0, 1) if mrp > sp else 0.0
                    if disc < min_discount:
                        continue

                    link_el = card.find("a", href=True)
                    clean_url = ("https://www.zeptonow.com" + link_el["href"].split("?")[0]) if link_el else url

                    title_match = re.search(r"OFF\s+(.+)$", card_text)
                    title = title_match.group(1).strip() if title_match else card_text[:45]

                    deals.append({
                        "title": title,
                        "price": sp,
                        "effective_price": sp,
                        "mrp": mrp,
                        "discount_percent": disc,
                        "platform": "zepto",
                        "url": clean_url,
                        "in_stock": True,
                    })
        except Exception as exc:
            pass

        return deals
