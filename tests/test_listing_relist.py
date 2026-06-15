import asyncio
import json

from services.delivery.store import DeliveryStore
from services.listing.models import ItemSnapshot, RelistApiResult
from services.listing.playwright_relist import build_playwright_relist_command
from services.listing.relist import RelistService, load_relist_request
from services.listing.store import ListingStore


class FakeItemProvider:
    def __init__(self, item=None):
        self.item = item

    async def get_item(self, item_id):
        return self.item


class FakeRelistApi:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def relist_item(self, item_id):
        self.calls.append(item_id)
        return self.result


class FakeStockRelistApi:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def relist_item(self, item_id, *, stock=None):
        self.calls.append({"item_id": item_id, "stock": stock})
        return self.result


class FakeStatusRelistApi:
    def __init__(self, status_item, relist_result):
        self.status_item = status_item
        self.relist_result = relist_result
        self.status_calls = []
        self.relist_calls = []

    async def get_item_status(self, item_id):
        self.status_calls.append(item_id)
        return {"success": True, "item": self.status_item}

    async def relist_item(self, item_id, *, stock=None):
        self.relist_calls.append({"item_id": item_id, "stock": stock})
        return self.relist_result


class FakeSequentialStatusRelistApi:
    def __init__(self, status_items, relist_result):
        self.status_items = list(status_items)
        self.relist_result = relist_result
        self.status_calls = []
        self.relist_calls = []

    async def get_item_status(self, item_id):
        self.status_calls.append(item_id)
        item = self.status_items.pop(0)
        return {"success": True, "item": item}

    async def relist_item(self, item_id, *, stock=None):
        self.relist_calls.append({"item_id": item_id, "stock": stock})
        return self.relist_result


class FakeRelistExecutor:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def relist(self, request):
        self.calls.append(request)
        return self.result


def _service(tmp_path, item, api_result=None, allow_playwright=False):
    db_path = str(tmp_path / "listing.db")
    return RelistService(
        listing_store=ListingStore(db_path=db_path),
        delivery_store=DeliveryStore(db_path=db_path),
        item_provider=FakeItemProvider(item),
        api_client=FakeRelistApi(api_result) if api_result else None,
        allow_playwright=allow_playwright,
    )


def test_relist_validates_item_belongs_to_current_account(tmp_path):
    service = _service(tmp_path, item=None)
    request = load_relist_request({"item_id": "item-1"})

    result = asyncio.run(service.relist(request))

    assert result.status == "item_not_found"
    assert "当前账号" in result.failed_reason
    assert service.listing_store.list_jobs()[0].result_status == "item_not_found"


def test_relist_with_fresh_database_records_item_not_found(tmp_path):
    db_path = str(tmp_path / "fresh.db")
    service = RelistService(
        listing_store=ListingStore(db_path=db_path),
        delivery_store=DeliveryStore(db_path=db_path),
    )

    result = asyncio.run(service.relist(load_relist_request({"item_id": "item-1"})))

    assert result.status == "item_not_found"
    assert service.listing_store.list_jobs()[0].result_status == "item_not_found"


def test_already_active_item_skips_platform_action_and_binds_delivery_config(tmp_path):
    item = ItemSnapshot(item_id="item-1", title="资料包", status="active", item_url="https://goofish/item-1")
    service = _service(tmp_path, item=item)
    request = load_relist_request(
        {
            "item_id": "item-1",
            "expected_title": "资料包",
            "delivery": {"type": "text", "content": "订单 {order_id}"},
        }
    )

    result = asyncio.run(service.relist(request))

    assert result.status == "already_active"
    configs = service.delivery_store.list_configs("item-1")
    assert len(configs) == 1
    assert configs[0].delivery_type == "text"
    assert configs[0].content == "订单 {order_id}"


def test_relist_api_success_records_job_and_binds_delivery_config(tmp_path):
    item = ItemSnapshot(item_id="item-1", title="资料包", status="inactive")
    service = _service(
        tmp_path,
        item=item,
        api_result=RelistApiResult(
            success=True,
            final_status="active",
            item_url="https://goofish/item-1",
            response_summary="success",
        ),
    )
    request = load_relist_request(
        {"item_id": "item-1", "delivery": {"type": "text", "content": "发货内容"}}
    )

    result = asyncio.run(service.relist(request))

    assert result.status == "relisted"
    assert result.final_status == "active"
    assert service.delivery_store.get_enabled_config("item-1").content == "发货内容"
    job = service.listing_store.list_jobs()[0]
    assert job.result_status == "relisted"
    assert job.item_url == "https://goofish/item-1"


def test_relist_request_passes_target_stock_to_api_and_records_job(tmp_path):
    db_path = str(tmp_path / "listing.db")
    item = ItemSnapshot(item_id="item-1", title="资料包", status="inactive")
    api = FakeStockRelistApi(
        RelistApiResult(
            success=True,
            final_status="active",
            item_url="https://goofish/item-1",
            response_summary="success",
        )
    )
    service = RelistService(
        listing_store=ListingStore(db_path=db_path),
        delivery_store=DeliveryStore(db_path=db_path),
        item_provider=FakeItemProvider(item),
        api_client=api,
    )

    result = asyncio.run(service.relist(load_relist_request({"item_id": "item-1", "stock": 7})))

    assert result.status == "relisted"
    assert api.calls == [{"item_id": "item-1", "stock": 7}]
    job = service.listing_store.list_jobs()[0]
    assert job.target_stock == 7


def test_active_item_with_target_stock_still_executes_relist_action(tmp_path):
    db_path = str(tmp_path / "listing.db")
    item = ItemSnapshot(item_id="item-1", title="资料包", status="active")
    api = FakeStockRelistApi(
        RelistApiResult(
            success=True,
            final_status="active",
            item_url="https://goofish/item-1",
            response_summary="stock refreshed",
        )
    )
    service = RelistService(
        listing_store=ListingStore(db_path=db_path),
        delivery_store=DeliveryStore(db_path=db_path),
        item_provider=FakeItemProvider(item),
        api_client=api,
    )

    result = asyncio.run(service.relist(load_relist_request({"item_id": "item-1", "stock": 7})))

    assert result.status == "relisted"
    assert api.calls == [{"item_id": "item-1", "stock": 7}]
    job = service.listing_store.list_jobs()[0]
    assert job.previous_status == "active"
    assert job.result_status == "relisted"


def test_relist_refreshes_live_item_status_before_using_local_snapshot(tmp_path):
    db_path = str(tmp_path / "listing.db")
    listing_store = ListingStore(db_path=db_path)
    listing_store.save_item_snapshot({"item_id": "item-1", "title": "资料包", "status": "active"})
    api = FakeSequentialStatusRelistApi(
        status_items=[
            {"item_id": "item-1", "title": "资料包", "status": "inactive"},
            {"item_id": "item-1", "title": "资料包", "status": "active"},
        ],
        relist_result=RelistApiResult(success=True, final_status="active", response_summary="success"),
    )
    service = RelistService(
        listing_store=listing_store,
        delivery_store=DeliveryStore(db_path=db_path),
        api_client=api,
    )

    result = asyncio.run(service.relist(load_relist_request({"item_id": "item-1", "stock": 7})))

    assert result.status == "relisted"
    assert api.status_calls == ["item-1", "item-1"]
    assert api.relist_calls == [{"item_id": "item-1", "stock": 7}]
    assert listing_store.get_item_snapshot("item-1").status == "active"
    job = listing_store.list_jobs()[0]
    assert job.previous_status == "inactive"


def test_relist_success_refreshes_post_action_status_and_records_final_state(tmp_path):
    db_path = str(tmp_path / "listing.db")
    listing_store = ListingStore(db_path=db_path)
    api = FakeSequentialStatusRelistApi(
        status_items=[
            {"item_id": "item-1", "title": "资料包", "status": "inactive"},
            {
                "item_id": "item-1",
                "title": "资料包",
                "status": "active",
                "status_source": "published_list",
                "platform_status_text": "在售",
            },
        ],
        relist_result=RelistApiResult(success=True, final_status="active", response_summary="api relist success"),
    )
    service = RelistService(
        listing_store=listing_store,
        delivery_store=DeliveryStore(db_path=db_path),
        api_client=api,
    )

    result = asyncio.run(service.relist(load_relist_request({"item_id": "item-1", "stock": 7})))

    assert result.status == "relisted"
    assert api.status_calls == ["item-1", "item-1"]
    assert result.previous_status == "inactive"
    assert result.final_status == "active"
    assert listing_store.get_item_snapshot("item-1").status == "active"
    job = listing_store.list_jobs()[0]
    assert job.result_status == "relisted"
    assert job.previous_status == "inactive"
    assert job.final_status == "active"
    assert "post_action_status" in job.response_summary
    evidence = json.loads(job.evidence_json)
    assert evidence["request"] == {
        "item_id": "item-1",
        "expected_title": "",
        "target_stock": 7,
        "delivery_present": False,
    }
    assert evidence["pre_action"]["status"] == "inactive"
    assert evidence["action"]["source"] == "api"
    assert evidence["action"]["success"] is True
    assert evidence["post_action"]["status"] == "active"
    assert evidence["post_action"]["status_source"] == "published_list"


def test_relist_uses_authorized_playwright_executor_when_api_is_unavailable(tmp_path):
    item = ItemSnapshot(item_id="item-1", title="资料包", status="inactive")
    api = FakeRelistApi(RelistApiResult(success=False, failed_reason="relist_api_not_configured"))
    executor = FakeRelistExecutor(
        RelistApiResult(
            success=True,
            final_status="active",
            item_url="https://www.goofish.com/item?id=item-1",
            response_summary="playwright relist success",
        )
    )
    db_path = str(tmp_path / "listing.db")
    service = RelistService(
        listing_store=ListingStore(db_path=db_path),
        delivery_store=DeliveryStore(db_path=db_path),
        item_provider=FakeItemProvider(item),
        api_client=api,
        allow_playwright=True,
        relist_executor=executor,
    )

    result = asyncio.run(service.relist(load_relist_request({"item_id": "item-1", "stock": 7})))

    assert result.status == "relisted"
    assert result.final_status == "active"
    assert executor.calls[0].item_id == "item-1"
    assert executor.calls[0].target_stock == 7
    assert service.listing_store.list_jobs()[0].result_status == "relisted"


def test_relist_records_playwright_risk_control_without_success(tmp_path):
    item = ItemSnapshot(item_id="item-1", title="资料包", status="inactive")
    executor = FakeRelistExecutor(
        RelistApiResult(
            success=False,
            failed_reason="risk_control",
            response_summary="检测到滑块验证，停止自动重新上架",
        )
    )
    service = RelistService(
        listing_store=ListingStore(db_path=str(tmp_path / "listing.db")),
        delivery_store=DeliveryStore(db_path=str(tmp_path / "listing.db")),
        item_provider=FakeItemProvider(item),
        allow_playwright=True,
        relist_executor=executor,
    )

    result = asyncio.run(service.relist(load_relist_request({"item_id": "item-1"})))

    assert result.status == "playwright_required"
    assert result.failed_reason == "risk_control"
    assert "滑块" in result.response_summary
    job = service.listing_store.list_jobs()[0]
    evidence = json.loads(job.evidence_json)
    assert evidence["request"]["item_id"] == "item-1"
    assert evidence["pre_action"]["status"] == "inactive"
    assert evidence["action"]["source"] == "playwright"
    assert evidence["action"]["success"] is False
    assert evidence["action"]["failed_reason"] == "risk_control"


def test_relist_records_custom_playwright_required_reason_when_executor_is_not_confirmed(tmp_path):
    item = ItemSnapshot(item_id="item-1", title="资料包", status="inactive")
    service = RelistService(
        listing_store=ListingStore(db_path=str(tmp_path / "listing.db")),
        delivery_store=DeliveryStore(db_path=str(tmp_path / "listing.db")),
        item_provider=FakeItemProvider(item),
        allow_playwright=True,
        playwright_required_reason="auto_relist_confirmation_required",
    )

    result = asyncio.run(service.relist(load_relist_request({"item_id": "item-1", "stock": 7})))

    assert result.status == "playwright_required"
    assert result.failed_reason == "auto_relist_confirmation_required"
    job = service.listing_store.list_jobs()[0]
    assert job.result_status == "playwright_required"
    assert job.failed_reason == "auto_relist_confirmation_required"


def test_relist_api_failure_returns_manual_required_reason(tmp_path):
    item = ItemSnapshot(item_id="item-1", title="资料包", status="inactive")
    service = _service(
        tmp_path,
        item=item,
        api_result=RelistApiResult(
            success=False,
            failed_reason="cookie_expired",
            response_summary="FAIL_SYS_TOKEN_EXPIRED",
        ),
    )

    result = asyncio.run(service.relist(load_relist_request({"item_id": "item-1"})))

    assert result.status == "manual_required"
    assert result.failed_reason == "cookie_expired"
    assert service.listing_store.list_jobs()[0].result_status == "manual_required"


def test_playwright_fallback_command_is_constructed_without_running_browser():
    command = build_playwright_relist_command(item_id="item-1", expected_title="资料包")

    assert command.item_id == "item-1"
    assert command.expected_title == "资料包"
    assert "seller.goofish.com" in command.management_url
    assert command.cookie_domains == (
        ".goofish.com",
        ".taobao.com",
        ".alipay.com",
    )
