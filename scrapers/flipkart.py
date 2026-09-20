"""Flipkart India scraper with deal hunting & search scan.

Supports single product tracking, 2026 buy-box selector mapping,
and automated clearance/deal search.
"""

from __future__ import annotations

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


class FlipkartScraper(BaseScraper):
    platform = "flipkart"
    prefer_js = False

    title_selectors = (
        "span.VU-ZEz",
        "span.B_NuCI",
        "h1 span.B_NuCI",
        "h1 span.B_NUCI",
        "h1 span",
        "h1._6EBuvT",
        "h1",
        ".B_NuCI",
        ".B_NUCI",
    )

    price_selectors = (
        "div.Nx9bqj.CxhGGd",
        "div.Nx9bqj",
        "div.CxhGGd",
        "div.hl05eU div.Nx9bqj",
        "#price-buy-box ._30jeq3",
        "._30jeq3._1_WHN1",
        "._30jeq3",
    )

    out_of_stock_keywords = (
        "currently unavailable",
        "out of stock",
        "sold out",
        "temporarily unavailable",
    )

    def _extract_stock(self, soup: BeautifulSoup) -> bool:
        banner = soup.select_one(".z3htrc")
        if banner is not None:
            text = banner.get_text(" ", strip=True).lower()
            if "unavailable" in text or "out of stock" in text:
                return False
        return super()._extract_stock(soup)

    def _extract_price(self, soup: BeautifulSoup) -> Optional[float]:
        """Extract primary product price using Schema.org JSON-LD, standard selectors, and dynamic fallbacks."""
        # 1. Authoritative: Schema.org Product JSON-LD (immune to recommendation carousels and bank offer tags)
        for script in soup.find_all("script"):
            stype = script.get("type", "")
            if "ld+json" in stype or "json" in stype:
                txt = script.string or script.get_text()
                if not txt or "offers" not in txt:
                    continue
                try:
                    data = json.loads(txt)
                    if isinstance(data, list) and data:
                        data = data[0]
                    if isinstance(data, dict):
                        offers = data.get("offers")
                        if isinstance(offers, dict) and "price" in offers:
                            val = float(offers["price"])
                            if val > 0:
                                return val
                        elif isinstance(offers, list) and offers:
                            for off in offers:
                                if isinstance(off, dict) and "price" in off:
                                    val = float(off["price"])
                                    if val > 0:
                                        return val
                except Exception:
                    continue

        # 2. Standard CSS Selectors
        for sel in self.price_selectors:
            for node in soup.select(sel):
                val = self.clean_price(node.get_text(" ", strip=True))
                if val is not None and val > 0:
                    return val

        # 3. Universal fallback for dynamic hashed React/Next.js utility classes
        for el in soup.find_all(True):
            if el.name in ("script", "style", "meta", "link", "noscript"):
                continue
            txt = el.get_text(" ", strip=True)
            if re.match(r"^₹\s*[0-9][0-9,]*(?:\.[0-9]+)?$", txt):
                val = self.clean_price(txt)
                if val is not None and val > 0:
                    return val
        return None

    async def _js_fetch(self, url: str) -> Optional[str]:
        """Render Flipkart page with Playwright, handling short links and Hyperlocal Minutes unwrapping."""
        if os.getenv("CI") or os.getenv("GITHUB_ACTIONS") or os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
            logger.debug("[flipkart] Skipping Playwright fetch in CI/serverless environment")
            return None

        for attempt in range(self.config.retries):
            try:
                from playwright.async_api import async_playwright
                async with async_playwright() as p:
                    try:
                        browser = await p.chromium.launch(
                            channel="chrome",
                            headless=self.config.headless,
                            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                        )
                    except Exception:
                        browser = await p.chromium.launch(
                            headless=self.config.headless,
                            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                        )

                    context = await browser.new_context(
                        user_agent=self._random_user_agent(),
                        locale="en-IN",
                        timezone_id="Asia/Kolkata",
                        viewport={"width": 1366, "height": 900},
                    )
                    page = await context.new_page()
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                        await page.wait_for_timeout(1000)

                        # Check for Flipkart Minutes / Hyperlocal splash redirect
                        curr_url = page.url
                        if "hyperlocal-preview-page" in curr_url or "originalUrl=" in curr_url:
                            from urllib.parse import parse_qs, unquote, urlparse
                            parsed = urlparse(curr_url)
                            qs = parse_qs(parsed.query)
                            orig = qs.get("originalUrl", [None])[0]
                            if orig:
                                target_url = f"https://www.flipkart.com{unquote(orig).split('?')[0]}"
                                logger.info("[flipkart] Unwrapping Hyperlocal Minutes link to: %s", target_url)
                                await page.goto(target_url, wait_until="domcontentloaded", timeout=25000)
                                await page.wait_for_timeout(1500)

                        return await page.content()
                    finally:
                        await context.close()
                        await browser.close()
            except Exception as exc:
                logger.warning("[flipkart] js_fetch error on %s: %s", url, exc)
            await self._polite_delay(backoff=attempt + 1)
        return None

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
        """Search Flipkart for deals matching brand facet, discount, price ceiling, and negative filters."""
        if custom_url:
            url = custom_url
        else:
            disc_tier = int(min_discount) if min_discount >= 10 else 10
            url = f"https://www.flipkart.com/search?q={quote_plus(query)}&p%5B%5D=facets.discount_range_v1%255B%255D%3D{disc_tier}%2525%2Bor%2Bmore"
            if brand:
                url += f"&p%5B%5D=facets.brand%255B%255D%3D{quote_plus(brand.upper())}"

        deals: List[dict[str, Any]] = []
        negative_set = [k.lower() for k in (negative_keywords or [])]

        html = await self._static_fetch(url)
        cards = []
        if html:
            soup = BeautifulSoup(html, "html.parser")
            cards = soup.select("div[data-id]")

        if not cards and not (os.getenv("CI") or os.getenv("GITHUB_ACTIONS") or os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME")):
            try:
                async with async_playwright() as p:
                    try:
                        browser = await p.chromium.launch(
                            channel="chrome",
                            headless=self.config.headless,
                            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                        )
                    except Exception:
                        browser = await p.chromium.launch(
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
                    await page.wait_for_timeout(2000)
                    html = await page.content()
                    await context.close()
                    await browser.close()

                    soup = BeautifulSoup(html, "html.parser")
                    cards = soup.select("div[data-id]")
            except Exception as pw_exc:
                logger.debug("[flipkart] Playwright search fallback error: %s", pw_exc)

        try:
            for card in cards:
                    # 0. Extract product_id (stable identifier)
                    product_id = card.get("data-id", "")

                    # 1. Extract link and title
                    link_el = None
                    title = ""
                    for a in card.find_all("a", href=True):
                        href = a["href"]
                        if "/p/" in href:
                            link_el = a
                            txt = a.get_text(" ", strip=True)
                            if txt and len(txt) > 3 and not re.search(r"^\d+% off", txt, re.I) and not txt.startswith("₹"):
                                title = txt
                    if not link_el:
                        continue

                    clean_url = "https://www.flipkart.com" + link_el["href"].split("?")[0]
                    if not title:
                        title = clean_url.split("/p/")[0].split("/")[-1].replace("-", " ").title()

                    title_lower = title.lower()
                    if any(neg in title_lower for neg in negative_set):
                        continue

                    # 2. Extract Explicit Brand from Flipkart card metadata
                    scraped_brand = None
                    # Strategy A: Flipkart renders brand in dedicated class spans
                    #   Common patterns: "syl9yP" class, or first short span in the card
                    for selector in ("span.syl9yP", "div._6sQKmB span", "div.NqpwHC span"):
                        brand_el = card.select_one(selector)
                        if brand_el:
                            btxt = brand_el.get_text(strip=True)
                            if btxt and len(btxt) < 40 and not btxt.startswith("₹") and not re.match(r"^\d", btxt):
                                scraped_brand = btxt
                                break

                    # Strategy B: First line of the product info that is short and
                    # appears before the full title (brand name row)
                    if not scraped_brand:
                        info_divs = card.select("a[href*='/p/'] div")
                        for div in info_divs:
                            txt = div.get_text(strip=True)
                            if txt and 2 < len(txt) < 35 and not txt.startswith("₹") and not re.match(r"^\d+%", txt):
                                # Check this isn't the full title
                                if txt != title and txt.lower() not in title_lower:
                                    scraped_brand = txt
                                    break

                    # Strict Brand Enforcement: Discard sponsored non-brand cards (e.g. Guess / Tommy Hilfiger on Casio pages)
                    if brand:
                        target_brand = brand.lower().strip()
                        card_text = card.get_text(" ", strip=True).lower()
                        brand_match = (
                            (scraped_brand and target_brand in scraped_brand.lower())
                            or target_brand in title_lower
                            or target_brand in card_text
                            or (
                                target_brand == "casio"
                                and any(
                                    k in title_lower or k in card_text
                                    for k in ["g-shock", "gshock", "edifice", "baby-g", "vintage"]
                                )
                            )
                        )
                        if not brand_match:
                            continue
                        if not scraped_brand:
                            scraped_brand = brand.title() if brand else None

                    # 3. Extract Price & MRP
                    prices = []
                    for el in card.find_all(True):
                        txt = el.get_text(" ", strip=True)
                        if "₹" in txt and len(txt) < 15:
                            val = self.clean_price(txt)
                            if val is not None and val > 0:
                                prices.append(val)

                    if not prices:
                        continue

                    selling_price = min(prices)
                    mrp_val = max(prices) if len(prices) > 1 else selling_price

                    if min_mrp is not None and mrp_val < min_mrp:
                        continue

                    # 4. Calculate discount
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
                        "platform": "flipkart",
                        "url": clean_url,
                        "in_stock": True,
                        "scraped_brand": scraped_brand,
                        "product_id": product_id,
                    })
        except Exception as exc:
            logger.warning("[flipkart] deal scan error for query '%s': %s", query, exc)

        return deals

    def _extract_color_from_soup(self, soup: BeautifulSoup) -> str:
        """Extract explicit color name from JSON-LD schema or Selected Color section."""
        for s in soup.find_all("script"):
            txt = s.string or s.get_text() or ""
            if "color" in txt and "schema.org" in txt:
                m = re.search(r'"color":\s*"([^"]+)"', txt)
                if m:
                    return m.group(1).strip()
        for node in soup.find_all(string=lambda t: t and "Selected Color" in t):
            parent = node.parent
            if parent:
                txt = parent.get_text(" ", strip=True)
                m = re.search(r"Selected Color:\s*([^\n<]+)", txt)
                if m:
                    return m.group(1).strip()
        return ""

    def _extract_mrp_from_soup(self, soup: BeautifulSoup) -> Optional[float]:
        """Extract MRP value from Flipkart DOM."""
        mrp_selectors = ("div.yRaY8j", "div._2p6XSc", "div._3I9_wc", "div._3auQ3N")
        for sel in mrp_selectors:
            node = soup.select_one(sel)
            if node:
                val = self.clean_price(node.get_text(" ", strip=True))
                if val is not None and val > 0:
                    return val
        return None

    def _extract_sizes_from_soup(self, soup: BeautifulSoup) -> List[dict[str, Any]]:
        """Extract all available size buttons and detect whether they are in stock or struck out."""
        sizes: List[dict[str, Any]] = []
        for a in soup.find_all("a", href=True):
            if "swatchAttr=size" in a["href"]:
                size_val = a.get_text(" ", strip=True)
                # Strike-through line or disabled overlay indicates sold out
                has_strike = any("height:1px" in str(d.get("style", "")) for d in a.find_all("div"))
                has_disabled = any("disabled" in str(c).lower() for c in a.get("class", []))
                in_stock = not (has_strike or has_disabled)
                href = a["href"]
                full_url = "https://www.flipkart.com" + href if href.startswith("/") else href
                sizes.append({
                    "size": size_val,
                    "in_stock": in_stock,
                    "url": full_url,
                })
        return sizes

    def _extract_color_swatches_from_soup(self, soup: BeautifulSoup, current_url: str = "") -> List[dict[str, Any]]:
        """Extract all color swatches from the Selected Color section and determine out-of-stock state."""
        swatches: List[dict[str, Any]] = []
        seen_pids = set()

        curr_pid_match = re.search(r"pid=([A-Z0-9]+)", current_url)
        curr_pid = curr_pid_match.group(1) if curr_pid_match else ""

        # Identify model keyword from current URL (e.g. 'literide-360' or 'literide')
        model_kw = ""
        if "literide-360" in current_url.lower():
            model_kw = "literide"
        elif "literide" in current_url.lower():
            model_kw = "literide"

        for node in soup.find_all(string=lambda t: t and "Selected Color" in t):
            p = node.parent
            # Find the closest parent that contains between 1 and 25 product links
            target_container = None
            curr = p
            for _ in range(3):
                if curr and curr.parent:
                    curr = curr.parent
                    p_links = [a for a in curr.find_all("a", href=True) if "/p/" in a["href"] and "swatchAttr=size" not in a["href"]]
                    if 0 < len(p_links) <= 25:
                        target_container = curr
                        break

            container = target_container or p
            for a in container.find_all("a", href=True):
                href = a["href"]
                if "/p/" in href and "swatchAttr=size" not in href:
                    if model_kw and model_kw not in href.lower():
                        continue

                    pid_m = re.search(r"pid=([A-Z0-9]+)", href)
                    pid = pid_m.group(1) if pid_m else ""
                    if pid and (pid == curr_pid or pid in seen_pids):
                        continue
                    if pid:
                        seen_pids.add(pid)

                    txt = a.get_text(" ", strip=True).lower()
                    is_oos = "out of stock" in txt
                    full_url = "https://www.flipkart.com" + href.split("&fm=")[0] if href.startswith("/") else href
                    swatches.append({
                        "url": full_url,
                        "pid": pid,
                        "is_oos": is_oos,
                    })
            if swatches:
                break
        return swatches

    async def check_product_variants(self, url: str) -> dict[str, Any]:
        """Inspect a multi-variant product across all colorways and sizes.

        Efficient: uses Scrapling static fetch (~1s). Only fetches secondary colorway
        pages if their swatch does not bear the 'Out of stock' badge.
        """
        html = await self._static_fetch(url)
        if not html:
            html = await self._js_fetch(url)

        if not html:
            return {
                "model_title": "",
                "in_stock": False,
                "lowest_price": None,
                "in_stock_variants": [],
                "total_colors_checked": 0,
            }

        soup = BeautifulSoup(html, "html.parser")
        model_title = self._extract_title(soup)

        # 1. Check current page
        current_sizes = self._extract_sizes_from_soup(soup)
        current_in_stock_sizes = [s["size"] for s in current_sizes if s["in_stock"]]
        current_price = self._extract_price(soup)
        current_mrp = self._extract_mrp_from_soup(soup) or current_price
        current_color = self._extract_color_from_soup(soup) or "Current Color"

        in_stock_variants: List[dict[str, Any]] = []

        page_in_stock = self._extract_stock(soup) and (len(current_in_stock_sizes) > 0 or not current_sizes)
        if page_in_stock and current_price is not None and current_price > 0:
            in_stock_variants.append({
                "color": current_color,
                "sizes": current_in_stock_sizes or ["Standard"],
                "price": current_price,
                "mrp": current_mrp or current_price,
                "url": url,
            })

        # 2. Check all color swatches
        swatch_links = self._extract_color_swatches_from_soup(soup, current_url=url)
        total_colors = 1 + len(swatch_links)

        for swatch in swatch_links:
            if swatch.get("is_oos", False):
                continue

            swatch_url = swatch["url"]
            s_html = await self._static_fetch(swatch_url)
            if not s_html:
                s_html = await self._js_fetch(swatch_url)
            if not s_html:
                continue

            s_soup = BeautifulSoup(s_html, "html.parser")
            s_color = self._extract_color_from_soup(s_soup) or f"Color ({swatch.get('pid', '')})"
            s_sizes = self._extract_sizes_from_soup(s_soup)
            s_in_stock_sizes = [s["size"] for s in s_sizes if s["in_stock"]]
            s_price = self._extract_price(s_soup)
            s_mrp = self._extract_mrp_from_soup(s_soup) or s_price

            s_in_stock = self._extract_stock(s_soup) and (len(s_in_stock_sizes) > 0 or not s_sizes)
            if s_in_stock and s_price is not None and s_price > 0:
                in_stock_variants.append({
                    "color": s_color,
                    "sizes": s_in_stock_sizes or ["Standard"],
                    "price": s_price,
                    "mrp": s_mrp or s_price,
                    "url": swatch_url,
                })

        lowest_price = min((v["price"] for v in in_stock_variants), default=None)

        return {
            "model_title": model_title,
            "in_stock": len(in_stock_variants) > 0,
            "lowest_price": lowest_price,
            "in_stock_variants": in_stock_variants,
            "total_colors_checked": total_colors,
        }