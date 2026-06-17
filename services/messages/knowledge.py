import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_ITEM_KNOWLEDGE_DIR = "data/item_knowledge"
DEFAULT_UNKNOWN_QUESTIONS_PATH = "data/unknown_questions.jsonl"


class ItemKnowledgeBase:
    """Read per-item Markdown knowledge used by the reply bot."""

    def __init__(self, root_dir: str | os.PathLike[str] | None = None, max_chars: int | None = None):
        self.root_dir = Path(root_dir or os.getenv("ITEM_KNOWLEDGE_DIR", DEFAULT_ITEM_KNOWLEDGE_DIR))
        self.max_chars = max_chars or int(os.getenv("ITEM_KNOWLEDGE_MAX_CHARS", "6000"))

    def path_for_item(self, item_id: str) -> Path:
        return self.root_dir / f"{self._safe_item_id(item_id)}.md"

    def read(self, item_id: str | None) -> str:
        if not item_id:
            return ""

        path = self.path_for_item(str(item_id))
        if not path.is_file():
            return ""

        content = path.read_text(encoding="utf-8").strip()
        if len(content) > self.max_chars:
            return content[: self.max_chars].rstrip()
        return content

    def format_for_prompt(self, item_id: str | None) -> str:
        content = self.read(item_id)
        if not content:
            return ""

        return (
            "【商品知识库】\n"
            "以下内容来自当前商品对应的 Markdown 知识库。"
            "请优先依据商品信息和知识库回答；"
            "知识库或商品信息没有明确写到时，不要编造，回复“这个我确认一下，稍后回复你”。\n\n"
            f"{content}"
        )

    def _safe_item_id(self, item_id: str) -> str:
        value = re.sub(r"[^A-Za-z0-9_.-]+", "_", item_id.strip())
        return value.strip("._") or "unknown"


class UnknownQuestionLog:
    """Append questions that need knowledge-base review to a JSONL file."""

    def __init__(self, path: str | os.PathLike[str] | None = None):
        self.path = Path(path or os.getenv("UNKNOWN_QUESTIONS_PATH", DEFAULT_UNKNOWN_QUESTIONS_PATH))

    def append(
        self,
        *,
        item_id: str | None,
        chat_id: str | None,
        question: str,
        reason: str,
        reply: str,
        intent: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "item_id": item_id or "",
            "chat_id": chat_id or "",
            "question": question,
            "reason": reason,
            "reply": reply,
            "intent": intent or "",
        }
        if extra:
            row["extra"] = extra
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


UNKNOWN_REPLY_PATTERNS = (
    "这个我确认一下",
    "确认下",
    "稍后回复",
    "不确定",
    "不太确定",
    "不清楚",
    "不知道",
    "核实一下",
    "问一下",
    "查一下",
    "没有明确",
    "没写到",
)


def looks_like_unknown_reply(reply: str | None) -> bool:
    text = (reply or "").strip()
    if not text:
        return False
    return any(pattern in text for pattern in UNKNOWN_REPLY_PATTERNS)
