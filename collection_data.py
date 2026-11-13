"""Collection Data Manager for My Collection (Personal Inventory & Ownership Archive).

Handles persistence, schema validation, search, filtering, and initial seeding
of exactly 17 items (7 watches, 10 shoes) into `my_collection.json`.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

COLLECTION_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "my_collection.json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CollectionImage(BaseModel):
    url: str
    type: str = "primary"  # primary | front | back | side | detail | personal-photo
    alt: Optional[str] = None
    sortOrder: int = 0


class CollectionItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    category: str  # Watches | Shoes | Electronics | Bags | etc.
    brand: str
    model: str
    nickname: Optional[str] = None
    reference: Optional[str] = None
    type: Optional[str] = None
    colour: Optional[str] = None
    material: Optional[str] = None
    description: Optional[str] = None
    images: List[CollectionImage] = []
    primaryImage: Optional[str] = None
    status: str = "Owned"  # Owned | Sold | Returned | Gifted | Archived
    size: Optional[str] = None
    purchasePrice: Optional[float] = None
    purchaseDate: Optional[str] = None
    purchasedFrom: Optional[str] = None
    condition: Optional[str] = None
    warrantyExpiry: Optional[str] = None
    notes: Optional[str] = None
    tags: List[str] = []
    categorySpecificMetadata: Dict[str, Any] = {}
    createdAt: str = Field(default_factory=_now)
    updatedAt: str = Field(default_factory=_now)


INITIAL_COLLECTION_ITEMS: List[Dict[str, Any]] = [
    # =========================================================================
    # WATCHES (7 Items)
    # =========================================================================
    {
        "id": "watch-01-titan-classique",
        "category": "Watches",
        "brand": "Titan",
        "model": "Classique",
        "reference": "NP1584SM03",
        "type": "Dress / Analog",
        "colour": "Silver",
        "material": "Stainless Steel",
        "description": "Titan Classique dress-style analog watch with a silver-tone metal case and silver metal bracelet, paired with a clean silver dial and understated traditional styling.",
        "primaryImage": "https://www.titan.co.in/dw/image/v2/BKDD_PRD/on/demandware.static/-/Sites-titan-master-catalog/default/dw1572c8ea/images/Titan/Catalog/1584SM03_1.jpg",
        "images": [
            {
                "url": "https://www.titan.co.in/dw/image/v2/BKDD_PRD/on/demandware.static/-/Sites-titan-master-catalog/default/dw1572c8ea/images/Titan/Catalog/1584SM03_1.jpg",
                "type": "primary",
                "alt": "Titan Classique NP1584SM03 front dial view",
                "sortOrder": 0,
            }
        ],
        "status": "Owned",
        "purchasePrice": 2495,
        "purchasedFrom": "Titan World",
        "condition": "Mint",
        "tags": ["Analog", "Dress", "Silver", "Metal Bracelet"],
        "categorySpecificMetadata": {
            "movement": "Quartz",
            "caseMaterial": "Silver-tone Stainless Steel",
            "caseColour": "Silver",
            "dialColour": "Silver",
            "strapType": "Metal Bracelet",
            "strapColour": "Silver",
            "waterResistance": "50 m (5 ATM)",
            "caseSize": "42 mm",
        },
        "createdAt": "2026-01-10T10:00:00Z",
        "updatedAt": "2026-01-10T10:00:00Z",
    },
    {
        "id": "watch-02-titan-grandmaster-ii",
        "category": "Watches",
        "brand": "Titan",
        "model": "Grandmaster Brown Dial Analog Watch",
        "nickname": "Grandmaster Chessboard",
        "reference": "1828KM02",
        "type": "Analog / Dress",
        "colour": "Brown / Silver / Gold-tone",
        "material": "Stainless Steel",
        "description": "Titan Grandmaster Brown Dial Analog Watch for Men (1828KM02). Chess-inspired design featuring an intricate brown multi-layered dial with chessboard motifs, gold-tone Roman indices, and two-tone stainless steel bracelet.",
        "primaryImage": "https://www.titan.co.in/dw/image/v2/BKDD_PRD/on/demandware.static/-/Sites-titan-master-catalog/default/dwadc1a5c5/images/Titan/Catalog/1828KM02_1.jpg?sw=800&sh=800",
        "images": [
            {
                "url": "https://www.titan.co.in/dw/image/v2/BKDD_PRD/on/demandware.static/-/Sites-titan-master-catalog/default/dwadc1a5c5/images/Titan/Catalog/1828KM02_1.jpg?sw=800&sh=800",
                "type": "primary",
                "alt": "Titan Grandmaster 1828KM02 Brown Dial Front View",
                "sortOrder": 0,
            },
            {
                "url": "https://www.titan.co.in/dw/image/v2/BKDD_PRD/on/demandware.static/-/Sites-titan-master-catalog/default/dwadc1a5c5/images/Titan/Catalog/1828KM02_2.jpg?sw=800&sh=800",
                "type": "side",
                "alt": "Titan Grandmaster 1828KM02 Profile and Crown",
                "sortOrder": 1,
            },
            {
                "url": "https://www.titan.co.in/dw/image/v2/BKDD_PRD/on/demandware.static/-/Sites-titan-master-catalog/default/dwadc1a5c5/images/Titan/Catalog/1828KM02_3.jpg?sw=800&sh=800",
                "type": "back",
                "alt": "Titan Grandmaster 1828KM02 Caseback View",
                "sortOrder": 2,
            },
        ],
        "status": "Owned",
        "purchasePrice": 12995,
        "purchasedFrom": "Titan Official",
        "condition": "Mint",
        "tags": ["Titan Grandmaster", "Chess Tribute", "Analog", "Two-Tone", "1828KM02"],
        "categorySpecificMetadata": {
            "movement": "Quartz",
            "caseMaterial": "Stainless Steel with Gold-Tone Accents",
            "caseColour": "Silver / Gold",
            "dialColour": "Brown (Chessboard Pattern)",
            "strapType": "Stainless Steel Bracelet",
            "strapColour": "Silver / Gold-Tone",
            "waterResistance": "50 m (5 ATM)",
            "caseSize": "44 mm",
        },
        "notes": "Official Reference: https://www.titan.co.in/product/titan-grandmaster-brown-dial-analog-watch-for-men-1828km02.html (SKU: 1828KM02)",
        "createdAt": "2026-01-10T10:00:00Z",
        "updatedAt": "2026-01-10T10:00:00Z",
    },
    {
        "id": "watch-03-titan-octane-chronograph",
        "category": "Watches",
        "brand": "Titan",
        "model": "Octane Chronograph",
        "reference": "9324SM04",
        "type": "Chronograph / Analog",
        "colour": "Silver / Black / Red",
        "material": "Stainless Steel",
        "description": "Titan Octane Chronograph with a silver-tone metal case and bracelet, black chronograph dial, multiple sub-dials and distinctive red accents.",
        "primaryImage": "https://www.titan.co.in/dw/image/v2/BKDD_PRD/on/demandware.static/-/Sites-titan-master-catalog/default/dw4f57a3e7/images/Titan/Catalog/9324SM04_1.jpg",
        "images": [
            {
                "url": "https://www.titan.co.in/dw/image/v2/BKDD_PRD/on/demandware.static/-/Sites-titan-master-catalog/default/dw4f57a3e7/images/Titan/Catalog/9324SM04_1.jpg",
                "type": "primary",
                "alt": "Titan Octane Chronograph 9324SM04 dial with red accents",
                "sortOrder": 0,
            }
        ],
        "status": "Owned",
        "purchasePrice": 7995,
        "purchasedFrom": "Titan World",
        "condition": "Excellent",
        "tags": ["Chronograph", "Sport Analog", "Sub-Dials"],
        "categorySpecificMetadata": {
            "movement": "Quartz Chronograph",
            "caseMaterial": "Silver-tone Metal",
            "caseColour": "Silver",
            "dialColour": "Black with red accents",
            "strapType": "Metal Bracelet",
            "strapColour": "Silver",
            "waterResistance": "100 m",
        },
        "createdAt": "2026-01-10T10:00:00Z",
        "updatedAt": "2026-01-10T10:00:00Z",
    },
    {
        "id": "watch-04-kenneth-cole-skeleton-automatic",
        "category": "Watches",
        "brand": "Kenneth Cole",
        "model": "KCWGY2104110MN",
        "nickname": "Kenneth Cole Skeleton Automatic",
        "reference": "KCWGY2104110MN",
        "type": "Automatic / Skeleton",
        "colour": "Black / Orange-Gold",
        "material": "Stainless Steel / Ion Plated",
        "description": "Kenneth Cole automatic skeleton watch with a black case and black metal bracelet, exposed mechanical movement, orange/gold hands and markers, and exhibition caseback showing the automatic movement.",
        "primaryImage": "/assets/collection/kenneth-cole-skeleton.jpg",
        "images": [
            {
                "url": "/assets/collection/kenneth-cole-skeleton.jpg",
                "type": "primary",
                "alt": "Kenneth Cole KCWGY2104110MN Skeleton Automatic Dial",
                "sortOrder": 0,
            }
        ],
        "status": "Owned",
        "purchasePrice": 13995,
        "purchasedFrom": "Kenneth Cole Boutique",
        "condition": "Mint",
        "tags": ["Automatic", "Skeleton", "Exhibition Caseback", "Black IP"],
        "categorySpecificMetadata": {
            "movement": "Automatic Self-Winding",
            "caseMaterial": "Black Stainless Steel",
            "caseColour": "Black",
            "dialColour": "Skeleton / Partially Openworked",
            "strapType": "Metal Bracelet",
            "strapColour": "Black",
            "caseSize": "44 mm",
            "waterResistance": "30 m",
        },
        "createdAt": "2026-01-10T10:00:00Z",
        "updatedAt": "2026-01-10T10:00:00Z",
    },
    {
        "id": "watch-05-casio-mcw-200h-9avdf",
        "category": "Watches",
        "brand": "Casio",
        "model": "MCW-200H-9AVDF",
        "reference": "MCW-200H-9AVDF",
        "type": "Analog Chronograph",
        "colour": "Black / Gold",
        "material": "Resin",
        "description": "Casio MCW-200H-9AVDF analog chronograph with a black resin case and strap, gold dial and gold detailing, with chronograph sub-dials and date display.",
        "primaryImage": "/assets/collection/casio-mcw-200h.png",
        "images": [
            {
                "url": "/assets/collection/casio-mcw-200h.png",
                "type": "primary",
                "alt": "Casio MCW-200H-9AVDF Black and Gold Dial",
                "sortOrder": 0,
            }
        ],
        "status": "Owned",
        "purchasePrice": 3995,
        "purchasedFrom": "Casio India",
        "condition": "Mint",
        "tags": ["Analog Chronograph", "Gold Dial", "100m Water Resistance", "Sport"],
        "categorySpecificMetadata": {
            "movement": "Quartz Chronograph",
            "caseMaterial": "Black Resin",
            "caseColour": "Black",
            "dialColour": "Gold",
            "strapType": "Resin Strap",
            "strapColour": "Black",
            "waterResistance": "100 m",
            "caseSize": "55.8 × 53.5 × 14.1 mm",
        },
        "createdAt": "2026-01-10T10:00:00Z",
        "updatedAt": "2026-01-10T10:00:00Z",
    },
    {
        "id": "watch-06-casio-ae-1200whd-1avdf",
        "category": "Watches",
        "brand": "Casio",
        "model": "AE-1200WHD-1AVDF",
        "nickname": "Casio Royale",
        "reference": "AE-1200WHD-1AVDF",
        "type": "Digital / World Time",
        "colour": "Silver / Black",
        "material": "Stainless Steel / Resin Glass",
        "description": "Casio AE-1200WHD-1AVDF, commonly known as the Casio Royale. Digital world-time watch with a black digital display/case and silver metal bracelet.",
        "primaryImage": "/assets/collection/casio-royale.jpg",
        "images": [
            {
                "url": "/assets/collection/casio-royale.jpg",
                "type": "primary",
                "alt": "Casio Royale AE-1200WHD-1AVDF World Time Watch",
                "sortOrder": 0,
            }
        ],
        "status": "Owned",
        "purchasePrice": 3595,
        "purchasedFrom": "Casio India",
        "condition": "Mint",
        "tags": ["Casio Royale", "Digital", "World Time", "10-Year Battery", "Stainless Steel"],
        "categorySpecificMetadata": {
            "movement": "Digital Quartz",
            "caseMaterial": "Resin / Chrome plated",
            "caseColour": "Black / Silver",
            "dialColour": "Digital LCD with World Map",
            "strapType": "Stainless Steel Bracelet",
            "strapColour": "Silver",
            "waterResistance": "100 m",
            "caseSize": "45 × 42.1 × 12.5 mm",
        },
        "createdAt": "2026-01-10T10:00:00Z",
        "updatedAt": "2026-01-10T10:00:00Z",
    },
    {
        "id": "watch-07-g-shock-gbd-300-orange",
        "category": "Watches",
        "brand": "G-Shock",
        "model": "GBD-300",
        "reference": "GBD-300",
        "type": "Digital / Sports / Fitness",
        "colour": "Orange",
        "material": "Resin / Mineral Glass",
        "description": "G-Shock GBD-300 digital sports watch in bright orange, with orange resin case and strap and a dark digital display.",
        "primaryImage": "/assets/collection/g-shock-gbd-300-9.png",
        "images": [
            {
                "url": "/assets/collection/g-shock-gbd-300-9.png",
                "type": "primary",
                "alt": "G-Shock GBD-300 in vibrant Orange with dark digital display",
                "sortOrder": 0,
            }
        ],
        "status": "Owned",
        "purchasePrice": 11995,
        "purchasedFrom": "Casio India",
        "condition": "Brand New",
        "tags": ["G-Shock", "G-SQUAD", "Orange", "Bluetooth", "Step Tracker", "200m WR"],
        "categorySpecificMetadata": {
            "movement": "Digital Quartz / MIP LCD",
            "caseMaterial": "Orange Bio-based Resin",
            "caseColour": "Orange",
            "dialColour": "Dark / Negative MIP LCD",
            "strapType": "Urethane Resin Band",
            "strapColour": "Orange",
            "waterResistance": "200 m (20 Bar)",
            "caseSize": "48.9 × 47.4 × 14.9 mm",
        },
        "createdAt": "2026-01-10T10:00:00Z",
        "updatedAt": "2026-01-10T10:00:00Z",
    },

    # =========================================================================
    # SHOES (10 Items)
    # =========================================================================
    {
        "id": "shoe-01-adidas-duramo-10",
        "category": "Shoes",
        "brand": "Adidas",
        "model": "Duramo 10",
        "reference": None,
        "type": "Running / Training",
        "colour": "Black / White",
        "material": "Engineered Mesh / Lightmotion",
        "description": "Adidas Duramo 10 running/training shoe in black and white, with an athletic lightweight profile and performance-oriented cushioning.",
        "primaryImage": "/assets/collection/adidas-duramo-10.jpg",
        "images": [
            {
                "url": "/assets/collection/adidas-duramo-10.jpg",
                "type": "primary",
                "alt": "Adidas Duramo 10 Black White running shoe",
                "sortOrder": 0,
            }
        ],
        "status": "Owned",
        "size": "UK 9 / EU 43",
        "purchasePrice": 4999,
        "purchasedFrom": "Adidas",
        "condition": "Good",
        "tags": ["Running", "Training", "Lightmotion Cushioning", "Breathable Mesh"],
        "categorySpecificMetadata": {
            "shoeType": "Road Running / Trainer",
            "upperMaterial": "Engineered Mesh Upper (50% recycled)",
            "soleOutsole": "Lightmotion Midsole & Rubber Outsole",
            "intendedUse": "Daily Running & Gym Training",
            "colour": "Core Black / Cloud White",
        },
        "createdAt": "2026-01-10T10:00:00Z",
        "updatedAt": "2026-01-10T10:00:00Z",
    },
    {
        "id": "shoe-02-asics-tiger-runner-ii",
        "category": "Shoes",
        "brand": "ASICS",
        "model": "Tiger Runner II",
        "reference": None,
        "type": "Lifestyle / Retro Runner",
        "colour": "Grey",
        "material": "Mesh / Synthetic Leather",
        "description": "ASICS Tiger Runner II in grey, with a retro 1980s-inspired running silhouette, grey upper, contrasting ASICS detailing and a light-coloured sole.",
        "primaryImage": "/assets/collection/asics-tiger-runner-ii.jpg",
        "images": [
            {
                "url": "/assets/collection/asics-tiger-runner-ii.jpg",
                "type": "primary",
                "alt": "ASICS Tiger Runner II Grey Retro Runner",
                "sortOrder": 0,
            }
        ],
        "status": "Owned",
        "size": "UK 9 / EU 43",
        "purchasePrice": 4499,
        "purchasedFrom": "ASICS India",
        "condition": "Mint",
        "tags": ["ASICS", "Retro 80s", "Lifestyle", "Grey"],
        "categorySpecificMetadata": {
            "shoeType": "Casual / Retro Sneaker",
            "upperMaterial": "Breathable Mesh & Synthetic Leather",
            "soleOutsole": "Cushioned EVA Midsole & Rubber Outsole",
            "intendedUse": "Everyday Casual Wear",
            "colour": "Grey / Light Grey / White",
        },
        "createdAt": "2026-01-10T10:00:00Z",
        "updatedAt": "2026-01-10T10:00:00Z",
    },
    {
        "id": "shoe-03-nike-revolution-4",
        "category": "Shoes",
        "brand": "Nike",
        "model": "Revolution 4",
        "reference": None,
        "type": "Running / Daily",
        "colour": "White / Neon",
        "material": "Single-layer Mesh / Phylon Foam",
        "description": "Nike Revolution 4 in white with a bright neon-coloured Nike Swoosh/symbol, designed as a lightweight running and everyday athletic shoe.",
        "primaryImage": "/assets/collection/nike-revolution-4.jpg",
        "images": [
            {
                "url": "/assets/collection/nike-revolution-4.jpg",
                "type": "primary",
                "alt": "Nike Revolution 4 White with Neon Swoosh",
                "sortOrder": 0,
            }
        ],
        "status": "Owned",
        "size": "UK 9 / EU 43",
        "purchasePrice": 3695,
        "purchasedFrom": "Nike Store",
        "condition": "Lightly Used",
        "tags": ["Nike", "Running", "Lightweight", "Neon Swoosh"],
        "categorySpecificMetadata": {
            "shoeType": "Running / Daily Trainer",
            "upperMaterial": "Single-Layer Breathable Mesh",
            "soleOutsole": "Soft Foam Phylon Midsole",
            "intendedUse": "Light Running & Daily Active",
            "colour": "White / Bright Neon Accent",
        },
        "createdAt": "2026-01-10T10:00:00Z",
        "updatedAt": "2026-01-10T10:00:00Z",
    },
    {
        "id": "shoe-04-nike-waffle-debut",
        "category": "Shoes",
        "brand": "Nike",
        "model": "Waffle Debut",
        "reference": None,
        "type": "Lifestyle / Retro",
        "colour": "Black",
        "material": "Suede / Textile",
        "description": "Nike Waffle Debut in black with white Nike Swoosh, white laces, white midsole and black outsole.",
        "primaryImage": "/assets/collection/nike-waffle-debut.jpg",
        "images": [
            {
                "url": "/assets/collection/nike-waffle-debut.jpg",
                "type": "primary",
                "alt": "Nike Waffle Debut Black with White Swoosh",
                "sortOrder": 0,
            }
        ],
        "status": "Owned",
        "size": "UK 9 / EU 43",
        "purchasePrice": 5995,
        "purchasedFrom": "Nike Store",
        "condition": "Mint",
        "tags": ["Nike Waffle", "Retro Runner", "Suede Overlay", "Waffle Outsole"],
        "categorySpecificMetadata": {
            "shoeType": "Heritage Casual Sneaker",
            "upperMaterial": "Suede Overlays & Nylon Mesh",
            "soleOutsole": "Lifted Foam Midsole & Signature Waffle Rubber Outsole",
            "intendedUse": "Casual Streetwear",
            "colour": "Black / White",
        },
        "createdAt": "2026-01-10T10:00:00Z",
        "updatedAt": "2026-01-10T10:00:00Z",
    },
    {
        "id": "shoe-05-puma-r78-res",
        "category": "Shoes",
        "brand": "Puma",
        "model": "R78 Res",
        "reference": None,
        "type": "Lifestyle / Retro Runner",
        "colour": "White / Green",
        "material": "Mesh / Synthetic Suede",
        "description": "Puma R78 Res in a white and green colourway with a retro running-inspired silhouette and chunky athletic sole.",
        "primaryImage": "/assets/collection/puma-r78-strong-feather.png",
        "images": [
            {
                "url": "/assets/collection/puma-r78-strong-feather.png",
                "type": "primary",
                "alt": "Puma R78 Res White Green retro silhouette",
                "sortOrder": 0,
            }
        ],
        "status": "Owned",
        "size": "UK 9 / EU 43",
        "purchasePrice": 3999,
        "purchasedFrom": "Puma Store",
        "condition": "Mint",
        "tags": ["Puma", "Retro 70s", "White Green", "SoftFoam+"],
        "categorySpecificMetadata": {
            "shoeType": "Retro Athletic Sneaker",
            "upperMaterial": "Mesh Upper with Synthetic Overlays",
            "soleOutsole": "Cushioned EVA Midsole & Durable Rubber Sole",
            "intendedUse": "Casual Lifestyle",
            "colour": "White / Green / Black",
        },
        "createdAt": "2026-01-10T10:00:00Z",
        "updatedAt": "2026-01-10T10:00:00Z",
    },
    {
        "id": "shoe-06-puma-palermo",
        "category": "Shoes",
        "brand": "Puma",
        "model": "Palermo",
        "reference": None,
        "type": "Lifestyle / Terrace",
        "colour": "White / Black",
        "material": "Suede / Leather",
        "description": "Puma Palermo in white with black suede detailing, using the classic low-profile terrace/football-inspired silhouette.",
        "primaryImage": "/assets/collection/puma-palermo-leather.png",
        "images": [
            {
                "url": "/assets/collection/puma-palermo-leather.png",
                "type": "primary",
                "alt": "Puma Palermo White Black Suede Terrace Silhouette",
                "sortOrder": 0,
            }
        ],
        "status": "Owned",
        "size": "UK 9 / EU 43",
        "purchasePrice": 6999,
        "purchasedFrom": "Puma India",
        "condition": "Brand New",
        "tags": ["Terrace Culture", "Palermo", "Suede", "Gum Sole"],
        "categorySpecificMetadata": {
            "shoeType": "Low-Profile Terrace Sneaker",
            "upperMaterial": "Leather Upper with Premium Suede Formstrip & Overlays",
            "soleOutsole": "Classic Gum Rubber Outsole",
            "intendedUse": "Terrace / Streetwear Fashion",
            "colour": "White / Black",
        },
        "createdAt": "2026-01-10T10:00:00Z",
        "updatedAt": "2026-01-10T10:00:00Z",
    },
    {
        "id": "shoe-07-woodland-beige-sneaker",
        "category": "Shoes",
        "brand": "Woodland",
        "model": "Beige Sneaker",
        "reference": None,
        "type": "Lifestyle / Casual",
        "colour": "Beige / Cream / Light Grey / Peach-Orange",
        "material": "Suede / Nubuck / Chunky Midsole",
        "description": "Chunky Woodland casual sneaker with beige/cream upper, light grey detailing, peach/orange accents, chunky off-white midsole and dark outsole.",
        "primaryImage": "/assets/collection/woodland-beige.webp",
        "images": [
            {
                "url": "/assets/collection/woodland-beige.webp",
                "type": "primary",
                "alt": "Woodland Chunky Beige Sneaker with Peach Accents",
                "sortOrder": 0,
            }
        ],
        "status": "Owned",
        "size": "UK 9 / EU 43",
        "purchasePrice": 3495,
        "purchasedFrom": "Woodland",
        "condition": "Good",
        "tags": ["Woodland", "Chunky Sneaker", "Beige Cream", "Casual"],
        "categorySpecificMetadata": {
            "shoeType": "Chunky Casual Sneaker",
            "upperMaterial": "Suede & Nubuck Paneling",
            "soleOutsole": "Chunky Off-White Midsole & Grippy Dark Tread",
            "intendedUse": "Casual & Lifestyle Wear",
            "colour": "Beige / Cream / Light Grey / Peach-Orange",
        },
        "createdAt": "2026-01-10T10:00:00Z",
        "updatedAt": "2026-01-10T10:00:00Z",
    },
    {
        "id": "shoe-08-woodland-flame-sports-shoes",
        "category": "Shoes",
        "brand": "Woodland",
        "model": "Flame Sports Shoes",
        "reference": "ND213202861M",
        "type": "Sports / Outdoor",
        "colour": "Dark Olive / Black / Orange",
        "material": "Breathable Mesh / Rugged Rubber Outsole",
        "description": "Woodland Flame sports/outdoor shoe with dark olive and black upper, strong orange accents around the collar and upper, cushioned midsole and rugged outsole.",
        "primaryImage": "/assets/collection/woodland-flame.webp",
        "images": [
            {
                "url": "/assets/collection/woodland-flame.webp",
                "type": "primary",
                "alt": "Woodland Flame Sports Shoes ND213202861M Dark Olive Orange",
                "sortOrder": 0,
            }
        ],
        "status": "Owned",
        "size": "UK 9 / EU 43",
        "purchasePrice": 3995,
        "purchasedFrom": "Woodland",
        "condition": "Mint",
        "tags": ["Woodland Flame", "Outdoor", "Sports", "Dark Olive", "Rugged"],
        "categorySpecificMetadata": {
            "shoeType": "Performance Sports / Outdoor Trainer",
            "upperMaterial": "Engineered Breathable Mesh & Protective Overlays",
            "soleOutsole": "Contoured Cushioned Midsole with Rugged Lugs",
            "intendedUse": "Outdoor Training, Gym & Trail Walking",
            "colour": "Dark Olive / Black / Orange",
        },
        "notes": "Official reference: https://www.woodlandworldwide.com/product/flame-sports-shoes-for-men (SKU: ND213202861M)",
        "createdAt": "2026-01-10T10:00:00Z",
        "updatedAt": "2026-01-10T10:00:00Z",
    },
    {
        "id": "shoe-09-woodland-trekking-trail-shoe",
        "category": "Shoes",
        "brand": "Woodland",
        "model": "Woodland Trekking / Trail Shoe",
        "reference": None,
        "type": "Trekking / Trail / Outdoor",
        "colour": "Dark Olive / Black / Orange",
        "material": "Heavy-duty Nubuck / Trail Lugged Sole",
        "description": "Woodland trekking/trail shoe shown in my supplied photographs, with a dark olive/black upper, orange collar/detailing, beige/tan midsole and aggressive black trail lugs.",
        "primaryImage": "/assets/collection/woodland-trekking.jpg",
        "images": [
            {
                "url": "/assets/collection/woodland-trekking.jpg",
                "type": "primary",
                "alt": "Woodland Trekking Trail Shoe with aggressive black lugs",
                "sortOrder": 0,
            }
        ],
        "status": "Owned",
        "size": "UK 9 / EU 43",
        "purchasePrice": 4295,
        "purchasedFrom": "Woodland",
        "condition": "Good",
        "tags": ["Woodland Trekking", "Trail Shoe", "Aggressive Lugs", "Outdoor"],
        "categorySpecificMetadata": {
            "shoeType": "Trekking / Trail Hiking Shoe",
            "upperMaterial": "Heavy-duty Nubuck Leather & Ballistic Nylon Collar",
            "soleOutsole": "Beige/Tan Shock-Absorbing Midsole with Aggressive Deep Trail Lugs",
            "intendedUse": "Trekking, Hiking, Rough Mountain Terrains",
            "colour": "Dark Olive / Black / Orange",
        },
        "notes": "Separate pair from Woodland Flame. Verified trail lugs & tan midsole.",
        "createdAt": "2026-01-10T10:00:00Z",
        "updatedAt": "2026-01-10T10:00:00Z",
    },
    {
        "id": "shoe-10-zudio-sneaker",
        "category": "Shoes",
        "brand": "Zudio",
        "model": "Zudio Sneaker",
        "reference": None,
        "type": "Lifestyle / Casual",
        "colour": "White / Cream / Neon Green / Black",
        "material": "Synthetic Paneling / Chunky Sole",
        "description": "Zudio chunky casual sneaker with a white/cream upper, bright neon-green tongue, black tongue/collar detailing, black-and-white rope-style laces and a chunky white midsole.",
        "primaryImage": "/assets/collection/zudio-sneaker.jpg",
        "images": [
            {
                "url": "/assets/collection/zudio-sneaker.jpg",
                "type": "primary",
                "alt": "Zudio Chunky Sneaker with Neon Green Tongue and Rope Laces",
                "sortOrder": 0,
            }
        ],
        "status": "Owned",
        "size": "44",
        "purchasePrice": 999,
        "purchasedFrom": "Zudio",
        "condition": "Good",
        "tags": ["Zudio", "Chunky Sneaker", "Neon Green Tongue", "Rope Laces", "Size 44"],
        "categorySpecificMetadata": {
            "shoeType": "Chunky Casual Sneaker",
            "shoeSize": "44",
            "upperMaterial": "White/Cream Synthetic Leather & Mesh",
            "soleOutsole": "Chunky White Platform Midsole",
            "intendedUse": "Everyday Casual Wear",
            "colour": "White / Cream / Neon Green / Black",
        },
        "notes": "Exact Zudio model name is not officially published. Size 44.",
        "createdAt": "2026-01-10T10:00:00Z",
        "updatedAt": "2026-01-10T10:00:00Z",
    },
]


def _normalize_item_input(data: Dict[str, Any], is_update: bool = False) -> Dict[str, Any]:
    """Normalize input dictionary so snake_case frontend inputs map seamlessly to model schema."""
    norm = dict(data)

    # 1. Field name aliases
    if "reference_number" in norm and not norm.get("reference"):
        norm["reference"] = norm.pop("reference_number")
    if "purchase_price" in norm and not norm.get("purchasePrice"):
        norm["purchasePrice"] = norm.pop("purchase_price")
    if "purchased_from" in norm and not norm.get("purchasedFrom"):
        norm["purchasedFrom"] = norm.pop("purchased_from")
    if "category_specific_specs" in norm and not norm.get("categorySpecificMetadata"):
        norm["categorySpecificMetadata"] = norm.pop("category_specific_specs")
    if "purchase_date" in norm and not norm.get("purchaseDate"):
        norm["purchaseDate"] = norm.pop("purchase_date")
    if "warranty_expiry" in norm and not norm.get("warrantyExpiry"):
        norm["warrantyExpiry"] = norm.pop("warranty_expiry")

    # 2. Images normalization
    has_images_field = "images" in norm

    if "primary_image" in norm and not norm.get("primaryImage"):
        norm["primaryImage"] = norm.pop("primary_image")

    if has_images_field:
        raw_images = norm.get("images") or []
        norm_images = []
        for idx, img in enumerate(raw_images):
            if isinstance(img, str):
                norm_images.append({
                    "url": img,
                    "type": "primary" if idx == 0 else "detail",
                    "alt": None,
                    "sortOrder": idx,
                })
            elif isinstance(img, dict):
                url = img.get("url") or ""
                img_type = img.get("type") or ("primary" if img.get("is_primary") else "detail")
                norm_images.append({
                    "url": url,
                    "type": img_type,
                    "alt": img.get("alt") or img.get("caption"),
                    "sortOrder": img.get("sortOrder", idx),
                })
        norm["images"] = norm_images
        if not norm.get("primaryImage") and norm_images:
            norm["primaryImage"] = norm_images[0]["url"]
    elif not is_update:
        # Creating new item without explicit images array
        pri = norm.get("primaryImage")
        if pri:
            norm["images"] = [{"url": pri, "type": "primary", "sortOrder": 0}]
        else:
            norm["images"] = []

    # 3. Category specific metadata normalization
    has_meta_field = "categorySpecificMetadata" in norm or "category_specific_specs" in norm
    if has_meta_field or not is_update:
        meta = norm.get("categorySpecificMetadata") or {}
        if isinstance(meta, dict):
            norm_meta = dict(meta)
            if "case_diameter" in norm_meta and "caseSize" not in norm_meta:
                norm_meta["caseSize"] = norm_meta["case_diameter"]
            if "water_resistance" in norm_meta and "waterResistance" not in norm_meta:
                norm_meta["waterResistance"] = norm_meta["water_resistance"]
            if "strap_material" in norm_meta and "strapType" not in norm_meta:
                norm_meta["strapType"] = norm_meta["strap_material"]
            if "dial_colour" in norm_meta and "dialColour" not in norm_meta:
                norm_meta["dialColour"] = norm_meta["dial_colour"]
            if "shoe_size" in norm_meta and "shoeSize" not in norm_meta:
                norm_meta["shoeSize"] = norm_meta["shoe_size"]
            if "upper_material" in norm_meta and "upperMaterial" not in norm_meta:
                norm_meta["upperMaterial"] = norm_meta["upper_material"]
            if "sole_material" in norm_meta and "soleOutsole" not in norm_meta:
                norm_meta["soleOutsole"] = norm_meta["sole_material"]
            if "intended_use" in norm_meta and "intendedUse" not in norm_meta:
                norm_meta["intendedUse"] = norm_meta["intended_use"]
            norm["categorySpecificMetadata"] = norm_meta
            if "shoeSize" in norm_meta and not norm.get("size"):
                norm["size"] = norm_meta["shoeSize"]

    return norm


def _format_item_response(item: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure both camelCase and snake_case aliases are available in all responses."""
    res = dict(item)
    ref = res.get("reference") or res.get("reference_number")
    res["reference"] = ref
    res["reference_number"] = ref

    price = res.get("purchasePrice") if res.get("purchasePrice") is not None else res.get("purchase_price")
    res["purchasePrice"] = price
    res["purchase_price"] = price

    from_val = res.get("purchasedFrom") or res.get("purchased_from")
    res["purchasedFrom"] = from_val
    res["purchased_from"] = from_val

    meta = res.get("categorySpecificMetadata") or res.get("category_specific_specs") or {}
    res["categorySpecificMetadata"] = meta
    res["category_specific_specs"] = meta

    pri = res.get("primaryImage") or res.get("primary_image")
    res["primaryImage"] = pri
    res["primary_image"] = pri

    p_date = res.get("purchaseDate") or res.get("purchase_date")
    res["purchaseDate"] = p_date
    res["purchase_date"] = p_date

    w_exp = res.get("warrantyExpiry") or res.get("warranty_expiry")
    res["warrantyExpiry"] = w_exp
    res["warranty_expiry"] = w_exp

    c_at = res.get("createdAt") or res.get("created_at") or _now()
    res["createdAt"] = c_at
    res["created_at"] = c_at

    u_at = res.get("updatedAt") or res.get("updated_at") or _now()
    res["updatedAt"] = u_at
    res["updated_at"] = u_at

    return res


class CollectionManager:
    """Manages collection items in local storage file and computes dynamic metrics."""

    def __init__(self, file_path: str = COLLECTION_FILE_PATH, data_file: Optional[str] = None) -> None:
        self.file_path = data_file or file_path
        self._ensure_storage()

    @property
    def items(self) -> List[Dict[str, Any]]:
        """Direct access to all current collection items."""
        return self.get_all_items()

    def _ensure_storage(self) -> None:
        """Create file and seed initial 17 items if missing."""
        # On serverless platforms like Vercel with read-only filesystems, use temp directory if available
        tmp_dir = tempfile.gettempdir()
        tmp_file = os.path.join(tmp_dir, "my_collection.json")
        if os.path.exists(tmp_file):
            self.file_path = tmp_file

        if not os.path.exists(self.file_path):
            self._save_items(copy.deepcopy(INITIAL_COLLECTION_ITEMS))
            logger.info("Created %s with %s initial items.", self.file_path, len(INITIAL_COLLECTION_ITEMS))
        else:
            try:
                items = self._read_raw_items()
                if not items:
                    self._save_items(copy.deepcopy(INITIAL_COLLECTION_ITEMS))
            except Exception as exc:
                logger.error("Error reading %s: %s; re-seeding defaults.", self.file_path, exc)
                self._save_items(copy.deepcopy(INITIAL_COLLECTION_ITEMS))

    def _read_raw_items(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.file_path):
            return copy.deepcopy(INITIAL_COLLECTION_ITEMS)
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.error("Failed to load collection items: %s", exc)
            return copy.deepcopy(INITIAL_COLLECTION_ITEMS)

    def _save_items(self, items: List[Dict[str, Any]]) -> None:
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(items, f, indent=2, ensure_ascii=False)
        except (OSError, IOError) as exc:
            # Fallback to temp directory on serverless environments if primary path is read-only
            tmp_path = os.path.join(tempfile.gettempdir(), "my_collection.json")
            if self.file_path != tmp_path:
                try:
                    with open(tmp_path, "w", encoding="utf-8") as f:
                        json.dump(items, f, indent=2, ensure_ascii=False)
                    self.file_path = tmp_path
                    logger.info("Fell back to %s for persistence: %s", tmp_path, exc)
                    return
                except Exception as inner_exc:
                    logger.error("Failed writing to fallback tmp path: %s", inner_exc)
            raise

    def get_all_items(self) -> List[Dict[str, Any]]:
        """Read all collection items with compatibility aliases."""
        raw = self._read_raw_items()
        return [_format_item_response(i) for i in raw]

    def get_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        items = self.get_all_items()
        target = str(item_id).strip().lower()
        for item in items:
            if str(item.get("id")).strip().lower() == target:
                return item
        return None

    def add_item(self, item_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate, normalize and insert a new item into collection."""
        norm_data = _normalize_item_input(item_data, is_update=False)
        items = self._read_raw_items()
        item_id = norm_data.get("id") or str(uuid.uuid4())

        # Ensure ID uniqueness (case-insensitive)
        if any(str(i.get("id")).strip().lower() == str(item_id).strip().lower() for i in items):
            item_id = str(uuid.uuid4())

        norm_data["id"] = item_id
        if not norm_data.get("createdAt"):
            norm_data["createdAt"] = _now()
        norm_data["updatedAt"] = _now()

        item = CollectionItem(**norm_data)
        item_dict = item.model_dump()
        items.insert(0, item_dict)
        self._save_items(items)
        return _format_item_response(item_dict)

    def update_item(self, item_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update fields on an existing collection item with normalization and merging."""
        norm_updates = _normalize_item_input(updates, is_update=True)
        items = self._read_raw_items()
        updated_item = None
        target = str(item_id).strip().lower()
        for idx, item in enumerate(items):
            if str(item.get("id")).strip().lower() == target:
                # Merge category-specific metadata if provided
                merged_meta = dict(item.get("categorySpecificMetadata") or {})
                if "categorySpecificMetadata" in norm_updates:
                    merged_meta.update(norm_updates["categorySpecificMetadata"])
                    norm_updates["categorySpecificMetadata"] = merged_meta

                # Merge images if primaryImage provided without full images array
                if "images" not in norm_updates and "primaryImage" in norm_updates:
                    cur_images = list(item.get("images") or [])
                    new_pri = norm_updates["primaryImage"]
                    if cur_images:
                        cur_images[0] = {**cur_images[0], "url": new_pri, "type": "primary"}
                    elif new_pri:
                        cur_images = [{"url": new_pri, "type": "primary", "sortOrder": 0}]
                    norm_updates["images"] = cur_images

                actual_id = item.get("id", item_id)
                merged = {**item, **norm_updates, "id": actual_id, "updatedAt": _now()}
                validated = CollectionItem(**merged)
                updated_item = validated.model_dump()
                items[idx] = updated_item
                break

        if updated_item:
            self._save_items(items)
            return _format_item_response(updated_item)
        return None

    def archive_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        """Toggle or set item status to Archived without deleting."""
        item = self.get_item(item_id)
        if not item:
            return None
        new_status = "Owned" if item.get("status") == "Archived" else "Archived"
        return self.update_item(item_id, {"status": new_status})

    def delete_item(self, item_id: str) -> bool:
        """Remove item from collection (case-insensitive ID)."""
        items = self._read_raw_items()
        initial_len = len(items)
        target = str(item_id).strip().lower()
        items = [i for i in items if str(i.get("id")).strip().lower() != target]
        if len(items) < initial_len:
            self._save_items(items)
            return True
        return False

    def reset_to_defaults(self) -> List[Dict[str, Any]]:
        """Restore the initial 17 verified items."""
        self._save_items(copy.deepcopy(INITIAL_COLLECTION_ITEMS))
        return self.get_all_items()

    def get_summary_stats(self) -> Dict[str, Any]:
        """Compute live counts, categories, brands, and valuation dynamically from current data."""
        items = self.get_all_items()
        total_count = len(items)
        owned_items = [i for i in items if i.get("status", "Owned") == "Owned"]
        owned_count = len(owned_items)
        archived_count = sum(1 for i in items if i.get("status") == "Archived")

        categories: Dict[str, int] = {}
        brands: set[str] = set()
        total_valuation = 0.0
        watches_valuation = 0.0
        shoes_valuation = 0.0

        for i in items:
            cat = i.get("category") or "Uncategorized"
            categories[cat] = categories.get(cat, 0) + 1
            brand = i.get("brand")
            if brand and brand.strip():
                brands.add(brand.strip())

            # Valuation metrics on owned items
            if i.get("status", "Owned") == "Owned":
                price = i.get("purchasePrice") if i.get("purchasePrice") is not None else i.get("purchase_price")
                if price:
                    try:
                        p_float = float(price)
                        total_valuation += p_float
                        if cat.lower() == "watches":
                            watches_valuation += p_float
                        elif cat.lower() == "shoes":
                            shoes_valuation += p_float
                    except (ValueError, TypeError):
                        pass

        watches = categories.get("Watches", 0)
        shoes = categories.get("Shoes", 0)

        return {
            "total": total_count,
            "total_items": total_count,
            "owned_items": owned_count,
            "archived_items": archived_count,
            "watches_count": watches,
            "shoes_count": shoes,
            "total_brands": len(brands),
            "unique_brands_count": len(brands),
            "total_valuation": round(total_valuation, 2),
            "watches_valuation": round(watches_valuation, 2),
            "shoes_valuation": round(shoes_valuation, 2),
            "categories": {
                "watches": watches,
                "shoes": shoes,
                **categories,
            },
            "brands": sorted(list(brands)),
        }

    def get_stats(self) -> Dict[str, Any]:
        """Convenience alias for get_summary_stats."""
        return self.get_summary_stats()


collection_mgr = CollectionManager()
