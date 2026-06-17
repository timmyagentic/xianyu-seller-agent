import inspect
import asyncio
import json
import time

from main import XianyuLive
from services.delivery.orders import OrderDetail, OrderInfo
from services.delivery.service import DeliveryService
from services.delivery.store import DeliveryStore
from services.messages import MessageDeduplicator, MessageParser
from services.messages.models import IncomingMessage


def test_xianyu_live_accepts_reply_bot_injection():
    signature = inspect.signature(XianyuLive)

    assert "reply_bot" in signature.parameters


class FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def send(self, payload):
        self.sent.append(json.loads(payload))


def test_xianyu_live_marks_incoming_message_as_read():
    live = XianyuLive.__new__(XianyuLive)
    websocket = FakeWebSocket()

    asyncio.run(live.mark_message_read(websocket, "chat-1", "msg-1"))

    assert websocket.sent[0]["lwp"] == "/r/Conversation/clearRedPoint"
    assert websocket.sent[0]["body"] == [[{"cid": "chat-1@goofish", "messageId": "msg-1"}]]
    assert websocket.sent[1]["lwp"] == "/r/MessageStatus/read"
    assert websocket.sent[1]["body"] == [["msg-1"]]


class FakeXianyuApi:
    def __init__(self):
        self.calls = 0
        self.confirm_calls = []

    def renew_login_cookies(self):
        self.calls += 1
        return {
            "status": "token_refreshed",
            "message": "令牌已刷新",
            "updated_cookie_names": ["_m_h5_tk"],
        }

    def get_cookie_string(self):
        return "unb=seller-1; _m_h5_tk=newtoken_456"

    def confirm_delivery(self, order_id, item_id=None):
        self.confirm_calls.append({"order_id": order_id, "item_id": item_id})
        return {"success": True, "message": "SUCCESS::调用成功"}


def test_xianyu_live_refresh_cookies_updates_runtime_cookie_string():
    live = XianyuLive.__new__(XianyuLive)
    live.xianyu = FakeXianyuApi()
    live.cookies_str = "unb=seller-1; _m_h5_tk=oldtoken_123"
    live.cookies = {"unb": "seller-1", "_m_h5_tk": "oldtoken_123"}
    live.last_cookie_refresh_time = 0

    result = asyncio.run(live.refresh_cookies())

    assert result is True
    assert live.xianyu.calls == 1
    assert live.cookies_str == "unb=seller-1; _m_h5_tk=newtoken_456"
    assert live.cookies["_m_h5_tk"] == "newtoken_456"
    assert live.last_cookie_refresh_time > 0


def test_xianyu_live_confirms_platform_delivery_and_syncs_cookies():
    live = XianyuLive.__new__(XianyuLive)
    live.xianyu = FakeXianyuApi()
    live.cookies_str = "unb=seller-1; _m_h5_tk=oldtoken_123"
    live.cookies = {"unb": "seller-1", "_m_h5_tk": "oldtoken_123"}

    result = asyncio.run(
        live.confirm_platform_delivery(
            OrderInfo(
                order_id="order-1",
                item_id="item-1",
                buyer_id="buyer-1",
                chat_id="chat-1",
            )
        )
    )

    assert result["success"] is True
    assert live.xianyu.confirm_calls == [{"order_id": "order-1", "item_id": "item-1"}]
    assert live.cookies_str == "unb=seller-1; _m_h5_tk=newtoken_456"
    assert live.cookies["_m_h5_tk"] == "newtoken_456"


class FakeDeliverySender:
    def __init__(self):
        self.calls = []

    async def __call__(self, *, chat_id, buyer_id, content):
        self.calls.append({"chat_id": chat_id, "buyer_id": buyer_id, "content": content})
        return True


class FakeReplyBot:
    def __init__(self):
        self.calls = []
        self.last_intent = "default"

    def generate_reply(self, user_msg, item_desc, context=None):
        self.calls.append({"user_msg": user_msg, "item_desc": item_desc, "context": context})
        return "自动回复"


def test_xianyu_live_wires_auto_confirm_delivery_flag(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("AUTO_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("AUTO_CONFIRM_DELIVERY_ENABLED", "true")

    live = XianyuLive("unb=seller-1", reply_bot=FakeReplyBot())

    assert live.delivery_service.enabled is True
    assert live.delivery_service.confirm_delivery_enabled is True
    assert live.delivery_service.confirm_delivery is not None


def test_xianyu_live_skips_chat_reply_when_auto_reply_disabled():
    live = XianyuLive.__new__(XianyuLive)
    live.auto_reply_enabled = False
    live.reply_bot = FakeReplyBot()
    websocket = FakeWebSocket()
    incoming = IncomingMessage(
        chat_id="chat-1",
        item_id="item-1",
        sender_id="buyer-1",
        sender_name="买家",
        text="你好",
        message_id="msg-chat-1",
        message_time=1781430000000,
        raw={},
        is_from_self=False,
        kind="chat",
    )

    asyncio.run(live.handle_incoming_message(incoming, websocket))

    assert live.reply_bot.calls == []
    assert websocket.sent == []


def test_xianyu_live_skips_chat_reply_for_unconfigured_item(tmp_path):
    live = XianyuLive.__new__(XianyuLive)
    live.auto_reply_enabled = True
    live.delivery_store = DeliveryStore(db_path=str(tmp_path / "app.db"))
    live.listing_store = None
    live.reply_bot = FakeReplyBot()
    websocket = FakeWebSocket()
    incoming = IncomingMessage(
        chat_id="chat-1",
        item_id="item-unconfigured",
        sender_id="buyer-1",
        sender_name="买家",
        text="你好",
        message_id="msg-chat-1",
        message_time=1781430000000,
        raw={},
        is_from_self=False,
        kind="chat",
    )

    asyncio.run(live.handle_incoming_message(incoming, websocket))

    assert live.reply_bot.calls == []
    assert websocket.sent == []


def test_xianyu_live_allows_chat_reply_for_configured_item(tmp_path):
    live = XianyuLive.__new__(XianyuLive)
    live.auto_reply_enabled = True
    live.myid = "seller-1"
    live.manual_mode_conversations = set()
    live.manual_mode_timestamps = {}
    live.manual_mode_timeout = 3600
    live.simulate_human_typing = False
    live.delivery_store = DeliveryStore(db_path=str(tmp_path / "app.db"))
    live.delivery_store.add_config(item_id="item-1", name="文本", delivery_type="text", content="发货内容")
    live.listing_store = None
    live.reply_bot = FakeReplyBot()
    live.context_manager = type(
        "FakeContextManager",
        (),
        {
            "get_item_info": lambda self, item_id: {"title": "资料包", "soldPrice": 990, "quantity": 1, "skuList": []},
            "get_context_by_chat": lambda self, chat_id: [],
            "add_message_by_chat": lambda self, *args: None,
            "increment_bargain_count_by_chat": lambda self, chat_id: None,
            "get_bargain_count_by_chat": lambda self, chat_id: 0,
        },
    )()
    websocket = FakeWebSocket()
    incoming = IncomingMessage(
        chat_id="chat-1",
        item_id="item-1",
        sender_id="buyer-1",
        sender_name="买家",
        text="你好",
        message_id="msg-chat-1",
        message_time=1781430000000,
        raw={},
        is_from_self=False,
        kind="chat",
    )

    asyncio.run(live.handle_incoming_message(incoming, websocket))

    assert len(live.reply_bot.calls) == 1
    assert any(payload["lwp"] == "/r/MessageStatus/read" for payload in websocket.sent)


def test_xianyu_live_keeps_missing_stock_unknown_in_item_description():
    live = XianyuLive.__new__(XianyuLive)

    description = json.loads(
        live.build_item_description(
            {
                "title": "资料包",
                "price_text": "¥5",
                "status": "active",
                "platform_status_text": "在售",
                "skuList": [],
            }
        )
    )

    assert description["total_stock"] is None
    assert description["stock_state"] == "unknown"
    assert description["price_range"] == "¥5"
    assert description["status"] == "active"
    assert description["platform_status_text"] == "在售"


def test_xianyu_live_answers_availability_from_active_item_without_llm(tmp_path):
    live = XianyuLive.__new__(XianyuLive)
    live.delivery_store = DeliveryStore(db_path=str(tmp_path / "app.db"))
    live.delivery_store.add_config(item_id="item-1", name="文本", delivery_type="text", content="发货内容")
    live.delivery_service = type("FakeDeliveryService", (), {"enabled": True})()

    reply = live.build_fact_reply(
        "还有不",
        {
            "title": "资料包",
            "status": "active",
            "platform_status_text": "在售",
            "skuList": [],
        },
        "item-1",
    )

    assert reply == "有的，拍下后自动发货"


def test_xianyu_live_does_not_invent_new_account_discount_without_fact(tmp_path):
    live = XianyuLive.__new__(XianyuLive)
    live.delivery_store = DeliveryStore(db_path=str(tmp_path / "app.db"))
    live.delivery_service = type("FakeDeliveryService", (), {"enabled": True})()

    assert live.build_fact_reply("刚刚注册新号", {"title": "资料包", "skuList": []}, "item-1") == "这个我确认一下，稍后回复你"


def test_xianyu_live_answers_new_account_when_item_fact_mentions_new_user(tmp_path):
    live = XianyuLive.__new__(XianyuLive)
    live.delivery_store = DeliveryStore(db_path=str(tmp_path / "app.db"))
    live.delivery_store.add_config(item_id="item-1", name="文本", delivery_type="text", content="发货内容")
    live.delivery_service = type("FakeDeliveryService", (), {"enabled": True})()

    reply = live.build_fact_reply(
        "刚刚注册新号",
        {"title": "新用户 7 天体验卡", "skuList": []},
        "item-1",
    )

    assert reply == "新号可以用，拍下后自动发货"


def test_xianyu_live_replaces_unsupported_out_of_stock_reply(tmp_path):
    live = XianyuLive.__new__(XianyuLive)
    live.delivery_store = DeliveryStore(db_path=str(tmp_path / "app.db"))
    live.delivery_store.add_config(item_id="item-1", name="文本", delivery_type="text", content="发货内容")
    live.delivery_service = type("FakeDeliveryService", (), {"enabled": True})()

    reply = live.guard_fact_reply(
        "亲，暂时没货呢\n后续关注下补货哈",
        {"title": "资料包", "status": "active", "platform_status_text": "在售", "skuList": []},
        "item-1",
        intent="default",
    )

    assert reply == "有的，拍下后自动发货"


def test_xianyu_live_replaces_unsupported_discount_reply_outside_price_intent(tmp_path):
    live = XianyuLive.__new__(XianyuLive)
    live.delivery_store = DeliveryStore(db_path=str(tmp_path / "app.db"))

    reply = live.guard_fact_reply(
        "亲，新号有优惠哦\n关注店铺不迷路",
        {"title": "资料包", "status": "active", "platform_status_text": "在售", "skuList": []},
        "item-1",
        intent="default",
    )

    assert reply == "这个我确认一下，稍后回复你"


def _paid_order_message():
    return IncomingMessage(
        chat_id="chat-1",
        item_id="item-1",
        sender_id="buyer-1",
        sender_name="买家",
        text="我已付款，等待你发货",
        message_id="msg-paid-1",
        message_time=1781430000000,
        raw={},
        is_from_self=False,
        kind="paid_order",
        order_id="order-1",
        is_paid_order=True,
    )


def _live_with_delivery(store, sender):
    live = XianyuLive.__new__(XianyuLive)
    live.myid = "seller-1"
    live.delivery_service = DeliveryService(store=store, send_message=sender, enabled=True)
    live.order_detail_provider = None
    return live


def test_xianyu_live_delivers_paid_order_message_once(tmp_path):
    store = DeliveryStore(db_path=str(tmp_path / "delivery.db"))
    store.add_config(
        item_id="item-1",
        name="文本",
        delivery_type="text",
        content="订单 {order_id} 买家 {buyer_id}",
    )
    sender = FakeDeliverySender()
    live = _live_with_delivery(store, sender)
    websocket = FakeWebSocket()
    incoming = _paid_order_message()

    asyncio.run(live.handle_incoming_message(incoming, websocket))
    asyncio.run(live.handle_incoming_message(incoming, websocket))

    assert sender.calls == [
        {"chat_id": "chat-1", "buyer_id": "buyer-1", "content": "订单 order-1 买家 buyer-1"}
    ]
    assert store.has_sent_order("order-1") is True
    assert [payload["lwp"] for payload in websocket.sent[-2:]] == [
        "/r/Conversation/clearRedPoint",
        "/r/MessageStatus/read",
    ]


def test_xianyu_live_skips_paid_order_for_unconfigured_item(tmp_path):
    store = DeliveryStore(db_path=str(tmp_path / "delivery.db"))
    sender = FakeDeliverySender()
    live = _live_with_delivery(store, sender)
    live.order_detail_provider = lambda order_id: (_ for _ in ()).throw(AssertionError("should not fetch order detail"))
    websocket = FakeWebSocket()

    result = asyncio.run(live.handle_paid_order_message(_paid_order_message(), websocket))

    assert result is None
    assert sender.calls == []
    assert websocket.sent == []


class FailingConfirmDelivery:
    async def __call__(self, order):
        return {"success": False, "error": "确认发货失败"}


def test_xianyu_live_marks_paid_message_read_after_delivery_content_sent_even_if_confirm_fails(tmp_path):
    store = DeliveryStore(db_path=str(tmp_path / "delivery.db"))
    store.add_config(item_id="item-1", name="文本", delivery_type="text", content="发货内容")
    sender = FakeDeliverySender()
    live = _live_with_delivery(store, sender)
    live.delivery_service = DeliveryService(
        store=store,
        send_message=sender,
        enabled=True,
        confirm_delivery=FailingConfirmDelivery(),
        confirm_delivery_enabled=True,
    )
    websocket = FakeWebSocket()

    result = asyncio.run(live.handle_paid_order_message(_paid_order_message(), websocket))

    assert result.status == "sent_confirm_failed"
    assert sender.calls == [{"chat_id": "chat-1", "buyer_id": "buyer-1", "content": "发货内容"}]
    assert store.has_delivery_status("order-1", "platform_confirm_failed") is True
    assert [payload["lwp"] for payload in websocket.sent[-2:]] == [
        "/r/Conversation/clearRedPoint",
        "/r/MessageStatus/read",
    ]


def test_xianyu_live_uses_order_detail_quantity_for_data_inventory(tmp_path):
    store = DeliveryStore(db_path=str(tmp_path / "delivery.db"))
    config_id = store.add_config(item_id="item-1", name="库存", delivery_type="data", content="")
    store.add_inventory(config_id, ["KEY-A", "KEY-B", "KEY-C"])
    sender = FakeDeliverySender()
    live = _live_with_delivery(store, sender)
    live.order_detail_provider = lambda order_id: OrderDetail(quantity=2, spec_name="套餐", spec_value="双份")
    websocket = FakeWebSocket()

    asyncio.run(live.handle_incoming_message(_paid_order_message(), websocket))

    assert sender.calls == [{"chat_id": "chat-1", "buyer_id": "buyer-1", "content": "KEY-A\nKEY-B"}]
    rows = store.list_inventory(config_id)
    assert [row.status for row in rows] == ["sent", "sent", "available"]


def test_xianyu_live_handles_raw_paid_order_message_and_skips_duplicate(tmp_path):
    store = DeliveryStore(db_path=str(tmp_path / "delivery.db"))
    store.add_config(item_id="item-raw", name="文本", delivery_type="text", content="发货内容")
    sender = FakeDeliverySender()
    live = _live_with_delivery(store, sender)
    live.message_parser = MessageParser(myid="seller-1")
    live.message_deduplicator = MessageDeduplicator()
    websocket = FakeWebSocket()
    paid_message = {
        "1": "buyer-raw@goofish",
        "2": "chat-raw@goofish",
        "3": {
            "redReminder": "等待卖家发货",
            "bizOrderId": "1234567890126",
            "itemId": "item-raw",
        },
        "5": int(time.time() * 1000),
    }

    asyncio.run(live.handle_message(paid_message, websocket))
    asyncio.run(live.handle_message(paid_message, websocket))

    assert sender.calls == [{"chat_id": "chat-raw", "buyer_id": "buyer-raw", "content": "发货内容"}]
    assert store.has_sent_order("1234567890126") is True
