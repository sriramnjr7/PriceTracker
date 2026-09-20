"""Universal Radar Steal Rules & Master Deal Catalog with Full-Catalog Brand Faceting.

Monitors the entire product catalog of flagship brands (Apple, Samsung, Nothing, Realme, Xiaomi)
with source-level brand facets, price floors, negative keyword filters, and AI validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class RadarRule:
    """A declarative rule for hunting genuine steal deals and pricing glitches."""

    name: str
    category: str
    query: str
    brand: Optional[str] = None  # Source-level brand facet filter (e.g. 'Casio', 'Apple', 'Samsung', 'Crocs')
    platforms: List[str] = field(default_factory=lambda: ["amazon", "flipkart"])
    min_discount: float = 70.0  # Percentage discount vs MRP
    max_price: Optional[float] = None  # Hard price ceiling in INR
    min_price: Optional[float] = None  # Hard price floor in INR (eradicates cheap straps/pins)
    min_mrp: Optional[float] = None  # Minimum baseline MRP
    required_keywords: List[str] = field(default_factory=list)  # Must contain at least one of these genuine brand tokens
    negative_keywords: List[str] = field(default_factory=list)  # Rejects title if any of these match
    search_url_template: Optional[dict[str, str]] = None
    is_active: bool = True


# Pre-configured Master Rules Catalog
DEFAULT_RADAR_RULES: List[RadarRule] = [
    # 1. 2TB External Storage / SSDs (Deactivated)
    RadarRule(
        name="2TB External Hard Disk & SSD Steals",
        category="Tech & Storage",
        query="2tb external hard drive ssd seagate wd crucial sandisk",
        platforms=["amazon", "flipkart"],
        min_discount=50.0,
        max_price=5000.0,
        min_price=2000.0,
        min_mrp=6000.0,
        required_keywords=["seagate", "wd", "western digital", "crucial", "sandisk", "samsung", "toshiba", "kingston"],
        negative_keywords=["case", "cover", "enclosure", "cable", "pouch", "stand", "adapter", "sleeve"],
        is_active=False,
    ),

    # 2. Amazon Basics 80%-95% Clearance Glitches (Deactivated)
    RadarRule(
        name="Amazon Basics 80%-95% Clearance",
        category="Amazon Basics",
        query="amazon basics clearance",
        brand="AmazonBasics",
        platforms=["amazon"],
        min_discount=80.0,
        required_keywords=["amazon basics", "amazonbasics"],
        search_url_template={
            "amazon": "https://www.amazon.in/s?k=amazonbasics&rh=p_8%3A80-&sort=price-asc-rank"
        },
        is_active=False,
    ),

    # 3. The Whole Truth & Premium Whey Protein Steals (Deactivated)
    RadarRule(
        name="Premium Whey Protein Steals",
        category="Fitness & Nutrition",
        query="whey protein isolate optimum nutrition muscleblaze dymatize myprotein",
        platforms=["amazon", "flipkart", "blinkit", "zepto", "instamart", "bigbasket"],
        min_discount=50.0,
        max_price=1600.0,
        min_price=800.0,
        min_mrp=2500.0,
        required_keywords=["whole truth", "optimum nutrition", "muscleblaze", "dymatize", "myprotein", "avvatar", "asitis", "as-it-is", "nakpro", "muscletech", "isopure"],
        negative_keywords=["shaker", "bottle", "scoop", "creatine sample", "empty", "peanut butter", "multivitamin"],
        is_active=False,
    ),

    # 4. Crocs 70%+ Clearance (Deactivated)
    RadarRule(
        name="Crocs All Footwear 70%+ OFF",
        category="Fashion & Footwear",
        query="crocs",
        brand="Crocs",
        platforms=["myntra", "ajio", "amazon", "flipkart"],
        min_discount=70.0,
        min_price=800.0,
        min_mrp=2200.0,
        required_keywords=["crocs"],
        negative_keywords=["jibbitz", "charm", "charms", "pin", "pins", "keychain", "shoe cleaner", "socks", "strap", "straps"],
        search_url_template={
            "myntra": "https://www.myntra.com/crocs?f=Discount:70.0_100.0",
            "ajio": "https://www.ajio.com/s/crocs-steals?query=discount:70-100",
        },
        is_active=False,
    ),

    # 5. Acoustic & Electric Guitars Steals (Deactivated)
    RadarRule(
        name="Acoustic & Electric Guitars Steals",
        category="Music & Gear",
        query="acoustic electric guitar yamaha fender ibanez epiphone cort",
        platforms=["amazon", "flipkart"],
        min_discount=60.0,
        max_price=5000.0,
        min_price=2000.0,
        min_mrp=6500.0,
        required_keywords=["yamaha", "fender", "ibanez", "vault", "cort", "epiphone", "kadence", "juarez", "intern", "squier", "gibson"],
        negative_keywords=["strings", "pick", "strap", "capo", "bag", "cover", "stand", "hanger", "cable", "tuner", "amplifier", "amp"],
        is_active=False,
    ),

    # 6. Casio 70%+ Drops (Casio Bhawar & Flipkart Only)
    RadarRule(
        name="Casio 70%+ Drops (Bhawar & Flipkart)",
        category="Watches",
        query="casio watch",
        brand="Casio",
        platforms=["casio", "flipkart"],
        min_discount=70.0,
        min_price=None,  # casiostore.bhawar.com lists only genuine watches
        min_mrp=None,    # allows all watches with 70%+ discount regardless of price
        required_keywords=["casio", "g-shock", "gshock", "edifice", "vintage", "enticer"],
        negative_keywords=[
            "strap", "straps", "band", "bands", "resin strap", "silicone strap",
            "replacement", "belt", "loop", "buckle", "bezel", "adapter", "link",
            "pin", "spring bar", "chain", "connector", "case cover", "screen protector"
        ],
        search_url_template={
            "casio": "https://casiostore.bhawar.com/collections/all",
        },
        is_active=True,
    ),
    # 6b. Specific GBD-300 Tracker (Casio Bhawar & Flipkart)
    RadarRule(
        name="Casio GBD-300 Specific Tracker",
        category="Watches",
        query="casio g-shock gbd-300",
        brand="Casio",
        platforms=["casio", "flipkart"],
        min_discount=70.0,
        max_price=4000.0,  # Target price floor (~70% off ₹12,995 MRP)
        min_mrp=12995.0,
        required_keywords=["gbd-300", "g-300", "gbd300", "300"],
        negative_keywords=["strap", "band", "bezel", "protector"],
        search_url_template={
            "casio": (
                "https://casiostore.bhawar.com/products/casio-g-shock-gbd-300-1dr-black-digital-mens-watch,"
                "https://casiostore.bhawar.com/products/casio-g-shock-gbd-300-7dr-watch,"
                "https://casiostore.bhawar.com/products/casio-g-shock-gbd-300-9dr-watch"
            ),
        },
        is_active=True,
    ),
    # 6c. G-Shock & Edifice 50%+ Drops (Casio Bhawar & Flipkart)
    RadarRule(
        name="G-Shock & Edifice 50%+ Drops",
        category="Watches",
        query="g-shock edifice",
        brand="Casio",
        platforms=["casio", "flipkart"],
        min_discount=50.0,
        min_price=None,
        min_mrp=None,
        required_keywords=["g-shock", "gshock", "edifice"],
        negative_keywords=[
            "strap", "straps", "band", "bands", "resin strap", "silicone strap",
            "replacement", "belt", "loop", "buckle", "bezel", "adapter", "link",
            "pin", "spring bar", "chain", "connector", "case cover", "screen protector"
        ],
        search_url_template={
            "casio": "https://casiostore.bhawar.com/collections/g-shock",
        },
        is_active=True,
    ),

    # 7. Apple All Products & Gadgets (Deactivated)
    RadarRule(
        name="Apple All Gadgets & Hardware (50%+ OFF)",
        category="Premium Tech",
        query="apple",
        brand="Apple",
        platforms=["amazon", "flipkart", "blinkit", "zepto"],
        min_discount=50.0,
        min_price=2000.0,
        min_mrp=5000.0,
        required_keywords=["apple", "iphone", "macbook", "ipad", "airpods", "watch", "imac", "pencil", "vision", "airtag"],
        negative_keywords=["case", "cover", "strap", "tempered glass", "adapter", "charging cable", "skin", "pouch", "stand"],
        is_active=False,
    ),

    # 8. Samsung All Products & Gadgets (Deactivated)
    RadarRule(
        name="Samsung All Gadgets & Hardware (50%+ OFF)",
        category="Premium Tech",
        query="samsung",
        brand="Samsung",
        platforms=["amazon", "flipkart", "blinkit", "zepto"],
        min_discount=50.0,
        min_price=1500.0,
        min_mrp=4000.0,
        required_keywords=["samsung", "galaxy"],
        negative_keywords=["case", "cover", "strap", "tempered glass", "adapter", "charging cable", "skin", "screen guard"],
        is_active=False,
    ),

    # 9. Nothing & CMF All Products & Gadgets (Deactivated)
    RadarRule(
        name="Nothing & CMF All Products (70%+ OFF)",
        category="Audio & Wearables",
        query="nothing cmf",
        brand="Nothing",
        platforms=["amazon", "flipkart"],
        min_discount=70.0,
        min_price=800.0,
        min_mrp=2500.0,
        required_keywords=["nothing", "cmf"],
        negative_keywords=["case", "cover", "earpad", "ear pads", "cable", "pouch", "stand", "skin", "silicone cover"],
        is_active=False,
    ),

    # 10. Realme All Products & Gadgets (Deactivated)
    RadarRule(
        name="Realme All Products (70%+ OFF)",
        category="Tech & Gadgets",
        query="realme",
        brand="Realme",
        platforms=["amazon", "flipkart"],
        min_discount=70.0,
        min_price=800.0,
        min_mrp=2500.0,
        required_keywords=["realme"],
        negative_keywords=["case", "cover", "strap", "tempered glass", "cable", "back cover", "skin"],
        is_active=False,
    ),

    # 11. Xiaomi & Redmi All Products & Gadgets (Deactivated)
    RadarRule(
        name="Xiaomi & Redmi All Products (70%+ OFF)",
        category="Tech & Gadgets",
        query="xiaomi redmi",
        brand="Xiaomi",
        platforms=["amazon", "flipkart"],
        min_discount=70.0,
        min_price=800.0,
        min_mrp=2500.0,
        required_keywords=["xiaomi", "redmi", "mi "],
        negative_keywords=["case", "cover", "strap", "tempered glass", "cable", "back cover", "skin"],
        is_active=False,
    ),

    # 12. Wakefit Gravita Ergonomic Chair Steals (Deactivated)
    RadarRule(
        name="Wakefit Gravita Ergonomic Chair Steals",
        category="Furniture & Home",
        query="wakefit gravita ergonomic chair",
        brand="Wakefit",
        platforms=["amazon", "flipkart"],
        min_discount=40.0,
        max_price=6000.0,
        min_price=2500.0,
        min_mrp=7000.0,
        required_keywords=["wakefit", "gravita"],
        negative_keywords=["wheel", "wheels", "cover", "cushion", "armrest only", "gas lift", "parts", "mat"],
        is_active=False,
    ),

    # 13. Power Bank Steals (Deactivated)
    RadarRule(
        name="10000mAh & 20000mAh Power Bank Steals",
        category="Tech & Gadgets",
        query="10000mah 20000mah power bank mi ambrane anker portronics urbn",
        platforms=["amazon", "flipkart", "blinkit", "zepto", "instamart"],
        min_discount=65.0,
        max_price=700.0,
        min_price=300.0,
        min_mrp=1500.0,
        required_keywords=["mi", "xiaomi", "ambrane", "anker", "portronics", "urbn", "belkin", "samsung", "realme"],
        negative_keywords=["case", "cover", "pouch", "strap", "cable only", "adapter", "protector", "skin"],
        is_active=False,
    ),
]
