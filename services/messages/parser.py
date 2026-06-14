import base64
import json
import time
from typing import Any, Callable

from .models import IncomingMessage


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
        return ""

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
