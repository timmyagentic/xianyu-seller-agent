import json
import os
import sqlite3
from datetime import datetime

from .models import AutoRelistConfig, ItemSnapshot, ListingJob, RelistRequest


def initialize_listing_schema(db_path: str) -> None:
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                item_id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                price REAL,
                description TEXT,
                last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS listing_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_type TEXT NOT NULL,
                item_id TEXT NOT NULL,
                expected_title TEXT,
                target_stock INTEGER,
                delivery_config TEXT,
                previous_status TEXT,
                result_status TEXT NOT NULL,
                final_status TEXT,
                item_url TEXT,
                screenshot_path TEXT,
                response_summary TEXT,
                evidence_json TEXT,
                failed_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_listing_jobs_item_id ON listing_jobs (item_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_listing_jobs_status ON listing_jobs (result_status)")
        _ensure_column(conn, "listing_jobs", "target_stock", "INTEGER")
        _ensure_column(conn, "listing_jobs", "evidence_json", "TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS auto_relist_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id TEXT NOT NULL UNIQUE,
                target_stock INTEGER NOT NULL,
                expected_title TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                allow_playwright INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_auto_relist_configs_item_id ON auto_relist_configs (item_id)")


def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, column_type: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


class ListingStore:
    def __init__(self, db_path: str = "data/chat_history.db"):
        self.db_path = db_path
        initialize_listing_schema(db_path)

    def get_item_snapshot(self, item_id: str) -> ItemSnapshot | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT data FROM items WHERE item_id = ?", (item_id,)).fetchone()
        if not row:
            return None
        try:
            data = json.loads(row[0])
        except (TypeError, json.JSONDecodeError):
            return None

        snapshot_item_id = str(data.get("item_id") or data.get("itemId") or data.get("id") or item_id)
        title = str(data.get("title") or data.get("name") or "")
        status = normalize_item_status(data.get("status", data.get("item_status", data.get("itemStatus", ""))))
        item_url = str(data.get("item_url") or data.get("itemUrl") or data.get("detail_url") or data.get("detailUrl") or "")
        return ItemSnapshot(
            item_id=snapshot_item_id,
            title=title,
            status=status,
            item_url=item_url,
            raw=data,
        )

    def save_item_snapshots(self, items: list[dict]) -> tuple[int, int]:
        saved_count = 0
        changed_count = 0
        for item in items:
            saved, changed = self.save_item_snapshot(item)
            if saved:
                saved_count += 1
            if changed:
                changed_count += 1
        return saved_count, changed_count

    def save_item_snapshot(self, item: dict) -> tuple[bool, bool]:
        item_id = self._item_id_from_data(item)
        if not item_id or item_id.startswith("auto_"):
            return False, False

        now = datetime.now().isoformat()
        normalized = dict(item)
        normalized.setdefault("item_id", item_id)
        normalized.setdefault("itemId", item_id)
        data_json = json.dumps(normalized, ensure_ascii=False)
        price = self._price_from_data(normalized)
        description = self._description_from_data(normalized)

        with sqlite3.connect(self.db_path) as conn:
            existing = conn.execute(
                "SELECT data, price, description FROM items WHERE item_id = ?",
                (item_id,),
            ).fetchone()
            changed = existing != (data_json, price, description)
            conn.execute(
                """
                INSERT INTO items (item_id, data, price, description, last_updated)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(item_id)
                DO UPDATE SET data = excluded.data,
                              price = excluded.price,
                              description = excluded.description,
                              last_updated = excluded.last_updated
                """,
                (item_id, data_json, price, description, now),
            )
        return True, changed

    def list_item_snapshots(self, limit: int = 100) -> list[ItemSnapshot]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT item_id
                FROM items
                ORDER BY last_updated DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        snapshots = []
        for (item_id,) in rows:
            snapshot = self.get_item_snapshot(item_id)
            if snapshot:
                snapshots.append(snapshot)
        return snapshots

    def record_job(
        self,
        *,
        request: RelistRequest,
        result_status: str,
        previous_status: str = "",
        final_status: str = "",
        item_url: str = "",
        screenshot_path: str = "",
        response_summary: str = "",
        evidence: dict | None = None,
        failed_reason: str = "",
    ) -> int:
        now = datetime.now().isoformat()
        delivery_config = ""
        if request.delivery:
            delivery_config = json.dumps(request.delivery.__dict__, ensure_ascii=False)
        evidence_json = json.dumps(evidence or {}, ensure_ascii=False)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO listing_jobs
                (task_type, item_id, expected_title, target_stock, delivery_config, previous_status, result_status,
                 final_status, item_url, screenshot_path, response_summary, evidence_json, failed_reason, created_at, updated_at)
                VALUES ('relist', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request.item_id,
                    request.expected_title,
                    request.target_stock,
                    delivery_config,
                    previous_status,
                    result_status,
                    final_status,
                    item_url,
                    screenshot_path,
                    response_summary,
                    evidence_json,
                    failed_reason,
                    now,
                    now,
                ),
            )
            return int(cursor.lastrowid)

    def upsert_auto_relist_config(
        self,
        *,
        item_id: str,
        target_stock: int,
        expected_title: str = "",
        enabled: bool = True,
        allow_playwright: bool = False,
    ) -> int:
        item_id = str(item_id).strip()
        if not item_id:
            raise ValueError("item_id is required")
        if target_stock <= 0:
            raise ValueError("target_stock must be positive")

        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO auto_relist_configs
                (item_id, target_stock, expected_title, enabled, allow_playwright, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(item_id)
                DO UPDATE SET target_stock = excluded.target_stock,
                              expected_title = excluded.expected_title,
                              enabled = excluded.enabled,
                              allow_playwright = excluded.allow_playwright,
                              updated_at = excluded.updated_at
                """,
                (
                    item_id,
                    int(target_stock),
                    str(expected_title or ""),
                    1 if enabled else 0,
                    1 if allow_playwright else 0,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT id FROM auto_relist_configs WHERE item_id = ?",
                (item_id,),
            ).fetchone()
            return int(row[0])

    def get_enabled_auto_relist_config(self, item_id: str) -> AutoRelistConfig | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT id, item_id, target_stock, expected_title, enabled, allow_playwright, created_at, updated_at
                FROM auto_relist_configs
                WHERE item_id = ? AND enabled = 1
                LIMIT 1
                """,
                (item_id,),
            ).fetchone()
        return self._auto_relist_config_from_row(row) if row else None

    def list_auto_relist_configs(self, item_id: str | None = None) -> list[AutoRelistConfig]:
        query = """
            SELECT id, item_id, target_stock, expected_title, enabled, allow_playwright, created_at, updated_at
            FROM auto_relist_configs
        """
        params: tuple[object, ...] = ()
        if item_id:
            query += " WHERE item_id = ?"
            params = (item_id,)
        query += " ORDER BY id ASC"
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._auto_relist_config_from_row(row) for row in rows]

    def list_jobs(self, limit: int = 50) -> list[ListingJob]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, task_type, item_id, expected_title, target_stock, delivery_config, previous_status,
                       result_status, final_status, item_url, screenshot_path, response_summary,
                       evidence_json, failed_reason, created_at, updated_at
                FROM listing_jobs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._job_from_row(row) for row in rows]

    def _job_from_row(self, row) -> ListingJob:
        return ListingJob(
            id=row[0],
            task_type=row[1],
            item_id=row[2],
            expected_title=row[3] or "",
            target_stock=row[4],
            delivery_config=row[5] or "",
            previous_status=row[6] or "",
            result_status=row[7],
            final_status=row[8] or "",
            item_url=row[9] or "",
            screenshot_path=row[10] or "",
            response_summary=row[11] or "",
            evidence_json=row[12] or "{}",
            failed_reason=row[13] or "",
            created_at=row[14],
            updated_at=row[15],
        )

    def _auto_relist_config_from_row(self, row) -> AutoRelistConfig:
        return AutoRelistConfig(
            id=int(row[0]),
            item_id=row[1],
            target_stock=int(row[2]),
            expected_title=row[3] or "",
            enabled=bool(row[4]),
            allow_playwright=bool(row[5]),
            created_at=row[6],
            updated_at=row[7],
        )

    def _item_id_from_data(self, item: dict) -> str:
        return str(item.get("item_id") or item.get("itemId") or item.get("id") or "").strip()

    def _price_from_data(self, item: dict) -> float | None:
        price = item.get("price")
        if price is None and isinstance(item.get("priceInfo"), dict):
            price = item["priceInfo"].get("price")
        if price is None:
            price = item.get("soldPrice")
        try:
            text = "".join(ch for ch in str(price) if ch.isdigit() or ch == ".")
            return float(text) if text else None
        except (TypeError, ValueError):
            return None

    def _description_from_data(self, item: dict) -> str:
        return str(item.get("description") or item.get("desc") or item.get("detail") or "")


def normalize_item_status(value: object) -> str:
    if value is None or value == "":
        return "unknown"
    text = str(value).strip().lower()
    active_values = {"0", "active", "online", "on_sale", "selling", "在售", "已上架"}
    inactive_values = {"1", "inactive", "offline", "off_sale", "down", "下架", "已下架"}
    sold_values = {"sold", "sold_out", "已售出", "卖掉了"}
    relistable_values = {"relistable", "可重新上架", "重新上架"}
    if text in active_values:
        return "active"
    if text in sold_values:
        return "sold"
    if text in relistable_values:
        return "relistable"
    if text in inactive_values:
        return "inactive"
    return text
