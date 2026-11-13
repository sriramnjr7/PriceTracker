import os
import json
import pytest
from fastapi.testclient import TestClient
from collection_data import (
    CollectionManager,
    CollectionItem,
    CollectionImage,
    INITIAL_COLLECTION_ITEMS
)
from api.index import app

client = TestClient(app)

def test_initial_collection_count():
    """Ensure initial collection contains exactly 17 items (7 watches + 10 shoes)."""
    assert len(INITIAL_COLLECTION_ITEMS) == 17
    
    watches = [item for item in INITIAL_COLLECTION_ITEMS if item["category"] == "Watches"]
    shoes = [item for item in INITIAL_COLLECTION_ITEMS if item["category"] == "Shoes"]
    
    assert len(watches) == 7, f"Expected 7 watches, found {len(watches)}"
    assert len(shoes) == 10, f"Expected 10 shoes, found {len(shoes)}"

def test_distinct_woodland_models():
    """Ensure all 3 Woodland shoes remain separate records and Flame is never merged with Trekking."""
    woodland_shoes = [
        item for item in INITIAL_COLLECTION_ITEMS 
        if item["category"] == "Shoes" and item["brand"] == "Woodland"
    ]
    assert len(woodland_shoes) == 3, f"Expected 3 Woodland shoes, found {len(woodland_shoes)}"
    
    models = [item["model"] for item in woodland_shoes]
    assert "Beige Sneaker" in models
    assert "Flame Sports Shoes" in models
    assert any("Trekking" in m for m in models)
    
    flame_shoe = next(item for item in woodland_shoes if item["model"] == "Flame Sports Shoes")
    assert flame_shoe["reference"] == "ND213202861M"
    assert "Flame" in flame_shoe.get("model", "")

def test_excluded_items_not_present():
    """Ensure Puma R78 Year of Sports (Returned) and Nike Pegasus 40 (Unconfirmed) are excluded from active collection."""
    all_titles = [f"{item['brand']} {item['model']}".lower() for item in INITIAL_COLLECTION_ITEMS]
    for title in all_titles:
        assert "year of sports" not in title, "Puma R78 Year of Sports must not be in active owned collection"
        assert "pegasus 40" not in title, "Nike Pegasus 40 must not be in active owned collection"

def test_collection_manager_crud(tmp_path):
    """Test full CRUD operations on CollectionManager using an isolated temporary JSON file."""
    temp_file = str(tmp_path / "test_collection.json")
    manager = CollectionManager(data_file=temp_file)
    
    # Manager automatically seeds initial 17 items
    assert len(manager.items) == 17
    stats = manager.get_stats()
    assert stats["total"] == 17
    assert stats["categories"]["watches"] == 7
    assert stats["categories"]["shoes"] == 10
    
    # Create / Add
    new_item = manager.add_item({
        "category": "Electronics",
        "brand": "Sony",
        "model": "WH-1000XM5",
        "reference": "WH1000XM5/B",
        "status": "Owned",
        "categorySpecificMetadata": {"type": "Over-Ear Wireless ANC Headphones"}
    })
    assert new_item["id"] is not None
    assert len(manager.items) == 18
    assert manager.get_item(new_item["id"]) is not None
    
    # Update
    updated = manager.update_item(new_item["id"], {"colour": "Silver", "notes": "Daily work headphones"})
    assert updated is not None
    assert updated["colour"] == "Silver"
    assert updated["notes"] == "Daily work headphones"
    
    # Archive
    archived = manager.archive_item(new_item["id"])
    assert archived["status"] == "Archived"
    
    # Unarchive
    unarchived = manager.archive_item(new_item["id"])
    assert unarchived["status"] == "Owned"
    
    # Delete
    deleted = manager.delete_item(new_item["id"])
    assert deleted is True
    assert manager.get_item(new_item["id"]) is None
    assert len(manager.items) == 17

def test_collection_api_endpoints():
    """Test FastAPI REST endpoints for My Collection."""
    # GET /api/collection
    res = client.get("/api/collection")
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert "stats" in data
    assert len(data["items"]) >= 17
    assert data["stats"]["total"] >= 17
    
    # GET /my-collection and /collection route serve the dashboard
    res_page = client.get("/my-collection")
    assert res_page.status_code == 200
    assert "MY COLLECTION" in res_page.text
    assert "tab-content-collection" in res_page.text
    
    res_page2 = client.get("/collection")
    assert res_page2.status_code == 200

def test_dashboard_cache_control_header():
    """Verify that /api/dashboard/data returns no-cache headers to fix UI pause toggle caching."""
    from unittest.mock import AsyncMock, MagicMock, patch
    mock_db = MagicMock()
    mock_db.initialize = AsyncMock()
    mock_db.close = AsyncMock()
    mock_db.get_products = AsyncMock(return_value=[])
    mock_db.get_recent_deal_alerts = AsyncMock(return_value=[])
    with patch("api.index.get_database", return_value=mock_db):
        res = client.get("/api/dashboard/data")
        assert res.status_code == 200
        cache_control = res.headers.get("cache-control", "")
        assert "no-cache" in cache_control
        assert "no-store" in cache_control
        assert "max-age=0" in cache_control


def test_collection_valuation_stats():
    """Verify that portfolio and category valuations are dynamically calculated."""
    manager = CollectionManager()
    stats = manager.get_summary_stats()
    assert "total_valuation" in stats
    assert "watches_valuation" in stats
    assert "shoes_valuation" in stats
    assert stats["total_valuation"] > 50000
    assert stats["watches_valuation"] > 20000
    assert stats["shoes_valuation"] > 20000
    assert abs(stats["total_valuation"] - (stats["watches_valuation"] + stats["shoes_valuation"])) < 1.0


def test_collection_input_normalization_and_aliases(tmp_path):
    """Verify that snake_case payloads from forms are normalized into the schema with full aliases."""
    temp_file = str(tmp_path / "normalize_test.json")
    manager = CollectionManager(data_file=temp_file)

    created = manager.add_item({
        "category": "Watches",
        "brand": "Casio",
        "model": "G-Shock Mudman",
        "reference_number": "G-9300-1ER",
        "purchase_price": 9995.0,
        "purchased_from": "Casio Exclusive",
        "condition": "Mint",
        "category_specific_specs": {
            "movement": "Tough Solar",
            "case_diameter": "53mm",
            "water_resistance": "200m"
        },
        "images": [{"url": "https://example.com/mudman.jpg", "is_primary": True}],
        "tags": ["G-Shock", "Tough Solar", "Mudman"]
    })

    # Assert both camelCase and snake_case aliases are available
    assert created["reference"] == "G-9300-1ER"
    assert created["reference_number"] == "G-9300-1ER"
    assert created["purchasePrice"] == 9995.0
    assert created["purchase_price"] == 9995.0
    assert created["purchasedFrom"] == "Casio Exclusive"
    assert created["purchased_from"] == "Casio Exclusive"
    assert created["primaryImage"] == "https://example.com/mudman.jpg"
    assert created["categorySpecificMetadata"]["caseSize"] == "53mm"
    assert created["category_specific_specs"]["case_diameter"] == "53mm"

    # Fetch from storage
    fetched = manager.get_item(created["id"])
    assert fetched is not None
    assert fetched["reference"] == "G-9300-1ER"
    assert fetched["purchase_price"] == 9995.0


def test_collection_single_item_and_stats_routes():
    """Verify GET /api/collection/stats and GET /api/collection/{id}."""
    res_stats = client.get("/api/collection/stats")
    assert res_stats.status_code == 200
    data_stats = res_stats.json()
    assert data_stats["status"] == "success"
    assert "total_valuation" in data_stats["stats"]

    res_item = client.get("/api/collection/watch-02-titan-grandmaster-ii")
    assert res_item.status_code == 200
    item = res_item.json()["item"]
    assert item["model"] == "Grandmaster Brown Dial Analog Watch"
    assert item["purchasePrice"] == 12995

    res_not_found = client.get("/api/collection/non-existent-xyz-999")
    assert res_not_found.status_code == 404


def test_collection_asset_serving():
    """Verify local asset serving for collection images."""
    res = client.get("/assets/collection/casio-royale.jpg")
    assert res.status_code == 200
    assert res.headers["content-type"] in ("image/jpeg", "image/jpg")
    assert len(res.content) > 10000


def test_api_collection_json_with_browser_accept_header():
    """Ensure /api/collection returns JSON even if client sends text/html in Accept header."""
    res = client.get("/api/collection", headers={"Accept": "text/html,application/xhtml+xml"})
    assert res.status_code == 200
    assert "application/json" in res.headers["content-type"]
    assert res.json()["status"] == "success"


def test_partial_update_preserves_images_and_specs(tmp_path):
    """Regression test: Ensure partial updates do NOT wipe existing images or specs."""
    temp_file = str(tmp_path / "preservation_test.json")
    manager = CollectionManager(data_file=temp_file)

    created = manager.add_item({
        "category": "Watches",
        "brand": "Casio",
        "model": "G-Shock Gravitymaster",
        "reference": "GR-B200-1A",
        "categorySpecificMetadata": {
            "movement": "Quad Sensor Quartz",
            "caseSize": "54.1mm",
            "waterResistance": "200m",
            "carbonCore": True,
        },
        "images": [
            {"url": "https://example.com/front.jpg", "type": "primary"},
            {"url": "https://example.com/side.jpg", "type": "side"},
        ],
        "purchasePrice": 24995.0,
        "status": "Owned",
    })

    item_id = created["id"]
    assert len(created["images"]) == 2
    assert created["categorySpecificMetadata"]["caseSize"] == "54.1mm"

    # 1. Update only notes - images and specs must survive untouched
    updated_notes = manager.update_item(item_id, {"notes": "Updated personal note"})
    assert updated_notes["notes"] == "Updated personal note"
    assert len(updated_notes["images"]) == 2, "Images must NOT be wiped on partial notes update"
    assert updated_notes["images"][0]["url"] == "https://example.com/front.jpg"
    assert updated_notes["categorySpecificMetadata"]["caseSize"] == "54.1mm", "Specs must NOT be wiped on partial notes update"
    assert updated_notes["categorySpecificMetadata"]["carbonCore"] is True

    # 2. Update a single spec - should merge with existing specs, not overwrite them completely
    updated_spec = manager.update_item(item_id, {
        "category_specific_specs": {"dial_colour": "Black / Orange"}
    })
    assert updated_spec["categorySpecificMetadata"]["dialColour"] == "Black / Orange"
    assert updated_spec["categorySpecificMetadata"]["caseSize"] == "54.1mm", "Previous specs must be preserved when merging"
    assert len(updated_spec["images"]) == 2, "Images must survive spec updates"


def test_archive_preserves_images_and_specs(tmp_path):
    """Regression test: Archiving an item must never wipe images or metadata."""
    temp_file = str(tmp_path / "archive_preservation_test.json")
    manager = CollectionManager(data_file=temp_file)

    # Pick an initial seeded item (Titan Grandmaster with 3 images and 8 specs)
    grandmaster = manager.get_item("watch-02-titan-grandmaster-ii")
    assert grandmaster is not None
    orig_images_count = len(grandmaster["images"])
    orig_specs_count = len(grandmaster["categorySpecificMetadata"])
    assert orig_images_count == 3
    assert orig_specs_count >= 6

    # Archive it
    archived = manager.archive_item("watch-02-titan-grandmaster-ii")
    assert archived["status"] == "Archived"
    assert len(archived["images"]) == orig_images_count, "Archiving must not wipe images"
    assert len(archived["categorySpecificMetadata"]) == orig_specs_count, "Archiving must not wipe specs"

    # Restore to owned
    restored = manager.archive_item("watch-02-titan-grandmaster-ii")
    assert restored["status"] == "Owned"
    assert len(restored["images"]) == orig_images_count
    assert len(restored["categorySpecificMetadata"]) == orig_specs_count


def test_case_insensitive_item_id_operations(tmp_path):
    """Ensure get, update, archive, and delete work case-insensitively for UUIDs and custom IDs."""
    temp_file = str(tmp_path / "case_test.json")
    manager = CollectionManager(data_file=temp_file)

    # Upper/Mixed case lookup for seeded item
    found_mixed = manager.get_item("WATCH-01-TITAN-CLASSIQUE")
    assert found_mixed is not None
    assert found_mixed["brand"] == "Titan"

    # Update with mixed case ID
    updated = manager.update_item("WATCH-01-TITAN-CLASSIQUE", {"notes": "Case-insensitive update verified"})
    assert updated is not None
    assert updated["notes"] == "Case-insensitive update verified"

    # Archive with mixed case ID
    archived = manager.archive_item("WATCH-01-TITAN-CLASSIQUE")
    assert archived is not None
    assert archived["status"] == "Archived"

    # Delete with mixed case ID
    deleted = manager.delete_item("WATCH-01-TITAN-CLASSIQUE")
    assert deleted is True
    assert manager.get_item("watch-01-titan-classique") is None


def test_update_primary_image_preserves_secondary_images(tmp_path):
    """Ensure updating primaryImage without full images list keeps existing secondary images."""
    temp_file = str(tmp_path / "image_update_test.json")
    manager = CollectionManager(data_file=temp_file)

    item = manager.get_item("watch-02-titan-grandmaster-ii")
    assert len(item["images"]) == 3
    new_hero = "https://example.com/new-grandmaster-hero.jpg"

    updated = manager.update_item("watch-02-titan-grandmaster-ii", {"primaryImage": new_hero})
    assert updated["primaryImage"] == new_hero
    assert len(updated["images"]) == 3, "Secondary images must be preserved"
    assert updated["images"][0]["url"] == new_hero


def test_api_crud_full_lifecycle():
    """Verify complete CRUD lifecycle through FastAPI test client."""
    # 1. Create
    add_payload = {
        "category": "Electronics",
        "brand": "Apple",
        "model": "AirPods Max",
        "reference_number": "MGYH3AM/A",
        "nickname": "Space Grey Cans",
        "colour": "Space Grey",
        "material": "Anodized Aluminum",
        "purchase_price": 49900.0,
        "purchased_from": "Apple Store BKC",
        "purchase_date": "2026-02-01",
        "condition": "Mint",
        "status": "Owned",
        "primary_image": "https://example.com/airpods.jpg",
        "category_specific_specs": {
            "driver": "40mm Apple-designed dynamic driver",
            "anc": "Active Noise Cancellation with Transparency mode"
        },
        "tags": ["Apple", "ANC", "Wireless", "Audio"]
    }
    res_add = client.post("/api/collection", json=add_payload)
    assert res_add.status_code == 201
    created = res_add.json()["item"]
    item_id = created["id"]
    assert created["model"] == "AirPods Max"
    assert created["reference"] == "MGYH3AM/A"
    assert created["purchasePrice"] == 49900.0
    assert created["purchasedFrom"] == "Apple Store BKC"
    assert created["purchaseDate"] == "2026-02-01"

    # 2. Read single
    res_get = client.get(f"/api/collection/{item_id}")
    assert res_get.status_code == 200
    assert res_get.json()["item"]["id"] == item_id

    # 3. Update
    res_put = client.put(f"/api/collection/{item_id}", json={"notes": "Audiophile listening only"})
    assert res_put.status_code == 200
    updated = res_put.json()["item"]
    assert updated["notes"] == "Audiophile listening only"
    assert updated["purchasePrice"] == 49900.0, "Purchase price must survive update"
    assert updated["primaryImage"] == "https://example.com/airpods.jpg", "Image must survive update"

    # 4. Toggle Archive
    res_arch = client.post(f"/api/collection/{item_id}/archive")
    assert res_arch.status_code == 200
    assert res_arch.json()["item"]["status"] == "Archived"

    # 5. Delete
    res_del = client.delete(f"/api/collection/{item_id}")
    assert res_del.status_code == 200
    assert res_del.json()["deleted"] is True

    # 6. Verify 404 after delete
    res_gone = client.get(f"/api/collection/{item_id}")
    assert res_gone.status_code == 404

    # 7. Reset defaults restores initial collection
    res_reset = client.post("/api/collection/reset")
    assert res_reset.status_code == 200
    assert len(res_reset.json()["items"]) == 17

