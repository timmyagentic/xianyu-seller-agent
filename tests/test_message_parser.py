import base64
import json
import time

from services.messages.dedup import MessageDeduplicator
from services.messages.parser import MessageParser


def _chat_message(**overrides):
    now_ms = int(time.time() * 1000)
    message = {
        "1": {
            "2": "chat-1@goofish",
            "5": now_ms,
            "10": {
                "senderUserId": "buyer-1",
                "senderNick": "买家",
                "reminderTitle": "买家标题",
                "reminderContent": "你好",
                "reminderUrl": "https://www.goofish.com/item?id=x&itemId=item-1&spm=a",
                "bizTag": json.dumps({"messageId": "msg-1", "itemId": "item-from-biz"}),
            },
        }
    }
    message["1"]["10"].update(overrides)
    return message


def _sync_package(inner_message):
    encoded = base64.b64encode(json.dumps(inner_message).encode("utf-8")).decode("utf-8")
    return {"body": {"syncPushPackage": {"data": [{"data": encoded}]}}}


def test_parser_detects_sync_package_and_decodes_chat_message():
    parser = MessageParser(myid="seller-1")

    result = parser.parse_message_data(_sync_package(_chat_message()))

    assert len(result) == 1
    incoming = result[0]
    assert incoming.kind == "chat"
    assert incoming.chat_id == "chat-1"
    assert incoming.item_id == "item-1"
    assert incoming.sender_id == "buyer-1"
    assert incoming.sender_name == "买家"
    assert incoming.text == "你好"
    assert incoming.message_id == "msg-1"
    assert incoming.is_from_self is False


def test_parser_uses_decrypt_fallback_when_base64_decode_fails():
    parser = MessageParser(
        myid="seller-1",
        decrypt_func=lambda value: json.dumps(_chat_message(reminderContent=value)),
    )

    result = parser.parse_message_data({"body": {"syncPushPackage": {"data": [{"data": "加密内容"}]}}})

    assert result[0].text == "加密内容"


def test_parser_extracts_item_id_from_ext_json_when_url_missing():
    parser = MessageParser(myid="seller-1")
    message = _chat_message(reminderUrl="", bizTag="", extJson=json.dumps({"itemId": "item-ext", "messageId": "msg-ext"}))

    incoming = parser.parse_single_message(message)

    assert incoming.item_id == "item-ext"
    assert incoming.message_id == "msg-ext"


def test_parser_marks_seller_messages_as_self():
    parser = MessageParser(myid="seller-1")

    incoming = parser.parse_single_message(_chat_message(senderUserId="seller-1"))

    assert incoming.is_from_self is True


def test_parser_filters_marketing_msgtips_messages():
    parser = MessageParser(myid="seller-1")
    message = _chat_message(extJson=json.dumps({"msgArg1": "MsgTips", "messageId": "msg-tip"}))

    assert parser.parse_single_message(message) is None


def test_parser_filters_expired_messages():
    old_ms = int((time.time() - 301) * 1000)
    parser = MessageParser(myid="seller-1", message_expire_time_ms=300_000)
    message = _chat_message()
    message["1"]["5"] = old_ms

    assert parser.parse_single_message(message) is None


def test_parser_parses_card_update_message():
    parser = MessageParser(myid="seller-1")
    message = {
        "1": "card-ref",
        "2": "chat-1@goofish",
        "5": int(time.time() * 1000),
        "4": {
            "senderUserId": "buyer-1",
            "reminderTitle": "买家",
            "reminderContent": "我已付款，等待你发货",
            "reminderUrl": "https://www.goofish.com/item?itemId=item-2",
            "extJson": json.dumps({"messageId": "msg-card"}),
        },
    }

    incoming = parser.parse_single_message(message)

    assert incoming.kind == "card_update"
    assert incoming.chat_id == "chat-1"
    assert incoming.item_id == "item-2"
    assert incoming.message_id == "msg-card"
    assert incoming.text == "我已付款，等待你发货"


def test_deduplicator_tracks_processed_message_ids():
    dedup = MessageDeduplicator(max_size=2)

    assert dedup.mark_seen("msg-1") is False
    assert dedup.mark_seen("msg-1") is True
    assert dedup.mark_seen("msg-2") is False
    assert dedup.mark_seen("msg-3") is False
    assert dedup.mark_seen("msg-1") is False
