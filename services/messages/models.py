from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class IncomingMessage:
    chat_id: str
    item_id: str
    sender_id: str
    sender_name: str
    text: str
    message_id: str | None
    message_time: int | None
    raw: dict[str, Any]
    is_from_self: bool
    kind: str
    order_id: str = ""
    is_paid_order: bool = False
