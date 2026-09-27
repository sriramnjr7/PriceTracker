import pytest
from httpx import ASGITransport, AsyncClient
from api.index import app
from database import Database

@pytest.mark.asyncio
async def test_update_target_price_endpoint(tmp_path):
    db_file = str(tmp_path / "test_target.db")
    db = Database(db_file)
    await db.initialize()
    
    prod_id = await db.add_product(
        url="https://www.flipkart.com/test-product/p/itm123",
        target_price=2000.0,
        title="Test Shoe",
        platform="flipkart",
        initial_price=2500.0,
    )
    assert prod_id is not None
    await db.close()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Update target price via PATCH /api/products/{id}
        res = await client.patch(f"/api/products/{prod_id}", json={"target_price": 1800.0})
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["status"] == "success"
        assert data["target_price"] == 1800.0

        # 2. Reject <= 0 target price
        res_bad = await client.patch(f"/api/products/{prod_id}", json={"target_price": 0})
        assert res_bad.status_code == 400

        # 3. Post route alias
        res_post = await client.post(f"/api/products/{prod_id}/target-price", json={"target_price": 1600.0})
        assert res_post.status_code == 200
        assert res_post.json()["target_price"] == 1600.0
