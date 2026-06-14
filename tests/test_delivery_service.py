import asyncio

from services.delivery.orders import OrderInfo
from services.delivery.service import DeliveryService
from services.delivery.store import DeliveryStore


class FakeSender:
    def __init__(self, succeed=True):
        self.succeed = succeed
        self.calls = []

    async def __call__(self, *, chat_id, buyer_id, content):
        self.calls.append({"chat_id": chat_id, "buyer_id": buyer_id, "content": content})
        if not self.succeed:
            raise RuntimeError("send failed")
        return True


def _order(quantity=1):
    return OrderInfo(
        order_id="order-1",
        item_id="item-1",
        buyer_id="buyer-1",
        chat_id="chat-1",
        buyer_name="张三",
        item_title="资料",
        quantity=quantity,
    )


def test_text_delivery_sends_rendered_content_once(tmp_path):
    store = DeliveryStore(db_path=str(tmp_path / "delivery.db"))
    store.add_config(
        item_id="item-1",
        name="文本",
        delivery_type="text",
        content="订单 {order_id} 买家 {buyer_name}",
    )
    sender = FakeSender()
    service = DeliveryService(store=store, send_message=sender, enabled=True)

    result = asyncio.run(service.deliver_order(_order()))

    assert result.status == "sent"
    assert sender.calls == [
        {"chat_id": "chat-1", "buyer_id": "buyer-1", "content": "订单 order-1 买家 张三"}
    ]
    assert store.has_sent_order("order-1") is True


def test_delivery_skips_order_that_was_already_sent(tmp_path):
    store = DeliveryStore(db_path=str(tmp_path / "delivery.db"))
    config_id = store.add_config(item_id="item-1", name="文本", delivery_type="text", content="content")
    store.record_delivery_log(
        order_no="order-1",
        chat_id="chat-1",
        item_id="item-1",
        buyer_id="buyer-1",
        config_id=config_id,
        content="content",
        status="sent",
    )
    sender = FakeSender()
    service = DeliveryService(store=store, send_message=sender, enabled=True)

    result = asyncio.run(service.deliver_order(_order()))

    assert result.status == "already_sent"
    assert sender.calls == []


def test_data_delivery_reserves_quantity_rows_before_sending(tmp_path):
    store = DeliveryStore(db_path=str(tmp_path / "delivery.db"))
    config_id = store.add_config(item_id="item-1", name="库存", delivery_type="data", content="")
    store.add_inventory(config_id, ["A", "B", "C"])
    sender = FakeSender()
    service = DeliveryService(store=store, send_message=sender, enabled=True)

    result = asyncio.run(service.deliver_order(_order(quantity=2)))

    assert result.status == "sent"
    assert sender.calls[0]["content"] == "A\nB"
    rows = store.list_inventory(config_id)
    assert [row.status for row in rows] == ["sent", "sent", "available"]
    assert [row.reserved_order_no for row in rows[:2]] == ["order-1", "order-1"]
    assert [row.reservation_line_no for row in rows[:2]] == [1, 2]


def test_data_delivery_does_not_partially_reserve_when_inventory_is_insufficient(tmp_path):
    store = DeliveryStore(db_path=str(tmp_path / "delivery.db"))
    config_id = store.add_config(item_id="item-1", name="库存", delivery_type="data", content="")
    store.add_inventory(config_id, ["A"])
    sender = FakeSender()
    service = DeliveryService(store=store, send_message=sender, enabled=True)

    result = asyncio.run(service.deliver_order(_order(quantity=2)))

    assert result.status == "insufficient_inventory"
    assert sender.calls == []
    rows = store.list_inventory(config_id)
    assert rows[0].status == "available"
    assert rows[0].reserved_order_no is None


def test_data_delivery_failure_keeps_reserved_rows_for_retry(tmp_path):
    store = DeliveryStore(db_path=str(tmp_path / "delivery.db"))
    config_id = store.add_config(item_id="item-1", name="库存", delivery_type="data", content="")
    store.add_inventory(config_id, ["A", "B"])
    failing_sender = FakeSender(succeed=False)
    service = DeliveryService(store=store, send_message=failing_sender, enabled=True)

    failed = asyncio.run(service.deliver_order(_order(quantity=2)))

    assert failed.status == "failed_retryable"
    rows_after_failure = store.list_inventory(config_id)
    assert [row.status for row in rows_after_failure] == ["failed_retryable", "failed_retryable"]
    assert [row.reserved_order_no for row in rows_after_failure] == ["order-1", "order-1"]

    retry_sender = FakeSender()
    retry_service = DeliveryService(store=store, send_message=retry_sender, enabled=True)
    retried = asyncio.run(retry_service.deliver_order(_order(quantity=2)))

    assert retried.status == "sent"
    assert retry_sender.calls[0]["content"] == "A\nB"
    rows_after_retry = store.list_inventory(config_id)
    assert [row.status for row in rows_after_retry] == ["sent", "sent"]


def test_delivery_service_respects_disabled_flag(tmp_path):
    store = DeliveryStore(db_path=str(tmp_path / "delivery.db"))
    store.add_config(item_id="item-1", name="文本", delivery_type="text", content="content")
    sender = FakeSender()
    service = DeliveryService(store=store, send_message=sender, enabled=False)

    result = asyncio.run(service.deliver_order(_order()))

    assert result.status == "disabled"
    assert sender.calls == []
