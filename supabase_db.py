"""Supabase PostgREST asynchronous client.

Provides connectionless, stateless PostgreSQL operations over HTTPS.
Requires zero native C-extensions (works out of the box on Vercel Python serverless).
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

import httpx

from database import Product

logger = logging.getLogger("supabase_db")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_product(row: dict[str, Any]) -> Product:
    return Product(
        id=int(row["id"]),
        url=row["url"],
        platform=row["platform"],
        title=row.get("title"),
        initial_price=float(row["initial_price"]) if row.get("initial_price") is not None else None,
        current_price=float(row["current_price"]) if row.get("current_price") is not None else None,
        target_price=float(row["target_price"]) if row.get("target_price") is not None else None,
        percentage_drop_target=float(row["percentage_drop_target"]) if row.get("percentage_drop_target") is not None else None,
        last_checked=row.get("last_checked"),
        is_active=bool(row.get("is_active", True)),
        last_notified_price=float(row["last_notified_price"]) if row.get("last_notified_price") is not None else None,
    )


class SupabaseDatabase:
    """PostgREST client implementing the Database interface for Supabase."""

    def __init__(self, supabase_url: Optional[str] = None, supabase_key: Optional[str] = None):
        self.url = (supabase_url or os.getenv("SUPABASE_URL", "")).rstrip("/")
        self.key = supabase_key or os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        self.base_rest = f"{self.url}/rest/v1"
        self._headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    @property
    def is_configured(self) -> bool:
        return bool(self.url and self.key)

    async def _request(
        self,
        method: str,
        path_or_url: str,
        max_retries: int = 3,
        **kwargs,
    ) -> httpx.Response:
        """Resilient HTTP request to Supabase PostgREST with exponential retry on transport errors."""
        url = path_or_url if path_or_url.startswith("http") else f"{self.base_rest}/{path_or_url.lstrip('/')}"
        headers = kwargs.pop("headers", self._headers)
        timeout = kwargs.pop("timeout", 15.0)

        last_exc = None
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(
                    timeout=timeout,
                    limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
                ) as client:
                    resp = await client.request(method, url, headers=headers, timeout=timeout, **kwargs)
                    return resp
            except (httpx.TransportError, httpx.RemoteProtocolError, ConnectionResetError, Exception) as exc:
                last_exc = exc
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.4 * (attempt + 1))
                else:
                    logger.warning("Supabase %s %s failed after %s attempts: %s", method, url, max_retries, exc)
        if last_exc:
            raise last_exc
        raise RuntimeError(f"Request failed: {method} {url}")

    async def initialize(self) -> None:
        """Verify connectivity to Supabase."""
        if not self.is_configured:
            logger.warning("Supabase URL or Key not configured; client uninitialized.")
            return
        try:
            r = await self._request("GET", "/products?select=id&limit=1", timeout=10.0)
            if r.status_code in (200, 206):
                logger.info("Connected to Supabase PostgreSQL successfully.")
            else:
                logger.warning("Supabase test query returned HTTP %s: %s", r.status_code, r.text)
        except Exception as exc:
            logger.warning("Supabase connection check error: %s", exc)

    async def close(self) -> None:
        pass

    # ---------------------------------------------------------------- products
    async def add_product(
        self,
        url: str,
        platform: str,
        title: Optional[str] = None,
        initial_price: Optional[float] = None,
        target_price: Optional[float] = None,
        percentage_drop_target: Optional[float] = None,
    ) -> int:
        """Insert or upsert product into Supabase products table."""
        payload = {
            "url": url,
            "platform": platform,
            "title": title,
            "initial_price": initial_price,
            "current_price": initial_price,
            "target_price": target_price,
            "percentage_drop_target": percentage_drop_target,
            "is_active": True,
            "last_notified_price": None,
        }
        headers = dict(self._headers)
        headers["Prefer"] = "resolution=merge-duplicates,return=representation"

        resp = await self._request("POST", "/products?on_conflict=url", json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        if data and isinstance(data, list):
            return int(data[0]["id"])
        raise RuntimeError("Failed to upsert product in Supabase")

    async def get_product(self, product_id: int) -> Optional[Product]:
        resp = await self._request("GET", f"/products?id=eq.{product_id}&limit=1")
        if resp.status_code == 200:
            rows = resp.json()
            if rows:
                return _row_to_product(rows[0])
        return None

    async def get_product_by_url(self, url: str) -> Optional[Product]:
        resp = await self._request("GET", "/products", params={"url": f"eq.{url}", "limit": "1"})
        if resp.status_code == 200:
            rows = resp.json()
            if rows:
                return _row_to_product(rows[0])
        return None

    async def get_products(self, active_only: bool = False) -> List[Product]:
        url = "/products?select=*&order=id.asc"
        if active_only:
            url += "&is_active=eq.true"

        resp = await self._request("GET", url)
        if resp.status_code == 200:
            rows = resp.json()
            return [_row_to_product(r) for r in rows]
        return []

    async def remove_product(self, product_id: int) -> None:
        await self._request("DELETE", f"/products?id=eq.{product_id}")

    async def set_active(self, product_id: int, active: bool) -> None:
        payload = {"is_active": active, "last_checked": _now()}
        await self._request("PATCH", f"/products?id=eq.{product_id}", json=payload)

    async def update_target_price(self, product_id: int, target_price: float) -> bool:
        """Update target price threshold in Supabase PostgREST with retries."""
        payload = {"target_price": float(target_price)}
        resp = await self._request("PATCH", f"/products?id=eq.{product_id}", json=payload)
        return resp.status_code in (200, 204)

    async def update_price(
        self, product_id: int, price: Optional[float], title: Optional[str] = None
    ) -> None:
        ts = _now()
        if price is not None:
            # Log price history
            try:
                await self._request(
                    "POST",
                    "/price_logs",
                    json={"product_id": product_id, "price": price, "timestamp": ts},
                )
            except Exception as exc:
                logger.debug("Failed logging price_logs for %s: %s", product_id, exc)

            payload: dict[str, Any] = {"current_price": price, "last_checked": ts}
            if title:
                payload["title"] = title
            await self._request("PATCH", f"/products?id=eq.{product_id}", json=payload)
        else:
            payload = {
                "last_checked": ts,
                "current_price": None,
                "last_notified_price": None,
            }
            if title:
                payload["title"] = title
            await self._request("PATCH", f"/products?id=eq.{product_id}", json=payload)

    async def update_last_checked(self, product_id: int) -> None:
        """Update last_checked timestamp when a product was probed/checked."""
        ts = _now()
        await self._request("PATCH", f"/products?id=eq.{product_id}", json={"last_checked": ts})

    async def set_last_notified(self, product_id: int, price: float) -> None:
        payload = {"last_notified_price": price}
        await self._request("PATCH", f"/products?id=eq.{product_id}", json=payload)

    async def price_history(self, product_id: int, limit: int = 20) -> List[tuple[float, str]]:
        resp = await self._request("GET", f"/price_logs?product_id=eq.{product_id}&order=timestamp.desc&limit={limit}")
        if resp.status_code == 200:
            rows = resp.json()
            return [(float(r["price"]), r["timestamp"]) for r in rows]
        return []

    # -------------------------------------------------------- deal_alerts_log
    async def is_deal_recently_notified(
        self,
        product_url: str,
        hours: Optional[float] = None,
        minutes: Optional[int] = None,
        current_price: Optional[float] = None,
    ) -> bool:
        """Check if an alert was already dispatched in Supabase within the last N minutes/hours."""
        if minutes is not None:
            delta = timedelta(minutes=minutes)
        elif hours is not None:
            delta = timedelta(hours=hours)
        else:
            delta = timedelta(minutes=20)  # Default: 20-minute de-duplication window

        cutoff = (datetime.now(timezone.utc) - delta).isoformat()
        params = {
            "product_url": f"eq.{product_url}",
            "notified_at": f"gte.{cutoff}",
            "order": "notified_at.desc",
            "limit": "1",
        }
        resp = await self._request("GET", "/deal_alerts_log", params=params)
        if resp.status_code == 200:
            rows = resp.json()
            if not rows:
                return False
            if current_price is not None:
                last_eff = float(rows[0].get("effective_price") or rows[0].get("price") or 0)
                if current_price < (last_eff - 2.0):
                    return False
            return True
        return False

    async def log_deal_alert(
        self,
        product_url: str,
        title: Optional[str] = None,
        price: Optional[float] = None,
        effective_price: Optional[float] = None,
        discount_percent: Optional[float] = None,
        coupon_text: Optional[str] = None,
        platform: Optional[str] = None,
    ) -> None:
        payload = {
            "product_url": product_url,
            "title": title,
            "price": price,
            "effective_price": effective_price if effective_price is not None else price,
            "discount_percent": discount_percent,
            "coupon_text": coupon_text,
            "platform": platform,
            "notified_at": _now(),
        }
        await self._request("POST", "/deal_alerts_log", json=payload)

    async def get_recent_deal_alerts(self, limit: int = 15) -> List[dict[str, Any]]:
        """Fetch the most recent steal deals and glitch notifications."""
        resp = await self._request("GET", f"/deal_alerts_log?select=*&order=notified_at.desc&limit={limit}")
        if resp.status_code == 200:
            return resp.json()
        return []

    async def get_recent_price_logs(
        self, product_id: Optional[int] = None, limit: int = 20
    ) -> List[dict[str, Any]]:
        """Fetch recent price logs."""
        url = f"/price_logs?select=*&order=timestamp.desc&limit={limit}"
        if product_id is not None:
            url += f"&product_id=eq.{product_id}"
        resp = await self._request("GET", url)
        if resp.status_code == 200:
            return resp.json()
        return []

    # --------------------------------------------------- custom_radar_rules
    async def add_custom_rule(
        self,
        name: str,
        query: str,
        category: Optional[str] = "Custom",
        platforms: Optional[list[str]] = None,
        min_discount: float = 70.0,
        max_price: Optional[float] = None,
        min_mrp: Optional[float] = None,
        negative_keywords: Optional[list[str]] = None,
    ) -> int:
        payload = {
            "name": name,
            "category": category,
            "query": query,
            "platforms": ",".join(platforms) if platforms else "amazon,flipkart",
            "min_discount": min_discount,
            "max_price": max_price,
            "min_mrp": min_mrp,
            "negative_keywords": ",".join(negative_keywords) if negative_keywords else None,
            "is_active": True,
            "created_at": _now(),
        }
        resp = await self._request("POST", "/custom_radar_rules", json=payload)
        resp.raise_for_status()
        data = resp.json()
        if data and isinstance(data, list):
            return int(data[0]["id"])
        return 1

    async def get_custom_rules(self, active_only: bool = True) -> list[dict[str, Any]]:
        url = "/custom_radar_rules?select=*&name=not.in.(DAEMON_LOG,VIP_LOG)&order=id.asc"
        if active_only:
            url += "&is_active=eq.true"
        resp = await self._request("GET", url)
        if resp.status_code == 200:
            return resp.json()
        return []
