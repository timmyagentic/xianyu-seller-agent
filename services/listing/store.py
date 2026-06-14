import json
import os
import sqlite3
from datetime import datetime

from .models import ItemSnapshot, ListingJob, RelistRequest


def initialize_listing_schema(db_path: str) -> None:
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS listing_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_type TEXT NOT NULL,
                item_id TEXT NOT NULL,
                expected_title TEXT,
                delivery_config TEXT,
                previous_status TEXT,
                result_status TEXT NOT NULL,
                final_status TEXT,
                item_url TEXT,
                screenshot_path TEXT,
                response_summary TEXT,
                failed_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_listing_jobs_item_id ON listing_jobs (item_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_listing_jobs_status ON listing_jobs (result_status)")


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
        failed_reason: str = "",
    ) -> int:
        now = datetime.now().isoformat()
        delivery_config = ""
        if request.delivery:
            delivery_config = json.dumps(request.delivery.__dict__, ensure_ascii=False)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO listing_jobs
                (task_type, item_id, expected_title, delivery_config, previous_status, result_status,
                 final_status, item_url, screenshot_path, response_summary, failed_reason, created_at, updated_at)
                VALUES ('relist', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request.item_id,
                    request.expected_title,
                    delivery_config,
                    previous_status,
                    result_status,
                    final_status,
                    item_url,
                    screenshot_path,
                    response_summary,
                    failed_reason,
                    now,
                    now,
                ),
            )
            return int(cursor.lastrowid)

    def list_jobs(self, limit: int = 50) -> list[ListingJob]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, task_type, item_id, expected_title, delivery_config, previous_status,
                       result_status, final_status, item_url, screenshot_path, response_summary,
                       failed_reason, created_at, updated_at
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
            delivery_config=row[4] or "",
            previous_status=row[5] or "",
            result_status=row[6],
            final_status=row[7] or "",
            item_url=row[8] or "",
            screenshot_path=row[9] or "",
            response_summary=row[10] or "",
            failed_reason=row[11] or "",
            created_at=row[12],
            updated_at=row[13],
        )


def normalize_item_status(value: object) -> str:
    if value is None or value == "":
        return "unknown"
    text = str(value).strip().lower()
    active_values = {"0", "active", "online", "on_sale", "selling", "在售", "已上架"}
    inactive_values = {"1", "inactive", "offline", "off_sale", "sold_out", "下架", "已下架"}
    if text in active_values:
        return "active"
    if text in inactive_values:
        return "inactive"
    return text
