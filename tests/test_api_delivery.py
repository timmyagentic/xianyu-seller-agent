import asyncio
import json

from services.delivery.api import ApiDeliveryClient, ApiDeliveryError, ApiResponse
from services.delivery.orders import OrderInfo
from services.delivery.service import DeliveryService
from services.delivery.store import DeliveryStore


class FakeRequester:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def __call__(self, *, method, url, headers, params, timeout):
        self.calls.append(
            {"method": method, "url": url, "headers": headers, "params": params, "timeout": timeout}
        )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeSender:
    def __init__(self):
        self.calls = []

    async def __call__(self, *, chat_id, buyer_id, content):
        self.calls.append({"chat_id": chat_id, "buyer_id": buyer_id, "content": content})
        return True


def _order():
    return OrderInfo(
        order_id="order-1",
        item_id="item-1",
        buyer_id="buyer-1",
        chat_id="chat-1",
        buyer_name="张三",
        item_title="资料",
        quantity=1,
    )


def test_api_delivery_client_replaces_dynamic_post_params_and_extracts_data():
    requester = FakeRequester([ApiResponse(status_code=200, text=json.dumps({"data": "CODE-1"}))])
    client = ApiDeliveryClient(request=requester)

    content = asyncio.run(
        client.fetch_content(
            {
                "url": "https://example.test/cards",
                "method": "POST",
                "params": {"order": "{order_id}", "buyer": "{buyer_id}"},
                "headers": {"X-Test": "1"},
            },
            {"order_id": "order-1", "buyer_id": "buyer-1"},
        )
    )

    assert content == "CODE-1"
    assert requester.calls[0]["method"] == "POST"
    assert requester.calls[0]["params"] == {"order": "order-1", "buyer": "buyer-1"}


def test_api_delivery_client_retries_server_error():
    requester = FakeRequester(
        [
            ApiResponse(status_code=500, text="bad"),
            ApiResponse(status_code=200, text=json.dumps({"content": "CODE-2"})),
        ]
    )
    client = ApiDeliveryClient(request=requester, retry_delay_seconds=0)

    content = asyncio.run(client.fetch_content({"url": "https://example.test", "method": "GET"}, {}))

    assert content == "CODE-2"
    assert len(requester.calls) == 2


def test_api_delivery_client_raises_after_client_error():
    requester = FakeRequester([ApiResponse(status_code=400, text="bad request")])
    client = ApiDeliveryClient(request=requester)

    try:
        asyncio.run(client.fetch_content({"url": "https://example.test", "method": "GET"}, {}))
    except ApiDeliveryError as exc:
        assert "400" in str(exc)
    else:
        raise AssertionError("expected ApiDeliveryError")


def test_delivery_service_sends_api_content_without_consuming_data_inventory(tmp_path):
    store = DeliveryStore(db_path=str(tmp_path / "delivery.db"))
    data_config_id = store.add_config(item_id="other", name="库存", delivery_type="data", content="")
    store.add_inventory(data_config_id, ["A"])
    store.add_config(
        item_id="item-1",
        name="API",
        delivery_type="api",
        content="",
        api_config=json.dumps({"url": "https://example.test", "method": "GET"}),
    )
    requester = FakeRequester([ApiResponse(status_code=200, text=json.dumps({"card": "API-CODE"}))])
    sender = FakeSender()
    service = DeliveryService(
        store=store,
        send_message=sender,
        enabled=True,
        api_client=ApiDeliveryClient(request=requester),
    )

    result = asyncio.run(service.deliver_order(_order()))

    assert result.status == "sent"
    assert sender.calls[0]["content"] == "API-CODE"
    assert store.list_inventory(data_config_id)[0].status == "available"
