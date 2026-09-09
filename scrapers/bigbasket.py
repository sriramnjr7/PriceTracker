"""BigBasket scraper with strict Selling Price vs You Save parsing.

Supports single product tracking, location context (560103 / 635109),
and automated catalog search with true discount calculation.
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


class BigBasketScraper(BaseScraper):
    platform = "bigbasket"
    prefer_js = False

    title_selectors = (
        "h1.Description___StyledH-sc-82kqkc-1",
        "h1[class*='Description']",
        "h1",
        ".ProductTitle___StyledHeading",
    )

    out_of_stock_keywords = (
        "out of stock",
        "currently unavailable",
        "sold out",
        "not available",
    )

    def _extract_title(self, soup: BeautifulSoup) -> str:
        for s in self.title_selectors:
            el = soup.select_one(s)
            if el and el.get_text(strip=True):
                return el.get_text(" ", strip=True)
        return super()._extract_title(soup)

    def _extract_price(self, soup: BeautifulSoup) -> float | None:
        # 1. Search for explicit 'Price: ₹X' row/cell
        for tr in soup.find_all(["tr", "div", "td", "span"]):
            txt = tr.get_text(" ", strip=True)
            if "you save" in txt.lower() or "off" in txt.lower():
                continue
            if txt.startswith("Price:") or "price: ₹" in txt.lower():
                m = re.search(r"Price:\s*(?:₹|Rs\.?)\s*([\d,]+(?:\.\d+)?)", txt, re.I)
                if m:
                    try:
                        return float(m.group(1).replace(",", ""))
                    except ValueError:
                        pass

        # 2. Look for primary pricing element
        for sel in ["td[class*='Description___StyledTd']", "span[class*='Pricing___StyledLabel']", "h3[class*='Pricing']"]:
            el = soup.select_one(sel)
            if el:
                txt = el.get_text(" ", strip=True)
                if "you save" not in txt.lower() and "off" not in txt.lower():
                    val = self.clean_price(txt)
                    if val is not None and val >= 5.0:
                        return val

        return super()._extract_price(soup)

    async def scan_deals(
        self,
        query: str,
        min_discount: float = 20.0,
        max_price: Optional[float] = None,
        min_mrp: Optional[float] = None,
        negative_keywords: Optional[List[str]] = None,
        custom_url: Optional[str] = None,
    ) -> List[dict[str, Any]]:
        """Search BigBasket for deals matching discount, price ceiling, and negative filters."""
        url = custom_url or f"https://www.bigbasket.com/ps/?q={quote_plus(query)}"
        deals: List[dict[str, Any]] = []
        negative_set = [k.lower() for k in (negative_keywords or [])]

        loc = self.config.get_location()

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
                    geolocation={"latitude": loc["lat"], "longitude": loc["lon"]},
                    permissions=["geolocation"],
                )
                await context.add_cookies([
                    {"name": "_bb_pincode", "value": loc.get("pincode", "560103"), "domain": ".bigbasket.com", "path": "/"},
                    {"name": "_bb_cid", "value": "1", "domain": ".bigbasket.com", "path": "/"},
                ])

                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                await page.wait_for_timeout(3500)
                html = await page.content()
                await context.close()
                await browser.close()

                soup = BeautifulSoup(html, "html.parser")
                cards = soup.select("li.PaginateItems___StyledLi-sc-1yrbjdr-0, div[class*='SKUDeck'], li[class*='PaginateItems']")

                for card in cards:
                    h3 = card.find("h3") or card.find("h2") or card.select_one("[class*='BrandName']")
                    title = h3.get_text(" ", strip=True) if h3 else ""
                    if not title or any(neg in title.lower() for neg in negative_set):
                        continue

                    link_el = card.find("a", href=True)
                    if not link_el or not link_el.get("href"):
                        continue
                    clean_url = "https://www.bigbasket.com" + link_el["href"].split("?")[0]

                    card_text = card.get_text(" ", strip=True)
                    
                    # 1. Extract MRP
                    mrp_val = None
                    mrp_match = re.search(r"MRP\s*(?:₹|Rs\.?)\s*([\d,]+(?:\.\d+)?)", card_text, re.I)
                    if mrp_match:
                        try:
                            mrp_val = float(mrp_match.group(1).replace(",", ""))
                        except ValueError:
                            pass

                    # 2. Extract Selling Price (excluding "You Save:" and "₹X OFF")
                    selling_price = None
                    # Try explicit price label first
                    sp_el = card.select_one("span[class*='Pricing___StyledLabel'], span[class*='Label-sc-15v1nk5-0'], [class*='Pricing']")
                    if sp_el and "off" not in sp_el.get_text().lower() and "save" not in sp_el.get_text().lower():
                        selling_price = self.clean_price(sp_el.get_text())

                    # If not found via selector, extract via regex from price section
                    if selling_price is None or selling_price <= 0:
                        # Extract first rupee amount that is NOT followed by OFF or preceded by You Save
                        clean_tokens = []
                        for txt in [t for t in card.stripped_strings]:
                            txt_low = txt.lower()
                            if "you save" in txt_low or "off" in txt_low or "mrp" in txt_low:
                                continue
                            if "₹" in txt or "rs" in txt_low:
                                v = self.clean_price(txt)
                                if v and v >= 5.0 and "/ 100" not in txt_low and "per" not in txt_low:
                                    clean_tokens.append(v)
                        if clean_tokens:
                            selling_price = clean_tokens[0]

                    if selling_price is None or selling_price <= 0:
                        continue

                    mrp_val = mrp_val or selling_price

                    if min_mrp is not None and mrp_val < min_mrp:
                        continue

                    # 3. Calculate true discount
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
                        "platform": "bigbasket",
                        "url": clean_url,
                        "in_stock": True,
                    })
        except Exception as exc:
            logger.warning("[bigbasket] deal scan error for query '%s': %s", query, exc)

        return deals
