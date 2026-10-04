"""Synchronize collection mockups and Titan Grandmaster updates."""
import json
import re

# 1. Update collection_data.py
with open("collection_data.py", "r", encoding="utf-8") as f:
    code = f.read()

mockup_map = {
    # Kenneth Cole
    "https://helioswatchstore.com/media/catalog/product/k/c/kcwgy2104110mn_1.jpg": "/assets/collection/kenneth-cole-skeleton.jpg",
    # Casio MCW-200H
    "https://www.casio.com/content/dam/casio/product-info/locales/in/en/timepiece/product/watch/M/MC/MCW/mcw-200h-9av/assets/MCW-200H-9AV_Seq1.png": "/assets/collection/casio-mcw-200h.jpg",
    # Casio Royale
    "https://www.casio.com/content/dam/casio/product-info/locales/in/en/timepiece/product/watch/A/AE/AE1/ae-1200whd-1a/assets/AE-1200WHD-1A_Seq1.png": "/assets/collection/casio-royale.jpg",
    # G-Shock GBD-300
    "https://www.casio.com/content/dam/casio/product-info/locales/in/en/timepiece/product/watch/G/GB/GBD/gbd-300-4/assets/GBD-300-4_Seq1.png": "/assets/collection/g-shock-gbd-300.jpg",
    # Adidas Duramo 10
    "https://assets.adidas.com/images/h_840,f_auto,q_auto,fl_lossy,c_fill,g_auto/c5b0244799014631862bad5c010b9d90_9366/Duramo_10_Shoes_Black_GW8336_01_standard.jpg": "/assets/collection/adidas-duramo-10.jpg",
    # ASICS Tiger Runner II
    "https://images.asics.com/is/image/asics/1201A792_020_SR_RT_GLB?$sfcc-product$": "/assets/collection/asics-tiger-runner-ii.jpg",
    # Nike Revolution 4
    "https://static.nike.com/a/images/t_PDP_1280_v1/f_auto,q_auto:eco/e8cf650b-80df-4ff2-a505-182d3e098485/revolution-4-running-shoe.jpg": "/assets/collection/nike-revolution-4.jpg",
    # Nike Waffle Debut
    "https://static.nike.com/a/images/t_PDP_1280_v1/f_auto,q_auto:eco/e53ff00c-7b47-4f67-a068-1e428e219ba4/waffle-debut-shoes-4kW4K7.png": "/assets/collection/nike-waffle-debut.jpg",
    # Zudio
    "https://www.zudio.com/cdn/shop/files/8909100067664_1.jpg?v=1712753641": "/assets/collection/zudio-sneaker.jpg",
}

for old_url, new_url in mockup_map.items():
    code = code.replace(old_url, new_url)

# Replace Woodland beige & flame image URLs
code = re.sub(
    r'https://www\.woodlandworldwide\.com/_next/image\?url=[^"\s]+ND213202861M[^"\s]+',
    '/assets/collection/woodland-flame.jpg',
    code
)
# For the beige sneaker, fix it to woodland-beige.jpg
code = code.replace(
    '"id": "shoe-07-woodland-beige-sneaker",\n        "category": "Shoes",\n        "brand": "Woodland",\n        "model": "Beige Sneaker",\n        "reference": None,\n        "type": "Lifestyle / Casual",\n        "colour": "Beige / Cream / Light Grey / Peach-Orange",\n        "material": "Suede / Nubuck / Chunky Midsole",\n        "description": "Chunky Woodland casual sneaker with beige/cream upper, light grey detailing, peach/orange accents, chunky off-white midsole and dark outsole.",\n        "primaryImage": "/assets/collection/woodland-flame.jpg"',
    '"id": "shoe-07-woodland-beige-sneaker",\n        "category": "Shoes",\n        "brand": "Woodland",\n        "model": "Beige Sneaker",\n        "reference": None,\n        "type": "Lifestyle / Casual",\n        "colour": "Beige / Cream / Light Grey / Peach-Orange",\n        "material": "Suede / Nubuck / Chunky Midsole",\n        "description": "Chunky Woodland casual sneaker with beige/cream upper, light grey detailing, peach/orange accents, chunky off-white midsole and dark outsole.",\n        "primaryImage": "/assets/collection/woodland-beige.jpg"'
)

# For Trekking shoe:
code = re.sub(
    r'https://www\.woodlandworldwide\.com/_next/image\?url=[^"\s]+GC3778119[^"\s]+',
    '/assets/collection/woodland-trekking.jpg',
    code
)

with open("collection_data.py", "w", encoding="utf-8") as f:
    f.write(code)

print("collection_data.py updated successfully.")

# 2. Re-import and re-seed my_collection.json
import importlib
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import collection_data
importlib.reload(collection_data)

mgr = collection_data.CollectionManager()
seeded = mgr.reset_to_defaults()
print(f"my_collection.json refreshed with {len(seeded)} items.")

# Verify all 17 items
watches = [i for i in seeded if i["category"] == "Watches"]
shoes = [i for i in seeded if i["category"] == "Shoes"]
print(f"Watches: {len(watches)}, Shoes: {len(shoes)}")

tgm = next(i for i in seeded if "grandmaster" in i["id"])
print(f"Titan Grandmaster SKU: {tgm.get('reference')}, Price: {tgm.get('purchasePrice')}")
print(f"Titan Grandmaster Primary Image: {tgm.get('primaryImage')}")
