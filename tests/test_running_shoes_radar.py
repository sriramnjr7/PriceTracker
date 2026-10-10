import pytest
from running_shoes_radar import (
    match_running_model,
    parse_uk_size,
    RunningShoesRadar,
    TARGET_SIZES,
    TARGET_PRICE_MIN,
    TARGET_PRICE_MAX,
)

def test_whitelist_positive_matches():
    # Saucony (New)
    assert match_running_model("Saucony Endorphin Speed 3 Mens Running Shoes") == ("Saucony", "Endorphin Speed")
    assert match_running_model("Saucony Endorphin Pro 3 Road Racing Shoes") == ("Saucony", "Endorphin Pro")
    assert match_running_model("Saucony Triumph 21 Max Cushion Running Shoes") == ("Saucony", "Triumph")
    assert match_running_model("Saucony Kinvara 14 Lightweight Running Shoes") == ("Saucony", "Kinvara")
    assert match_running_model("Saucony Ride 16 Mens Daily Trainer") == ("Saucony", "Ride")
    assert match_running_model("Saucony Tempus Structured Running Shoes") == ("Saucony", "Tempus")
    assert match_running_model("Saucony Guide 16 Running Shoes") == ("Saucony", "Guide")

    # Reebok (New)
    assert match_running_model("Reebok Floatride Energy 5 Lace-Up Running Shoes") == ("Reebok", "Floatride Energy")
    assert match_running_model("Reebok Floatride Energy X Carbon Plated Shoes") == ("Reebok", "Floatride Energy X")
    assert match_running_model("Reebok Floatride Energy Symmetros 2") == ("Reebok", "Floatride Energy Symmetros")

    # Hoka
    assert match_running_model("Hoka One One Mach 5 Running Shoes") == ("Hoka", "Mach")
    assert match_running_model("Hoka Clifton 9 Road Running Shoes") == ("Hoka", "Clifton")
    assert match_running_model("Hoka Bondi 8 Max Cushion Shoes") == ("Hoka", "Bondi")

    # Brooks
    assert match_running_model("Brooks Hyperion Max Road Running Shoes") == ("Brooks", "Hyperion Max")
    assert match_running_model("Brooks Ghost 15 Neutral Running Shoes") == ("Brooks", "Ghost")
    assert match_running_model("Brooks Glycerin 20 Nitrogen Infused Cushion") == ("Brooks", "Glycerin")

    # Puma
    assert match_running_model("Puma Velocity Nitro 3 Mens Running Shoes") == ("Puma", "Velocity Nitro")
    assert match_running_model("Puma Deviate Nitro 3 Running Shoes") == ("Puma", "Deviate Nitro")
    assert match_running_model("Puma Deviate Nitro Elite 2 Running Shoes") == ("Puma", "Deviate Nitro Elite")
    assert match_running_model("Puma Magnify Nitro 2 Max Cushion Road Running Shoes") == ("Puma", "Magnify Nitro")
    assert match_running_model("Puma ForeverRun Nitro Men Shoes") == ("Puma", "ForeverRun Nitro")
    assert match_running_model("Puma Liberate Nitro 2") == ("Puma", "Liberate Nitro")

    # Nike
    assert match_running_model("Nike Air Zoom Pegasus 40 Mens Road Running Shoes") == ("Nike", "Pegasus")
    assert match_running_model("Nike ZoomX Streakfly Road Racing Shoes") == ("Nike", "Streakfly")
    assert match_running_model("Nike Zoom Fly 5 Carbon Road Shoes") == ("Nike", "Zoom Fly")
    assert match_running_model("Nike ZoomX Invincible Run 3 Flyknit") == ("Nike", "Invincible Run")
    assert match_running_model("Nike Structure 25 Road Running Shoes") == ("Nike", "Structure")
    assert match_running_model("Nike Air Zoom Vomero 17 Road Running Shoes") == ("Nike", "Vomero")
    assert match_running_model("Nike Alphafly 3 Road Racing Shoes") == ("Nike", "Alphafly")
    assert match_running_model("Nike Vaporfly 3 Racing Shoes") == ("Nike", "Vaporfly")

    # Adidas
    assert match_running_model("Adidas Adizero SL 2 Running Shoes") == ("Adidas", "Adizero SL")
    assert match_running_model("Adidas Adizero Boston 12 M Running Shoes") == ("Adidas", "Adizero Boston")
    assert match_running_model("Adidas Adizero Takumi Sen 10 Running Shoes") == ("Adidas", "Adizero Takumi Sen")
    assert match_running_model("Adidas Adizero Adios 8 Shoes") == ("Adidas", "Adizero Adios")
    assert match_running_model("Adidas Adizero Adios Pro 3 Racing Shoes") == ("Adidas", "Adizero Adios Pro")
    assert match_running_model("Adidas Supernova Rise Running Shoes") == ("Adidas", "Supernova Rise")

    # Asics
    assert match_running_model("Asics Novablast 4 Mens Running Shoes") == ("Asics", "Novablast")
    assert match_running_model("Asics Magic Speed 3 Carbon Plated Running Shoes") == ("Asics", "Magic Speed")
    assert match_running_model("Asics GEL-Cumulus 26 Road Running Shoes") == ("Asics", "Gel-Cumulus")
    assert match_running_model("Asics GT-2000 12 Mens Stability Shoes") == ("Asics", "GT-2000")
    assert match_running_model("Asics Superblast Max Cushion Shoes") == ("Asics", "Superblast")

    # New Balance
    assert match_running_model("New Balance FuelCell Propel v4 Running Shoes") == ("New Balance", "FuelCell Propel")
    assert match_running_model("New Balance FuelCell Rebel v3") == ("New Balance", "FuelCell Rebel")
    assert match_running_model("New Balance FuelCell SuperComp Trainer v2") == ("New Balance", "FuelCell SuperComp Trainer")
    assert match_running_model("New Balance Fresh Foam X 1080 v13") == ("New Balance", "Fresh Foam X 1080")
    assert match_running_model("New Balance Fresh Foam X 880 v14") == ("New Balance", "Fresh Foam X 880")

    # Skechers
    assert match_running_model("Skechers GO RUN Ride 11 Mens Running Shoes") == ("Skechers", "Go Run Ride")
    assert match_running_model("Skechers GO RUN Razor 4 Hyper") == ("Skechers", "Go Run Razor")

    # On Running
    assert match_running_model("On Running Cloudmonster Mens Running Shoes") == ("On Running", "On Cloudmonster")
    assert match_running_model("On Running Cloudsurfer Road Shoes") == ("On Running", "On Cloudsurfer")


def test_whitelist_negative_exclusions():
    # Non-whitelisted cheap casual/tennis trap shoes must be rejected
    assert match_running_model("Nike Court Vision Low Casual Sneakers") is None
    assert match_running_model("Adidas Grand Court 2.0 Tennis Shoes") is None
    assert match_running_model("Puma Smash v2 Leather Sneakers") is None
    assert match_running_model("Adidas Advantage Base Court Shoes") is None


def test_sneaker_whitelist_matching():
    # Curated hype & retro lifestyle sneakers must be matched
    assert match_running_model("ADIDAS ORIGINALS SL 72 RS Sneakers For Men (White, Grey, 6)") == ("Adidas", "SL 72")
    assert match_running_model("Adidas Originals Samba OG Shoes For Men (White, Black)") == ("Adidas", "Samba")
    assert match_running_model("PUMA Palermo Leather Low-top Sneakers For Men") == ("Puma", "Palermo")
    assert match_running_model("Nike P-6000 Metallic Silver Shoes") == ("Nike", "P-6000")
    assert match_running_model("ASICS Gel-1130 White Pure Silver Running Shoes") == ("Asics", "Gel-1130")
    assert match_running_model("New Balance 550 White Green Basketball Sneakers") == ("New Balance", "New Balance 550")
    assert match_running_model("Nike Zoom Vomero 5 Lifestyle Sneakers") == ("Nike", "Vomero 5")
    assert match_running_model("Adidas Stan Smith Originals") == ("Adidas", "Stan Smith")

    # Trap Models: Reebok
    assert match_running_model("Reebok Energen Run Running Shoes") is None
    assert match_running_model("Reebok Rewind Run Sneakers") is None

    # Trap Models: Saucony
    assert match_running_model("Saucony Cohesion 16 Running Shoes") is None
    assert match_running_model("Saucony Excursion TR15 Trail") is None
    assert match_running_model("Saucony Versafoam Flare") is None

    # Trap Models: Nike
    assert match_running_model("Nike Downshifter 12 Road Running Shoes") is None
    assert match_running_model("Nike Revolution 7 Running Shoes") is None
    assert match_running_model("Nike Quest 5 Road Shoes") is None
    assert match_running_model("Nike Defy All Day Training Shoes") is None

    # Trap Models: Puma
    assert match_running_model("Puma Softride Rift Slip-On Walking Shoes") is None
    assert match_running_model("Puma Flyer Runner Running Shoes") is None
    assert match_running_model("Puma Anzarun Lite Modern Sneakers") is None

    # Trap Models: Asics
    assert match_running_model("Asics Gel-Contend 8 Running Shoes") is None
    assert match_running_model("Asics Jolt 4 Running Shoes") is None
    assert match_running_model("Asics Patriot 13 Running Shoes") is None
    assert match_running_model("Asics Raiden 3 Road Running Shoes") is None

    # Trap Models: Adidas
    assert match_running_model("Adidas Runfalcon 3.0 Running Shoes") is None
    assert match_running_model("Adidas Galaxy 6 M Running Shoes") is None
    assert match_running_model("Adidas Coreracer Running Shoes") is None
    assert match_running_model("Adidas Duramo 10 Running Shoes") is None
    assert match_running_model("Adidas Duramo SL Running Shoes") is None
    assert match_running_model("Adidas Duramo Lite 2.0") is None

    # Trap Models: New Balance
    assert match_running_model("New Balance Fresh Foam Arishi v4") is None
    assert match_running_model("New Balance Fresh Foam Roav") is None

    # Kids shoes
    assert match_running_model("Nike Air Zoom Pegasus 40 Kids Running Shoes") is None


def test_size_parsing():
    assert parse_uk_size("UK 10") == 10.0
    assert parse_uk_size("UK/IND-9.5") == 9.5
    assert parse_uk_size("10.5") == 10.5
    assert parse_uk_size("UK 11") == 11.0
    assert parse_uk_size("UK10") == 10.0

    # Non-target sizes must be rejected
    assert parse_uk_size("UK 6") is None
    assert parse_uk_size("UK 7") is None
    assert parse_uk_size("UK 8") is None
    assert parse_uk_size("UK 12") is None
    assert parse_uk_size("US 10") == 10.0 or parse_uk_size("US 10") is None  # normalized numeric check


def test_toggle_state_persistence():
    radar = RunningShoesRadar()
    initial = radar.is_active()
    
    # Toggle to opposite
    radar.set_active(not initial)
    assert radar.is_active() == (not initial)
    
    # Toggle back
    radar.set_active(initial)
    assert radar.is_active() == initial


def test_catalog_tracking_and_atl_detection():
    radar = RunningShoesRadar()
    catalog = radar.load_catalog()
    assert len(catalog) >= 56
    assert "saucony_endorphin_speed" in catalog
    assert "nike_pegasus" in catalog
    assert "adidas_adizero_sl" in catalog

    tracked_items = radar.get_tracked_catalog()
    assert len(tracked_items) >= 56
    first_item = tracked_items[0]
    assert "brand" in first_item
    assert "model" in first_item
    assert "status" in first_item
    assert "available_sizes" in first_item


def test_running_shoes_spa_browser_route():
    from fastapi.testclient import TestClient
    from api.index import app
    client = TestClient(app)

    # 1. Direct browser request to /running-shoes
    res_direct = client.get("/running-shoes", headers={"accept": "text/html,application/xhtml+xml"})
    assert res_direct.status_code == 200
    assert "text/html" in res_direct.headers.get("content-type", "")
    assert "<!DOCTYPE html>" in res_direct.text

    # 2. Vercel rewritten request to /api/index.py?_vercel_path=running-shoes
    res_vercel = client.get("/api/index.py?_vercel_path=running-shoes", headers={"accept": "text/html"})
    assert res_vercel.status_code == 200
    assert "text/html" in res_vercel.headers.get("content-type", "")
    assert "<!DOCTYPE html>" in res_vercel.text


def test_running_shoes_api_status_route():
    from fastapi.testclient import TestClient
    from api.index import app
    client = TestClient(app)

    # 1. Direct API call to /api/running-shoes/status
    res_direct = client.get("/api/running-shoes/status")
    assert res_direct.status_code == 200
    assert "application/json" in res_direct.headers.get("content-type", "")
    data = res_direct.json()
    assert data.get("status") == "online"
    assert "tracked_shoes" in data
    assert "whitelist_brands" in data

    # 2. Vercel rewritten request to /api/index.py?_vercel_path=api/running-shoes/status
    res_vercel = client.get("/api/index.py?_vercel_path=api/running-shoes/status")
    assert res_vercel.status_code == 200
    assert "application/json" in res_vercel.headers.get("content-type", "")
    data_v = res_vercel.json()
    assert data_v.get("status") == "online"
    assert "tracked_shoes" in data_v

