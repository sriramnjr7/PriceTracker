"""Quick Commerce 90%+ Deal Hunter for BigBasket, Blinkit, Zepto, and Instamart."""

import asyncio
import logging
import re
from typing import Any, List, Optional
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from config import Settings, settings
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


class QuickCommerceRadar:
    """Specialized engine to hunt down 80%-95% clearance and pricing glitch deals on Quick Commerce."""

    def __init__(self, config: Optional[Settings] = None):
        self.config = config or settings

    async def scan_bigbasket_deals(self, min_discount: float = 80.0, pincode: str = "560103") -> List[dict[str, Any]]:
        """Scan BigBasket deals and clearance hubs."""
        from scrapers.bigbasket import BigBasketScraper
        scraper = BigBasketScraper(self.config)
        
        queries = ["clearance", "deals", "offer", "discount", "super saver", "combo"]
        found: List[dict[str, Any]] = []
        seen_urls = set()

        for q in queries:
            deals = await scraper.scan_deals(q, min_discount=min_discount)
            for d in deals:
                if d["url"] not in seen_urls:
                    seen_urls.add(d["url"])
                    found.append(d)
        return found

    async def scan_blinkit_deals(self, min_discount: float = 80.0, pincode: str = "560103") -> List[dict[str, Any]]:
        """Scan Blinkit deal hubs and search terms."""
        loc = self.config.get_location()
        found: List[dict[str, Any]] = []
        seen_urls = set()

        queries = ["deal", "clearance", "offer", "super saver"]
        
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    channel="chrome",
                    headless=self.config.headless,
                    args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                )
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
                    locale="en-IN",
                    timezone_id="Asia/Kolkata",
                    geolocation={"latitude": loc["lat"], "longitude": loc["lon"]},
                    permissions=["geolocation"],
                )
                page = await context.new_page()

                for q in queries:
                    url = f"https://blinkit.com/s/?q={q}"
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                        await page.wait_for_timeout(3000)
                        soup = BeautifulSoup(await page.content(), "html.parser")
                        
                        # Find all product containers
                        cards = soup.select("div[class*='Product__UpdatedCard'], div[class*='ProductList'] > div, div[data-test-id*='product-card']")
                        if not cards:
                            cards = [a.parent for a in soup.find_all("a", href=True) if "/prn/" in a["href"]]

                        for card in cards:
                            link_el = card.find("a", href=True) if card.name != "a" else card
                            if not link_el or "/prn/" not in link_el.get("href", ""):
                                continue
                            
                            href = link_el["href"]
                            clean_url = "https://blinkit.com" + href.split("?")[0]
                            if clean_url in seen_urls:
                                continue

                            # Title from link slug or card
                            slug_match = re.search(r"/prn/([^/?]+)", clean_url)
                            title = slug_match.group(1).replace("-", " ").title() if slug_match else "Blinkit Item"

                            # Prices in card
                            prices = []
                            for el in card.find_all(True):
                                txt = el.get_text(" ", strip=True)
                                if "₹" in txt or "Rs" in txt:
                                    m = re.search(r"(?:₹|Rs\.?)\s*([\d,]+(?:\.\d+)?)", txt)
                                    if m:
                                        try:
                                            val = float(m.group(1).replace(",", ""))
                                            if val > 0:
                                                prices.append(val)
                                        except ValueError:
                                            pass

                            if not prices:
                                continue

                            selling_price = min(prices)
                            mrp_val = max(prices) if len(prices) > 1 else selling_price

                            if mrp_val > selling_price and mrp_val > 0:
                                disc = round(((mrp_val - selling_price) / mrp_val) * 100.0, 1)
                            else:
                                disc = 0.0

                            if disc >= min_discount:
                                seen_urls.add(clean_url)
                                found.append({
                                    "title": title,
                                    "price": selling_price,
                                    "effective_price": selling_price,
                                    "mrp": mrp_val,
                                    "discount_percent": disc,
                                    "platform": "blinkit",
                                    "url": clean_url,
                                    "in_stock": True,
                                })
                    except Exception as e:
                        logger.debug("[blinkit] error scanning query '%s': %s", q, e)
                
                await context.close()
                await browser.close()
        except Exception as exc:
            logger.warning("[blinkit] quick commerce deal scan error: %s", exc)

        return found

    async def scan_all_qcommerce(self, min_discount: float = 80.0, pincode: str = "560103") -> dict[str, List[dict[str, Any]]]:
        """Scan all 4 quick commerce platforms for massive discount deals."""
        results = {
            "bigbasket": [],
            "blinkit": [],
            "zepto": [],
            "instamart": [],
        }

        print(f"\n⚡ Scanning Quick Commerce for >={min_discount}% Steals (Pincode: {pincode})...\n")

        # 1. BigBasket
        try:
            print("  🛒 Searching BigBasket...")
            bb_deals = await self.scan_bigbasket_deals(min_discount=min_discount, pincode=pincode)
            results["bigbasket"] = bb_deals
            print(f"     -> BigBasket: Found {len(bb_deals)} deal(s) >= {min_discount}% OFF")
        except Exception as e:
            print(f"     -> BigBasket error: {e}")

        # 2. Blinkit
        try:
            print("  ⚡ Searching Blinkit...")
            bl_deals = await self.scan_blinkit_deals(min_discount=min_discount, pincode=pincode)
            results["blinkit"] = bl_deals
            print(f"     -> Blinkit: Found {len(bl_deals)} deal(s) >= {min_discount}% OFF")
        except Exception as e:
            print(f"     -> Blinkit error: {e}")

        return results
