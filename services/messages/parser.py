import base64
import json
import re
import time
from typing import Any, Callable

from .models import IncomingMessage


PAID_ORDER_KEYWORDS = (
    "我已付款，等待你发货",
    "我已付款，等待您发货",
    "已付款，待发货",
    "买家已付款",
    "付款完成",
    "等待卖家发货",
    "待发货",
    "记得及时发货",
)
UNPAID_ORDER_KEYWORDS = (
    "等待买家付款",
    "我已拍下，待付款",
    "待付款",
    "交易关闭",
)
REVIEWABLE_ORDER_KEYWORDS = (
    "交易成功",
    "交易完成",
    "订单已完成",
    "已完成",
    "待评价",
    "去评价",
    "评价买家",
    "买家已确认收货",
    "对方已收货",
)
NOT_REVIEWABLE_ORDER_KEYWORDS = (
    "等待卖家发货",
    "等待你发货",
    "等待您发货",
    "待发货",
    "待付款",
    "交易关闭",
    "退款",
)
ORDER_ID_KEYS = {"bizOrderId", "orderId", "order_id", "orderNo", "order_no", "biz_order_id", "tid"}
ORDER_ID_PATTERNS = (
    re.compile(r"orderId[=:](\d{10,})"),
    re.compile(r"order_detail\?id=(\d{10,})"),
    re.compile(r"bizOrderId[=:](\d{10,})"),
    re.compile(r'"(?:bizOrderId|orderId|order_no|orderNo|tid)"\s*:\s*"?(\d{10,})"?'),
)


class MessageParser:
    def __init__(
        self,
        *,
        myid: str,
        decrypt_func: Callable[[str], str] | None = None,
        message_expire_time_ms: int = 300_000,
    ):
        self.myid = str(myid)
        self.decrypt_func = decrypt_func
        self.message_expire_time_ms = message_expire_time_ms

    def is_sync_package(self, message_data: dict[str, Any]) -> bool:
        try:
            data = message_data["body"]["syncPushPackage"]["data"]
            return isinstance(data, list) and len(data) > 0
        except (KeyError, TypeError):
            return False

    def parse_message_data(self, message_data: dict[str, Any]) -> list[IncomingMessage]:
        if self.is_sync_package(message_data):
            messages: list[IncomingMessage] = []
            for sync_data in message_data["body"]["syncPushPackage"]["data"]:
                decoded = self._decode_sync_data(sync_data)
                if decoded:
                    incoming = self.parse_single_message(decoded)
                    if incoming:
                        messages.append(incoming)
            return messages

        incoming = self.parse_single_message(message_data)
        return [incoming] if incoming else []

    def parse_single_message(self, message: dict[str, Any]) -> IncomingMessage | None:
        if self.is_system_tip_message(message) or self.is_typing_status(message):
            return None
        if self.is_reviewable_order_message(message):
            return self._parse_reviewable_order_message(message)
        if self.is_paid_order_message(message):
            return self._parse_paid_order_message(message)
        if self.is_chat_message(message):
            return self._parse_chat_message(message)
        if self.is_card_update_message(message):
            return self._parse_card_update_message(message)
        return None

    def is_typing_status(self, message: dict[str, Any]) -> bool:
        try:
            entries = message.get("1")
            return (
                isinstance(entries, list)
                and len(entries) > 0
                and isinstance(entries[0], dict)
                and "@goofish" in str(entries[0].get("1", {}).get("1", ""))
            )
        except Exception:
            return False

    def is_chat_message(self, message: dict[str, Any]) -> bool:
        try:
            return (
                isinstance(message.get("1"), dict)
                and isinstance(message["1"].get("10"), dict)
                and "reminderContent" in message["1"]["10"]
            )
        except Exception:
            return False

    def is_card_update_message(self, message: dict[str, Any]) -> bool:
        try:
            return (
                isinstance(message.get("1"), str)
                and isinstance(message.get("4"), dict)
                and "reminderContent" in message["4"]
            )
        except Exception:
            return False

    def is_paid_order_message(self, message: dict[str, Any]) -> bool:
        status_text = self._extract_status_text(message)
        if not status_text:
            return False
        if any(keyword in status_text for keyword in UNPAID_ORDER_KEYWORDS):
            return False
        if not any(keyword in status_text for keyword in PAID_ORDER_KEYWORDS):
            return False
        return bool(self.extract_order_id(message))

    def is_reviewable_order_message(self, message: dict[str, Any]) -> bool:
        status_text = self._extract_status_text(message)
        if not status_text:
            return False
        if any(keyword in status_text for keyword in NOT_REVIEWABLE_ORDER_KEYWORDS):
            return False
        if not any(keyword in status_text for keyword in REVIEWABLE_ORDER_KEYWORDS):
            return False
        return bool(self.extract_order_id(message))

    def is_system_tip_message(self, message: dict[str, Any]) -> bool:
        meta = None
        if isinstance(message.get("1"), dict):
            meta = message["1"].get("10")
        elif isinstance(message.get("4"), dict):
            meta = message.get("4")
        if not isinstance(meta, dict):
            return False

        ext = self._json_dict(meta.get("extJson"))
        return ext.get("msgArg1") == "MsgTips"

    def extract_message_id(self, message: dict[str, Any]) -> str | None:
        meta = None
        if isinstance(message.get("1"), dict):
            meta = message["1"].get("10")
        elif isinstance(message.get("4"), dict):
            meta = message.get("4")
        if not isinstance(meta, dict):
            return None

        for field in ("bizTag", "extJson"):
            value = self._json_dict(meta.get(field))
            message_id = value.get("messageId")
            if message_id:
                return str(message_id)
        return None

    def extract_order_id(self, message: dict[str, Any]) -> str:
        direct = self._find_order_id_by_key(message)
        if direct:
            return direct

        for value in self._walk_string_values(message):
            for pattern in ORDER_ID_PATTERNS:
                match = pattern.search(value)
                if match:
                    return match.group(1)
        return ""

    def _parse_chat_message(self, message: dict[str, Any]) -> IncomingMessage | None:
        message_1 = message.get("1", {})
        meta = message_1.get("10", {})
        message_time = self._safe_int(message_1.get("5"))
        if self._is_expired(message_time):
            return None

        sender_id = str(meta.get("senderUserId", "unknown"))
        chat_id_raw = str(message_1.get("2", ""))
        return IncomingMessage(
            chat_id=self._strip_goofish(chat_id_raw),
            item_id=self._extract_item_id(meta, message),
            sender_id=sender_id,
            sender_name=str(meta.get("senderNick") or meta.get("reminderTitle") or "系统"),
            text=str(meta.get("reminderContent", "")),
            message_id=self.extract_message_id(message),
            message_time=message_time,
            raw=message,
            is_from_self=sender_id == self.myid,
            kind="chat",
        )

    def _parse_paid_order_message(self, message: dict[str, Any]) -> IncomingMessage | None:
        message_time = self._extract_message_time(message)
        if self._is_expired(message_time):
            return None

        meta = self._extract_message_meta(message)
        sender_id = str(meta.get("senderUserId") or self._extract_sender_id(message) or "unknown")
        order_id = self.extract_order_id(message)
        return IncomingMessage(
            chat_id=self._strip_goofish(str(self._extract_chat_id(message))),
            item_id=self._extract_item_id(meta, message),
            sender_id=sender_id,
            sender_name=str(meta.get("senderNick") or meta.get("reminderTitle") or self._extract_status_text(message) or "系统"),
            text=self._extract_status_text(message),
            message_id=self.extract_message_id(message) or order_id,
            message_time=message_time,
            raw=message,
            is_from_self=sender_id == self.myid,
            kind="paid_order",
            order_id=order_id,
            is_paid_order=True,
        )

    def _parse_reviewable_order_message(self, message: dict[str, Any]) -> IncomingMessage | None:
        message_time = self._extract_message_time(message)
        if self._is_expired(message_time):
            return None

        meta = self._extract_message_meta(message)
        sender_id = str(meta.get("senderUserId") or self._extract_sender_id(message) or "unknown")
        order_id = self.extract_order_id(message)
        return IncomingMessage(
            chat_id=self._strip_goofish(str(self._extract_chat_id(message))),
            item_id=self._extract_item_id(meta, message),
            sender_id=sender_id,
            sender_name=str(meta.get("senderNick") or meta.get("reminderTitle") or self._extract_status_text(message) or "系统"),
            text=self._extract_status_text(message),
            message_id=self.extract_message_id(message) or order_id,
            message_time=message_time,
            raw=message,
            is_from_self=sender_id == self.myid,
            kind="reviewable_order",
            order_id=order_id,
            is_reviewable_order=True,
        )

    def _parse_card_update_message(self, message: dict[str, Any]) -> IncomingMessage | None:
        meta = message.get("4", {})
        message_time = self._safe_int(message.get("5"))
        if self._is_expired(message_time):
            return None

        sender_id = str(meta.get("senderUserId", "unknown"))
        return IncomingMessage(
            chat_id=self._strip_goofish(str(message.get("2", ""))),
            item_id=self._extract_item_id(meta, message),
            sender_id=sender_id,
            sender_name=str(meta.get("senderNick") or meta.get("reminderTitle") or "系统"),
            text=str(meta.get("reminderContent", "")),
            message_id=self.extract_message_id(message),
            message_time=message_time,
            raw=message,
            is_from_self=sender_id == self.myid,
            kind="card_update",
        )

    def _decode_sync_data(self, sync_data: dict[str, Any]) -> dict[str, Any] | None:
        data = sync_data.get("data") if isinstance(sync_data, dict) else None
        if not isinstance(data, str):
            return None
        try:
            decoded = base64.b64decode(data).decode("utf-8")
            parsed = json.loads(decoded)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            if not self.decrypt_func:
                return None
            try:
                parsed = json.loads(self.decrypt_func(data))
                return parsed if isinstance(parsed, dict) else None
            except Exception:
                return None

    def _extract_item_id(self, meta: dict[str, Any], message: dict[str, Any]) -> str:
        for key in ("itemId", "item_id"):
            item_id = meta.get(key)
            if item_id:
                return str(item_id)

        url = str(meta.get("reminderUrl") or "")
        if "itemId=" in url:
            return url.split("itemId=", 1)[1].split("&", 1)[0]

        for field in ("bizTag", "extJson"):
            data = self._json_dict(meta.get(field))
            item_id = data.get("itemId")
            if item_id:
                return str(item_id)

        card_json = (
            message.get("1", {})
            .get("6", {})
            .get("3", {})
            .get("5", "")
            if isinstance(message.get("1"), dict)
            else ""
        )
        card_data = self._json_dict(card_json)
        jump_url = (
            card_data.get("dxCard", {})
            .get("item", {})
            .get("main", {})
            .get("exContent", {})
            .get("button", {})
            .get("intent", {})
            .get("page", {})
            .get("jumpUrl", "")
        )
        if "itemId=" in str(jump_url):
            return str(jump_url).split("itemId=", 1)[1].split("&", 1)[0]

        direct_item_id = self._find_first_key(message, {"itemId", "item_id"})
        if direct_item_id:
            return str(direct_item_id)
        return ""

    def _extract_message_meta(self, message: dict[str, Any]) -> dict[str, Any]:
        if isinstance(message.get("1"), dict):
            meta = message["1"].get("10")
            return meta if isinstance(meta, dict) else {}
        if isinstance(message.get("4"), dict):
            return message["4"]
        if isinstance(message.get("3"), dict):
            return message["3"]
        return {}

    def _extract_status_text(self, message: dict[str, Any]) -> str:
        meta = self._extract_message_meta(message)
        for key in ("redReminder", "reminderContent", "reminderTitle"):
            value = meta.get(key)
            if value:
                return str(value)
        return ""

    def _extract_chat_id(self, message: dict[str, Any]) -> str:
        if isinstance(message.get("1"), dict):
            return str(message["1"].get("2", ""))
        return str(message.get("2", ""))

    def _extract_sender_id(self, message: dict[str, Any]) -> str:
        raw_sender = message.get("1")
        if isinstance(raw_sender, str):
            return self._strip_goofish(raw_sender)
        return ""

    def _extract_message_time(self, message: dict[str, Any]) -> int | None:
        if isinstance(message.get("1"), dict):
            message_time = self._safe_int(message["1"].get("5"))
            if message_time:
                return message_time
        return self._safe_int(message.get("5"))

    def _find_order_id_by_key(self, value: Any) -> str:
        result = self._find_first_key(value, ORDER_ID_KEYS)
        return str(result) if result else ""

    def _find_first_key(self, value: Any, keys: set[str]) -> Any:
        if isinstance(value, dict):
            for key, inner in value.items():
                if key in keys and inner:
                    return inner
                found = self._find_first_key(inner, keys)
                if found:
                    return found
        elif isinstance(value, list):
            for inner in value:
                found = self._find_first_key(inner, keys)
                if found:
                    return found
        elif isinstance(value, str):
            parsed = self._json_dict(value)
            if parsed:
                return self._find_first_key(parsed, keys)
        return None

    def _walk_string_values(self, value: Any) -> list[str]:
        values: list[str] = []
        if isinstance(value, dict):
            for inner in value.values():
                values.extend(self._walk_string_values(inner))
        elif isinstance(value, list):
            for inner in value:
                values.extend(self._walk_string_values(inner))
        elif isinstance(value, str):
            values.append(value)
            parsed = self._json_dict(value)
            if parsed:
                values.extend(self._walk_string_values(parsed))
        return values

    def _is_expired(self, message_time_ms: int | None) -> bool:
        if not message_time_ms:
            return False
        return (time.time() * 1000 - message_time_ms) > self.message_expire_time_ms

    def _json_dict(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, str) or not value:
            return {}
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, json.JSONDecodeError):
            return {}

    def _safe_int(self, value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _strip_goofish(self, value: str) -> str:
        return value.split("@", 1)[0] if "@" in value else value
