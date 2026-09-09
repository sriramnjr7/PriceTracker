"""Scraper registry and platform detection."""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

import httpx

from .ajio import AjioScraper
from .amazon import AmazonScraper
from .base import BaseScraper, ScrapeError, ScrapeResult
from .bigbasket import BigBasketScraper
from .blinkit import BlinkitScraper
from .casio import CasioScraper
from .flipkart import FlipkartScraper
from .instamart import InstamartScraper
from .myntra import MyntraScraper
from .zepto import ZeptoScraper

SCRAPERS = {
    "amazon": AmazonScraper,
    "flipkart": FlipkartScraper,
    "myntra": MyntraScraper,
    "ajio": AjioScraper,
    "casio": CasioScraper,
    "bigbasket": BigBasketScraper,
    "blinkit": BlinkitScraper,
    "zepto": ZeptoScraper,
    "instamart": InstamartScraper,
}

# (domain, platform) mapping used for auto-detection.
HOST_MAP = {
    "amazon.in": "amazon",
    "amazon.com": "amazon",
    "amzn.in": "amazon",
    "amzn.to": "amazon",
    "flipkart.com": "flipkart",
    "dl.flipkart.com": "flipkart",
    "fkrt.co": "flipkart",
    "fkrt.it": "flipkart",
    "myntra.com": "myntra",
    "myntr.it": "myntra",
    "ajio.com": "ajio",
    "ajio.page.link": "ajio",
    "casiostore.bhawar.com": "casio",
    "bhawar.com": "casio",
    "bigbasket.com": "bigbasket",
    "bbinstant.com": "bigbasket",
    "blinkit.com": "blinkit",
    "zeptonow.com": "zepto",
    "zepto.com": "zepto",
    "swiggy.com": "instamart",
}


def detect_platform(url: str, safe: bool = False) -> Optional[str]:
    """Map a URL's hostname to a platform slug, or raise ValueError (or return None if safe=True)."""
    host = (urlparse(url).hostname or "").lower()
    for domain, platform in HOST_MAP.items():
        if host == domain or host.endswith("." + domain):
            return platform
    if safe:
        return None
    raise ValueError(
        f"Unsupported URL host '{host}'. Supported: {', '.join(HOST_MAP)}"
    )


async def resolve_platform(url: str) -> Optional[str]:
    """Detect platform, following redirects for short links (amzn.in, fkrt.co...)."""
    plat = detect_platform(url, safe=True)
    if plat:
        return plat
    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=15, headers={"User-Agent": "Mozilla/5.0"}
        ) as client:
            response = await client.get(url)
            return detect_platform(str(response.url), safe=True)
    except Exception:
        return None


def get_scraper(platform: str, config=None) -> BaseScraper:
    """Factory: return the scraper for a platform slug."""
    try:
        cls = SCRAPERS[platform]
    except KeyError:
        raise ValueError(
            f"Unknown platform '{platform}'. Available: {', '.join(SCRAPERS)}"
        )
    return cls(config) if config is not None else cls()


__all__ = [
    "SCRAPERS",
    "BaseScraper",
    "ScrapeError",
    "ScrapeResult",
    "detect_platform",
    "resolve_platform",
    "get_scraper",
]