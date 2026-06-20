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


class FakeConfirmDelivery:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    async def __call__(self, order):
        self.calls.append(order)
        return self.results.pop(0)


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


def test_delivery_store_finds_latest_successful_order_for_review(tmp_path):
    store = DeliveryStore(db_path=str(tmp_path / "delivery.db"))
    store.record_delivery_log(
        order_no="order-old",
        chat_id="chat-1",
        item_id="item-1",
        buyer_id="buyer-1",
        config_id=1,
        content="old",
        status="sent",
    )
    store.record_delivery_log(
        order_no="order-new",
        chat_id="chat-1",
        item_id="item-1",
        buyer_id="buyer-1",
        config_id=1,
        content="new",
        status="platform_confirmed",
    )
    store.record_delivery_log(
        order_no="order-other",
        chat_id="chat-2",
        item_id="item-1",
        buyer_id="buyer-2",
        config_id=1,
        content="other",
        status="platform_confirmed",
    )

    latest = store.get_latest_successful_order(chat_id="chat-1", item_id="item-1", buyer_id="buyer-1")

    assert latest == {
        "order_no": "order-new",
        "chat_id": "chat-1",
        "item_id": "item-1",
        "buyer_id": "buyer-1",
        "status": "platform_confirmed",
    }


def test_delivery_service_runs_post_delivery_hook_after_success(tmp_path):
    store = DeliveryStore(db_path=str(tmp_path / "delivery.db"))
    store.add_config(item_id="item-1", name="文本", delivery_type="text", content="content")
    sender = FakeSender()
    hook_calls = []

    async def post_delivery_hook(order, result):
        hook_calls.append(
            {
                "order_id": order.order_id,
                "item_id": order.item_id,
                "status": result.status,
                "content": result.content,
            }
        )

    service = DeliveryService(
        store=store,
        send_message=sender,
        enabled=True,
        post_delivery_hook=post_delivery_hook,
    )

    result = asyncio.run(service.deliver_order(_order()))

    assert result.status == "sent"
    assert hook_calls == [
        {
            "order_id": "order-1",
            "item_id": "item-1",
            "status": "sent",
            "content": "content",
        }
    ]


def test_delivery_service_confirms_platform_delivery_after_content_is_sent(tmp_path):
    store = DeliveryStore(db_path=str(tmp_path / "delivery.db"))
    store.add_config(item_id="item-1", name="文本", delivery_type="text", content="content")
    sender = FakeSender()
    confirmer = FakeConfirmDelivery([{"success": True, "message": "SUCCESS::调用成功"}])
    hook_calls = []

    async def post_delivery_hook(order, result):
        hook_calls.append({"status": result.status, "platform": result.platform_confirm_status})

    service = DeliveryService(
        store=store,
        send_message=sender,
        enabled=True,
        confirm_delivery=confirmer,
        confirm_delivery_enabled=True,
        post_delivery_hook=post_delivery_hook,
    )

    result = asyncio.run(service.deliver_order(_order()))

    assert result.status == "sent"
    assert result.platform_confirm_status == "confirmed"
    assert sender.calls[0]["content"] == "content"
    assert confirmer.calls[0].order_id == "order-1"
    assert store.has_delivery_status("order-1", "platform_confirmed") is True
    assert hook_calls == [{"status": "sent", "platform": "confirmed"}]


def test_delivery_service_records_confirm_failure_without_relist_hook(tmp_path):
    store = DeliveryStore(db_path=str(tmp_path / "delivery.db"))
    store.add_config(item_id="item-1", name="文本", delivery_type="text", content="content")
    sender = FakeSender()
    confirmer = FakeConfirmDelivery([{"success": False, "error": "确认发货失败"}])
    hook_calls = []

    async def post_delivery_hook(order, result):
        hook_calls.append(result.status)

    service = DeliveryService(
        store=store,
        send_message=sender,
        enabled=True,
        confirm_delivery=confirmer,
        confirm_delivery_enabled=True,
        post_delivery_hook=post_delivery_hook,
    )

    result = asyncio.run(service.deliver_order(_order()))

    assert result.status == "sent_confirm_failed"
    assert result.platform_confirm_status == "failed"
    assert result.platform_confirm_failed_reason == "确认发货失败"
    assert store.has_sent_order("order-1") is True
    assert store.has_delivery_status("order-1", "platform_confirm_failed") is True
    assert hook_calls == []


def test_delivery_service_retries_platform_confirm_for_already_sent_order_without_resending(tmp_path):
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
    confirmer = FakeConfirmDelivery([{"success": True, "already_delivered": True, "message": "ORDER_ALREADY_DELIVERY"}])
    service = DeliveryService(
        store=store,
        send_message=sender,
        enabled=True,
        confirm_delivery=confirmer,
        confirm_delivery_enabled=True,
    )

    result = asyncio.run(service.deliver_order(_order()))

    assert result.status == "already_sent"
    assert result.platform_confirm_status == "already_delivered"
    assert sender.calls == []
    assert confirmer.calls[0].order_id == "order-1"
    assert store.has_delivery_status("order-1", "platform_already_delivered") is True


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


def test_delivery_service_treats_false_sender_result_as_retryable_failure(tmp_path):
    store = DeliveryStore(db_path=str(tmp_path / "delivery.db"))
    store.add_config(item_id="item-1", name="文本", delivery_type="text", content="content")

    async def false_sender(*, chat_id, buyer_id, content):
        return False

    service = DeliveryService(store=store, send_message=false_sender, enabled=True)

    result = asyncio.run(service.deliver_order(_order()))

    assert result.status == "failed_retryable"
    assert store.has_sent_order("order-1") is False
