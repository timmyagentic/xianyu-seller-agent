import inspect
import asyncio
import json

from main import XianyuLive
from services.delivery.orders import OrderDetail
from services.delivery.service import DeliveryService
from services.delivery.store import DeliveryStore
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


class FakeDeliverySender:
    def __init__(self):
        self.calls = []

    async def __call__(self, *, chat_id, buyer_id, content):
        self.calls.append({"chat_id": chat_id, "buyer_id": buyer_id, "content": content})
        return True


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
