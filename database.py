"""SQLite persistence layer (async, aiosqlite).

Two tables are maintained:

* ``products``   -- one row per tracked product URL.
* ``price_logs`` -- an append-only history of every observed price, which
  powers the old -> new comparison in alerts and could later feed charts.

``last_notified_price`` is an internal marker used to avoid spamming the same
WhatsApp number when a product bounces around a price we already alerted on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    url                    TEXT UNIQUE NOT NULL,
    platform               TEXT NOT NULL,
    title                  TEXT,
    initial_price          REAL,
    current_price          REAL,
    target_price           REAL,
    percentage_drop_target REAL,
    last_checked           TEXT,
    is_active              INTEGER NOT NULL DEFAULT 1,
    last_notified_price    REAL
);

CREATE TABLE IF NOT EXISTS price_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    price      REAL NOT NULL,
    timestamp  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deal_alerts_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    product_url      TEXT NOT NULL,
    title            TEXT,
    price            REAL,
    effective_price  REAL,
    discount_percent REAL,
    coupon_text      TEXT,
    platform         TEXT,
    notified_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS custom_radar_rules (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    name               TEXT NOT NULL,
    category           TEXT,
    query              TEXT NOT NULL,
    platforms          TEXT,
    min_discount       REAL DEFAULT 70.0,
    max_price          REAL,
    min_mrp            REAL,
    negative_keywords  TEXT,
    is_active          INTEGER NOT NULL DEFAULT 1,
    created_at         TEXT NOT NULL
);
"""


@dataclass
class Product:
    """Row object mirroring the ``products`` table."""

    id: int
    url: str
    platform: str
    title: Optional[str]
    initial_price: Optional[float]
    current_price: Optional[float]
    target_price: Optional[float]
    percentage_drop_target: Optional[float]
    last_checked: Optional[str]
    is_active: bool
    last_notified_price: Optional[float]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _row_to_product(row: Any) -> Product:
    return Product(
        id=row["id"],
        url=row["url"],
        platform=row["platform"],
        title=row["title"],
        initial_price=row["initial_price"],
        current_price=row["current_price"],
        target_price=row["target_price"],
        percentage_drop_target=row["percentage_drop_target"],
        last_checked=row["last_checked"],
        is_active=bool(row["is_active"]),
        last_notified_price=row["last_notified_price"],
    )


def get_database(path_or_config: Any = None):
    """Return SupabaseDatabase if configured via environment, else SQLite Database."""
    import os
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if supabase_url and supabase_key:
        from supabase_db import SupabaseDatabase
        return SupabaseDatabase(supabase_url, supabase_key)

    path = "price_tracker.db"
    if isinstance(path_or_config, str):
        path = path_or_config
    elif hasattr(path_or_config, "database_path"):
        path = path_or_config.database_path
    return Database(path)


class Database:
    """Async SQLite wrapper exposing the CRUD ops used by the CLI and tracker."""

    def __init__(self, path: str = "price_tracker.db") -> None:
        self.path = path
        self._conn: Optional[aiosqlite.Connection] = None

    async def initialize(self) -> None:
        """Open the connection (idempotently) and create both tables."""
        if self._conn is not None:
            return
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database.initialize() must be called first")
        return self._conn

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
        """Insert a product, or reactivate/update it if the URL already exists.

        ``ON CONFLICT`` keeps the row id stable and resets the anti-spam
        marker so a deliberate re-add triggers a fresh alert.
        """
        conn = self.conn
        await conn.execute(
            """
            INSERT INTO products
                (url, platform, title, initial_price, current_price,
                 target_price, percentage_drop_target, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(url) DO UPDATE SET
                platform                = excluded.platform,
                title                   = COALESCE(excluded.title, products.title),
                initial_price           = COALESCE(excluded.initial_price, products.initial_price),
                current_price           = COALESCE(excluded.current_price, products.current_price),
                target_price            = COALESCE(excluded.target_price, products.target_price),
                percentage_drop_target  = COALESCE(excluded.percentage_drop_target,
                                                   products.percentage_drop_target),
                is_active               = 1,
                last_notified_price     = NULL
            """,
            (url, platform, title, initial_price, initial_price, target_price, percentage_drop_target),
        )
        await conn.commit()
        cursor = await conn.execute("SELECT id FROM products WHERE url = ?", (url,))
        row = await cursor.fetchone()
        return int(row["id"])

    async def get_product(self, product_id: int) -> Optional[Product]:
        cursor = await self.conn.execute("SELECT * FROM products WHERE id = ?", (product_id,))
        row = await cursor.fetchone()
        return _row_to_product(row) if row else None

    async def get_products(self, active_only: bool = False) -> list[Product]:
        query = "SELECT * FROM products"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY id"
        cursor = await self.conn.execute(query)
        return [_row_to_product(row) for row in await cursor.fetchall()]

    async def remove_product(self, product_id: int) -> None:
        await self.conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
        await self.conn.commit()

    async def set_active(self, product_id: int, active: bool) -> None:
        await self.conn.execute(
            "UPDATE products SET is_active = ?, last_checked = ? WHERE id = ?",
            (1 if active else 0, _now(), product_id),
        )
        await self.conn.commit()

    async def update_price(self, product_id: int, price: Optional[float], title: Optional[str] = None) -> None:
        """Record a newly observed price in ``price_logs`` and refresh the row."""
        ts = _now()
        if price is not None:
            await self.conn.execute(
                "INSERT INTO price_logs (product_id, price, timestamp) VALUES (?, ?, ?)",
                (product_id, price, ts),
            )
            if title:
                await self.conn.execute(
                    "UPDATE products SET current_price = ?, title = ?, last_checked = ? WHERE id = ?",
                    (price, title, ts, product_id),
                )
            else:
                await self.conn.execute(
                    "UPDATE products SET current_price = ?, last_checked = ? WHERE id = ?",
                    (price, ts, product_id),
                )
        else:
            if title:
                await self.conn.execute(
                    "UPDATE products SET title = ?, last_checked = ? WHERE id = ?",
                    (title, ts, product_id),
                )
            else:
                await self.conn.execute(
                    "UPDATE products SET last_checked = ? WHERE id = ?",
                    (ts, product_id),
                )
        await self.conn.commit()

    async def set_last_notified(self, product_id: int, price: float) -> None:
        await self.conn.execute(
            "UPDATE products SET last_notified_price = ? WHERE id = ?", (price, product_id)
        )
        await self.conn.commit()

    async def price_history(self, product_id: int, limit: int = 20) -> list[tuple[float, str]]:
        cursor = await self.conn.execute(
            "SELECT price, timestamp FROM price_logs WHERE product_id = ? "
            "ORDER BY timestamp DESC, id DESC LIMIT ?",
            (product_id, limit),
        )
        return [(row["price"], row["timestamp"]) for row in await cursor.fetchall()]

    # -------------------------------------------------------- deal_alerts_log
    async def is_deal_recently_notified(
        self, product_url: str, hours: int = 24, current_price: Optional[float] = None
    ) -> bool:
        """Check if an alert was already dispatched for this URL within the last N hours at this price."""
        cursor = await self.conn.execute(
            "SELECT effective_price, price, notified_at FROM deal_alerts_log WHERE product_url = ? "
            "ORDER BY datetime(notified_at) DESC, id DESC LIMIT 1",
            (product_url,),
        )
        row = await cursor.fetchone()
        if not row:
            return False

        # If price dropped further by >= ₹2, allow immediate re-alert!
        if current_price is not None:
            last_price = row["effective_price"] or row["price"]
            if last_price is not None and current_price < (last_price - 2.0):
                return False

        # Otherwise check 24-hour window for identical price
        cursor2 = await self.conn.execute(
            "SELECT id FROM deal_alerts_log WHERE product_url = ? AND datetime(notified_at) >= datetime('now', ?) LIMIT 1",
            (product_url, f"-{hours} hours"),
        )
        row2 = await cursor2.fetchone()
        return row2 is not None

    async def log_deal_alert(
        self,
        product_url: str,
        title: str,
        price: float,
        effective_price: float,
        discount_percent: float,
        coupon_text: Optional[str] = None,
        platform: Optional[str] = None,
    ) -> None:
        """Record an alert in the de-duplication log."""
        await self.conn.execute(
            "INSERT INTO deal_alerts_log (product_url, title, price, effective_price, discount_percent, coupon_text, platform, notified_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (product_url, title, price, effective_price, discount_percent, coupon_text, platform, _now()),
        )
        await self.conn.commit()

    # ----------------------------------------------------- custom_radar_rules
    async def add_custom_rule(
        self,
        name: str,
        query: str,
        category: str = "Custom",
        platforms: str = "amazon,flipkart",
        min_discount: float = 70.0,
        max_price: Optional[float] = None,
        min_mrp: Optional[float] = None,
        negative_keywords: str = "",
    ) -> int:
        cursor = await self.conn.execute(
            "INSERT INTO custom_radar_rules (name, category, query, platforms, min_discount, max_price, min_mrp, negative_keywords, is_active, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
            (name, category, query, platforms, min_discount, max_price, min_mrp, negative_keywords, _now()),
        )
        await self.conn.commit()
        return cursor.lastrowid

    async def get_custom_rules(self, active_only: bool = True) -> list[dict[str, Any]]:
        query = "SELECT * FROM custom_radar_rules"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY id"
        cursor = await self.conn.execute(query)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def remove_custom_rule(self, rule_id: int) -> None:
        await self.conn.execute("DELETE FROM custom_radar_rules WHERE id = ?", (rule_id,))
        await self.conn.commit()