"""Shared scraping machinery.

``BaseScraper`` implements the common retry/delay/fallback dance and a few
DOM-agnostic helpers.  Each platform sub-class only has to declare:

* ``platform``            - slug used in the DB.
* ``prefer_js``           - whether the site needs a real browser first.
* ``title_selectors``     - ordered CSS selectors for the product title.
* ``price_selectors``     - ordered CSS selectors for the selling price.
* ``out_of_stock_keywords`` - substrings that mark a product as sold out.

Two fetch strategies are provided:

* ``_static_fetch`` - plain ``httpx`` GET with rotated user agents. Fast and
  light, but Myntra/Ajio render prices with JavaScript so this returns no
  price for those sites.
* ``_js_fetch``     - headless Chromium via Playwright (optionally hardened
  with ``playwright-stealth``), waits for the price element, then dumps DOM.

``scrape()`` runs the preferred strategy first and transparently falls back to
the other one if no usable price/title could be extracted.  A random 2-5s
delay between attempts keeps us under the sites' rate limits.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from abc import ABC
from dataclasses import dataclass
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from config import settings

logger = logging.getLogger(__name__)


class ScrapeError(Exception):
    """Raised when a product page cannot be parsed after all retries."""


@dataclass
class ScrapeResult:
    """Normalised result of a successful scrape."""

    title: str
    price: Optional[float]
    in_stock: bool
    platform: str
    url: str


def _priceish_class(value) -> bool:
    """bs4 helper: match elements whose class attribute mentions 'price'."""
    classes = value if isinstance(value, list) else ([value] if value else [])
    return any("price" in str(cls).lower() for cls in classes)


class BaseScraper(ABC):
    platform: str = "base"
    prefer_js: bool = False
    title_selectors: tuple[str, ...] = ()
    price_selectors: tuple[str, ...] = ()
    out_of_stock_keywords: tuple[str, ...] = (
        "out of stock",
        "sold out",
        "currently unavailable",
        "not available",
    )

    def __init__(self, config=settings) -> None:
        self.config = config

    # ------------------------------------------------------------- public API
    async def scrape(self, url: str) -> ScrapeResult:
        """Fetch a product page and return a normalised result.

        Tries the preferred strategy first, then falls back to the other.
        Raises :class:`ScrapeError` when both strategies fail.
        """
        order = ("static", "js") if not self.prefer_js else ("js", "static")
        errors: list[str] = []
        for strategy in order:
            html = await (self._js_fetch(url) if strategy == "js" else self._static_fetch(url))
            if html is None:
                errors.append(f"{strategy}: no response")
                continue
            try:
                result = self.parse(html, url)
            except Exception as exc:  # a malformed page should never kill the loop
                errors.append(f"{strategy}: {exc}")
                continue
            if result.price is not None and result.title:
                logger.info(
                    "[%s] %s -> INR %s (%s)",
                    self.platform,
                    result.title[:60],
                    result.price,
                    "in stock" if result.in_stock else "out of stock",
                )
                return result
            if result.title and (result.in_stock is False or result.price is None):
                logger.info(
                    "[%s] %s -> Out of stock / unlisted price",
                    self.platform,
                    result.title[:60],
                )
                return result
            errors.append(f"{strategy}: price/title missing")
        raise ScrapeError(
            f"{self.platform}: could not extract product info for {url} ({'; '.join(errors)})"
        )

    # ---------------------------------------------------------------- parsing
    def parse(self, html: str, url: str) -> ScrapeResult:
        soup = BeautifulSoup(html, "html.parser")
        return ScrapeResult(
            title=self._extract_title(soup),
            price=self._extract_price(soup),
            in_stock=self._extract_stock(soup),
            platform=self.platform,
            url=url,
        )

    def _extract_title(self, soup: BeautifulSoup) -> str:
        for selector in self.title_selectors:
            node = soup.select_one(selector)
            if node:
                text = node.get_text(" ", strip=True)
                if text:
                    return text

        # Schema.org Product JSON-LD name
        for script in soup.find_all("script"):
            stype = script.get("type", "")
            if "ld+json" in stype or "json" in stype:
                txt = script.string or script.get_text()
                if not txt or "name" not in txt:
                    continue
                try:
                    data = json.loads(txt)
                    if isinstance(data, list) and data:
                        data = data[0]
                    if isinstance(data, dict) and data.get("@type") == "Product" and data.get("name"):
                        return str(data["name"]).strip()
                except Exception:
                    pass

        # Generic fallback: the OpenGraph title meta tag.
        meta = soup.find("meta", attrs={"property": "og:title"})
        if meta:
            content = (meta.get("content") or "").strip()
            if content:
                return content

        # Page <title> tag
        title_tag = soup.find("title")
        if title_tag:
            text = title_tag.get_text(" ", strip=True)
            if text:
                return text

        return ""

    def _extract_price(self, soup: BeautifulSoup) -> Optional[float]:
        """Extract selling price using Schema.org JSON-LD, platform selectors, and clean fallbacks."""
        # 1. Authoritative: Schema.org Product JSON-LD (supports Amazon, Myntra, Ajio, BigBasket, Casio, etc.)
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

        # 2. Platform CSS Selectors
        for selector in self.price_selectors:
            for node in soup.select(selector):
                value = self.clean_price(node.get_text(" ", strip=True))
                if value is not None and value > 0:
                    return value

        # 3. Last-resort: any element whose class mentions 'price'
        for node in soup.find_all(attrs={"class": _priceish_class}):
            if node.name in ("script", "style"):
                continue
            value = self.clean_price(node.get_text(" ", strip=True))
            if value is not None and value > 0:
                return value
        return None

    def _extract_stock(self, soup: BeautifulSoup) -> bool:
        """Default stock check: scan the whole body for 'out of stock' markers."""
        body = soup.get_text(" ", strip=True).lower()
        return not any(keyword in body for keyword in self.out_of_stock_keywords)

    @staticmethod
    def clean_price(text: Optional[str]) -> Optional[float]:
        """Turn display text like 'Rs. 1,29,999.00' or 'Price: ₹1,049' into 1049.0."""
        if not text:
            return None
        text = str(text).replace("\u00a0", " ").strip()
        lower = text.lower()

        # Reject discount badges, cashback, coupons, fee additions, and EMI phrases
        if any(bad in lower for bad in (" off", "/m", "per month", "cashback", "save ", "save₹", "coupon", "fee", "protect", "unlock")):
            return None

        # 1. Prefer explicit currency prefixed number
        m = re.search(r"(?:₹|Rs\.?|INR)\s*([0-9][0-9,]*(?:\.[0-9]+)?)", text, re.I)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                pass
        # 2. Strict fallback: ONLY standalone numeric strings (e.g. "3560" or "3560.00")
        # Prevents pulling model numbers like "360" or "10" from sentences/titles
        if len(text) < 15 and re.match(r"^\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*$", text):
            try:
                return float(text.replace(",", ""))
            except ValueError:
                pass
        return None

    # ------------------------------------------------------------ static fetch
    async def _static_fetch(self, url: str) -> Optional[str]:
        """Fetch static page with Scrapling (TLS impersonation) or httpx fallback."""
        import os
        is_serverless = bool(os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"))
        retries = 2 if is_serverless else self.config.retries
        timeout_val = 15 if is_serverless else int(self.config.request_timeout)

        # 1. Try Scrapling Fetcher with Chrome TLS Impersonation (AGENTS.md specification)
        try:
            from scrapling import Fetcher
            for attempt in range(retries):
                try:
                    response = Fetcher.get(
                        url,
                        impersonate="chrome",
                        stealthy_headers=True,
                        timeout=timeout_val,
                        follow_redirects=True,
                    )
                    if response.status == 200:
                        body_html = getattr(response, "html_content", "") or (
                            response.body.decode("utf-8", errors="ignore")
                            if hasattr(response, "body")
                            else ""
                        )
                        if body_html and len(body_html) > 3000:
                            # Reject bot challenge / captcha pages
                            lower_snippet = body_html[:4000].lower()
                            if not any(cap in lower_snippet for cap in ("api-services-support@amazon.com", "validatecaptcha", "/errors/validatecaptcha")):
                                return body_html
                            logger.warning("[%s] Scrapling received captcha challenge (attempt %s/%s)", self.platform, attempt + 1, retries)
                    logger.warning(
                        "[%s] scrapling GET %s -> HTTP %s (attempt %s/%s)",
                        self.platform, url, response.status, attempt + 1, retries,
                    )
                except Exception as exc:
                    logger.warning("[%s] scrapling fetch error: %s", self.platform, exc)
                await self._polite_delay(backoff=attempt + 1)
        except (ImportError, AttributeError) as exc:
            logger.debug("[%s] Scrapling Fetcher unavailable: %s", self.platform, exc)

        # 2. Fallback to standard httpx GET with realistic browser headers & Google referer
        headers = {
            "User-Agent": self._random_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
            "Referer": "https://www.google.com/",
            "Sec-Ch-Ua": '"Not A(Brand";v="99", "Google Chrome";v="125", "Chromium";v="125"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }
        for attempt in range(retries):
            try:
                async with httpx.AsyncClient(
                    follow_redirects=True, timeout=timeout_val
                ) as client:
                    response = await client.get(url, headers=headers)
                if response.status_code == 200 and len(response.text) > 3000:
                    lower_snippet = response.text[:4000].lower()
                    if not any(cap in lower_snippet for cap in ("api-services-support@amazon.com", "validatecaptcha", "/errors/validatecaptcha")):
                        return response.text
                logger.warning(
                    "[%s] static GET %s -> HTTP %s (len=%s, attempt %s/%s)",
                    self.platform, url, response.status_code, len(response.text), attempt + 1, retries,
                )
            except httpx.HTTPError as exc:
                logger.warning("[%s] static GET failed: %s", self.platform, exc)
            await self._polite_delay(backoff=attempt + 1)
        return None

    # ---------------------------------------------------------------- JS fetch
    async def _js_fetch(self, url: str) -> Optional[str]:
        """Render page in headless browser using Scrapling StealthyFetcher or Playwright fallback."""
        import os
        if os.getenv("CI") or os.getenv("GITHUB_ACTIONS") or os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
            logger.debug("[%s] Skipping headless browser fetch in CI/serverless environment", self.platform)
            return None

        # 1. Try Scrapling StealthyFetcher (anti-bot bypass) via async_fetch
        try:
            from scrapling import StealthyFetcher
            for attempt in range(self.config.retries):
                try:
                    response = await StealthyFetcher.async_fetch(
                        url,
                        headless=self.config.headless,
                        network_idle=True,
                        timeout=int(self.config.request_timeout * 1000),
                    )
                    if response.status == 200:
                        body_html = getattr(response, "html_content", "") or (
                            response.body.decode("utf-8", errors="ignore")
                            if hasattr(response, "body")
                            else ""
                        )
                        if body_html and len(body_html) > 5000:
                            return body_html
                except Exception as exc:
                    logger.debug("[%s] scrapling stealth fetch error: %s", self.platform, exc)
                await self._polite_delay(backoff=attempt + 1)
        except (ImportError, AttributeError):
            pass

        # 2. Fallback to native Playwright
        stealth = None
        try:
            from playwright_stealth import Stealth

            stealth = Stealth()
        except Exception as exc:  # playwright-stealth missing or incompatible
            logger.info("playwright-stealth unavailable (%s); continuing without it", exc)

        for attempt in range(self.config.retries):
            try:
                from playwright.async_api import async_playwright

                async with async_playwright() as p:
                    # Prefer installed Google Chrome channel for realistic TLS fingerprint
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

                    loc = self.config.get_location()
                    context = await browser.new_context(
                        user_agent=self._random_user_agent(),
                        locale="en-IN",
                        timezone_id="Asia/Kolkata",
                        viewport={"width": 1366, "height": 900},
                        geolocation={"latitude": loc["lat"], "longitude": loc["lon"]},
                        permissions=["geolocation"],
                    )

                    # Pre-seed dark store cookies for Q-commerce platforms
                    pincode = loc.get("pincode", "560103")
                    lat_str = str(loc["lat"])
                    lon_str = str(loc["lon"])
                    try:
                        await context.add_cookies([
                            {"name": "_bb_pincode", "value": pincode, "domain": ".bigbasket.com", "path": "/"},
                            {"name": "_bb_cid", "value": "1", "domain": ".bigbasket.com", "path": "/"},
                            {"name": "lat", "value": lat_str, "domain": ".blinkit.com", "path": "/"},
                            {"name": "lon", "value": lon_str, "domain": ".blinkit.com", "path": "/"},
                            {"name": "location_pincode", "value": pincode, "domain": ".blinkit.com", "path": "/"},
                            {"name": "user_pincode", "value": pincode, "domain": ".zeptonow.com", "path": "/"},
                        ])
                    except Exception:
                        pass

                    if stealth is not None:
                        try:
                            await stealth.apply_stealth_async(context)
                        except Exception as exc:  # pragma: no cover
                            logger.debug("stealth apply failed: %s", exc)
                    page = await context.new_page()
                    try:
                        await page.goto(
                            url,
                            wait_until="domcontentloaded",
                            timeout=int(self.config.request_timeout * 1000),
                        )
                        # Give client-side JS a moment, then wait for a price
                        # node to appear (the actual value is parsed later).
                        await page.wait_for_timeout(self.config.js_wait_milliseconds)
                        await self._wait_for_price(page)
                        return await page.content()
                    except Exception as exc:
                        logger.warning("[%s] page interaction issue: %s", self.platform, exc)
                    finally:
                        await context.close()
                        await browser.close()
            except Exception as exc:
                logger.warning("[%s] browser launch/use failed: %s", self.platform, exc)
            await self._polite_delay(backoff=attempt + 1)
        return None

    async def _wait_for_price(self, page) -> None:
        """Wait (briefly) for the first price selector to render."""
        for selector in self.price_selectors:
            try:
                await page.wait_for_selector(selector, timeout=8000)
                return
            except Exception:
                continue

    # ---------------------------------------------------------------- helpers
    def _random_user_agent(self) -> str:
        return random.choice(self.config.user_agents)

    async def _polite_delay(self, backoff: int = 1) -> None:
        """Sleep a random 2-5s, scaled by retry backoff, to avoid rate limits."""
        import os
        if os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
            return
        low, high = self.config.min_delay_seconds, self.config.max_delay_seconds
        await asyncio.sleep(random.uniform(low, high) * backoff)