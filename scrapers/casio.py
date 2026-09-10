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
                # If redirected to homepage or 404, product is not listed
                if response.status_code == 404 or "/products/" not in final_path:
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
                        fam, formatted_title = self._classify_casio_watch(result.title or fallback_title, handle=handle)
                        result.title = formatted_title
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
                                ".price-item--sale, .price--on-sale .price-item, .price__sale .price-item, .price--silent-off .price-item"
                            )
                            reg_el = soup.select_one(
                                ".price-item--regular, .price__regular .price-item, .price-item--last"
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
                    r = await client.get(
                        f"https://casiostore.bhawar.com/collections/{hub}/products.json?limit=250",
                        headers=headers,
                    )
                    if r.status_code == 200:
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
                    r = await client.get(
                        f"https://casiostore.bhawar.com/collections/{hub}/products.json?limit=250",
                        headers=headers,
                    )
                    if r.status_code == 200:
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
                    r = await client.get(
                        f"https://casiostore.bhawar.com/collections/all/products.json?limit=250&page={page}",
                        headers=headers,
                    )
                    if r.status_code != 200:
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
        """Fetch all products in a collection via filter tags, catalog sweep, or paginated JSON."""
        # If user asks for master catalog or broad casio collections, use catalog sweep
        if collection_handle.lower() in ("all", "master", "catalog", "casio-all-watches", "casio"):
            return await self.scan_catalog_deals(min_discount=min_discount)

        deals_map: dict[str, dict[str, Any]] = {}
        int_disc = int(min_discount)

        headers = {"User-Agent": self._random_user_agent()}

        # 1. Method A: Check Shopify Metafield Filter Tags (90%, 80%, 70%, 60%, 50%, 40%, 30%)
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

                                actual_deal_price = round(raw_mrp * (1.0 - float(d_tier) / 100.0), 2) if raw_mrp > 0 else 0.0

                                raw_title = model_name or clean_link.split("/products/")[-1].replace("-", " ").title()
                                family, formatted_title = self._classify_casio_watch(raw_title, handle=clean_link.split("/")[-1])

                                deals_map[clean_link] = {
                                    "title": formatted_title,
                                    "price": actual_deal_price,
                                    "mrp": raw_mrp,
                                    "discount_percent": float(d_tier),
                                    "in_stock": True,
                                    "url": clean_link,
                                    "family": family,
                                }
                    except Exception as exc:
                        logger.debug("[casio] filter tag scan %s error: %s", f_url, exc)
        except Exception as exc:
            logger.debug("[casio] filter tag client error: %s", exc)

        # 2. Method B: Paginated JSON scanning for mathematical compare_at discounts
        page = 1
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                while page <= 5:
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
                        tags = p.get("tags", [])
                        product_url = f"https://casiostore.bhawar.com/products/{handle}"
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
