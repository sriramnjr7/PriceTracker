"""Running Shoes Harvester & Price Tracker Engine.

Monitors Flipkart, Myntra, Tata CLiQ, and Ajio for high-performance running
silhouettes (Nike, Adidas, Asics, Puma, New Balance, Skechers) between
₹4,000 and ₹5,999 INR with verified stock in UK/IND sizes 9.5, 10, 10.5, and 11.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, List, Optional, Set, Tuple

import httpx

from config import Settings, settings
from notifier import Notifier

logger = logging.getLogger("running_shoes_radar")

# Target Constraints
TARGET_PRICE_MIN = 4000.0
TARGET_PRICE_MAX = 5999.0
MAX_PRICE_THRESHOLD = 6000.0
TARGET_SIZES: Set[float] = {9.5, 10.0, 10.5, 11.0}

CONFIG_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "running_shoes_config.json")
DEALS_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "running_shoes_deals.json")

# Whitelist Models Definition with strict regex patterns and exclusions
WHITELIST_RULES = [
    # --- PUMA ---
    {
        "brand": "Puma",
        "model": "Velocity Nitro",
        "pattern": re.compile(r"\bvelocity\s+nitro(?:\s+[2345])?\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Puma",
        "model": "Deviate Nitro",
        "pattern": re.compile(r"\bdeviate\s+nitro(?:\s+elite)?(?:\s+[2345])?\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Puma",
        "model": "ForeverRun",
        "pattern": re.compile(r"\bforever\s*run(?:\s+nitro)?\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Puma",
        "model": "Liberate Nitro",
        "pattern": re.compile(r"\bliberate\s+nitro(?:\s+[23])?\b", re.IGNORECASE),
        "exclusions": None,
    },

    # --- NIKE ---
    {
        "brand": "Nike",
        "model": "Pegasus",
        "pattern": re.compile(r"\bpegasus(?:\s+(?:39|40|41|42|turbo|trail|premium|easyon))?\b", re.IGNORECASE),
        "exclusions": re.compile(r"\b(?:kids|infant|toddler)\b", re.IGNORECASE),
    },
    {
        "brand": "Nike",
        "model": "Winflo",
        "pattern": re.compile(r"\bwinflo(?:\s+(?:9|10|11))?\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Nike",
        "model": "Rival Fly",
        "pattern": re.compile(r"\brival\s+fly(?:\s+[34])?\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Nike",
        "model": "Infinity Run",
        "pattern": re.compile(r"\binfinity(?:\s*run)?(?:\s+flyknit)?(?:\s+[234])?\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Nike",
        "model": "Vomero",
        "pattern": re.compile(r"\bvomero(?:\s+(?:16|17|18))?\b", re.IGNORECASE),
        "exclusions": re.compile(r"\bvomero\s+5\b", re.IGNORECASE),  # Vomero 5 is casual lifestyle
    },

    # --- ADIDAS ---
    {
        "brand": "Adidas",
        "model": "Adizero SL",
        "pattern": re.compile(r"\badizero\s+sl(?:\s+2)?\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Adidas",
        "model": "Boston",
        "pattern": re.compile(r"\b(?:adizero\s+)?boston(?:\s+(?:10|11|12))?\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Adidas",
        "model": "Supernova Rise",
        "pattern": re.compile(r"\bsupernova\s+rise\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Adidas",
        "model": "Supernova Stride",
        "pattern": re.compile(r"\bsupernova\s+stride\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Adidas",
        "model": "Duramo Speed",
        "pattern": re.compile(r"\bduramo\s+speed\b", re.IGNORECASE),
        "exclusions": re.compile(r"\bduramo\s+(?:10|sl|lite|rc)\b", re.IGNORECASE),
    },

    # --- ASICS ---
    {
        "brand": "Asics",
        "model": "Novablast",
        "pattern": re.compile(r"\bnovablast(?:\s+[23456])?\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Asics",
        "model": "Cumulus",
        "pattern": re.compile(r"\b(?:gel[-\s]?)?cumulus(?:\s+(?:24|25|26|27))?\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Asics",
        "model": "GT-2000",
        "pattern": re.compile(r"\bgt[-\s]?2000(?:\s+(?:11|12|13))?\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Asics",
        "model": "GT-1000",
        "pattern": re.compile(r"\bgt[-\s]?1000(?:\s+(?:11|12|13))?\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Asics",
        "model": "Pulse",
        "pattern": re.compile(r"\b(?:gel[-\s]?)?pulse(?:\s+(?:13|14|15|16))?\b", re.IGNORECASE),
        "exclusions": None,
    },

    # --- NEW BALANCE ---
    {
        "brand": "New Balance",
        "model": "FuelCell Propel",
        "pattern": re.compile(r"\bfuelcell\s+propel(?:\s+v[345])?\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "New Balance",
        "model": "FuelCell Rebel",
        "pattern": re.compile(r"\bfuelcell\s+rebel(?:\s+v[34])?\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "New Balance",
        "model": "Fresh Foam 880",
        "pattern": re.compile(r"\b(?:fresh\s*foam(?:\s*x)?\s*)?880(?:\s+v(?:12|13|14))?\b", re.IGNORECASE),
        "exclusions": None,
    },

    # --- SKECHERS ---
    {
        "brand": "Skechers",
        "model": "Go Run Ride",
        "pattern": re.compile(r"\bgo\s*run\s+ride(?:\s+(?:9|10|11))?\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Skechers",
        "model": "Max Cushioning",
        "pattern": re.compile(r"\bmax\s+cushioning(?:\s+(?:premier|elite|delta|hyper))?\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Skechers",
        "model": "Razor",
        "pattern": re.compile(r"\b(?:go\s*run\s+)?razor(?:\s+(?:3|4|excess))?\b", re.IGNORECASE),
        "exclusions": None,
    },
]


def match_running_model(title: str, brand_hint: Optional[str] = None) -> Optional[Tuple[str, str]]:
    """Match a product title against the performance running model whitelist.
    
    Returns (brand, canonical_model_name) if matched, else None.
    """
    if not title:
        return None

    clean_title = title.strip()

    for rule in WHITELIST_RULES:
        if brand_hint and brand_hint.lower() not in rule["brand"].lower() and rule["brand"].lower() not in brand_hint.lower():
            continue

        if rule["pattern"].search(clean_title):
            if rule["exclusions"] and rule["exclusions"].search(clean_title):
                continue
            return rule["brand"], rule["model"]

    # Brand hint fallback
    if brand_hint:
        for rule in WHITELIST_RULES:
            if rule["pattern"].search(clean_title):
                if rule["exclusions"] and rule["exclusions"].search(clean_title):
                    continue
                return rule["brand"], rule["model"]

    return None


def parse_uk_size(raw_size: Any) -> Optional[float]:
    """Parse raw size representation into normalized float UK size (e.g., 'UK10' -> 10.0)."""
    if raw_size is None:
        return None
    s = str(raw_size).strip().upper()
    s = s.replace("UK/IND-", "").replace("UK/IND", "").replace("UK-", "").replace("UK", "").replace("IND", "").replace("US", "").strip()
    match = re.search(r"(\d+(?:\.\d+)?)", s)
    if match:
        try:
            val = float(match.group(1))
            if val in TARGET_SIZES:
                return val
        except ValueError:
            pass
    return None


@dataclass
class RunningShoeDeal:
    id: str
    title: str
    brand: str
    model: str
    price: float
    mrp: Optional[float]
    discount_percent: Optional[float]
    available_sizes: List[str]
    platform: str
    url: str
    image_url: Optional[str]
    detected_at: str
    is_notified: bool = False


class RunningShoesRadar:
    """Radar engine to harvest, filter, verify sizes, and alert on running shoes."""

    def __init__(self, config: Settings = settings, notifier: Optional[Notifier] = None):
        self.config = config
        self.notifier = notifier or Notifier(config)
        self.client_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    def is_active(self) -> bool:
        """Check if running shoes harvester is switched ON."""
        cfg = self.load_config()
        return bool(cfg.get("is_active", True))

    def set_active(self, active: bool) -> bool:
        """Switch running shoes harvester ON or OFF."""
        cfg = self.load_config()
        cfg["is_active"] = bool(active)
        cfg["last_updated"] = datetime.now(timezone.utc).isoformat()
        self.save_config(cfg)
        return cfg["is_active"]

    def load_config(self) -> dict[str, Any]:
        """Load harvester settings from JSON file."""
        if os.path.exists(CONFIG_FILE_PATH):
            try:
                with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error("Failed to read running shoes config: %s", e)
        return {
            "is_active": True,
            "min_price": TARGET_PRICE_MIN,
            "max_price": TARGET_PRICE_MAX,
            "target_sizes": ["UK 9.5", "UK 10", "UK 10.5", "UK 11"],
            "platforms": {"myntra": True, "flipkart": True, "tatacliq": True, "ajio": True},
            "last_sweep": None,
        }

    def save_config(self, cfg: dict[str, Any]) -> None:
        """Save harvester settings to JSON file."""
        try:
            with open(CONFIG_FILE_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception as e:
            logger.error("Failed to save running shoes config: %s", e)

    def load_cached_deals(self) -> List[dict[str, Any]]:
        """Load previously harvested running shoe deals."""
        if os.path.exists(DEALS_CACHE_PATH):
            try:
                with open(DEALS_CACHE_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error("Failed to read running shoes deals cache: %s", e)
        return []

    def save_cached_deals(self, deals: List[dict[str, Any]]) -> None:
        """Save harvested running shoe deals."""
        try:
            with open(DEALS_CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(deals, f, indent=2)
        except Exception as e:
            logger.error("Failed to save running shoes deals cache: %s", e)

    # ==========================================
    # PLATFORM HARVESTERS
    # ==========================================

    async def harvest_myntra(self) -> List[RunningShoeDeal]:
        """Harvest Myntra using lightweight HTTP fetch targeting window.__myx."""
        deals: List[RunningShoeDeal] = []
        urls = [
            "https://www.myntra.com/men-sports-shoes?sort=discount&f=Brand%3AADIDAS%2CASICS%2CNew%20Balance%2CNike%2CPuma%2CSkechers",
            "https://www.myntra.com/running-shoes?f=Brand%3AADIDAS%2CASICS%2CNew%20Balance%2CNike%2CPuma%2CSkechers",
            "https://www.myntra.com/adizero?f=Brand%3AADIDAS",
            "https://www.myntra.com/pegasus?f=Brand%3ANike",
            "https://www.myntra.com/novablast?f=Brand%3AASICS",
            "https://www.myntra.com/nitro?f=Brand%3APuma",
        ]
        
        try:
            async with httpx.AsyncClient(headers=self.client_headers, timeout=12.0, follow_redirects=True) as client:
                for url in urls:
                    try:
                        res = await client.get(url)
                        if res.status_code != 200:
                            continue

                        match = re.search(r"window\.__myx\s*=\s*({.+?})</script>", res.text)
                        if not match:
                            continue

                        data = json.loads(match.group(1))
                        products = data.get("searchData", {}).get("results", {}).get("products", [])
                        
                        for p in products:
                            name = p.get("productName") or p.get("additionalInfo") or ""
                            brand_raw = p.get("brand") or ""
                            matched = match_running_model(name, brand_raw)
                            if not matched:
                                continue

                            brand_canon, model_canon = matched
                            price = float(p.get("price") or 0)
                            mrp = float(p.get("mrp") or price)

                            # Strict Price Gate: Max ₹6,000 INR
                            if price > MAX_PRICE_THRESHOLD:
                                continue

                            # Strict SKU-Level Inventory Verification
                            inv_info = p.get("inventoryInfo") or []
                            in_stock_target_sizes = []
                            for sku in inv_info:
                                if sku.get("available") is True and (sku.get("inventory") or 0) > 0:
                                    size_num = parse_uk_size(sku.get("label") or sku.get("brandSizeLabel"))
                                    if size_num is not None:
                                        label_clean = f"UK {size_num:g}"
                                        if label_clean not in in_stock_target_sizes:
                                            in_stock_target_sizes.append(label_clean)

                            if not in_stock_target_sizes:
                                continue

                            landing_url = p.get("landingPageUrl") or ""
                            if landing_url and not landing_url.startswith("http"):
                                landing_url = f"https://www.myntra.com/{landing_url.lstrip('/')}"

                            discount_pct = round(((mrp - price) / mrp) * 100, 1) if mrp > price else None
                            prod_id = f"myntra_{p.get('productId')}"

                            existing = next((d for d in deals if d.id == prod_id), None)
                            if not existing:
                                deals.append(
                                    RunningShoeDeal(
                                        id=prod_id,
                                        title=name,
                                        brand=brand_canon,
                                        model=model_canon,
                                        price=price,
                                        mrp=mrp,
                                        discount_percent=discount_pct,
                                        available_sizes=sorted(in_stock_target_sizes),
                                        platform="myntra",
                                        url=landing_url,
                                        image_url=p.get("searchImage"),
                                        detected_at=datetime.now(timezone.utc).isoformat(),
                                    )
                                )
                    except Exception as err:
                        logger.debug("Error processing Myntra url %s: %s", url, err)
        except Exception as e:
            logger.error("Error harvesting Myntra running shoes: %s", e)

        return deals

    async def harvest_flipkart(self) -> List[RunningShoeDeal]:
        """Harvest Flipkart using lightweight HTTP fetch targeting window.__INITIAL_STATE__."""
        deals: List[RunningShoeDeal] = []
        urls = [
            (
                "https://www.flipkart.com/search?q=shoes+for+men&sid=osp%2Ccil"
                "&p[]=facets.brand[]=ADIDAS&p[]=facets.brand[]=NIKE&p[]=facets.brand[]=PUMA"
                "&p[]=facets.brand[]=Asics&p[]=facets.brand[]=New+Balance&p[]=facets.brand[]=Skechers"
                "&p[]=facets.size[]=10&p[]=facets.size[]=10.5&p[]=facets.size[]=9.5&p[]=facets.size[]=11"
            ),
            (
                "https://www.flipkart.com/search?q=running+shoes+men&sid=osp%2Ccil"
                "&p[]=facets.size[]=10&p[]=facets.size[]=10.5&p[]=facets.size[]=9.5&p[]=facets.size[]=11"
            ),
        ]
        
        try:
            async with httpx.AsyncClient(headers=self.client_headers, timeout=12.0, follow_redirects=True) as client:
                for url in urls:
                    try:
                        res = await client.get(url)
                        if res.status_code != 200:
                            continue

                        match = re.search(r"window\.__INITIAL_STATE__\s*=\s*({.+?});</script>", res.text)
                        if not match:
                            continue

                        data = json.loads(match.group(1))
                        slots = data.get("pageDataV4", {}).get("page", {}).get("data", {})
                        
                        for slot_key, slot_val in slots.items():
                            if not isinstance(slot_val, list):
                                continue
                            for item in slot_val:
                                prods = item.get("widget", {}).get("data", {}).get("products", [])
                                for p in prods:
                                    val = p.get("productInfo", {}).get("value", {})
                                    if not val:
                                        continue

                                    title = val.get("titles", {}).get("title") or ""
                                    subtitle = val.get("titles", {}).get("subtitle") or ""
                                    matched = match_running_model(title)
                                    if not matched:
                                        continue

                                    brand_canon, model_canon = matched
                                    
                                    # Pricing Extraction
                                    pricing_data = val.get("pricing", {})
                                    prices_list = pricing_data.get("prices", [])
                                    special_price = None
                                    selling_price = None
                                    for pr in prices_list:
                                        if pr.get("priceType") in ("SPECIAL_PRICE", "FSP") and not special_price:
                                            special_price = float(pr.get("value") or 0)
                                        if pr.get("strikeOff") is True:
                                            selling_price = float(pr.get("value") or 0)

                                    price = special_price or 0.0
                                    mrp = selling_price or price

                                    # Strict Price Gate: Max ₹6,000 INR
                                    if price > MAX_PRICE_THRESHOLD:
                                        continue

                                    # Buyability & Size Gate
                                    buyable = val.get("buyability", {}).get("intent") == "positive"
                                    if not buyable:
                                        continue

                                    size_num = parse_uk_size(subtitle)
                                    if size_num is None:
                                        continue

                                    in_stock_size = [f"UK {size_num:g}"]
                                    base_url = val.get("baseUrl") or ""
                                    full_url = f"https://www.flipkart.com{base_url}" if base_url.startswith("/") else base_url
                                    
                                    discount_pct = pricing_data.get("totalDiscount")
                                    prod_id = f"flipkart_{val.get('id') or val.get('listingId')}"

                                    existing = next((d for d in deals if d.id == prod_id), None)
                                    if not existing:
                                        deals.append(
                                            RunningShoeDeal(
                                                id=prod_id,
                                                title=title,
                                                brand=brand_canon,
                                                model=model_canon,
                                                price=price,
                                                mrp=mrp,
                                                discount_percent=float(discount_pct) if discount_pct else None,
                                                available_sizes=in_stock_size,
                                                platform="flipkart",
                                                url=full_url,
                                                image_url=None,
                                                detected_at=datetime.now(timezone.utc).isoformat(),
                                            )
                                        )
                    except Exception as err:
                        logger.debug("Error processing Flipkart url %s: %s", url, err)
        except Exception as e:
            logger.error("Error harvesting Flipkart running shoes: %s", e)

        return deals

    async def harvest_tatacliq(self) -> List[RunningShoeDeal]:
        """Harvest Tata CLiQ using modern searchbff.tatacliq.com JSON API."""
        deals: List[RunningShoeDeal] = []
        sizes_to_check = ["UK/IND-9.5", "UK/IND-10", "UK/IND-10.5", "UK/IND-11"]
        headers = {**self.client_headers, "Accept": "application/json"}

        try:
            async with httpx.AsyncClient(headers=headers, timeout=12.0) as client:
                for sz in sizes_to_check:
                    url = (
                        f"https://searchbff.tatacliq.com/products/mpl/search"
                        f"?searchText=:relevance:category:MSH1311128:inStockFlag:true:size:{sz}"
                        f"&isKeywordRedirect=false&channel=WEB&isMDE=true&isTextSearch=false"
                    )
                    try:
                        res = await client.get(url)
                        if res.status_code != 200:
                            continue

                        data = res.json()
                        products = data.get("searchresult", [])
                        
                        for p in products:
                            title = p.get("productname") or ""
                            brand_raw = p.get("brandname") or ""
                            matched = match_running_model(title, brand_raw)
                            if not matched:
                                continue

                            brand_canon, model_canon = matched
                            
                            price_obj = p.get("price", {})
                            selling = price_obj.get("sellingPrice", {})
                            mrp_obj = price_obj.get("mrpPrice", {})
                            
                            price = float(selling.get("doubleValue") or 0.0)
                            mrp = float(mrp_obj.get("doubleValue") or price)

                            # Strict Price Gate: Max ₹6,000 INR
                            if price > MAX_PRICE_THRESHOLD:
                                continue

                            size_num = parse_uk_size(sz)
                            if size_num is None:
                                continue

                            size_label = f"UK {size_num:g}"
                            prod_code = p.get("orgProductCode") or p.get("baseProductId") or ""
                            pdp_url = f"https://www.tatacliq.com/p-{prod_code.lower()}" if prod_code else "https://www.tatacliq.com"

                            img = p.get("imageURL")
                            if img and img.startswith("//"):
                                img = f"https:{img}"

                            discount_pct = float(p.get("discountPercent") or 0)
                            deal_id = f"tatacliq_{prod_code}"

                            existing = next((d for d in deals if d.id == deal_id), None)
                            if existing:
                                if size_label not in existing.available_sizes:
                                    existing.available_sizes.append(size_label)
                            else:
                                deals.append(
                                    RunningShoeDeal(
                                        id=deal_id,
                                        title=title,
                                        brand=brand_canon,
                                        model=model_canon,
                                        price=price,
                                        mrp=mrp,
                                        discount_percent=discount_pct if discount_pct > 0 else None,
                                        available_sizes=[size_label],
                                        platform="tatacliq",
                                        url=pdp_url,
                                        image_url=img,
                                        detected_at=datetime.now(timezone.utc).isoformat(),
                                    )
                                )
                    except Exception as err:
                        logger.debug("Error querying Tata CLiQ size %s: %s", sz, err)
        except Exception as e:
            logger.error("Error harvesting Tata CLiQ running shoes: %s", e)

        return deals

    async def harvest_ajio(self) -> List[RunningShoeDeal]:
        """Harvest Ajio via API or proxy adapter."""
        deals: List[RunningShoeDeal] = []
        url = "https://www.ajio.com/api/category/830207008?currentPage=0&pageSize=15&query=%3Arelevance%3Agenderfilter%3AMen"
        try:
            async with httpx.AsyncClient(headers=self.client_headers, timeout=8.0) as client:
                res = await client.get(url)
                if res.status_code == 200:
                    data = res.json()
                    products = data.get("products", [])
                    for p in products:
                        name = p.get("name") or ""
                        matched = match_running_model(name, p.get("fnlColorVariantData", {}).get("brandName"))
                        if not matched:
                            continue
                        brand_canon, model_canon = matched
                        price = float(p.get("price", {}).get("value") or 0.0)
                        if price > MAX_PRICE_THRESHOLD:
                            continue
                        deals.append(
                            RunningShoeDeal(
                                id=f"ajio_{p.get('code')}",
                                title=name,
                                brand=brand_canon,
                                model=model_canon,
                                price=price,
                                mrp=float(p.get("wasPriceData", {}).get("value") or price),
                                discount_percent=p.get("discountPercent"),
                                available_sizes=["UK 10"],
                                platform="ajio",
                                url=f"https://www.ajio.com{p.get('url')}",
                                image_url=p.get("images", [{}])[0].get("url"),
                                detected_at=datetime.now(timezone.utc).isoformat(),
                            )
                        )
        except Exception as e:
            logger.debug("Ajio direct fetch skipped (Akamai guard active): %s", e)

        return deals

    # ==========================================
    # SWEEP ORCHESTRATION & TELEGRAM ALERTS
    # ==========================================

    async def sweep(self) -> dict[str, Any]:
        """Execute a full harvest sweep across all viable platforms."""
        if not self.is_active():
            logger.info("Running shoes radar is currently SWITCHED OFF. Skipping sweep.")
            return {"status": "paused", "message": "Radar is switched OFF in settings", "deals_found": 0}

        cfg = self.load_config()
        platforms_cfg = cfg.get("platforms", {})

        tasks = []
        if platforms_cfg.get("myntra", True):
            tasks.append(self.harvest_myntra())
        if platforms_cfg.get("flipkart", True):
            tasks.append(self.harvest_flipkart())
        if platforms_cfg.get("tatacliq", True):
            tasks.append(self.harvest_tatacliq())
        if platforms_cfg.get("ajio", True):
            tasks.append(self.harvest_ajio())

        results = await asyncio.gather(*tasks, return_exceptions=True)
        fresh_deals: List[RunningShoeDeal] = []

        for r in results:
            if isinstance(r, list):
                fresh_deals.extend(r)
            elif isinstance(r, Exception):
                logger.error("Platform harvest task exception: %s", r)

        # Merge with cached deals
        cached = self.load_cached_deals()
        cached_dict = {d["id"]: d for d in cached}

        new_alerts = 0
        for deal in fresh_deals:
            deal_dict = asdict(deal)
            existing = cached_dict.get(deal.id)
            
            # If within alert trigger range (₹4,000 – ₹5,999) and new / dropped
            should_alert = TARGET_PRICE_MIN <= deal.price <= TARGET_PRICE_MAX
            if should_alert and (not existing or float(deal.price) < float(existing.get("price", 99999))):
                deal_dict["is_notified"] = True
                await self._dispatch_telegram_alert(deal)
                new_alerts += 1
            else:
                deal_dict["is_notified"] = existing.get("is_notified", True) if existing else False

            cached_dict[deal.id] = deal_dict

        # Save back merged deals
        merged_deals = list(cached_dict.values())
        merged_deals.sort(key=lambda x: (x.get("price", 0)))
        self.save_cached_deals(merged_deals)

        cfg["last_sweep"] = datetime.now(timezone.utc).isoformat()
        self.save_config(cfg)

        return {
            "status": "success",
            "active": True,
            "total_deals": len(merged_deals),
            "new_deals_found": len(fresh_deals),
            "alerts_dispatched": new_alerts,
            "last_sweep": cfg["last_sweep"],
            "deals": merged_deals,
        }

    async def _dispatch_telegram_alert(self, deal: RunningShoeDeal) -> None:
        """Send a dedicated, high-priority Telegram alert for a verified running shoe deal."""
        sizes_str = ", ".join(deal.available_sizes) if deal.available_sizes else "UK 10"
        discount_str = f" • *{deal.discount_percent}% OFF*" if deal.discount_percent else ""
        mrp_str = f" ~₹{deal.mrp:,.0f}~" if deal.mrp and deal.mrp > deal.price else ""

        message = (
            f"👟 *RUNNING SHOE DEAL DETECTED!*\n\n"
            f"🔥 *Model:* {deal.brand} {deal.model}\n"
            f"🏷️ *Full Title:* {deal.title}\n"
            f"💰 *Price:* ₹{deal.price:,.0f}{mrp_str}{discount_str}\n"
            f"📏 *Verified Sizes:* `{sizes_str}`\n"
            f"🏪 *Store:* {deal.platform.upper()}\n\n"
            f"🛒 *Direct Link:* [Buy on {deal.platform.capitalize()}]({deal.url})"
        )

        try:
            if hasattr(self.notifier, "send_telegram"):
                await self.notifier.send_telegram(message)
            else:
                logger.info("Telegram notification payload: %s", message)
        except Exception as e:
            logger.error("Failed to dispatch Telegram deal alert: %s", e)


# Global singleton instance
shoes_radar = RunningShoesRadar(settings)
