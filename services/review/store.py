import json
import os
import sqlite3
from datetime import datetime

from services.messages.models import IncomingMessage

from .models import ReviewConfig, ReviewSubmissionResult, ReviewTask


PENDING_STATUS = "pending_confirmation"
SUBMITTED_STATUS = "submitted"
SKIPPED_NO_CONFIG_STATUS = "skipped_no_config"
FAILED_RETRYABLE_STATUS = "failed_retryable"
BLOCKED_RISK_CONTROL_STATUS = "blocked_risk_control"


def initialize_review_schema(db_path: str) -> None:
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS review_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id TEXT NOT NULL UNIQUE,
                content TEXT NOT NULL,
                rating INTEGER NOT NULL DEFAULT 5,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_review_configs_item_id ON review_configs (item_id)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS review_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL UNIQUE,
                item_id TEXT NOT NULL,
                buyer_id TEXT NOT NULL DEFAULT '',
                buyer_name TEXT NOT NULL DEFAULT '',
                chat_id TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                rating INTEGER NOT NULL DEFAULT 5,
                status TEXT NOT NULL,
                review_url TEXT NOT NULL DEFAULT '',
                screenshot_path TEXT NOT NULL DEFAULT '',
                response_summary TEXT NOT NULL DEFAULT '',
                evidence_json TEXT NOT NULL DEFAULT '{}',
                failed_reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                submitted_at TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_review_tasks_item_id ON review_tasks (item_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_review_tasks_status ON review_tasks (status)")


class ReviewStore:
    def __init__(self, db_path: str = "data/chat_history.db"):
        self.db_path = db_path
        initialize_review_schema(db_path)

    def upsert_config(
        self,
        *,
        item_id: str,
        content: str,
        enabled: bool = True,
        rating: int = 5,
    ) -> int:
        item_id = str(item_id or "").strip()
        content = str(content or "").strip()
        if not item_id:
            raise ValueError("item_id is required")
        if not content:
            raise ValueError("content is required")
        if int(rating) != 5:
            raise ValueError("rating is fixed to 5 in the first version")

        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO review_configs (item_id, content, rating, enabled, created_at, updated_at)
                VALUES (?, ?, 5, ?, ?, ?)
                ON CONFLICT(item_id)
                DO UPDATE SET content = excluded.content,
                              rating = 5,
                              enabled = excluded.enabled,
                              updated_at = excluded.updated_at
                """,
                (item_id, content, 1 if enabled else 0, now, now),
            )
            row = conn.execute("SELECT id FROM review_configs WHERE item_id = ?", (item_id,)).fetchone()
            return int(row[0])

    def list_configs(self, item_id: str | None = None) -> list[ReviewConfig]:
        query = """
            SELECT id, item_id, content, rating, enabled, created_at, updated_at
            FROM review_configs
        """
        params: tuple[object, ...] = ()
        if item_id:
            query += " WHERE item_id = ?"
            params = (str(item_id).strip(),)
        query += " ORDER BY id ASC"
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._config_from_row(row) for row in rows]

    def get_enabled_config(self, item_id: str) -> ReviewConfig | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT id, item_id, content, rating, enabled, created_at, updated_at
                FROM review_configs
                WHERE item_id = ? AND enabled = 1
                LIMIT 1
                """,
                (str(item_id).strip(),),
            ).fetchone()
        return self._config_from_row(row) if row else None

    def enqueue_from_message(self, incoming: IncomingMessage) -> ReviewTask:
        return self.enqueue_task(
            order_id=incoming.order_id,
            item_id=incoming.item_id,
            buyer_id=incoming.sender_id,
            buyer_name=incoming.sender_name,
            chat_id=incoming.chat_id,
        )

    def enqueue_task(
        self,
        *,
        order_id: str,
        item_id: str,
        buyer_id: str,
        buyer_name: str,
        chat_id: str,
        review_url: str = "",
    ) -> ReviewTask:
        order_id = str(order_id or "").strip()
        item_id = str(item_id or "").strip()
        if not order_id:
            raise ValueError("order_id is required")
        if not item_id:
            raise ValueError("item_id is required")

        now = datetime.now().isoformat()
        config = self.get_enabled_config(item_id)
        if config:
            content = config.content
            status = PENDING_STATUS
            rating = config.rating
            failed_reason = ""
        else:
            content = ""
            status = SKIPPED_NO_CONFIG_STATUS
            rating = 5
            failed_reason = "review_config_missing"

        with sqlite3.connect(self.db_path) as conn:
            existing = conn.execute(
                """
                SELECT id, order_id, item_id, buyer_id, buyer_name, chat_id, content, rating, status,
                       review_url, screenshot_path, response_summary, evidence_json, failed_reason,
                       created_at, updated_at, submitted_at
                FROM review_tasks
                WHERE order_id = ?
                """,
                (order_id,),
            ).fetchone()
            if existing:
                return self._task_from_row(existing)

            cursor = conn.execute(
                """
                INSERT INTO review_tasks
                (order_id, item_id, buyer_id, buyer_name, chat_id, content, rating, status,
                 review_url, failed_reason, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    item_id,
                    str(buyer_id or ""),
                    str(buyer_name or ""),
                    str(chat_id or ""),
                    content,
                    rating,
                    status,
                    str(review_url or ""),
                    failed_reason,
                    now,
                    now,
                ),
            )
            row_id = int(cursor.lastrowid)
        task = self.get_task(row_id)
        if not task:
            raise RuntimeError("review task was not created")
        return task

    def list_tasks(
        self,
        *,
        status: str | None = None,
        item_id: str | None = None,
        limit: int = 50,
    ) -> list[ReviewTask]:
        query = """
            SELECT id, order_id, item_id, buyer_id, buyer_name, chat_id, content, rating, status,
                   review_url, screenshot_path, response_summary, evidence_json, failed_reason,
                   created_at, updated_at, submitted_at
            FROM review_tasks
        """
        clauses = []
        params: list[object] = []
        if status:
            clauses.append("status = ?")
            params.append(str(status))
        if item_id:
            clauses.append("item_id = ?")
            params.append(str(item_id).strip())
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(int(limit))
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._task_from_row(row) for row in rows]

    def get_task(self, task_id: int) -> ReviewTask | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT id, order_id, item_id, buyer_id, buyer_name, chat_id, content, rating, status,
                       review_url, screenshot_path, response_summary, evidence_json, failed_reason,
                       created_at, updated_at, submitted_at
                FROM review_tasks
                WHERE id = ?
                """,
                (int(task_id),),
            ).fetchone()
        return self._task_from_row(row) if row else None

    def set_review_url(self, task_id: int, review_url: str) -> ReviewTask:
        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE review_tasks SET review_url = ?, updated_at = ? WHERE id = ?",
                (str(review_url or "").strip(), now, int(task_id)),
            )
        task = self.get_task(task_id)
        if not task:
            raise ValueError("review task not found")
        return task

    def record_submission_result(self, task_id: int, result: ReviewSubmissionResult) -> ReviewTask:
        now = datetime.now().isoformat()
        status = SUBMITTED_STATUS if result.success else self._failed_status(result.failed_reason)
        submitted_at = now if result.success else None
        evidence_json = json.dumps(result.evidence or {}, ensure_ascii=False)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE review_tasks
                SET status = ?,
                    screenshot_path = ?,
                    response_summary = ?,
                    evidence_json = ?,
                    failed_reason = ?,
                    updated_at = ?,
                    submitted_at = COALESCE(?, submitted_at)
                WHERE id = ?
                """,
                (
                    status,
                    result.screenshot_path,
                    result.response_summary,
                    evidence_json,
                    result.failed_reason,
                    now,
                    submitted_at,
                    int(task_id),
                ),
            )
        task = self.get_task(task_id)
        if not task:
            raise ValueError("review task not found")
        return task

    def _failed_status(self, failed_reason: str) -> str:
        if failed_reason == "risk_control":
            return BLOCKED_RISK_CONTROL_STATUS
        return FAILED_RETRYABLE_STATUS

    def _config_from_row(self, row) -> ReviewConfig:
        return ReviewConfig(
            id=int(row[0]),
            item_id=row[1],
            content=row[2],
            rating=int(row[3]),
            enabled=bool(row[4]),
            created_at=row[5],
            updated_at=row[6],
        )

    def _task_from_row(self, row) -> ReviewTask:
        return ReviewTask(
            id=int(row[0]),
            order_id=row[1],
            item_id=row[2],
            buyer_id=row[3] or "",
            buyer_name=row[4] or "",
            chat_id=row[5] or "",
            content=row[6] or "",
            rating=int(row[7]),
            status=row[8],
            review_url=row[9] or "",
            screenshot_path=row[10] or "",
            response_summary=row[11] or "",
            evidence_json=row[12] or "{}",
            failed_reason=row[13] or "",
            created_at=row[14],
            updated_at=row[15],
            submitted_at=row[16],
        )
