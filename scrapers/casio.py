"""Casio Store Bhawar (casiostore.bhawar.com) Scraper.

Handles both single product pages and collection-level discount scans
for G-Shock and Casio watches.
"""

from __future__ import annotations

import asyncio
import logging
import os
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
        ".price--on-sale .price-item--sale",
        ".price--silent-off .price-item--sale",
        ".price--on-sale .price-item--last",
        ".price__sale .price-item--sale",
        ".price__sale .price-item--last",
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

    def _extract_price(self, soup: BeautifulSoup) -> Optional[float]:
        """Extract selling price, prioritizing member silent sale discounts."""
        for selector in self.price_selectors:
            for node in soup.select(selector):
                val = self.clean_price(node.get_text(" ", strip=True))
                if val is not None and val > 0:
                    return val
        return super()._extract_price(soup)

    _auth_client: Optional[httpx.AsyncClient] = None

    async def _get_authenticated_client(self) -> httpx.AsyncClient:
        """Maintain a persistent authenticated customer session on casiostore.bhawar.com to unlock member discounts."""
        if self._auth_client is not None and not self._auth_client.is_closed:
            return self._auth_client

        import os
        email = getattr(self.config, "casio_bhawar_email", "") or os.getenv("CASIO_BHAWAR_EMAIL", "")
        password = getattr(self.config, "casio_bhawar_password", "") or os.getenv("CASIO_BHAWAR_PASSWORD", "")

        headers = {
            "User-Agent": self._random_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
        }
        client = httpx.AsyncClient(
            follow_redirects=True, timeout=self.config.request_timeout, headers=headers
        )

        if email and password:
            try:
                r_login = await client.get("https://casiostore.bhawar.com/account/login")
                post_data = {
                    "form_type": "customer_login",
                    "utf8": "✓",
                    "customer[email]": email,
                    "customer[password]": password,
                }
                soup = BeautifulSoup(r_login.text, "html.parser")
                form = soup.select_one("form[action*='/account/login']")
                if form:
                    for hidden in form.select("input[type='hidden']"):
                        name = hidden.get("name")
                        val = hidden.get("value", "")
                        if name:
                            post_data[name] = val

                r_post = await client.post("https://casiostore.bhawar.com/account/login", data=post_data)
                if "/account" in str(r_post.url) or "logout" in r_post.text.lower():
                    logger.info("[casio] Persistent member session active for %s", email)
                else:
                    logger.warning("[casio] Member login returned status %s (%s)", r_post.status_code, r_post.url)
            except Exception as exc:
                logger.warning("[casio] Member authentication error: %s", exc)

        self._auth_client = client
        return self._auth_client

    async def close(self) -> None:
        """Close authenticated client if open."""
        if self._auth_client and not self._auth_client.is_closed:
            await self._auth_client.aclose()
            self._auth_client = None

    async def _safe_get(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: Optional[dict[str, str]] = None,
        max_retries: int = 3,
    ) -> Optional[httpx.Response]:
        """Safely fetch a URL with automatic HTTP 429 rate limit backoff and retry handling."""
        import random
        for attempt in range(max_retries):
            try:
                r = await client.get(url, headers=headers)
                if r.status_code == 429:
                    retry_after = int(r.headers.get("Retry-After", "5"))
                    logger.warning(
                        "[casio] 429 Too Many Requests on %s. Backing off %ds (attempt %d/%d)...",
                        url,
                        retry_after,
                        attempt + 1,
                        max_retries,
                    )
                    await asyncio.sleep(retry_after + random.uniform(0.5, 1.5))
                    continue
                return r
            except Exception as exc:
                logger.debug("[casio] request error on %s: %s", url, exc)
                await asyncio.sleep(1.0)
        return None

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
        """Scrape an individual product page using authenticated session for member pricing."""
        handle_match = re.search(r"/products/([a-zA-Z0-9_-]+)", url)
        handle = handle_match.group(1) if handle_match else "casio-watch"
        fallback_title = handle.replace("-", " ").title()

        client = await self._get_authenticated_client()

        for attempt in range(self.config.retries):
            try:
                response = await client.get(url)

                final_path = urlparse(str(response.url)).path.lower()
                # If redirected to homepage or 404, product is not listed / out of stock
                if response.status_code == 404 or "/products/" not in final_path:
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
                        fam, formatted_title = self._classify_casio_watch(result.title or fallback_title, handle=handle)
                        result.title = formatted_title

                        # Authoritative stock verification via Shopify's .js endpoint
                        if result.in_stock and handle:
                            try:
                                js_url = f"https://casiostore.bhawar.com/products/{handle}.js"
                                r_js = await client.get(js_url)
                                if r_js.status_code == 200:
                                    js_data = r_js.json()
                                    is_avail = bool(js_data.get("available", False))
                                    has_avail_variant = any(
                                        bool(v.get("available", False))
                                        for v in js_data.get("variants", [])
                                    )
                                    if not is_avail and not has_avail_variant:
                                        logger.info(
                                            "[casio] Shopify .js reports %s is sold out; overriding in_stock=False",
                                            handle,
                                        )
                                        result.in_stock = False
                            except Exception as js_err:
                                logger.debug("[casio] Shopify .js check error for %s: %s", handle, js_err)

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

    def _classify_casio_watch(
        self, raw_title: str, tags: Optional[List[str]] = None, handle: str = ""
    ) -> tuple[str, str]:
        """Classify a Casio model into its family and generate a normalized brand title."""
        tags = [t.lower() for t in (tags or [])]
        clean_title = raw_title.strip()
        upper_title = clean_title.upper()
        handle_upper = handle.upper()

        # G-Shock patterns (model code prefixes & tags)
        gshock_prefixes = (
            "DW-", "GA-", "GMA-", "GD-", "GBD-", "GBX-", "GM-", "GMD-", "GMW-",
            "GW-", "GWG-", "GST-", "MTG-", "MRG-", "GG-", "GR-", "GLX-", "GCW-",
            "DW", "GA", "GD", "GMA", "GBD", "GM", "GW"
        )
        is_gshock = (
            any(upper_title.startswith(p) for p in gshock_prefixes)
            or any(k in upper_title for k in ["G-SHOCK", "GSHOCK", "BABY-G"])
            or any(k in tags for k in ["g-shock", "gshock", "resin", "master of g", "g-steel", "g-squad"])
            or any(handle_upper.startswith(p) for p in gshock_prefixes)
            or "g-shock" in handle.lower()
        )

        # Edifice patterns
        edifice_prefixes = (
            "EF-", "EFR-", "EFB-", "EFV-", "ECB-", "EQB-", "EQS-", "EFS-", "ERA-", "EMA-",
            "EF", "EFR", "EFB", "EFV", "ECB", "EQB", "EQS"
        )
        is_edifice = (
            any(upper_title.startswith(p) for p in edifice_prefixes)
            or "EDIFICE" in upper_title
            or any(k in tags for k in ["edifice", "10_motorsports"])
            or any(handle_upper.startswith(p) for p in edifice_prefixes)
            or "edifice" in handle.lower()
        )

        # Vintage patterns
        vintage_prefixes = ("A1", "A158", "A168", "A1000", "A700", "AQ-", "B6", "DBC-", "CA-")
        is_vintage = (
            any(upper_title.startswith(p) for p in vintage_prefixes)
            or "VINTAGE" in upper_title
            or any(k in tags for k in ["vintage", "a-1000"])
            or "vintage" in handle.lower()
        )

        if is_gshock:
            family = "G-Shock"
            if not re.search(r"\bg[- ]?shock\b", clean_title, re.I):
                formatted_title = f"Casio G-Shock {clean_title}"
            elif not clean_title.lower().startswith("casio"):
                formatted_title = f"Casio {clean_title}"
            else:
                formatted_title = clean_title
        elif is_edifice:
            family = "Edifice"
            if "edifice" not in clean_title.lower():
                formatted_title = f"Casio Edifice {clean_title}"
            elif not clean_title.lower().startswith("casio"):
                formatted_title = f"Casio {clean_title}"
            else:
                formatted_title = clean_title
        elif is_vintage:
            family = "Vintage"
            if not clean_title.lower().startswith("casio"):
                formatted_title = f"Casio Vintage {clean_title}"
            else:
                formatted_title = clean_title
        else:
            family = "Casio"
            if not clean_title.lower().startswith("casio"):
                formatted_title = f"Casio {clean_title}"
            else:
                formatted_title = clean_title

        return family, formatted_title

    async def scan_catalog_deals(self, min_discount: float = 0.0) -> List[dict[str, Any]]:
        """Sweep all pages of the Bhawar catalog plus silent-sale/promotional collections."""
        deals_map: dict[str, dict[str, Any]] = {}
        headers = {"User-Agent": self._random_user_agent()}

        async with httpx.AsyncClient(timeout=20) as client:
            # 1. Sweep dedicated discount and clearance hubs first
            auth_client = await self._get_authenticated_client()
            sem = asyncio.Semaphore(5)

            # Dedicated silent-sale hubs where discounts require customer session verification
            silent_hubs = ["silent-sale", "silent-sale-products", "corporate-discount"]
            
            async def _verify_silent_prod(p):
                handle = p.get("handle", "")
                product_url = f"https://casiostore.bhawar.com/products/{handle}"
                if product_url in deals_map:
                    return None
                tags = p.get("tags", [])
                fam, title = self._classify_casio_watch(p.get("title", ""), tags, handle)
                for v in p.get("variants", []):
                    if not bool(v.get("available", False)):
                        continue
                    price = float(v.get("price", 0))
                    compare_at = float(v.get("compare_at_price") or price)
                    # If variant JSON already has explicit discount
                    if compare_at > price:
                        disc = round(((compare_at - price) / compare_at * 100.0), 1)
                        if disc >= min_discount:
                            return {
                                "title": title,
                                "price": price,
                                "mrp": compare_at,
                                "discount_percent": disc,
                                "in_stock": True,
                                "url": product_url,
                                "family": fam,
                                "is_silent_sale": False,
                            }

                    # Otherwise verify against authenticated storefront for silent sale pricing
                    async with sem:
                        try:
                            resp = await auth_client.get(product_url)
                            soup = BeautifulSoup(resp.text, "html.parser")
                            sale_el = soup.select_one(
                                ".price--on-sale .price-item--sale, .price--silent-off .price-item--sale, .price__sale .price-item--sale, .price-item--sale"
                            )
                            reg_el = soup.select_one(
                                ".price__sale .price-item--regular, .price__regular .price-item--regular, s.price-item, .price-item--regular"
                            )
                            sale_p = self.clean_price(sale_el.get_text()) if sale_el else None
                            reg_p = self.clean_price(reg_el.get_text()) if reg_el else None
                            if sale_p and reg_p and reg_p > sale_p:
                                d = round(((reg_p - sale_p) / reg_p * 100.0), 1)
                                if d >= min_discount:
                                    return {
                                        "title": title,
                                        "price": sale_p,
                                        "mrp": reg_p,
                                        "discount_percent": d,
                                        "in_stock": True,
                                        "url": product_url,
                                        "family": fam,
                                        "is_silent_sale": True,
                                    }
                        except Exception as exc:
                            logger.debug("[casio] silent verify error for %s: %s", product_url, exc)
                return None

            for hub in silent_hubs:
                try:
                    r = await self._safe_get(
                        client,
                        f"https://casiostore.bhawar.com/collections/{hub}/products.json?limit=250",
                        headers=headers,
                    )
                    if r and r.status_code == 200:
                        prods = r.json().get("products", [])
                        verified_deals = await asyncio.gather(*(_verify_silent_prod(p) for p in prods))
                        for vd in verified_deals:
                            if vd and vd["url"] not in deals_map:
                                deals_map[vd["url"]] = vd
                except Exception as exc:
                    logger.debug("[casio] silent hub %s error: %s", hub, exc)

            # 2. Sweep other promotional collections with standard JSON variant discounts and silent-sale tags
            promo_hubs = ["sale-products", "promotional-watches", "casio"]
            for hub in promo_hubs:
                try:
                    r = await self._safe_get(
                        client,
                        f"https://casiostore.bhawar.com/collections/{hub}/products.json?limit=250",
                        headers=headers,
                    )
                    if r and r.status_code == 200:
                        prods = r.json().get("products", [])
                        silent_candidates = []
                        for p in prods:
                            handle = p.get("handle", "")
                            product_url = f"https://casiostore.bhawar.com/products/{handle}"
                            if product_url in deals_map:
                                continue
                            tags = p.get("tags", [])
                            # If tagged for silent sale, queue for storefront check
                            if any("silent" in str(t).lower() for t in tags):
                                silent_candidates.append(p)
                                continue

                            fam, title = self._classify_casio_watch(p.get("title", ""), tags, handle)
                            for v in p.get("variants", []):
                                if not bool(v.get("available", False)):
                                    continue
                                price = float(v.get("price", 0))
                                compare_at = float(v.get("compare_at_price") or price)
                                if compare_at > price:
                                    disc = round(((compare_at - price) / compare_at * 100.0), 1)
                                    if disc >= min_discount:
                                        deals_map[product_url] = {
                                            "title": title,
                                            "price": price,
                                            "mrp": compare_at,
                                            "discount_percent": disc,
                                            "in_stock": True,
                                            "url": product_url,
                                            "family": fam,
                                            "is_silent_sale": False,
                                        }
                        if silent_candidates:
                            v_deals = await asyncio.gather(*(_verify_silent_prod(p) for p in silent_candidates))
                            for vd in v_deals:
                                if vd and vd["url"] not in deals_map:
                                    deals_map[vd["url"]] = vd
                except Exception as exc:
                    logger.debug("[casio] promo hub %s error: %s", hub, exc)

            # 3. Sweep master catalog across all pages for genuine variant discounts
            page = 1
            max_pages = 2 if (os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME")) else 8
            while page <= max_pages:
                try:
                    r = await self._safe_get(
                        client,
                        f"https://casiostore.bhawar.com/collections/all/products.json?limit=250&page={page}",
                        headers=headers,
                    )
                    if not r or r.status_code != 200:
                        break
                    prods = r.json().get("products", [])
                    if not prods:
                        break
                    silent_candidates = []
                    for p in prods:
                        handle = p.get("handle", "")
                        product_url = f"https://casiostore.bhawar.com/products/{handle}"
                        if product_url in deals_map:
                            continue
                        tags = p.get("tags", [])
                        if any("silent" in str(t).lower() for t in tags):
                            silent_candidates.append(p)
                            continue

                        family, formatted_title = self._classify_casio_watch(
                            p.get("title", ""), tags, handle
                        )
                        for v in p.get("variants", []):
                            price = float(v.get("price", 0))
                            compare_at = float(v.get("compare_at_price") or price)
                            available = bool(v.get("available", False))
                            if not available:
                                continue
                            disc = (
                                round(((compare_at - price) / compare_at * 100.0), 1)
                                if compare_at > price
                                else 0.0
                            )
                            if disc >= min_discount and disc > 0:
                                deals_map[product_url] = {
                                    "title": formatted_title,
                                    "price": price,
                                    "mrp": compare_at,
                                    "discount_percent": disc,
                                    "in_stock": available,
                                    "url": product_url,
                                    "family": family,
                                    "is_silent_sale": False,
                                }
                    if silent_candidates:
                        v_deals = await asyncio.gather(*(_verify_silent_prod(p) for p in silent_candidates))
                        for vd in v_deals:
                            if vd and vd["url"] not in deals_map:
                                deals_map[vd["url"]] = vd
                    page += 1
                except Exception as exc:
                    logger.debug("[casio] master catalog page %s scan error: %s", page, exc)
                    break

        return list(deals_map.values())

    async def scan_collection_deals(
        self, collection_handle: str = "g-shock", min_discount: float = 0.0
    ) -> List[dict[str, Any]]:
        """Fetch all products in a collection via paginated JSON with automatic 429 backoff."""
        # If user asks for master catalog or broad casio collections, use catalog sweep
        if collection_handle.lower() in ("all", "master", "catalog", "casio-all-watches", "casio"):
            return await self.scan_catalog_deals(min_discount=min_discount)

        deals_map: dict[str, dict[str, Any]] = {}
        headers = {
            "User-Agent": self._random_user_agent(),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-IN,en;q=0.9",
        }

        # Scan collection via official Shopify products.json endpoint (limit=250 covers entire collection in 1 request)
        page = 1
        max_pages = 4
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                while page <= max_pages:
                    json_url = f"https://casiostore.bhawar.com/collections/{collection_handle}/products.json?limit=250&page={page}"

                    # Fetch with automatic 429 backoff
                    r = await self._safe_get(client, json_url, headers=headers)

                    if not r or r.status_code != 200:
                        break

                    data = r.json()
                    products = data.get("products", [])
                    if not products:
                        break

                    silent_candidates = []
                    for p in products:
                        title = p.get("title", "")
                        handle = p.get("handle", "")
                        tags = p.get("tags", [])
                        product_url = f"https://casiostore.bhawar.com/products/{handle}"
                        if product_url in deals_map:
                            continue
                        if any("silent" in str(t).lower() for t in tags):
                            silent_candidates.append(p)
                            continue
                        family, formatted_title = self._classify_casio_watch(title, tags, handle)
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
                                    "title": formatted_title,
                                    "price": price,
                                    "mrp": compare_at,
                                    "discount_percent": discount,
                                    "in_stock": available,
                                    "url": product_url,
                                    "family": family,
                                }

                    if silent_candidates:
                        auth_client = await self._get_authenticated_client()
                        sem = asyncio.Semaphore(2)

                        async def _verify_cand(cand):
                            h = cand.get("handle", "")
                            p_url = f"https://casiostore.bhawar.com/products/{h}"
                            f_fam, f_title = self._classify_casio_watch(
                                cand.get("title", ""), cand.get("tags", []), h
                            )
                            async with sem:
                                try:
                                    await asyncio.sleep(0.3)
                                    r_prod = await auth_client.get(p_url)
                                    if r_prod.status_code == 200:
                                        s_prod = BeautifulSoup(r_prod.text, "html.parser")
                                        # Strict stock check: If the item is sold out, skip immediately
                                        if not self._extract_stock(s_prod):
                                            return None
                                        s_el = s_prod.select_one(
                                            ".price--on-sale .price-item--sale, .price--silent-off .price-item--sale, .price__sale .price-item--sale, .price-item--sale"
                                        )
                                        r_el = s_prod.select_one(
                                            ".price__sale .price-item--regular, .price__regular .price-item--regular, s.price-item, .price-item--regular"
                                        )
                                        s_price = self.clean_price(s_el.get_text()) if s_el else None
                                        r_price = self.clean_price(r_el.get_text()) if r_el else None
                                        if s_price and r_price and r_price > s_price:
                                            disc_val = round(((r_price - s_price) / r_price * 100.0), 1)
                                            if disc_val >= min_discount:
                                                return {
                                                    "title": f_title,
                                                    "price": s_price,
                                                    "mrp": r_price,
                                                    "discount_percent": disc_val,
                                                    "in_stock": True,
                                                    "url": p_url,
                                                    "family": f_fam,
                                                    "is_silent_sale": True,
                                                }
                                except Exception as exc:
                                    logger.debug("[casio] silent verify error for %s: %s", p_url, exc)
                            return None

                        v_deals = await asyncio.gather(*(_verify_cand(c) for c in silent_candidates))
                        for vd in v_deals:
                            if vd and vd["url"] not in deals_map:
                                deals_map[vd["url"]] = vd

                    page += 1
                    if len(products) >= 250:
                        await asyncio.sleep(random.uniform(0.8, 1.5))
        except Exception as exc:
            logger.warning("[casio] collection JSON scan failed: %s", exc)

        return list(deals_map.values())

    def _extract_stock(self, soup: BeautifulSoup) -> bool:
        """Check for Add to Cart or Sold Out button with high precision."""
        # 1. First priority: Target the canonical Shopify Product Form submit button
        add_btn = soup.select_one(
            'button[name="add"], .product-form__submit, button[id*="ProductSubmitButton"], button.product__submit__add, button[data-main-add-to-cart-btn], .sticky-add-btn'
        )
        if add_btn:
            is_disabled = add_btn.has_attr("disabled") or "disabled" in add_btn.get("class", [])
            btn_text = add_btn.get_text(" ", strip=True).lower()
            if is_disabled or any(kw in btn_text for kw in self.out_of_stock_keywords):
                return False
            if "add to cart" in btn_text or "buy now" in btn_text:
                return True

        # 2. Check for explicit out-of-stock badges / messages inside product info container
        prod_container = soup.select_one(".product__info-container, .product-single, .product")
        if prod_container:
            c_text = prod_container.get_text(" ", strip=True).lower()
            if any(kw in c_text for kw in self.out_of_stock_keywords):
                return False

        # 3. Fallback to scanning buttons only (not arbitrary span/input tags)
        for button in soup.find_all("button"):
            text = button.get_text(" ", strip=True).lower()
            if any(kw in text for kw in self.out_of_stock_keywords):
                return False
            if "add to cart" in text or "buy now" in text:
                return True

        return super()._extract_stock(soup)
