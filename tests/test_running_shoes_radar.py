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
    # Puma
    assert match_running_model("Puma Velocity Nitro 3 Mens Running Shoes") == ("Puma", "Velocity Nitro")
    assert match_running_model("Puma Deviate Nitro Elite 2 Running Shoes") == ("Puma", "Deviate Nitro")
    assert match_running_model("Puma ForeverRun Nitro Men Shoes") == ("Puma", "ForeverRun")
    assert match_running_model("Puma Liberate Nitro 2") == ("Puma", "Liberate Nitro")

    # Nike
    assert match_running_model("Nike Air Zoom Pegasus 40 Mens Road Running Shoes") == ("Nike", "Pegasus")
    assert match_running_model("Nike Winflo 10 Mens Running Shoes") == ("Nike", "Winflo")
    assert match_running_model("Nike Rival Fly 3 Road Racing Shoes") == ("Nike", "Rival Fly")
    assert match_running_model("Nike Infinity Run 4 Flyknit") == ("Nike", "Infinity Run")
    assert match_running_model("Nike Air Zoom Vomero 17 Road Running Shoes") == ("Nike", "Vomero")

    # Adidas
    assert match_running_model("Adidas Adizero SL 2 Running Shoes") == ("Adidas", "Adizero SL")
    assert match_running_model("Adidas Adizero Boston 12 M Running Shoes") == ("Adidas", "Boston")
    assert match_running_model("Adidas Supernova Rise Running Shoes") == ("Adidas", "Supernova Rise")
    assert match_running_model("Adidas Supernova Stride M") == ("Adidas", "Supernova Stride")
    assert match_running_model("Adidas Duramo Speed M Running Shoes") == ("Adidas", "Duramo Speed")

    # Asics
    assert match_running_model("Asics Novablast 4 Mens Running Shoes") == ("Asics", "Novablast")
    assert match_running_model("Asics GEL-Cumulus 26 Road Running Shoes") == ("Asics", "Cumulus")
    assert match_running_model("Asics GT-2000 12 Mens Stability Shoes") == ("Asics", "GT-2000")
    assert match_running_model("Asics GT-1000 12 Running Shoes") == ("Asics", "GT-1000")
    assert match_running_model("Asics GEL-Pulse 15 Mens Shoes") == ("Asics", "Pulse")

    # New Balance
    assert match_running_model("New Balance FuelCell Propel v4 Running Shoes") == ("New Balance", "FuelCell Propel")
    assert match_running_model("New Balance FuelCell Rebel v3") == ("New Balance", "FuelCell Rebel")
    assert match_running_model("New Balance Fresh Foam X 880 v14") == ("New Balance", "Fresh Foam 880")

    # Skechers
    assert match_running_model("Skechers GO RUN Ride 11 Mens Running Shoes") == ("Skechers", "Go Run Ride")
    assert match_running_model("Skechers Max Cushioning Premier Trail") == ("Skechers", "Max Cushioning")
    assert match_running_model("Skechers GO RUN Razor 4 Hyper") == ("Skechers", "Razor")


def test_whitelist_negative_exclusions():
    # Casual/tennis shoes must be rejected
    assert match_running_model("Nike Court Vision Low Casual Sneakers") is None
    assert match_running_model("Adidas Grand Court 2.0 Tennis Shoes") is None
    assert match_running_model("Adidas Stan Smith Originals") is None
    assert match_running_model("Puma Smash v2 Leather Sneakers") is None

    # Lifestyle remakes
    assert match_running_model("Nike Zoom Vomero 5 Lifestyle Sneakers") is None

    # Low-end casual Duramos must be rejected (only Duramo Speed is performance)
    assert match_running_model("Adidas Duramo 10 Running Shoes") is None
    assert match_running_model("Adidas Duramo SL Running Shoes") is None
    assert match_running_model("Adidas Duramo Lite 2.0") is None

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
