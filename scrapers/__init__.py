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


def normalize_product_url(url: str, platform: Optional[str] = None) -> str:
    """Strip search tokens, tracking IDs, and affiliate cruft to produce a canonical product URL."""
    import re
    from urllib.parse import urlparse

    clean = url.strip()
    p = platform or detect_platform(clean, safe=True) or ""

    if p == "amazon":
        # Extract ASIN (10 alphanumeric characters) from /dp/ASIN or /gp/product/ASIN
        m = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", clean, re.IGNORECASE)
        if m:
            asin = m.group(1).upper()
            host = urlparse(clean).hostname or "www.amazon.in"
            return f"https://{host}/dp/{asin}"
    elif p == "casio":
        # Strip all Shopify search parameters (?_pos=...&_fid=...&_ss=...)
        return clean.split("?")[0].rstrip("/")
    elif p == "flipkart":
        # Keep product path, preserve pid if present
        base = clean.split("?")[0].rstrip("/")
        m = re.search(r"[?&]pid=([A-Za-z0-9]+)", clean)
        if m:
            return f"{base}?pid={m.group(1)}"
        return base
    elif p in ("myntra", "ajio"):
        return clean.split("?")[0].rstrip("/")

    return clean.split("?")[0] if "?" in clean and any(k in clean for k in ("ref=", "utm_", "dib=")) else clean


def extract_fallback_title(url: str, platform: str) -> str:
    """Generate a clean, human-readable title from URL path slug instead of query parameters."""
    import re
    from urllib.parse import urlparse, unquote

    parsed = urlparse(url)
    segments = [s for s in parsed.path.split("/") if s and s.lower() not in ("dp", "gp", "product", "products", "p", "buy")]

    if segments:
        candidate = segments[0].replace("-", " ").replace("_", " ")
        candidate = unquote(candidate).strip()
        # Ensure it's not just an ASIN or model ID
        if len(candidate) > 3 and not re.match(r"^[A-Z0-9]{8,12}$", candidate, re.IGNORECASE):
            return " ".join(w.capitalize() for w in candidate.split())[:80]

    return f"Tracked Product ({platform.title()})"


__all__ = [
    "SCRAPERS",
    "BaseScraper",
    "ScrapeError",
    "ScrapeResult",
    "detect_platform",
    "resolve_platform",
    "get_scraper",
    "normalize_product_url",
    "extract_fallback_title",
]