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
from .computech import ComputechScraper
from .elitehubs import EliteHubsScraper
from .flipkart import FlipkartScraper
from .gameloot import GameLootScraper
from .genesispc import GenesisPCScraper
from .instamart import InstamartScraper
from .myntra import MyntraScraper
from .zepto import ZeptoScraper

SCRAPERS = {
    "amazon": AmazonScraper,
    "flipkart": FlipkartScraper,
    "myntra": MyntraScraper,
    "ajio": AjioScraper,
    "casio": CasioScraper,
    "elitehubs": EliteHubsScraper,
    "computech": ComputechScraper,
    "gameloot": GameLootScraper,
    "genesispc": GenesisPCScraper,
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
    "elitehubs.com": "elitehubs",
    "computechstore.in": "computech",
    "gameloot.in": "gameloot",
    "genesispc.in": "genesispc",
    "bigbasket.com": "bigbasket",
    "bbinstant.com": "bigbasket",
    "blinkit.com": "blinkit",
    "zeptonow.com": "zepto",
    "zepto.com": "zepto",
    "swiggy.com": "instamart",
}


SHORTLINK_DOMAINS = (
    "amzn.in",
    "amzn.to",
    "fkrt.co",
    "fkrt.it",
    "myntr.it",
    "ajio.page.link",
    "bit.ly",
    "tinyurl.com",
    "t.co",
)


def is_shortlink(url: str) -> bool:
    """Return True if URL is a known redirector/shortlink service or short pattern."""
    import re
    host = (urlparse(url).hostname or "").lower()
    if any(host == d or host.endswith("." + d) for d in SHORTLINK_DOMAINS):
        return True
    if "dl.flipkart.com" in host and "/s/" in url:
        return True
    if "amazon" in host and re.search(r"/d/[a-zA-Z0-9]+", url):
        return True
    return False


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


def _clean_resolved_url(final_url: str) -> str:
    """Normalize redirected URL and decode nested shortlink destination parameters."""
    if "hyperlocal-preview-page" in final_url and "originalUrl=" in final_url:
        from urllib.parse import urlparse, parse_qs, unquote
        parsed = urlparse(final_url)
        qs = parse_qs(parsed.query)
        orig = qs.get("originalUrl", [""])[0]
        if orig:
            unquoted = unquote(orig)
            if not unquoted.startswith("http"):
                return f"https://www.flipkart.com{unquoted}"
            return unquoted
    return final_url


async def resolve_platform_and_url(url: str) -> tuple[Optional[str], str]:
    """Detect platform and expand any shortlinks to their final canonical destination URL."""
    clean = url.strip()
    if is_shortlink(clean):
        # 1. Use curl_cffi with Chrome impersonation to reliably resolve Flipkart & anti-bot shortlinks
        try:
            from curl_cffi.requests import AsyncSession
            async with AsyncSession(impersonate="chrome") as session:
                r = await session.get(clean, allow_redirects=True, timeout=8.0)
                final_url = _clean_resolved_url(str(r.url))
                plat = detect_platform(final_url, safe=True)
                if plat:
                    return plat, final_url
        except Exception:
            pass

        # 2. Fallback to httpx AsyncClient
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=5.0,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            ) as client:
                resp = await client.get(clean)
                final_url = _clean_resolved_url(str(resp.url))
                plat = detect_platform(final_url, safe=True)
                if plat:
                    return plat, final_url
        except Exception:
            pass

    plat = detect_platform(clean, safe=True)
    if plat:
        return plat, clean

    try:
        from curl_cffi.requests import AsyncSession
        async with AsyncSession(impersonate="chrome") as session:
            r = await session.get(clean, allow_redirects=True, timeout=8.0)
            final_url = _clean_resolved_url(str(r.url))
            return detect_platform(final_url, safe=True), final_url
    except Exception:
        pass

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=5.0,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        ) as client:
            resp = await client.get(clean)
            final_url = _clean_resolved_url(str(resp.url))
            return detect_platform(final_url, safe=True), final_url
    except Exception:
        return None, clean


async def resolve_platform(url: str) -> Optional[str]:
    """Detect platform, following redirects for short links (amzn.in, fkrt.co...)."""
    plat, _ = await resolve_platform_and_url(url)
    return plat


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
    from urllib.parse import urlparse, parse_qs, unquote

    clean = url.strip()

    # Handle Flipkart hyperlocal-preview-page with originalUrl parameter
    if "hyperlocal-preview-page" in clean and "originalUrl=" in clean:
        parsed_hl = urlparse(clean)
        qs_hl = parse_qs(parsed_hl.query)
        orig = qs_hl.get("originalUrl", [""])[0]
        if orig:
            unquoted = unquote(orig)
            clean = f"https://www.flipkart.com{unquoted}" if not unquoted.startswith("http") else unquoted

    p = platform or detect_platform(clean, safe=True) or ""

    if p == "amazon":
        # Extract ASIN (10 alphanumeric characters) from /dp/ASIN or /gp/product/ASIN
        m = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", clean, re.IGNORECASE)
        if m:
            asin = m.group(1).upper()
            host = urlparse(clean).hostname or "www.amazon.in"
            return f"https://{host}/dp/{asin}"
    elif p in ("casio", "elitehubs", "genesispc"):
        # Canonicalize Shopify product URLs: /products/<handle>
        # Preserve ?variant=<id> if present, but strip all other tracking cruft
        parsed = urlparse(clean)
        domain = parsed.hostname or ("casiostore.bhawar.com" if p == "casio" else ("elitehubs.com" if p == "elitehubs" else "www.genesispc.in"))
        scheme = parsed.scheme or "https"
        m = re.search(r"/products/([a-zA-Z0-9_-]+)", parsed.path)
        qs = parse_qs(parsed.query)
        variant_id = qs.get("variant", [None])[0]
        variant_suffix = f"?variant={variant_id}" if variant_id else ""
        if m:
            return f"{scheme}://{domain}/products/{m.group(1)}{variant_suffix}"
        if p == "casio":
            m_col = re.search(r"/collections/([a-zA-Z0-9_-]+)", parsed.path)
            if m_col:
                return f"{scheme}://{domain}/collections/{m_col.group(1)}"
        return f"{scheme}://{domain}{parsed.path.rstrip('/')}{variant_suffix}"
    elif p in ("computech", "gameloot"):
        return clean.split("?")[0].rstrip("/") + "/"
    elif p == "zepto":
        # Standardize zeptonow.com -> zepto.com and strip tracking queries
        base = clean.split("?")[0].rstrip("/")
        base = base.replace("zeptonow.com", "zepto.com")
        if not base.startswith("https://"):
            base = "https://" + base.lstrip("http://")
        return base
    elif p == "flipkart":
        # Keep product path, preserve pid if present
        base = clean.split("?")[0].rstrip("/")
        if "dl.flipkart.com/dl/" in base:
            base = base.replace("dl.flipkart.com/dl/", "www.flipkart.com/")
        m = re.search(r"[?&]pid=([A-Za-z0-9]+)", clean)
        if m:
            return f"{base}?pid={m.group(1)}"
        return base
    elif p in ("myntra", "ajio", "blinkit", "bigbasket", "instamart"):
        return clean.split("?")[0].rstrip("/")

    return clean.split("?")[0] if "?" in clean and any(k in clean for k in ("ref=", "utm_", "dib=", "gclid=", "fbclid=", "gad_source=")) else clean


def extract_fallback_title(url: str, platform: str) -> str:
    """Generate a clean, human-readable title from URL path slug instead of query parameters."""
    import re
    from urllib.parse import urlparse, unquote, parse_qs

    clean = url.strip()
    if "hyperlocal-preview-page" in clean and "originalUrl=" in clean:
        parsed_hl = urlparse(clean)
        orig = parse_qs(parsed_hl.query).get("originalUrl", [""])[0]
        if orig:
            clean = unquote(orig)

    parsed = urlparse(clean)
    segments = [s for s in parsed.path.split("/") if s and s.lower() not in ("dp", "gp", "product", "products", "p", "buy", "s", "dl", "hyperlocal-preview-page")]

    if segments:
        candidate = segments[0].replace("-", " ").replace("_", " ")
        candidate = unquote(candidate).strip()
        # Ensure it's not just an ASIN, PID, or short code
        if len(candidate) > 2 and not re.match(r"^[A-Z0-9]{8,12}$", candidate, re.IGNORECASE):
            return " ".join(w.capitalize() for w in candidate.split())[:80]

    return f"Tracked Product ({platform.title()})"


__all__ = [
    "SCRAPERS",
    "BaseScraper",
    "ScrapeError",
    "ScrapeResult",
    "detect_platform",
    "resolve_platform",
    "resolve_platform_and_url",
    "get_scraper",
    "normalize_product_url",
    "extract_fallback_title",
]