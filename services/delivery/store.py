import os
import hashlib
import sqlite3
from datetime import datetime
from typing import Iterable

from .models import DeliveryConfig, DeliveryInventoryItem


VALID_DELIVERY_TYPES = {"text", "data", "api"}


def initialize_delivery_schema(db_path: str) -> None:
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS delivery_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id TEXT NOT NULL,
                name TEXT NOT NULL,
                delivery_type TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                api_config TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_delivery_configs_item_id ON delivery_configs (item_id)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS delivery_inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                config_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'available',
                reserved_order_no TEXT,
                reservation_id TEXT,
                reservation_line_no INTEGER,
                reserved_at TEXT,
                sent_at TEXT,
                failed_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(config_id) REFERENCES delivery_configs(id),
                UNIQUE(reserved_order_no, reservation_line_no)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_delivery_inventory_config_status ON delivery_inventory (config_id, status)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS delivery_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_no TEXT NOT NULL,
                chat_id TEXT,
                item_id TEXT,
                buyer_id TEXT,
                config_id INTEGER,
                content_digest TEXT,
                status TEXT NOT NULL,
                failed_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(order_no, status)
            )
            """
        )


class DeliveryStore:
    def __init__(self, db_path: str = "data/chat_history.db"):
        self.db_path = db_path
        initialize_delivery_schema(db_path)

    def add_config(
        self,
        *,
        item_id: str,
        name: str,
        delivery_type: str,
        content: str,
        enabled: bool = True,
        api_config: str | None = None,
    ) -> int:
        if delivery_type not in VALID_DELIVERY_TYPES:
            raise ValueError(f"delivery_type must be one of {sorted(VALID_DELIVERY_TYPES)}")

        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO delivery_configs
                (item_id, name, delivery_type, content, api_config, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (item_id, name, delivery_type, content, api_config, 1 if enabled else 0, now, now),
            )
            return int(cursor.lastrowid)

    def list_configs(self, item_id: str | None = None) -> list[DeliveryConfig]:
        query = "SELECT id, item_id, name, delivery_type, content, enabled, api_config, created_at, updated_at FROM delivery_configs"
        params: tuple[str, ...] = ()
        if item_id is not None:
            query += " WHERE item_id = ?"
            params = (item_id,)
        query += " ORDER BY id ASC"

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._config_from_row(row) for row in rows]

    def get_enabled_config(self, item_id: str) -> DeliveryConfig | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT id, item_id, name, delivery_type, content, enabled, api_config, created_at, updated_at
                FROM delivery_configs
                WHERE item_id = ? AND enabled = 1
                ORDER BY id DESC
                LIMIT 1
                """,
                (item_id,),
            ).fetchone()
        return self._config_from_row(row) if row else None

    def set_config_enabled(self, config_id: int, enabled: bool) -> None:
        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE delivery_configs SET enabled = ?, updated_at = ? WHERE id = ?",
                (1 if enabled else 0, now, config_id),
            )

    def upsert_config_for_item(
        self,
        *,
        item_id: str,
        name: str,
        delivery_type: str,
        content: str,
        enabled: bool = True,
        api_config: str | None = None,
    ) -> int:
        if delivery_type not in VALID_DELIVERY_TYPES:
            raise ValueError(f"delivery_type must be one of {sorted(VALID_DELIVERY_TYPES)}")

        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT id
                FROM delivery_configs
                WHERE item_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (item_id,),
            ).fetchone()
            if row:
                conn.execute(
                    """
                    UPDATE delivery_configs
                    SET name = ?, delivery_type = ?, content = ?, api_config = ?, enabled = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (name, delivery_type, content, api_config, 1 if enabled else 0, now, row[0]),
                )
                return int(row[0])

            cursor = conn.execute(
                """
                INSERT INTO delivery_configs
                (item_id, name, delivery_type, content, api_config, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (item_id, name, delivery_type, content, api_config, 1 if enabled else 0, now, now),
            )
            return int(cursor.lastrowid)

    def add_inventory(self, config_id: int, contents: Iterable[str]) -> list[int]:
        now = datetime.now().isoformat()
        row_ids: list[int] = []
        with sqlite3.connect(self.db_path) as conn:
            for content in contents:
                cursor = conn.execute(
                    """
                    INSERT INTO delivery_inventory
                    (config_id, content, status, created_at, updated_at)
                    VALUES (?, ?, 'available', ?, ?)
                    """,
                    (config_id, content, now, now),
                )
                row_ids.append(int(cursor.lastrowid))
        return row_ids

    def list_inventory(self, config_id: int, status: str | None = None) -> list[DeliveryInventoryItem]:
        query = """
            SELECT id, config_id, content, status, reserved_order_no, reservation_id,
                   reservation_line_no, reserved_at, sent_at, failed_reason
            FROM delivery_inventory
            WHERE config_id = ?
        """
        params: tuple[object, ...] = (config_id,)
        if status:
            query += " AND status = ?"
            params = (config_id, status)
        query += " ORDER BY id ASC"
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._inventory_from_row(row) for row in rows]

    def reserve_inventory(self, *, config_id: int, order_no: str, quantity: int) -> list[DeliveryInventoryItem]:
        if quantity <= 0:
            raise ValueError("quantity must be positive")

        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            existing = conn.execute(
                """
                SELECT id, config_id, content, status, reserved_order_no, reservation_id,
                       reservation_line_no, reserved_at, sent_at, failed_reason
                FROM delivery_inventory
                WHERE config_id = ?
                  AND reserved_order_no = ?
                  AND status IN ('reserved', 'failed_retryable', 'sent')
                ORDER BY reservation_line_no ASC
                """,
                (config_id, order_no),
            ).fetchall()
            if len(existing) >= quantity:
                return [self._inventory_from_row(row) for row in existing[:quantity]]

            available = conn.execute(
                """
                SELECT id
                FROM delivery_inventory
                WHERE config_id = ? AND status = 'available'
                ORDER BY id ASC
                LIMIT ?
                """,
                (config_id, quantity),
            ).fetchall()
            if len(available) < quantity:
                return []

            reservation_id = f"{order_no}-{int(datetime.now().timestamp() * 1000)}"
            for line_no, (row_id,) in enumerate(available, start=1):
                conn.execute(
                    """
                    UPDATE delivery_inventory
                    SET status = 'reserved',
                        reserved_order_no = ?,
                        reservation_id = ?,
                        reservation_line_no = ?,
                        reserved_at = ?,
                        failed_reason = NULL,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (order_no, reservation_id, line_no, now, now, row_id),
                )

            rows = conn.execute(
                """
                SELECT id, config_id, content, status, reserved_order_no, reservation_id,
                       reservation_line_no, reserved_at, sent_at, failed_reason
                FROM delivery_inventory
                WHERE config_id = ? AND reserved_order_no = ?
                ORDER BY reservation_line_no ASC
                """,
                (config_id, order_no),
            ).fetchall()
            return [self._inventory_from_row(row) for row in rows]

    def mark_inventory_sent(self, row_ids: list[int]) -> None:
        if not row_ids:
            return
        now = datetime.now().isoformat()
        placeholders = ",".join("?" for _ in row_ids)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"""
                UPDATE delivery_inventory
                SET status = 'sent', sent_at = ?, updated_at = ?, failed_reason = NULL
                WHERE id IN ({placeholders})
                """,
                (now, now, *row_ids),
            )

    def mark_inventory_failed(self, row_ids: list[int], reason: str) -> None:
        if not row_ids:
            return
        now = datetime.now().isoformat()
        placeholders = ",".join("?" for _ in row_ids)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"""
                UPDATE delivery_inventory
                SET status = 'failed_retryable', failed_reason = ?, updated_at = ?
                WHERE id IN ({placeholders})
                """,
                (reason, now, *row_ids),
            )

    def has_sent_order(self, order_no: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM delivery_logs WHERE order_no = ? AND status = 'sent' LIMIT 1",
                (order_no,),
            ).fetchone()
        return row is not None

    def has_delivery_status(self, order_no: str, status: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM delivery_logs WHERE order_no = ? AND status = ? LIMIT 1",
                (order_no, status),
            ).fetchone()
        return row is not None

    def has_platform_confirmed_order(self, order_no: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM delivery_logs
                WHERE order_no = ?
                  AND status IN ('platform_confirmed', 'platform_already_delivered')
                LIMIT 1
                """,
                (order_no,),
            ).fetchone()
        return row is not None

    def record_delivery_log(
        self,
        *,
        order_no: str,
        chat_id: str | None,
        item_id: str | None,
        buyer_id: str | None,
        config_id: int | None,
        content: str,
        status: str,
        failed_reason: str | None = None,
    ) -> None:
        now = datetime.now().isoformat()
        content_digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO delivery_logs
                (order_no, chat_id, item_id, buyer_id, config_id, content_digest, status, failed_reason, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_no, status)
                DO UPDATE SET
                    chat_id = excluded.chat_id,
                    item_id = excluded.item_id,
                    buyer_id = excluded.buyer_id,
                    config_id = excluded.config_id,
                    content_digest = excluded.content_digest,
                    failed_reason = excluded.failed_reason,
                    updated_at = excluded.updated_at
                """,
                (
                    order_no,
                    chat_id,
                    item_id,
                    buyer_id,
                    config_id,
                    content_digest,
                    status,
                    failed_reason,
                    now,
                    now,
                ),
            )

    def _config_from_row(self, row) -> DeliveryConfig:
        return DeliveryConfig(
            id=int(row[0]),
            item_id=row[1],
            name=row[2],
            delivery_type=row[3],
            content=row[4],
            enabled=bool(row[5]),
            api_config=row[6],
            created_at=row[7],
            updated_at=row[8],
        )

    def _inventory_from_row(self, row) -> DeliveryInventoryItem:
        return DeliveryInventoryItem(
            id=int(row[0]),
            config_id=int(row[1]),
            content=row[2],
            status=row[3],
            reserved_order_no=row[4],
            reservation_id=row[5],
            reservation_line_no=row[6],
            reserved_at=row[7],
            sent_at=row[8],
            failed_reason=row[9],
        )
