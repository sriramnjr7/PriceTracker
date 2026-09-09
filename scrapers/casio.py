"""Casio Store Bhawar (casiostore.bhawar.com) Scraper.

Handles both single product pages and collection-level discount scans
for G-Shock and Casio watches.
"""

from __future__ import annotations

import logging
import re
from typing import Any, List, Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from .base import BaseScraper, ScrapeResult

logger = logging.getLogger(__name__)


class CasioScraper(BaseScraper):
    platform: str = "casio"
    prefer_js: bool = False  # Shopify store with clean JSON & HTML endpoints

    title_selectors: tuple[str, ...] = (
        "h1.product__title",
        ".product-title h1",
        "h1",
        ".product__info-container h1",
    )
    price_selectors: tuple[str, ...] = (
        ".price-item--sale",
        ".price__regular .price-item--regular",
        ".price-item--regular",
        ".price .price-item",
        "span.price-item",
    )
    out_of_stock_keywords: tuple[str, ...] = (
        "sold out",
        "out of stock",
        "currently unavailable",
        "unavailable",
    )

    async def scrape(self, url: str) -> ScrapeResult:
        """Fetch and parse a Casio product or collection page."""
        parsed = urlparse(url)
        path = parsed.path.lower()

        # Handle collection URLs
        if "/collections/" in path and "/products/" not in path:
            return await self.scrape_collection(url)

        # Handle single product URLs
        return await self.scrape_product(url)

    async def scrape_product(self, url: str) -> ScrapeResult:
        """Scrape an individual product page or handle 404 gracefully."""
        # 1. Try fetching via HTTP
        headers = {
            "User-Agent": self._random_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
        }

        # Extract handle from URL for fallback naming & search
        handle_match = re.search(r"/products/([a-zA-Z0-9_-]+)", url)
        handle = handle_match.group(1) if handle_match else "casio-watch"
        fallback_title = handle.replace("-", " ").title()

        for attempt in range(self.config.retries):
            try:
                async with httpx.AsyncClient(
                    follow_redirects=True, timeout=self.config.request_timeout
                ) as client:
                    response = await client.get(url, headers=headers)

                final_path = urlparse(str(response.url)).path.lower()
                # If redirected to homepage or 404, product is not listed
                if response.status_code == 404 or "/products/" not in final_path:
                    # Check search suggest API in case slug changed
                    search_result = await self._search_suggest(handle)
                    if search_result:
                        return search_result

                    logger.info("[casio] Product %s is unlisted/redirected (%s)", handle, response.url)
                    return ScrapeResult(
                        title=fallback_title,
                        price=None,
                        in_stock=False,
                        platform=self.platform,
                        url=url,
                    )

                if response.status_code == 200:
                    result = self.parse(response.text, str(response.url))
                    if result.title or result.price:
                        return result

            except Exception as exc:
                logger.warning("[casio] fetch attempt %s failed: %s", attempt + 1, exc)
            await self._polite_delay(backoff=attempt + 1)

        # If all retries fail, return unlisted/unavailable state
        return ScrapeResult(
            title=fallback_title,
            price=None,
            in_stock=False,
            platform=self.platform,
            url=url,
        )

    async def _search_suggest(self, query: str) -> Optional[ScrapeResult]:
        """Query Shopify search suggestions for matching product with strict model validation."""
        search_query = query.replace("casio-", "").replace("-watch", "").replace("-", " ").strip()
        search_url = f"https://casiostore.bhawar.com/search/suggest.json?q={search_query}&resources[type]=product"

        # Extract specific watch series number (e.g. 300 from gbd-300, 2100 from ga-2100)
        series_nums = re.findall(r"\b\d{3,4}\b", query)
        model_prefixes = re.findall(r"[a-zA-Z]{2,4}[- ]?\d{3,4}", query)

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(search_url, headers={"User-Agent": self._random_user_agent()})
                if r.status_code == 200:
                    data = r.json()
                    products = data.get("resources", {}).get("results", {}).get("products", [])
                    for p in products:
                        p_title = p.get("title", "").lower()
                        p_url = p.get("url", "").split("?")[0].lower()
                        p_combined = f"{p_title} {p_url}"

                        # Strict model validation: Must match the series number (e.g. "300")
                        if series_nums:
                            if not all(num in p_combined for num in series_nums):
                                continue

                        # If full prefix pattern like "gbd-300" exists, ensure prefix matches
                        if model_prefixes:
                            clean_prefix = re.sub(r"[- ]", "", model_prefixes[0].lower())
                            clean_combined = re.sub(r"[- ]", "", p_combined)
                            if clean_prefix not in clean_combined:
                                continue

                        price = float(p.get("price", 0)) if p.get("price") else None
                        return ScrapeResult(
                            title=p.get("title", query),
                            price=price,
                            in_stock=p.get("available", True),
                            platform=self.platform,
                            url=f"https://casiostore.bhawar.com{p.get('url')}",
                        )
        except Exception as exc:
            logger.debug("[casio] search suggest error: %s", exc)
        return None


    async def scrape_collection(self, url: str) -> ScrapeResult:
        """Scrape collection page and find best available deal."""
        parsed = urlparse(url)
        match = re.search(r"/collections/([^/?]+)", parsed.path)
        collection_handle = match.group(1) if match else "casio"
        category_name = collection_handle.replace("-", " ").title()

        deals = await self.scan_collection_deals(collection_handle)
        if deals:
            best_deal = max(deals, key=lambda d: d.get("discount_percent", 0))
            return ScrapeResult(
                title=f"[Category: {category_name}] Best: {best_deal['title']} ({best_deal['discount_percent']:.0f}% OFF)",
                price=best_deal["price"],
                in_stock=True,
                platform=self.platform,
                url=best_deal["url"],
            )

        return ScrapeResult(
            title=f"[Category: {category_name}] (0 active deals currently)",
            price=None,
            in_stock=False,
            platform=self.platform,
            url=url,
        )

    async def scan_collection_deals(
        self, collection_handle: str = "g-shock", min_discount: float = 0.0
    ) -> List[dict[str, Any]]:
        """Fetch all products in a collection via filter tags and paginated JSON."""
        deals_map: dict[str, dict[str, Any]] = {}
        int_disc = int(min_discount)

        headers = {"User-Agent": self._random_user_agent()}

        # 1. Method A: Check Shopify Metafield Filter Tags (90%, 80%, 70%, 60%, 50%, 40%, 30%)
        # Check higher tiers first so items get matched to their highest valid discount
        filter_urls = []
        for d_tier in range(90, int_disc - 10, -10):
            if d_tier >= int_disc:
                filter_urls.append(
                    (d_tier, f"https://casiostore.bhawar.com/collections/{collection_handle}?filter.p.m.cobrsw.meta_92={d_tier}%25+Off+Or+More")
                )

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                for d_tier, f_url in filter_urls:
                    try:
                        r = await client.get(f_url, headers=headers)
                        if r.status_code == 200:
                            soup = BeautifulSoup(r.text, "html.parser")
                            cards = soup.select("ul#product-grid li.grid__item, .card-wrapper")
                            for card in cards:
                                # Find product title and link
                                model_link = None
                                model_name = None
                                for a in card.find_all("a", href=True):
                                    href = a["href"]
                                    txt = a.get_text(" ", strip=True)
                                    if "/products/" in href:
                                        if not model_link:
                                            model_link = f"https://casiostore.bhawar.com{href}" if href.startswith("/") else href
                                        if txt and len(txt) > 2 and "wishlist" not in txt.lower():
                                            model_name = txt
                                if not model_link:
                                    continue

                                clean_link = model_link.split("?")[0]
                                if clean_link in deals_map:
                                    continue

                                price_el = card.select_one(".price-item--sale, .price__regular .price-item--regular, .price-item")
                                raw_mrp = 0.0
                                if price_el:
                                    price_text = re.sub(r"[^\d.]", "", price_el.get_text(strip=True))
                                    if price_text:
                                        try:
                                            raw_mrp = float(price_text)
                                        except ValueError:
                                            pass

                                # Compute actual discounted deal price
                                if raw_mrp > 0:
                                    actual_deal_price = round(raw_mrp * (1.0 - float(d_tier) / 100.0), 2)
                                else:
                                    actual_deal_price = 0.0

                                deals_map[clean_link] = {
                                    "title": f"[{collection_handle.title()}] " + (model_name or clean_link.split("/products/")[-1].replace("-", " ").title()),
                                    "price": actual_deal_price,
                                    "mrp": raw_mrp,
                                    "discount_percent": float(d_tier),
                                    "in_stock": True,
                                    "url": clean_link,
                                }
                    except Exception as exc:
                        logger.debug("[casio] filter tag scan %s error: %s", f_url, exc)
        except Exception as exc:
            logger.debug("[casio] filter tag client error: %s", exc)

        # 2. Method B: Paginated JSON scanning for mathematical compare_at discounts
        page = 1
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                while page <= 5:  # Scan up to 5 pages (1,250 items)
                    json_url = f"https://casiostore.bhawar.com/collections/{collection_handle}/products.json?limit=250&page={page}"
                    r = await client.get(json_url, headers=headers)
                    if r.status_code != 200:
                        break
                    data = r.json()
                    products = data.get("products", [])
                    if not products:
                        break

                    for p in products:
                        title = p.get("title", "")
                        handle = p.get("handle", "")
                        product_url = f"https://casiostore.bhawar.com/products/{handle}"
                        for v in p.get("variants", []):
                            price = float(v.get("price", 0))
                            compare_at = float(v.get("compare_at_price") or price)
                            available = bool(v.get("available", False))
                            discount = (
                                ((compare_at - price) / compare_at * 100.0)
                                if compare_at > price and compare_at > 0
                                else 0.0
                            )

                            if available and discount >= min_discount:
                                deals_map[product_url] = {
                                    "title": f"[{collection_handle.title()}] {title}",
                                    "price": price,
                                    "mrp": compare_at,
                                    "discount_percent": discount,
                                    "in_stock": available,
                                    "url": product_url,
                                }
                    page += 1
        except Exception as exc:
            logger.warning("[casio] collection JSON scan failed: %s", exc)

        return list(deals_map.values())

    def _extract_stock(self, soup: BeautifulSoup) -> bool:
        """Check for Add to Cart or Sold Out button."""
        for button in soup.find_all(["button", "input", "span"]):
            text = button.get_text(" ", strip=True).lower()
            if any(kw in text for kw in self.out_of_stock_keywords):
                return False
            if "add to cart" in text or "buy now" in text:
                return True
        return super()._extract_stock(soup)
