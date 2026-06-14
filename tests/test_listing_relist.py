import asyncio

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
        ".seller.goofish.com",
    )
