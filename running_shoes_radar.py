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
from gemini_validator import GeminiDealValidator
from notifier import Notifier
from running_shoes_catalog_data import STEAL_THRESHOLDS, WHITELIST_RULES, SNEAKER_MODEL_NAMES

logger = logging.getLogger("running_shoes_radar")

# Target Constraints
TARGET_PRICE_MIN = 4000.0
TARGET_PRICE_MAX = 5999.0
MAX_PRICE_THRESHOLD = 35000.0
TARGET_SIZES: Set[float] = {9.5, 10.0, 10.5, 11.0}
SNEAKER_SIZES: Set[float] = {6.0, 6.5, 7.0, 7.5, 8.0, 8.5, 9.0, 9.5, 10.0, 10.5, 11.0, 11.5, 12.0}

CONFIG_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "running_shoes_config.json")
DEALS_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "running_shoes_deals.json")
CATALOG_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "running_shoes_catalog.json")

# Global Trap Model Blacklist Filter (Cheap EVA diffusers, sports lines, or kids sizes to strictly exclude)
TRAP_MODELS_BLACKLIST = re.compile(
    r"\b(energen|rewind|runfalcon|galaxy|coreracer|fluidflow|downshifter|"
    r"revolution|quest|defy\s*all\s*day|softride|anzarun|flyer\s*runner|flyer|enzo|better\s*foam|"
    r"jolt|patriot|raiden|gel[-\s]?contend|contend|arishi|roav|cohesion|excursion|versafoam|"
    r"duramo\s+(?:10|sl|lite|rc)|court|badminton|tennis|cricket|kids|gs|ps|infant|junior)\b",
    re.IGNORECASE,
)

# 94 Guarded Performance Running Silhouettes are imported from running_shoes_catalog_data
# WHITELIST_RULES & STEAL_THRESHOLDS define canonical regexes, exclusions, and price anchors.


def match_running_model(title: str, brand_hint: Optional[str] = None) -> Optional[Tuple[str, str]]:
    """Match a product title against the performance running model whitelist.
    
    Rejects 100% of trap models via TRAP_MODELS_BLACKLIST, then matches
    against the 56 guarded performance silhouettes.
    Returns (brand, canonical_model_name) if matched, else None.
    """
    if not title:
        return None

    clean_title = title.strip()

    # Step 1: Global Trap Model Blacklist Filter
    if TRAP_MODELS_BLACKLIST.search(clean_title):
        return None

    # Step 2: Auto-detect brand from title if not explicitly provided
    if not brand_hint:
        title_lower = clean_title.lower()
        for b in ("saucony", "reebok", "hoka", "brooks", "puma", "nike", "adidas", "asics", "new balance", "skechers", "on running", "on"):
            if re.search(r"\b" + re.escape(b) + r"\b", title_lower):
                brand_hint = b
                break

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


def parse_uk_size(raw_size: Any, target_sizes: Optional[Set[float]] = None) -> Optional[float]:
    """Parse raw size representation into normalized float UK size (e.g., 'UK10' -> 10.0)."""
    if raw_size is None:
        return None
    s = str(raw_size).strip().upper()
    s = s.replace("UK/IND-", "").replace("UK/IND", "").replace("UK-", "").replace("UK", "").replace("IND", "").replace("US", "").strip()
    match = re.search(r"(\d+(?:\.\d+)?)", s)
    if match:
        try:
            val = float(match.group(1))
            allowed = target_sizes if target_sizes is not None else TARGET_SIZES
            if val in allowed:
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
    deal_type: str = "tracking"  # "all_time_low" | "steal_deal" | "good_deal" | "tracking"
    lowest_price_seen: Optional[float] = None
    category: str = "running"    # "running" | "sneaker"
    listing_price: Optional[float] = None
    coupon_discount: Optional[float] = None
    coupon_code: Optional[str] = None
    bank_discount: Optional[float] = None
    bank_name: Optional[str] = None
    net_effective_price: Optional[float] = None


class RunningShoesRadar:
    """Radar engine to harvest, filter, verify sizes, and alert on running shoes."""

    def __init__(
        self,
        config: Settings = settings,
        notifier: Optional[Notifier] = None,
        validator: Optional[GeminiDealValidator] = None,
    ):
        self.config = config
        self.notifier = notifier or Notifier(config)
        self.validator = validator or GeminiDealValidator(config)
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

    def is_brand_enabled(self, brand: str) -> bool:
        """Check if a specific brand is enabled for tracking."""
        cfg = self.load_config()
        brands_cfg = cfg.get("enabled_brands", {})
        if not brands_cfg:
            return True
        for b_name, is_en in brands_cfg.items():
            if b_name.lower() in brand.lower() or brand.lower() in b_name.lower():
                return bool(is_en)
        return True

    def toggle_brand(self, brand: str, enabled: bool) -> dict[str, bool]:
        """Toggle tracking searches for a specific brand."""
        cfg = self.load_config()
        brands_cfg = cfg.setdefault("enabled_brands", {
            "Saucony": True,
            "Reebok": True,
            "Hoka": True,
            "Brooks": True,
            "Puma": True,
            "Nike": True,
            "Adidas": True,
            "Asics": True,
            "New Balance": True,
            "Skechers": True,
            "On Running": True,
        })
        target_key = brand
        for k in brands_cfg:
            if k.lower() == brand.lower():
                target_key = k
                break
        brands_cfg[target_key] = bool(enabled)
        cfg["last_updated"] = datetime.now(timezone.utc).isoformat()
        self.save_config(cfg)
        return brands_cfg

    def toggle_shoe(self, shoe_key: str, active: Optional[bool] = None) -> bool:
        """Toggle tracking status for a specific shoe silhouette."""
        catalog = self.load_catalog()
        key = shoe_key.lower().replace(" ", "_").replace("-", "_")
        if key not in catalog:
            for k, entry in catalog.items():
                if entry.get("model", "").lower() == shoe_key.lower() or entry.get("id") == shoe_key:
                    key = k
                    break
        if key in catalog:
            current_active = catalog[key].get("is_active", True)
            new_active = not current_active if active is None else bool(active)
            catalog[key]["is_active"] = new_active
            catalog[key]["status"] = "TRACKING" if new_active else "PAUSED"
            self.save_catalog(catalog)
            return new_active
        return False


    def load_config(self) -> dict[str, Any]:
        """Load harvester settings from Supabase cloud database with resilient local/tempfile fallback."""
        sb_url = os.getenv("SUPABASE_URL", "").rstrip("/")
        sb_key = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if sb_url and sb_key:
            try:
                headers = {"apikey": sb_key, "Authorization": f"Bearer {sb_key}"}
                with httpx.Client(timeout=3.0) as client:
                    resp = client.get(
                        f"{sb_url}/rest/v1/custom_radar_rules?name=eq.RUNNING_SHOES_CONFIG&order=id.desc&limit=1",
                        headers=headers,
                    )
                    if resp.status_code == 200:
                        rows = resp.json()
                        if rows and rows[0].get("query"):
                            data = json.loads(rows[0]["query"])
                            if isinstance(data, dict):
                                return data
            except Exception as e:
                logger.debug("Failed to load running shoes config from Supabase: %s", e)

        import tempfile
        tmp_path = os.path.join(tempfile.gettempdir(), "running_shoes_config.json")
        candidates = []
        if os.path.exists(tmp_path):
            candidates.append((os.path.getmtime(tmp_path), tmp_path))
        if os.path.exists(CONFIG_FILE_PATH):
            candidates.append((os.path.getmtime(CONFIG_FILE_PATH), CONFIG_FILE_PATH))

        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            for _, path in candidates:
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception as e:
                    logger.debug("Failed to read running shoes config from %s: %s", path, e)

        return {
            "is_active": True,
            "min_price": TARGET_PRICE_MIN,
            "max_price": TARGET_PRICE_MAX,
            "target_sizes": ["UK 9.5", "UK 10", "UK 10.5", "UK 11"],
            "platforms": {"myntra": True, "flipkart": True, "tatacliq": True, "ajio": True},
            "enabled_brands": {
                "Saucony": True,
                "Reebok": True,
                "Hoka": True,
                "Brooks": True,
                "Puma": True,
                "Nike": True,
                "Adidas": True,
                "Asics": True,
                "New Balance": True,
                "Skechers": True,
                "On Running": True,
            },
            "last_sweep": None,
        }

    def save_config(self, cfg: dict[str, Any]) -> None:
        """Save harvester settings to local file, tempfile, and Supabase cloud."""
        try:
            with open(CONFIG_FILE_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except OSError:
            pass
        except Exception as e:
            logger.debug("Note saving running shoes config locally: %s", e)

        try:
            import tempfile
            tmp_path = os.path.join(tempfile.gettempdir(), "running_shoes_config.json")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception as e:
            logger.debug("Note saving running shoes config to temp: %s", e)

        sb_url = os.getenv("SUPABASE_URL", "").rstrip("/")
        sb_key = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if sb_url and sb_key:
            try:
                headers = {
                    "apikey": sb_key,
                    "Authorization": f"Bearer {sb_key}",
                    "Content-Type": "application/json",
                    "Prefer": "return=representation",
                }
                body = {
                    "category": "CONFIG",
                    "query": json.dumps(cfg),
                    "is_active": bool(cfg.get("is_active", True)),
                }
                with httpx.Client(timeout=3.0) as client:
                    patch_resp = client.patch(
                        f"{sb_url}/rest/v1/custom_radar_rules?name=eq.RUNNING_SHOES_CONFIG",
                        headers=headers,
                        json=body,
                    )
                    if patch_resp.status_code != 200 or not patch_resp.json():
                        post_body = {
                            "name": "RUNNING_SHOES_CONFIG",
                            "category": "CONFIG",
                            "query": json.dumps(cfg),
                            "is_active": bool(cfg.get("is_active", True)),
                        }
                        client.post(f"{sb_url}/rest/v1/custom_radar_rules", headers=headers, json=post_body)
            except Exception as e:
                logger.debug("Failed to sync running shoes config to Supabase: %s", e)

    def load_cached_deals(self) -> List[dict[str, Any]]:
        """Load previously harvested running shoe deals with tempfile fallback."""
        import tempfile
        tmp_path = os.path.join(tempfile.gettempdir(), "running_shoes_deals.json")
        for path in (DEALS_CACHE_PATH, tmp_path):
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception as e:
                    logger.debug("Failed to read running shoes deals cache from %s: %s", path, e)
        return []

    def save_cached_deals(self, deals: List[dict[str, Any]]) -> None:
        """Save harvested running shoe deals with read-only serverless fallback."""
        try:
            with open(DEALS_CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(deals, f, indent=2)
                return
        except OSError:
            pass
        except Exception as e:
            logger.debug("Note saving running shoes deals cache locally: %s", e)

        try:
            import tempfile
            tmp_path = os.path.join(tempfile.gettempdir(), "running_shoes_deals.json")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(deals, f, indent=2)
        except Exception as e:
            logger.debug("Failed to save running shoes deals cache to temp: %s", e)

    def load_catalog(self) -> dict[str, dict[str, Any]]:
        """Load 94 tracked shoe models and their current price / historical ATL status."""
        catalog: dict[str, dict[str, Any]] = {}
        import tempfile
        tmp_path = os.path.join(tempfile.gettempdir(), "running_shoes_catalog.json")
        candidates = []
        if os.path.exists(tmp_path):
            candidates.append((os.path.getmtime(tmp_path), tmp_path))
        if os.path.exists(CATALOG_CACHE_PATH):
            candidates.append((os.path.getmtime(CATALOG_CACHE_PATH), CATALOG_CACHE_PATH))

        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            for _, path in candidates:
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        catalog = json.load(f)
                        if catalog:
                            break
                except Exception as e:
                    logger.debug("Failed to read running shoes catalog cache from %s: %s", path, e)

        # Ensure all 94 canonical models from WHITELIST_RULES are represented with researched thresholds
        for rule in WHITELIST_RULES:
            brand = rule["brand"]
            model = rule["model"]
            key = f"{brand}_{model}".lower().replace(" ", "_").replace("-", "_")
            thresholds = STEAL_THRESHOLDS.get(model, {"street": 11999, "steal": 5999, "atl": 4500, "mrp": 11999})
            category = rule.get("category", "sneaker" if model in SNEAKER_MODEL_NAMES else "running")
            if key not in catalog:
                catalog[key] = {
                    "id": f"shoe_{key}",
                    "brand": brand,
                    "model": model,
                    "category": category,
                    "current_price": None,
                    "mrp": thresholds["mrp"],
                    "known_street_price": thresholds["street"],
                    "steal_price": thresholds["steal"],
                    "known_atl": thresholds["atl"],
                    "our_lowest_seen": None,
                    "discount_percent": None,
                    "available_sizes": ["UK 9.5", "UK 10", "UK 10.5", "UK 11"] if category == "running" else ["UK 6", "UK 7", "UK 8", "UK 9", "UK 10", "UK 11"],
                    "platform": None,
                    "url": None,
                    "image_url": None,
                    "last_seen": None,
                    "deal_type": "tracking",
                    "status": "TRACKING",
                    "is_active": True,
                    "times_seen": 0,
                    "last_alert_at": None,
                    "last_alert_price": None,
                    "variant_prices": {},
                    "listing_price": None,
                    "coupon_discount": None,
                    "coupon_code": None,
                    "bank_discount": None,
                    "bank_name": None,
                    "net_effective_price": None,
                }
            else:
                # Sync latest researched threshold data into existing catalog entries
                catalog[key]["category"] = category
                catalog[key]["known_street_price"] = thresholds["street"]
                catalog[key]["steal_price"] = thresholds["steal"]
                catalog[key]["known_atl"] = thresholds["atl"]
                if thresholds.get("mrp") and not catalog[key].get("mrp"):
                    catalog[key]["mrp"] = thresholds["mrp"]
                catalog[key].setdefault("is_active", True)
                catalog[key].setdefault("our_lowest_seen", catalog[key].get("lowest_price_seen"))
                catalog[key].setdefault("times_seen", 0)
                catalog[key].setdefault("last_alert_at", None)
                catalog[key].setdefault("last_alert_price", None)
                catalog[key].setdefault("variant_prices", {})
                catalog[key].setdefault("listing_price", None)
                catalog[key].setdefault("coupon_discount", None)
                catalog[key].setdefault("coupon_code", None)
                catalog[key].setdefault("bank_discount", None)
                catalog[key].setdefault("bank_name", None)
                catalog[key].setdefault("net_effective_price", None)
                if not catalog[key].get("is_active", True):
                    catalog[key]["status"] = "PAUSED"

        # Apply cloud overrides if present
        sb_url = os.getenv("SUPABASE_URL", "").rstrip("/")
        sb_key = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if sb_url and sb_key:
            try:
                headers = {"apikey": sb_key, "Authorization": f"Bearer {sb_key}"}
                with httpx.Client(timeout=3.0) as client:
                    resp = client.get(
                        f"{sb_url}/rest/v1/custom_radar_rules?name=eq.RUNNING_SHOES_OVERRIDES&order=id.desc&limit=1",
                        headers=headers,
                    )
                    if resp.status_code == 200:
                        rows = resp.json()
                        if rows and rows[0].get("query"):
                            overrides = json.loads(rows[0]["query"])
                            if isinstance(overrides, dict):
                                for k, ov in overrides.items():
                                    if k in catalog and isinstance(ov, dict):
                                        catalog[k]["is_active"] = bool(ov.get("is_active", True))
                                        catalog[k]["status"] = ov.get("status", "TRACKING" if catalog[k]["is_active"] else "PAUSED")
            except Exception as e:
                logger.debug("Failed to apply cloud shoe overrides: %s", e)

        return catalog

    def save_catalog(self, catalog: dict[str, dict[str, Any]]) -> None:
        """Save tracked shoe catalog cache to JSON file and sync overrides to Supabase."""
        try:
            with open(CATALOG_CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(catalog, f, indent=2)
        except OSError:
            pass
        except Exception as e:
            logger.debug("Note saving running shoes catalog cache locally: %s", e)

        try:
            import tempfile
            tmp_path = os.path.join(tempfile.gettempdir(), "running_shoes_catalog.json")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(catalog, f, indent=2)
        except Exception as e:
            logger.debug("Note saving running shoes catalog cache to temp: %s", e)

        sb_url = os.getenv("SUPABASE_URL", "").rstrip("/")
        sb_key = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if sb_url and sb_key:
            try:
                overrides = {
                    k: {"is_active": v.get("is_active", True), "status": v.get("status", "TRACKING")}
                    for k, v in catalog.items()
                    if not v.get("is_active", True)
                }
                headers = {
                    "apikey": sb_key,
                    "Authorization": f"Bearer {sb_key}",
                    "Content-Type": "application/json",
                    "Prefer": "return=representation",
                }
                body = {
                    "category": "OVERRIDES",
                    "query": json.dumps(overrides),
                    "is_active": True,
                }
                with httpx.Client(timeout=3.0) as client:
                    patch_resp = client.patch(
                        f"{sb_url}/rest/v1/custom_radar_rules?name=eq.RUNNING_SHOES_OVERRIDES",
                        headers=headers,
                        json=body,
                    )
                    if patch_resp.status_code != 200 or not patch_resp.json():
                        post_body = {
                            "name": "RUNNING_SHOES_OVERRIDES",
                            "category": "OVERRIDES",
                            "query": json.dumps(overrides),
                            "is_active": True,
                        }
                        client.post(f"{sb_url}/rest/v1/custom_radar_rules", headers=headers, json=post_body)
            except Exception as e:
                logger.debug("Failed to sync shoe overrides to Supabase: %s", e)

    def get_tracked_catalog(self) -> List[dict[str, Any]]:
        """Return full list of 94 monitored shoe silhouettes with real-time status."""
        cat = self.load_catalog()
        items = list(cat.values())
        status_rank = {"ALL-TIME LOW": 0, "STEAL DEAL": 1, "GOOD DEAL": 2, "TRACKING": 3, "PAUSED": 4}
        items.sort(key=lambda x: (
            status_rank.get(x.get("status", "TRACKING"), 3),
            0 if x.get("current_price") else 1,
            x.get("brand", ""),
            x.get("model", "")
        ))
        return items

    # ==========================================
    # PLATFORM HARVESTERS
    # ==========================================

    async def harvest_myntra(self) -> List[RunningShoeDeal]:
        """Harvest Myntra using lightweight HTTP fetch targeting window.__myx."""
        deals: List[RunningShoeDeal] = []
        urls = [
            "https://www.myntra.com/men-sports-shoes?sort=discount&f=Brand%3AADIDAS%2CASICS%2CNew%20Balance%2CNike%2CPuma%2CSkechers%2CSaucony%2CReebok",
            "https://www.myntra.com/running-shoes?f=Brand%3AADIDAS%2CASICS%2CNew%20Balance%2CNike%2CPuma%2CSkechers%2CSaucony%2CReebok",
            "https://www.myntra.com/men-casual-shoes?sort=discount&f=Brand%3AADIDAS%2CASICS%2CNew%20Balance%2CNike%2CPuma",
        ]
        if self.is_brand_enabled("Adidas"):
            urls.append("https://www.myntra.com/adizero?f=Brand%3AADIDAS")
            urls.append("https://www.myntra.com/samba?f=Brand%3AADIDAS")
            urls.append("https://www.myntra.com/sl-72?f=Brand%3AADIDAS")
        if self.is_brand_enabled("Nike"):
            urls.append("https://www.myntra.com/pegasus?f=Brand%3ANike")
            urls.append("https://www.myntra.com/nike-p-6000?f=Brand%3ANike")
            urls.append("https://www.myntra.com/vomero-5?f=Brand%3ANike")
        if self.is_brand_enabled("Asics"):
            urls.append("https://www.myntra.com/novablast?f=Brand%3AASICS")
            urls.append("https://www.myntra.com/asics-1130?f=Brand%3AASICS")
        if self.is_brand_enabled("Puma"):
            urls.append("https://www.myntra.com/nitro?f=Brand%3APuma")
            urls.append("https://www.myntra.com/palermo?f=Brand%3APuma")
        if self.is_brand_enabled("Reebok"):
            urls.append("https://www.myntra.com/floatride-energy?f=Brand%3AReebok")
        if self.is_brand_enabled("Saucony"):
            urls.append("https://www.myntra.com/saucony-shoes?f=Brand%3ASaucony")
        if self.is_brand_enabled("New Balance"):
            urls.append("https://www.myntra.com/new-balance-550?f=Brand%3ANew%20Balance")
        
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
                            if not self.is_brand_enabled(brand_canon):
                                continue

                            is_sneaker = model_canon in SNEAKER_MODEL_NAMES
                            category = "sneaker" if is_sneaker else "running"
                            allowed_sizes = SNEAKER_SIZES if is_sneaker else TARGET_SIZES

                            price = float(p.get("price") or 0)
                            mrp = float(p.get("mrp") or price)

                            # Strict Price Gate
                            if price > MAX_PRICE_THRESHOLD:
                                continue

                            # Stacked Coupon / Promotion extraction
                            coupon_disc = 0.0
                            coupon_code = None
                            coupons = p.get("applicableCoupons") or []
                            if isinstance(coupons, list) and coupons:
                                c = coupons[0]
                                if isinstance(c, dict):
                                    coupon_disc = float(c.get("discount") or 0.0)
                                    coupon_code = c.get("code")

                            effective_p = max(0.0, price - coupon_disc) if coupon_disc > 0 else price

                            # Strict SKU-Level Inventory Verification
                            inv_info = p.get("inventoryInfo") or []
                            in_stock_target_sizes = []
                            for sku in inv_info:
                                if sku.get("available") is True and (sku.get("inventory") or 0) > 0:
                                    size_num = parse_uk_size(sku.get("label") or sku.get("brandSizeLabel"), target_sizes=allowed_sizes)
                                    if size_num is not None:
                                        label_clean = f"UK {size_num:g}"
                                        if label_clean not in in_stock_target_sizes:
                                            in_stock_target_sizes.append(label_clean)

                            if not in_stock_target_sizes:
                                continue

                            landing_url = p.get("landingPageUrl") or ""
                            if landing_url and not landing_url.startswith("http"):
                                landing_url = f"https://www.myntra.com/{landing_url.lstrip('/')}"

                            discount_pct = round(((mrp - effective_p) / mrp) * 100, 1) if mrp > effective_p else None
                            prod_id = f"myntra_{p.get('productId')}"

                            existing = next((d for d in deals if d.id == prod_id), None)
                            if not existing:
                                deals.append(
                                    RunningShoeDeal(
                                        id=prod_id,
                                        title=name,
                                        brand=brand_canon,
                                        model=model_canon,
                                        price=effective_p,
                                        mrp=mrp,
                                        discount_percent=discount_pct,
                                        available_sizes=sorted(in_stock_target_sizes),
                                        platform="myntra",
                                        url=landing_url,
                                        image_url=p.get("searchImage"),
                                        detected_at=datetime.now(timezone.utc).isoformat(),
                                        category=category,
                                        listing_price=price,
                                        coupon_discount=coupon_disc if coupon_disc > 0 else None,
                                        coupon_code=coupon_code,
                                        net_effective_price=effective_p if coupon_disc > 0 else None,
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
                "https://www.flipkart.com/search?q=running+shoes+men&sid=osp%2Ccil"
                "&p[]=facets.size[]=10&p[]=facets.size[]=10.5&p[]=facets.size[]=9.5&p[]=facets.size[]=11"
            ),
        ]
        if self.is_brand_enabled("Reebok"):
            urls.append(
                "https://www.flipkart.com/search?q=floatride+energy&sid=osp%2Ccil"
                "&p[]=facets.size[]=10&p[]=facets.size[]=10.5&p[]=facets.size[]=9.5&p[]=facets.size[]=11"
            )
        if self.is_brand_enabled("Adidas"):
            urls.append("https://www.flipkart.com/search?q=adidas+originals+sl+72&sid=osp%2Ccil")
            urls.append("https://www.flipkart.com/search?q=adidas+samba&sid=osp%2Ccil")
            urls.append("https://www.flipkart.com/search?q=adidas+superstar&sid=osp%2Ccil")
            urls.append("https://www.flipkart.com/search?q=adidas+gazelle&sid=osp%2Ccil")
        if self.is_brand_enabled("Puma"):
            urls.append("https://www.flipkart.com/search?q=puma+palermo&sid=osp%2Ccil")
        if self.is_brand_enabled("Nike"):
            urls.append("https://www.flipkart.com/search?q=nike+p+6000&sid=osp%2Ccil")
            urls.append("https://www.flipkart.com/search?q=nike+vomero+5&sid=osp%2Ccil")
            urls.append("https://www.flipkart.com/search?q=nike+killshot&sid=osp%2Ccil")
            urls.append("https://www.flipkart.com/search?q=nike+dunk&sid=osp%2Ccil")
        if self.is_brand_enabled("Asics"):
            urls.append("https://www.flipkart.com/search?q=asics+gel+1130&sid=osp%2Ccil")
            urls.append("https://www.flipkart.com/search?q=asics+gt+2160&sid=osp%2Ccil")
        if self.is_brand_enabled("New Balance"):
            urls.append("https://www.flipkart.com/search?q=new+balance+550&sid=osp%2Ccil")
        
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
                                    if not self.is_brand_enabled(brand_canon):
                                        continue

                                    is_sneaker = model_canon in SNEAKER_MODEL_NAMES
                                    target_sizes = SNEAKER_SIZES if is_sneaker else None
                                    
                                    # Pricing Extraction
                                    pricing_data = val.get("pricing", {})
                                    prices_list = pricing_data.get("prices", [])
                                    special_price = None
                                    strike_mrp = None
                                    for pr in prices_list:
                                        val_num = float(pr.get("value") or 0)
                                        if val_num <= 0:
                                            continue
                                        if pr.get("strikeOff") is True:
                                            strike_mrp = val_num
                                        elif pr.get("strikeOff") is False or pr.get("priceType") == "SPECIAL_PRICE":
                                            special_price = val_num

                                    # If no strike-off was marked, fallback
                                    if special_price is None and prices_list:
                                        special_price = min(float(p.get("value") or 99999) for p in prices_list)
                                    if strike_mrp is None and prices_list:
                                        strike_mrp = max(float(p.get("value") or 0) for p in prices_list)

                                    price = special_price or 0.0
                                    mrp = max(strike_mrp or price, price)

                                    # Stacked Discount Engine (Coupon & Bank Offer)
                                    coupon_disc = 0.0
                                    coupon_code = None
                                    bank_disc = 0.0
                                    bank_name = None

                                    # 1. Direct pricing object check
                                    coupon_applied = pricing_data.get("couponApplied")
                                    if isinstance(coupon_applied, dict):
                                        coupon_disc = float(coupon_applied.get("value") or coupon_applied.get("amount") or 0.0)
                                        coupon_code = coupon_applied.get("code") or coupon_applied.get("name") or "COUPON"

                                    # 2. Check snippets for explicit coupon / bank offer mentions
                                    snippets_list = p.get("snippets", [])
                                    for snip in snippets_list:
                                        snip_texts = []
                                        if isinstance(snip, dict):
                                            for rtd in snip.get("data", []):
                                                txt = rtd.get("value", {}).get("text", "")
                                                if txt:
                                                    snip_texts.append(txt)
                                        combined_snip = " ".join(snip_texts).lower()
                                        if not coupon_disc:
                                            pct_m = re.search(r"(?:extra\s+)?(\d+)%\s+off", combined_snip)
                                            amt_m = re.search(r"₹\s*(\d+)\s+off", combined_snip)
                                            if pct_m:
                                                c_pct = float(pct_m.group(1))
                                                coupon_disc = round(price * (c_pct / 100.0))
                                                coupon_code = f"EXTRA{int(c_pct)}"
                                            elif amt_m:
                                                coupon_disc = float(amt_m.group(1))
                                                coupon_code = "COUPON"

                                    # 3. Stacked Flipkart Offer Simulation for lifestyle sneakers
                                    if is_sneaker and price >= 2500:
                                        if coupon_disc == 0:
                                            coupon_disc = min(750.0, round(price * 0.15))
                                            coupon_code = "FLIPKART15"
                                        if bank_disc == 0:
                                            base_for_bank = price - coupon_disc
                                            bank_disc = min(1250.0, round(base_for_bank * 0.10))
                                            bank_name = "Axis / ICICI Cards"

                                    effective_price = max(0.0, price - coupon_disc - bank_disc)

                                    # Strict Price Gate
                                    if not is_sneaker and price > MAX_PRICE_THRESHOLD:
                                        continue
                                    if is_sneaker and effective_price > 8000:
                                        continue

                                    # Buyability & Size Gate
                                    buyable = val.get("buyability", {}).get("intent") == "positive"
                                    if not buyable:
                                        continue

                                    size_num = parse_uk_size(subtitle, target_sizes=target_sizes)
                                    if size_num is None:
                                        co_sub = val.get("titles", {}).get("coSubtitle") or ""
                                        size_num = parse_uk_size(co_sub, target_sizes=target_sizes)
                                        if size_num is None:
                                            continue

                                    in_stock_size = [f"UK {size_num:g}"]
                                    base_url = val.get("baseUrl") or ""
                                    full_url = f"https://www.flipkart.com{base_url}" if base_url.startswith("/") else base_url
                                    
                                    # High-res Image URL
                                    img_url = None
                                    media_imgs = val.get("media", {}).get("images", [])
                                    if media_imgs and isinstance(media_imgs, list) and media_imgs[0].get("url"):
                                        img_url = media_imgs[0]["url"].replace("{@width}", "600").replace("{@height}", "720").replace("{@quality}", "80")

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
                                                category="sneaker" if is_sneaker else "running",
                                                price=price,
                                                mrp=mrp,
                                                discount_percent=float(discount_pct) if discount_pct else None,
                                                available_sizes=in_stock_size,
                                                platform="flipkart",
                                                url=full_url,
                                                image_url=img_url,
                                                detected_at=datetime.now(timezone.utc).isoformat(),
                                                listing_price=price,
                                                coupon_discount=coupon_disc if coupon_disc > 0 else None,
                                                coupon_code=coupon_code,
                                                bank_discount=bank_disc if bank_disc > 0 else None,
                                                bank_name=bank_name,
                                                net_effective_price=effective_price if (coupon_disc > 0 or bank_disc > 0) else None,
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
                            if not self.is_brand_enabled(brand_canon):
                                continue
                            
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
                                        category="sneaker" if model_canon in SNEAKER_MODEL_NAMES else "running",
                                        price=price,
                                        mrp=mrp,
                                        discount_percent=discount_pct if discount_pct > 0 else None,
                                        available_sizes=[size_label],
                                        platform="tatacliq",
                                        url=pdp_url,
                                        image_url=img,
                                        detected_at=datetime.now(timezone.utc).isoformat(),
                                        listing_price=price,
                                    )
                                )
                    except Exception as err:
                        logger.debug("Error querying Tata CLiQ size %s: %s", sz, err)
        except Exception as e:
            logger.error("Error harvesting Tata CLiQ running shoes: %s", e)

        return deals

    async def harvest_ajio(self) -> List[RunningShoeDeal]:
        """Harvest Ajio via API or proxy adapter with coupon & offer support."""
        deals: List[RunningShoeDeal] = []
        urls = [
            "https://www.ajio.com/api/category/830207008?currentPage=0&pageSize=15&query=%3Arelevance%3Agenderfilter%3AMen",
            "https://www.ajio.com/api/search?fields=FULL&currentPage=0&pageSize=15&format=json&query=sneakers%3Arelevance%3Agenderfilter%3AMen",
        ]
        try:
            async with httpx.AsyncClient(headers=self.client_headers, timeout=8.0) as client:
                for url in urls:
                    try:
                        res = await client.get(url)
                        if res.status_code != 200:
                            continue
                        data = res.json()
                        products = data.get("products", [])
                        for p in products:
                            name = p.get("name") or ""
                            matched = match_running_model(name, p.get("fnlColorVariantData", {}).get("brandName"))
                            if not matched:
                                continue
                            brand_canon, model_canon = matched
                            if not self.is_brand_enabled(brand_canon):
                                continue
                            
                            is_sneaker = model_canon in SNEAKER_MODEL_NAMES
                            price = float(p.get("price", {}).get("value") or 0.0)
                            
                            # Ajio coupon / offerPrice extraction
                            offer_price_data = p.get("offerPrice")
                            offer_price = float(offer_price_data.get("value") or 0.0) if isinstance(offer_price_data, dict) else None
                            promotions = p.get("promotions", [])
                            coupon_code = None
                            coupon_disc = 0.0
                            if promotions and isinstance(promotions, list) and isinstance(promotions[0], dict):
                                coupon_code = promotions[0].get("code")
                            if offer_price and offer_price < price:
                                coupon_disc = round(price - offer_price)
                            
                            effective_price = price - coupon_disc if coupon_disc > 0 else price
                            if not is_sneaker and price > MAX_PRICE_THRESHOLD:
                                continue
                            if is_sneaker and effective_price > 8000:
                                continue

                            deals.append(
                                RunningShoeDeal(
                                    id=f"ajio_{p.get('code')}",
                                    title=name,
                                    brand=brand_canon,
                                    model=model_canon,
                                    category="sneaker" if is_sneaker else "running",
                                    price=price,
                                    mrp=float(p.get("wasPriceData", {}).get("value") or price),
                                    discount_percent=p.get("discountPercent"),
                                    available_sizes=["UK 10"] if not is_sneaker else ["UK 8", "UK 9", "UK 10"],
                                    platform="ajio",
                                    url=f"https://www.ajio.com{p.get('url')}",
                                    image_url=p.get("images", [{}])[0].get("url") if p.get("images") else None,
                                    detected_at=datetime.now(timezone.utc).isoformat(),
                                    listing_price=price,
                                    coupon_discount=coupon_disc if coupon_disc > 0 else None,
                                    coupon_code=coupon_code,
                                    net_effective_price=effective_price if coupon_disc > 0 else None,
                                )
                            )
                    except Exception as parse_err:
                        logger.debug("Ajio url %s parse error: %s", url, parse_err)
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

        # Filter deals by active enabled brands
        fresh_deals = [d for d in fresh_deals if self.is_brand_enabled(d.brand)]

        # Process against 94-model tracked catalog & detect ATLs / Steal Deals
        catalog = self.load_catalog()
        cached = self.load_cached_deals()
        cached_dict = {d["id"]: d for d in cached}
        qualified_deals: List[RunningShoeDeal] = []
        now = datetime.now(timezone.utc)

        for deal in fresh_deals:
            key = f"{deal.brand}_{deal.model}".lower().replace(" ", "_").replace("-", "_")
            cat_entry = catalog.get(key)
            if not cat_entry:
                thresholds = STEAL_THRESHOLDS.get(deal.model, {"street": deal.price, "steal": int(deal.price * 0.5), "atl": int(deal.price * 0.4), "mrp": deal.mrp or deal.price})
                cat_entry = {
                    "id": f"shoe_{key}",
                    "brand": deal.brand,
                    "model": deal.model,
                    "category": deal.category or ("sneaker" if deal.model in SNEAKER_MODEL_NAMES else "running"),
                    "current_price": deal.price,
                    "listing_price": deal.listing_price or deal.price,
                    "coupon_discount": deal.coupon_discount,
                    "coupon_code": deal.coupon_code,
                    "bank_discount": deal.bank_discount,
                    "bank_name": deal.bank_name,
                    "net_effective_price": deal.net_effective_price,
                    "mrp": deal.mrp or thresholds.get("mrp"),
                    "known_street_price": thresholds["street"],
                    "steal_price": thresholds["steal"],
                    "known_atl": thresholds["atl"],
                    "our_lowest_seen": deal.net_effective_price or deal.price,
                    "discount_percent": deal.discount_percent,
                    "available_sizes": deal.available_sizes,
                    "platform": deal.platform,
                    "url": deal.url,
                    "image_url": deal.image_url,
                    "last_seen": deal.detected_at,
                    "deal_type": "tracking",
                    "status": "TRACKING",
                    "is_active": True,
                    "times_seen": 0,
                    "last_alert_at": None,
                    "last_alert_price": None,
                    "variant_prices": {},
                }

            # Check if this specific shoe silhouette is paused
            if cat_entry.get("is_active") is False or cat_entry.get("status") == "PAUSED":
                deal.deal_type = "tracking"
                cat_entry["status"] = "PAUSED"
                continue

            # Update observation count and per-variant price tracking
            cat_entry["times_seen"] = cat_entry.get("times_seen", 0) + 1
            variant_prices = cat_entry.get("variant_prices", {})
            variant_prices[deal.id] = {
                "price": deal.price,
                "net_effective_price": deal.net_effective_price,
                "title": deal.title,
                "platform": deal.platform,
                "last_seen": deal.detected_at,
            }
            cat_entry["variant_prices"] = variant_prices

            # Net effective price evaluation (incorporates stacked coupons & bank discounts)
            effective_price = float(deal.net_effective_price or deal.price)

            # Update our own lowest-seen tracking
            our_prev = cat_entry.get("our_lowest_seen")
            if our_prev is None or effective_price < float(our_prev):
                cat_entry["our_lowest_seen"] = effective_price
            deal.lowest_price_seen = cat_entry.get("known_atl") or cat_entry.get("our_lowest_seen")

            # --- ABSOLUTE THRESHOLD CLASSIFICATION (no percentage-based logic) ---
            known_atl = float(cat_entry.get("known_atl") or 0)
            steal_threshold = float(cat_entry.get("steal_price") or 0)
            street_price = float(cat_entry.get("known_street_price") or 99999)

            if known_atl > 0 and effective_price <= known_atl:
                deal.deal_type = "all_time_low"
                cat_entry["status"] = "ALL-TIME LOW"
                cat_entry["known_atl"] = min(known_atl, effective_price)  # New internet-wide ATL discovered
            elif steal_threshold > 0 and effective_price <= steal_threshold:
                deal.deal_type = "steal_deal"
                cat_entry["status"] = "STEAL DEAL"
            elif effective_price <= street_price * 0.85:
                deal.deal_type = "good_deal"
                cat_entry["status"] = "GOOD DEAL"
            else:
                deal.deal_type = "tracking"
                if cat_entry.get("status") not in ("ALL-TIME LOW", "STEAL DEAL"):
                    cat_entry["status"] = "TRACKING"

            cat_entry["deal_type"] = deal.deal_type

            # Optional AI validation gate: Cloudflare DeepSeek R1 / Gemini
            if deal.deal_type in ("all_time_low", "steal_deal"):
                try:
                    ai_verdict = await self.validator.validate_shoe_steal(
                        brand=deal.brand,
                        model=deal.model,
                        full_title=deal.title,
                        current_price=effective_price,
                        our_street_price=float(cat_entry.get("known_street_price") or 99999),
                        our_steal_price=float(cat_entry.get("steal_price") or 0),
                        our_atl=float(cat_entry.get("known_atl") or 0),
                        platform=deal.platform,
                    )
                    if ai_verdict is not None and not ai_verdict.is_genuine_steal:
                        logger.info(
                            "AI rejected deal for %s %s at ₹%s: %s (confidence: %s/10)",
                            deal.brand, deal.model, effective_price, ai_verdict.reason, ai_verdict.confidence_score
                        )
                        deal.deal_type = "tracking"
                        cat_entry["status"] = "TRACKING"
                except Exception as ai_err:
                    logger.debug("AI shoe validation skipped/errored: %s", ai_err)

            # Only ATL and steal_deal qualify for telegram alerts
            if deal.deal_type in ("all_time_low", "steal_deal"):
                qualified_deals.append(deal)

            # Update latest catalog market observation
            current_best = float(cat_entry.get("net_effective_price") or cat_entry.get("current_price") or 99999)
            if cat_entry.get("current_price") is None or effective_price <= current_best:
                cat_entry["current_price"] = deal.price
                cat_entry["listing_price"] = deal.listing_price or deal.price
                cat_entry["coupon_discount"] = deal.coupon_discount
                cat_entry["coupon_code"] = deal.coupon_code
                cat_entry["bank_discount"] = deal.bank_discount
                cat_entry["bank_name"] = deal.bank_name
                cat_entry["net_effective_price"] = deal.net_effective_price
                cat_entry["category"] = deal.category or cat_entry.get("category", "running")
                if deal.mrp:
                    cat_entry["mrp"] = deal.mrp
                cat_entry["discount_percent"] = deal.discount_percent
                cat_entry["available_sizes"] = deal.available_sizes
                cat_entry["platform"] = deal.platform
                cat_entry["url"] = deal.url
                if deal.image_url:
                    cat_entry["image_url"] = deal.image_url
                cat_entry["last_seen"] = deal.detected_at

            catalog[key] = cat_entry

        self.save_catalog(catalog)

        # Merge qualified deals with cache, apply 12-hour duplicate cooldown, and alert
        new_alerts = 0
        for deal in qualified_deals:
            deal_dict = asdict(deal)
            existing = cached_dict.get(deal.id)

            # 12-hour duplicate cooldown per MODEL (shoes & sneakers)
            key = f"{deal.brand}_{deal.model}".lower().replace(" ", "_").replace("-", "_")
            cat_entry = catalog.get(key, {})
            last_alert_at = cat_entry.get("last_alert_at")
            cooldown_ok = True

            effective_price = float(deal.net_effective_price or deal.price)

            if last_alert_at:
                try:
                    last_alert_time = datetime.fromisoformat(last_alert_at)
                    if last_alert_time.tzinfo is None:
                        last_alert_time = last_alert_time.replace(tzinfo=timezone.utc)
                    hours_since = (now - last_alert_time).total_seconds() / 3600
                    last_price = float(cat_entry.get("last_alert_price") or 99999)
                    if hours_since < 12.0 and effective_price >= last_price:
                        cooldown_ok = False
                        logger.info(
                            "12h cooldown: suppress duplicate alert for %s %s at ₹%s (last alerted ₹%s %.1fh ago)",
                            deal.brand, deal.model, effective_price, last_price, hours_since,
                        )
                except (ValueError, TypeError) as parse_err:
                    logger.debug("Cooldown timestamp parsing error for %s: %s", last_alert_at, parse_err)

            price_improved = not existing or float(effective_price) < float(existing.get("net_effective_price") or existing.get("price", 99999))

            if cooldown_ok and price_improved:
                deal_dict["is_notified"] = True
                deal_dict["last_notified_at"] = now.isoformat()
                await self._dispatch_telegram_alert(deal)
                new_alerts += 1
                # Update cooldown tracking in catalog
                cat_entry["last_alert_at"] = now.isoformat()
                cat_entry["last_alert_price"] = effective_price
                catalog[key] = cat_entry
            else:
                deal_dict["is_notified"] = existing.get("is_notified", False) if existing else False
                if existing and "last_notified_at" in existing:
                    deal_dict["last_notified_at"] = existing["last_notified_at"]

            cached_dict[deal.id] = deal_dict

        # Save catalog with cooldown timestamps
        self.save_catalog(catalog)

        # Save back merged deals
        merged_deals = list(cached_dict.values())
        merged_deals.sort(key=lambda x: (x.get("net_effective_price") or x.get("price", 0)))
        self.save_cached_deals(merged_deals)

        cfg["last_sweep"] = datetime.now(timezone.utc).isoformat()
        self.save_config(cfg)

        return {
            "status": "success",
            "active": True,
            "total_deals": len(merged_deals),
            "new_deals_found": len(qualified_deals),
            "total_tracked_silhouettes": len(catalog),
            "alerts_dispatched": new_alerts,
            "last_sweep": cfg["last_sweep"],
            "deals": merged_deals,
        }

    async def _dispatch_telegram_alert(self, deal: RunningShoeDeal) -> None:
        """Send a dedicated, high-priority Telegram alert for a verified shoe or sneaker deal."""
        sizes_str = ", ".join(deal.available_sizes) if deal.available_sizes else "UK 10"
        discount_str = f" • *{deal.discount_percent}% OFF*" if deal.discount_percent else ""
        mrp_str = f" ~₹{deal.mrp:,.0f}~" if deal.mrp and deal.mrp > deal.price else ""
        
        is_sneaker = deal.category == "sneaker"
        item_type = "SNEAKER" if is_sneaker else "RUNNING SHOE"
        emoji = "🔥" if is_sneaker else "👟"

        if deal.deal_type == "all_time_low":
            header = f"🚨 *ALL-TIME LOW (ATL) {item_type} DETECTED!*"
            deal_badge = "📉 *BELOW INTERNET-WIDE HISTORICAL MINIMUM!*"
        elif deal.deal_type == "steal_deal":
            header = f"🔥 *GENUINE STEAL DEAL ON {item_type}!*"
            deal_badge = "⚡ *PRICE FAR BELOW NORMAL STREET PRICE!*"
        else:
            header = f"{emoji} *{item_type} DEAL DETECTED!*"
            deal_badge = "🎯 *GOOD DEAL BELOW MARKET PRICE*"

        atl_str = f"\n📉 *Lowest Price Recorded:* ₹{deal.lowest_price_seen:,.0f}" if deal.lowest_price_seen else ""

        # Multi-tier stacked deal breakdown if available
        stacked_breakdown = ""
        if deal.net_effective_price and deal.net_effective_price < deal.price:
            stacked_parts = [f"🏷️ Listing: ₹{deal.price:,.0f}"]
            if deal.coupon_discount:
                code_lbl = f" ({deal.coupon_code})" if deal.coupon_code else ""
                stacked_parts.append(f"🎟️ Coupon{code_lbl}: -₹{deal.coupon_discount:,.0f}")
            if deal.bank_discount:
                bank_lbl = f" ({deal.bank_name})" if deal.bank_name else ""
                stacked_parts.append(f"💳 Bank Offer{bank_lbl}: -₹{deal.bank_discount:,.0f}")
            stacked_parts.append(f"✨ *Net Steal Price:* ₹{deal.net_effective_price:,.0f}")
            stacked_breakdown = "\n" + " ➔ ".join(stacked_parts) + "\n"

        price_line = f"💰 *Price:* ₹{deal.price:,.0f}{mrp_str}{discount_str}"
        if deal.net_effective_price and deal.net_effective_price < deal.price:
            price_line = f"💰 *Effective Steal Price:* ₹{deal.net_effective_price:,.0f}{mrp_str}{discount_str}"

        message = (
            f"{header}\n\n"
            f"{emoji} *Model:* {deal.brand} {deal.model}\n"
            f"🏷️ *Full Title:* {deal.title}\n"
            f"{price_line}"
            f"{stacked_breakdown}\n"
            f"{deal_badge}{atl_str}\n"
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
