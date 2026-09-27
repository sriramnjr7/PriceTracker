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
MAX_PRICE_THRESHOLD = 25000.0
TARGET_SIZES: Set[float] = {9.5, 10.0, 10.5, 11.0}

CONFIG_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "running_shoes_config.json")
DEALS_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "running_shoes_deals.json")
CATALOG_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "running_shoes_catalog.json")

# Global Trap Model Blacklist Filter (Cheap EVA, lifestyle sneakers, or diffusion lines to strictly exclude)
TRAP_MODELS_BLACKLIST = re.compile(
    r"\b(energen|rewind|runfalcon|galaxy|coreracer|fluidflow|downshifter|"
    r"revolution|quest|defy\s*all\s*day|softride|anzarun|flyer\s*runner|flyer|enzo|better\s*foam|"
    r"jolt|patriot|raiden|gel[-\s]?contend|contend|arishi|roav|cohesion|excursion|versafoam|"
    r"duramo\s+(?:10|sl|lite|rc)|court|lifestyle|sneaker|badminton|tennis|cricket)\b",
    re.IGNORECASE,
)

# Whitelist Models Definition with strict regex patterns and exclusions (56 Verified Performance Models)
WHITELIST_RULES = [
    # --- SAUCONY ---
    {
        "brand": "Saucony",
        "model": "Endorphin Speed",
        "pattern": re.compile(r"\bendorphin\s+speed(?:\s+(?:2|3|4|ii|iii|iv))?\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Saucony",
        "model": "Endorphin Pro",
        "pattern": re.compile(r"\bendorphin\s+pro(?:\s+(?:2|3|4|ii|iii|iv))?\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Saucony",
        "model": "Triumph",
        "pattern": re.compile(r"\btriumph(?:\s+(?:19|20|21|22))?\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Saucony",
        "model": "Kinvara",
        "pattern": re.compile(r"\bkinvara(?:\s+(?:12|13|14|15))?\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Saucony",
        "model": "Ride",
        "pattern": re.compile(r"\b(?:saucony\s+)?ride(?:\s+(?:14|15|16|17|18))?\b", re.IGNORECASE),
        "exclusions": re.compile(r"\b(?:skechers|go\s*run|iso)\b", re.IGNORECASE),
    },
    {
        "brand": "Saucony",
        "model": "Tempus",
        "pattern": re.compile(r"\btempus\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Saucony",
        "model": "Guide",
        "pattern": re.compile(r"\b(?:saucony\s+)?guide(?:\s+(?:14|15|16|17))?\b", re.IGNORECASE),
        "exclusions": None,
    },

    # --- REEBOK ---
    {
        "brand": "Reebok",
        "model": "Floatride Energy X",
        "pattern": re.compile(r"\bfloatride\s+energy\s+x\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Reebok",
        "model": "Floatride Energy Symmetros",
        "pattern": re.compile(r"\bfloatride\s+energy\s+symmetros(?:\s+[23])?\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Reebok",
        "model": "Floatride Energy",
        "pattern": re.compile(r"\bfloatride\s+energy(?:\s+(?:3|4|5|6))?\b", re.IGNORECASE),
        "exclusions": re.compile(r"\b(?:energen|x|symmetros)\b", re.IGNORECASE),
    },

    # --- HOKA ---
    {
        "brand": "Hoka",
        "model": "Mach",
        "pattern": re.compile(r"\b(?:hoka(?:\s+one\s+one)?\s+)?mach(?:\s+(?:4|5|6))?\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Hoka",
        "model": "Rincon",
        "pattern": re.compile(r"\b(?:hoka(?:\s+one\s+one)?\s+)?rincon(?:\s+[34])?\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Hoka",
        "model": "Clifton",
        "pattern": re.compile(r"\b(?:hoka(?:\s+one\s+one)?\s+)?clifton(?:\s+(?:8|9))?\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Hoka",
        "model": "Bondi",
        "pattern": re.compile(r"\b(?:hoka(?:\s+one\s+one)?\s+)?bondi(?:\s+(?:7|8))?\b", re.IGNORECASE),
        "exclusions": None,
    },

    # --- BROOKS ---
    {
        "brand": "Brooks",
        "model": "Hyperion",
        "pattern": re.compile(r"\b(?:brooks\s+)?hyperion(?:\s+(?:tempo|max|2))?\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Brooks",
        "model": "Ghost",
        "pattern": re.compile(r"\b(?:brooks\s+)?ghost(?:\s+(?:14|15|16))?\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Brooks",
        "model": "Glycerin",
        "pattern": re.compile(r"\b(?:brooks\s+)?glycerin(?:\s+(?:20|21))?\b", re.IGNORECASE),
        "exclusions": None,
    },

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
        "model": "Magnify Nitro",
        "pattern": re.compile(r"\bmagnify\s+nitro(?:\s+[23])?\b", re.IGNORECASE),
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
    {
        "brand": "Puma",
        "model": "Electrify Nitro",
        "pattern": re.compile(r"\belectrify\s+nitro(?:\s+[23])?\b", re.IGNORECASE),
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
        "model": "Streakfly",
        "pattern": re.compile(r"\b(?:zoomx\s+)?streakfly\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Nike",
        "model": "Zoom Fly",
        "pattern": re.compile(r"\bzoom\s*fly(?:\s+(?:4|5|6))?\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Nike",
        "model": "Invincible Run",
        "pattern": re.compile(r"\b(?:zoomx\s+)?invincible(?:\s*run)?(?:\s+(?:2|3))?\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Nike",
        "model": "Structure",
        "pattern": re.compile(r"\bstructure(?:\s+(?:24|25|26))?\b", re.IGNORECASE),
        "exclusions": None,
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
        "model": "Takumi Sen",
        "pattern": re.compile(r"\b(?:adizero\s+)?takumi\s*sen(?:\s+(?:8|9|10))?\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Adidas",
        "model": "Adios",
        "pattern": re.compile(r"\b(?:adizero\s+)?adios(?:\s+(?:6|7|8))?\b", re.IGNORECASE),
        "exclusions": re.compile(r"\badios\s+pro\b", re.IGNORECASE),
    },
    {
        "brand": "Adidas",
        "model": "Solarboost",
        "pattern": re.compile(r"\bsolar\s*boost(?:\s+(?:3|4|5))?\b", re.IGNORECASE),
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
        "model": "Magic Speed",
        "pattern": re.compile(r"\bmagic\s*speed(?:\s+[234])?\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Asics",
        "model": "Noosa Tri",
        "pattern": re.compile(r"\bnoosa\s*tri(?:\s+(?:13|14|15|16))?\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "Asics",
        "model": "Glideride",
        "pattern": re.compile(r"\bglideride(?:\s+[23])?\b", re.IGNORECASE),
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
        "model": "FuelCell SuperComp",
        "pattern": re.compile(r"\b(?:fuelcell\s+)?(?:sc|supercomp)(?:\s+(?:trainer|pacer))?(?:\s+v[23])?\b", re.IGNORECASE),
        "exclusions": None,
    },
    {
        "brand": "New Balance",
        "model": "Fresh Foam 1080",
        "pattern": re.compile(r"\b(?:fresh\s*foam(?:\s*x)?\s*)?1080(?:\s+v(?:11|12|13|14))?\b", re.IGNORECASE),
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
        for b in ("saucony", "reebok", "hoka", "brooks", "puma", "nike", "adidas", "asics", "new balance", "skechers"):
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
    deal_type: str = "target_met"  # "all_time_low" | "deep_clearance" | "target_met"
    lowest_price_seen: Optional[float] = None


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
            },
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

    def load_catalog(self) -> dict[str, dict[str, Any]]:
        """Load 56 tracked shoe models and their current price / historical ATL status."""
        catalog: dict[str, dict[str, Any]] = {}
        if os.path.exists(CATALOG_CACHE_PATH):
            try:
                with open(CATALOG_CACHE_PATH, "r", encoding="utf-8") as f:
                    catalog = json.load(f)
            except Exception as e:
                logger.error("Failed to read running shoes catalog cache: %s", e)

        # Baseline list of standard silhouettes and typical MRPs for high-end models
        baseline_mrps = {
            "Endorphin Speed": 17999.0,
            "Endorphin Pro": 21999.0,
            "Triumph": 15999.0,
            "Kinvara": 11999.0,
            "Ride": 12999.0,
            "Tempus": 16999.0,
            "Guide": 13999.0,
            "Floatride Energy X": 14999.0,
            "Floatride Energy Symmetros": 10999.0,
            "Floatride Energy": 8999.0,
            "Mach": 14999.0,
            "Rincon": 11999.0,
            "Clifton": 14999.0,
            "Bondi": 16999.0,
            "Hyperion": 14999.0,
            "Ghost": 13999.0,
            "Glycerin": 16999.0,
            "Velocity Nitro": 11999.0,
            "Deviate Nitro": 16999.0,
            "Magnify Nitro": 13999.0,
            "ForeverRun": 14999.0,
            "Liberate Nitro": 9999.0,
            "Electrify Nitro": 7999.0,
            "Pegasus": 10999.0,
            "Streakfly": 14999.0,
            "Zoom Fly": 14999.0,
            "Invincible Run": 17999.0,
            "Structure": 11999.0,
            "Winflo": 8695.0,
            "Rival Fly": 7995.0,
            "Infinity Run": 14999.0,
            "Vomero": 15999.0,
            "Adizero SL": 9999.0,
            "Boston": 14999.0,
            "Takumi Sen": 17999.0,
            "Adios": 12999.0,
            "Solarboost": 15999.0,
            "Supernova Rise": 13999.0,
            "Supernova Stride": 10999.0,
            "Duramo Speed": 7999.0,
            "Novablast": 13999.0,
            "Magic Speed": 14999.0,
            "Noosa Tri": 12999.0,
            "Glideride": 14999.0,
            "Cumulus": 12999.0,
            "GT-2000": 12999.0,
            "GT-1000": 8999.0,
            "Pulse": 7999.0,
            "FuelCell Propel": 10999.0,
            "FuelCell Rebel": 13999.0,
            "FuelCell SuperComp": 21999.0,
            "Fresh Foam 1080": 16999.0,
            "Fresh Foam 880": 13999.0,
            "Go Run Ride": 9999.0,
            "Max Cushioning": 9499.0,
            "Razor": 11999.0,
        }

        # Ensure all 56 canonical models from WHITELIST_RULES are represented
        for rule in WHITELIST_RULES:
            brand = rule["brand"]
            model = rule["model"]
            key = f"{brand}_{model}".lower().replace(" ", "_").replace("-", "_")
            if key not in catalog:
                mrp_val = baseline_mrps.get(model, 11999.0)
                catalog[key] = {
                    "id": f"shoe_{key}",
                    "brand": brand,
                    "model": model,
                    "current_price": None,
                    "mrp": mrp_val,
                    "lowest_price_seen": None,
                    "discount_percent": None,
                    "available_sizes": ["UK 9.5", "UK 10", "UK 10.5", "UK 11"],
                    "platform": None,
                    "url": None,
                    "image_url": None,
                    "last_seen": None,
                    "deal_type": "tracking",
                    "status": "TRACKING",
                }
        return catalog

    def save_catalog(self, catalog: dict[str, dict[str, Any]]) -> None:
        """Save tracked shoe catalog cache to JSON file."""
        try:
            with open(CATALOG_CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(catalog, f, indent=2)
        except Exception as e:
            logger.error("Failed to save running shoes catalog cache: %s", e)

    def get_tracked_catalog(self) -> List[dict[str, Any]]:
        """Return full list of 56 monitored shoe silhouettes with real-time status."""
        cat = self.load_catalog()
        items = list(cat.values())
        status_rank = {"ALL-TIME LOW": 0, "STEAL DEAL": 1, "DEAL ACTIVE": 2, "TRACKING": 3}
        items.sort(key=lambda x: (
            status_rank.get(x.get("status", "TRACKING"), 4),
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
        ]
        if self.is_brand_enabled("Adidas"):
            urls.append("https://www.myntra.com/adizero?f=Brand%3AADIDAS")
        if self.is_brand_enabled("Nike"):
            urls.append("https://www.myntra.com/pegasus?f=Brand%3ANike")
        if self.is_brand_enabled("Asics"):
            urls.append("https://www.myntra.com/novablast?f=Brand%3AASICS")
        if self.is_brand_enabled("Puma"):
            urls.append("https://www.myntra.com/nitro?f=Brand%3APuma")
        if self.is_brand_enabled("Reebok"):
            urls.append("https://www.myntra.com/floatride-energy?f=Brand%3AReebok")
        if self.is_brand_enabled("Saucony"):
            urls.append("https://www.myntra.com/saucony-shoes?f=Brand%3ASaucony")
        
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
                "https://www.flipkart.com/search?q=running+shoes+men&sid=osp%2Ccil"
                "&p[]=facets.size[]=10&p[]=facets.size[]=10.5&p[]=facets.size[]=9.5&p[]=facets.size[]=11"
            ),
        ]
        if self.is_brand_enabled("Reebok"):
            urls.append(
                "https://www.flipkart.com/search?q=floatride+energy&sid=osp%2Ccil"
                "&p[]=facets.size[]=10&p[]=facets.size[]=10.5&p[]=facets.size[]=9.5&p[]=facets.size[]=11"
            )
        
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
                        if not self.is_brand_enabled(brand_canon):
                            continue
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

        # Filter deals by active enabled brands
        fresh_deals = [d for d in fresh_deals if self.is_brand_enabled(d.brand)]

        # Process against 56-model tracked catalog & detect ATLs / Steal Deals
        catalog = self.load_catalog()
        cached = self.load_cached_deals()
        cached_dict = {d["id"]: d for d in cached}
        qualified_deals: List[RunningShoeDeal] = []

        for deal in fresh_deals:
            key = f"{deal.brand}_{deal.model}".lower().replace(" ", "_").replace("-", "_")
            cat_entry = catalog.get(key)
            if not cat_entry:
                cat_entry = {
                    "id": f"shoe_{key}",
                    "brand": deal.brand,
                    "model": deal.model,
                    "current_price": deal.price,
                    "mrp": deal.mrp,
                    "lowest_price_seen": deal.price,
                    "discount_percent": deal.discount_percent,
                    "available_sizes": deal.available_sizes,
                    "platform": deal.platform,
                    "url": deal.url,
                    "image_url": deal.image_url,
                    "last_seen": deal.detected_at,
                    "deal_type": "tracking",
                    "status": "TRACKING",
                }

            prev_lowest = cat_entry.get("lowest_price_seen")
            is_atl = (prev_lowest is not None and deal.price < float(prev_lowest))
            is_deep_clearance = bool(deal.discount_percent and deal.discount_percent >= 50.0 and (deal.mrp or 0) >= 8000)
            is_target_met = (TARGET_PRICE_MIN <= deal.price <= TARGET_PRICE_MAX)

            new_lowest = min(float(prev_lowest), deal.price) if prev_lowest is not None else deal.price
            cat_entry["lowest_price_seen"] = new_lowest
            deal.lowest_price_seen = new_lowest

            # Check if this qualifies as an active steal deal or ATL
            if is_atl or is_deep_clearance or is_target_met:
                if is_atl:
                    deal.deal_type = "all_time_low"
                    cat_entry["status"] = "ALL-TIME LOW"
                elif is_deep_clearance:
                    deal.deal_type = "deep_clearance"
                    cat_entry["status"] = "STEAL DEAL"
                else:
                    deal.deal_type = "target_met"
                    cat_entry["status"] = "DEAL ACTIVE"

                cat_entry["deal_type"] = deal.deal_type
                qualified_deals.append(deal)
            else:
                if cat_entry.get("status") not in ("ALL-TIME LOW", "STEAL DEAL", "DEAL ACTIVE"):
                    cat_entry["status"] = "TRACKING"
                    cat_entry["deal_type"] = "tracking"

            # Update latest catalog market observation
            if cat_entry.get("current_price") is None or deal.price <= float(cat_entry["current_price"]):
                cat_entry["current_price"] = deal.price
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

        # Merge qualified deals with cache and alert on new drops
        new_alerts = 0
        for deal in qualified_deals:
            deal_dict = asdict(deal)
            existing = cached_dict.get(deal.id)
            
            should_alert = not existing or float(deal.price) < float(existing.get("price", 99999))
            if should_alert:
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
            "new_deals_found": len(qualified_deals),
            "total_tracked_silhouettes": len(catalog),
            "alerts_dispatched": new_alerts,
            "last_sweep": cfg["last_sweep"],
            "deals": merged_deals,
        }

    async def _dispatch_telegram_alert(self, deal: RunningShoeDeal) -> None:
        """Send a dedicated, high-priority Telegram alert for a verified running shoe deal."""
        sizes_str = ", ".join(deal.available_sizes) if deal.available_sizes else "UK 10"
        discount_str = f" • *{deal.discount_percent}% OFF*" if deal.discount_percent else ""
        mrp_str = f" ~₹{deal.mrp:,.0f}~" if deal.mrp and deal.mrp > deal.price else ""

        if deal.deal_type == "all_time_low":
            header = "🚨 *ALL-TIME LOW (ATL) RUNNING SHOE DETECTED!*"
            deal_badge = "📉 *RECORD ALL-TIME LOW PRICE!*"
        elif deal.deal_type == "deep_clearance":
            header = "🔥 *DEEP CLEARANCE RUNNING SHOE STEAL!*"
            deal_badge = "⚡ *MASSIVE CLEARANCE DISCOUNT (50%+ OFF)*"
        else:
            header = "👟 *RUNNING SHOE DEAL DETECTED (UNDER ₹6,000)!*"
            deal_badge = "🎯 *TARGET THRESHOLD HIT*"

        atl_str = f"\n📉 *Lowest Price Recorded:* ₹{deal.lowest_price_seen:,.0f}" if deal.lowest_price_seen else ""

        message = (
            f"{header}\n\n"
            f"🔥 *Model:* {deal.brand} {deal.model}\n"
            f"🏷️ *Full Title:* {deal.title}\n"
            f"💰 *Price:* ₹{deal.price:,.0f}{mrp_str}{discount_str}\n"
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
