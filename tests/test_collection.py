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
    res = client.get("/api/dashboard/data")
    assert res.status_code == 200
    cache_control = res.headers.get("cache-control", "")
    assert "no-cache" in cache_control
    assert "no-store" in cache_control
    assert "max-age=0" in cache_control
