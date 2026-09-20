"""Myntra scraper (JS-rendered with deal scanning).

Supports single product tracking, anti-bot TLS bypass, and clearance deal search.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
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
        brand: Optional[str] = None,
    ) -> List[dict[str, Any]]:
        """Search Myntra for deals matching discount, brand, price ceiling, and negative filters."""
        if custom_url:
            url = custom_url
        else:
            disc_tier = int(min_discount) if min_discount >= 10 else 10
            url = f"https://www.myntra.com/{quote_plus(query)}?f=Discount:{disc_tier}.0_100.0"
            if brand:
                url += f"::Brand:{quote_plus(brand.upper())}"

        deals: List[dict[str, Any]] = []
        negative_set = [k.lower() for k in (negative_keywords or [])]
        brand_lower = (brand or "").lower().strip()

        # Method 1: Fast & reliable curl_cffi extraction from window.__myx
        try:
            from curl_cffi import requests as c_requests
            response = await asyncio.to_thread(
                c_requests.get,
                url,
                impersonate="chrome124",
                timeout=15,
            )
            if response.status_code == 200 and "window.__myx" in response.text:
                idx = response.text.find("window.__myx = ")
                end_idx = response.text.find("</script>", idx)
                if idx != -1 and end_idx != -1:
                    raw_json = response.text[idx + len("window.__myx = "):end_idx].strip().rstrip(";").strip()
                    data = json.loads(raw_json)
                    products = data.get("searchData", {}).get("results", {}).get("products", [])
                    for p in products:
                        p_brand = p.get("brand", "").strip()
                        p_name = p.get("product", "") or p.get("productName", "")
                        title = f"{p_brand} {p_name}".strip()
                        title_lower = title.lower()

                        if any(neg in title_lower for neg in negative_set):
                            continue

                        # Strict brand verification
                        if brand_lower:
                            if p_brand.lower() != brand_lower and brand_lower not in title_lower:
                                continue

                        price = float(p.get("price", 0))
                        if price <= 0:
                            continue

                        mrp = float(p.get("mrp") or price)
                        if min_mrp is not None and mrp < min_mrp:
                            continue

                        if mrp > price and mrp > 0:
                            discount_percent = round(((mrp - price) / mrp) * 100.0, 1)
                        else:
                            discount_percent = 0.0

                        if discount_percent < min_discount and (max_price is None or price > max_price):
                            continue

                        if max_price is not None and price > max_price:
                            continue

                        in_stock = True
                        if p.get("inventoryInfo"):
                            in_stock = any(bool(inv.get("available", False)) for inv in p["inventoryInfo"])

                        clean_url = "https://www.myntra.com/" + p.get("landingPageUrl", "").lstrip("/")

                        deals.append({
                            "title": title,
                            "price": price,
                            "effective_price": price,
                            "mrp": mrp,
                            "discount_percent": discount_percent,
                            "coupon_text": None,
                            "platform": "myntra",
                            "url": clean_url,
                            "in_stock": in_stock,
                            "scraped_brand": p_brand,
                        })

                    if deals:
                        return deals
        except Exception as curl_exc:
            logger.debug("[myntra] curl_cffi extraction error: %s", curl_exc)

        # Method 2: Playwright fallback (local non-CI only)
        if not (os.getenv("CI") or os.getenv("GITHUB_ACTIONS") or os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME")):
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

                        if brand_lower and brand_lower != brand_txt.lower() and brand_lower not in title_lower:
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
                            "scraped_brand": brand_txt,
                        })
            except Exception as exc:
                logger.warning("[myntra] deal scan error for query '%s': %s", query, exc)

        return deals