import asyncio
import json

import main
from main import XianyuLive, run_cli
from services.delivery.orders import OrderInfo
from services.delivery.service import DeliveryResult
from services.listing.models import RelistResult
from services.listing.playwright_relist import SELLER_PUBLISH_RELIST_URL
from services.listing.store import ListingStore


class FakeSession:
    def __init__(self):
        self.cookies = {}


class FakeApi:
    def __init__(self):
        self.session = FakeSession()


class FakePlaywrightExecutor:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        FakePlaywrightExecutor.instances.append(self)

    async def preview(self, request):
        return {
            "success": True,
            "item_id": request.item_id,
            "expected_title": request.expected_title,
            "item_found": True,
            "relist_button_found": True,
            "would_fill_stock": request.target_stock,
            "response_summary": "preview only; no click or stock fill executed",
        }


class FakeRelistService:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.requests = []
        FakeRelistService.instances.append(self)

    async def relist(self, request):
        self.requests.append(request)
        item_id = request.item_id if hasattr(request, "item_id") else request["item_id"]
        return RelistResult(status="manual_required", item_id=item_id)


def test_listing_relist_cli_injects_api_client_when_cookies_exist(tmp_path, monkeypatch, capsys):
    FakeRelistService.instances = []
    monkeypatch.setenv("COOKIES_STR", "unb=seller-1; _m_h5_tk=token_123")
    monkeypatch.setattr(main, "XianyuApis", FakeApi)
    monkeypatch.setattr(main, "RelistService", FakeRelistService)

    exit_code = run_cli(
        ["listing", "--db-path", str(tmp_path / "listing.db"), "relist", "--item-id", "item-1"]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "manual_required"
    assert isinstance(FakeRelistService.instances[0].kwargs["api_client"], FakeApi)


def test_listing_relist_allow_playwright_does_not_create_executor_without_real_confirm(tmp_path, monkeypatch, capsys):
    FakeRelistService.instances = []
    FakePlaywrightExecutor.instances = []
    monkeypatch.setenv("COOKIES_STR", "unb=seller-1; _m_h5_tk=token_123")
    monkeypatch.setattr(main, "XianyuApis", FakeApi)
    monkeypatch.setattr(main, "RelistService", FakeRelistService)
    monkeypatch.setattr(main, "PlaywrightRelistExecutor", FakePlaywrightExecutor)

    exit_code = run_cli(
        [
            "listing",
            "--db-path",
            str(tmp_path / "listing.db"),
            "relist",
            "--item-id",
            "item-1",
            "--allow-playwright",
        ]
    )

    assert exit_code == 0
    assert FakeRelistService.instances[0].kwargs["allow_playwright"] is True
    assert FakeRelistService.instances[0].kwargs["relist_executor"] is None
    assert FakeRelistService.instances[0].kwargs["playwright_required_reason"] == "real_relist_confirmation_required"
    assert FakePlaywrightExecutor.instances == []


def test_listing_relist_confirm_real_relist_creates_authorized_executor(tmp_path, monkeypatch, capsys):
    FakeRelistService.instances = []
    FakePlaywrightExecutor.instances = []
    monkeypatch.setenv("COOKIES_STR", "unb=seller-1; _m_h5_tk=token_123")
    monkeypatch.setattr(main, "XianyuApis", FakeApi)
    monkeypatch.setattr(main, "RelistService", FakeRelistService)
    monkeypatch.setattr(main, "PlaywrightRelistExecutor", FakePlaywrightExecutor)

    exit_code = run_cli(
        [
            "listing",
            "--db-path",
            str(tmp_path / "listing.db"),
            "relist",
            "--item-id",
            "item-1",
            "--allow-playwright",
            "--confirm-real-relist",
        ]
    )

    assert exit_code == 0
    assert FakeRelistService.instances[0].kwargs["allow_playwright"] is True
    assert isinstance(FakeRelistService.instances[0].kwargs["relist_executor"], FakePlaywrightExecutor)
    assert FakePlaywrightExecutor.instances[0].kwargs["cookies_str"]


def test_listing_relist_executor_uses_configured_management_url(tmp_path, monkeypatch, capsys):
    FakeRelistService.instances = []
    FakePlaywrightExecutor.instances = []
    monkeypatch.setenv("COOKIES_STR", "unb=seller-1; _m_h5_tk=token_123")
    monkeypatch.setenv("AUTO_RELIST_MANAGEMENT_URL", "https://seller.goofish.com/?site=COMMONPRO#/seller-item/goods-manage")
    monkeypatch.setattr(main, "XianyuApis", FakeApi)
    monkeypatch.setattr(main, "RelistService", FakeRelistService)
    monkeypatch.setattr(main, "PlaywrightRelistExecutor", FakePlaywrightExecutor)

    exit_code = run_cli(
        [
            "listing",
            "--db-path",
            str(tmp_path / "listing.db"),
            "relist",
            "--item-id",
            "item-1",
            "--allow-playwright",
            "--confirm-real-relist",
        ]
    )

    assert exit_code == 0
    assert (
        FakePlaywrightExecutor.instances[0].kwargs["management_url"]
        == "https://seller.goofish.com/?site=COMMONPRO#/seller-item/goods-manage"
    )


def test_listing_relist_executor_defaults_to_seller_publish_route_when_stock_set(tmp_path, monkeypatch, capsys):
    FakeRelistService.instances = []
    FakePlaywrightExecutor.instances = []
    monkeypatch.setenv("COOKIES_STR", "unb=seller-1; _m_h5_tk=token_123")
    monkeypatch.delenv("AUTO_RELIST_MANAGEMENT_URL", raising=False)
    monkeypatch.setattr(main, "XianyuApis", FakeApi)
    monkeypatch.setattr(main, "RelistService", FakeRelistService)
    monkeypatch.setattr(main, "PlaywrightRelistExecutor", FakePlaywrightExecutor)

    exit_code = run_cli(
        [
            "listing",
            "--db-path",
            str(tmp_path / "listing.db"),
            "relist",
            "--item-id",
            "item-1",
            "--stock",
            "7",
            "--allow-playwright",
            "--confirm-real-relist",
        ]
    )

    assert exit_code == 0
    assert FakePlaywrightExecutor.instances[0].kwargs["management_url"] == SELLER_PUBLISH_RELIST_URL


def test_listing_relist_preflight_uses_live_status_and_preview_executor(tmp_path, monkeypatch, capsys):
    FakePlaywrightExecutor.instances = []

    class FakeStatusApi:
        def __init__(self):
            self.session = FakeSession()

        def get_item_status(self, item_id, *, page_size=20, max_pages=None, myid=None):
            return {
                "success": True,
                "item": {
                    "item_id": item_id,
                    "title": "资料包",
                    "status": "sold",
                    "status_source": "item_detail",
                    "platform_status": 1,
                    "platform_status_text": "卖掉了",
                    "can_relist": True,
                },
            }

    monkeypatch.setenv("COOKIES_STR", "unb=seller-1; _m_h5_tk=token_123")
    monkeypatch.setattr(main, "XianyuApis", FakeStatusApi)
    monkeypatch.setattr(main, "PlaywrightRelistExecutor", FakePlaywrightExecutor)

    exit_code = run_cli(
        [
            "listing",
            "--db-path",
            str(tmp_path / "listing.db"),
            "relist-preflight",
            "--item-id",
            "item-1",
            "--expected-title",
            "资料包",
            "--stock",
            "7",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["success"] is True
    assert payload["item"]["status"] == "sold"
    assert payload["playwright"]["item_found"] is True
    assert payload["playwright"]["relist_button_found"] is True
    assert payload["playwright"]["would_fill_stock"] == 7
    assert FakePlaywrightExecutor.instances[0].kwargs["cookies_str"]
    assert FakePlaywrightExecutor.instances[0].kwargs["management_url"] == SELLER_PUBLISH_RELIST_URL


def test_post_delivery_relist_allow_playwright_does_not_create_executor_without_confirm(tmp_path, monkeypatch):
    FakeRelistService.instances = []
    FakePlaywrightExecutor.instances = []
    monkeypatch.setenv("DB_PATH", str(tmp_path / "listing.db"))
    monkeypatch.setenv("AUTO_RELIST_ENABLED", "true")
    monkeypatch.setenv("AUTO_RELIST_ALLOW_PLAYWRIGHT", "true")
    monkeypatch.delenv("AUTO_RELIST_CONFIRM_PLAYWRIGHT", raising=False)
    monkeypatch.setattr(main, "RelistService", FakeRelistService)
    monkeypatch.setattr(main, "PlaywrightRelistExecutor", FakePlaywrightExecutor, raising=False)

    live = XianyuLive("unb=seller-1; _m_h5_tk=token_123", reply_bot=object())
    ListingStore(db_path=str(tmp_path / "listing.db")).upsert_auto_relist_config(
        item_id="item-1",
        target_stock=7,
        expected_title="资料包",
        enabled=True,
        allow_playwright=True,
    )

    asyncio.run(
        live.handle_post_delivery_relist(
            OrderInfo(order_id="order-1", item_id="item-1", buyer_id="buyer-1", chat_id="chat-1"),
            DeliveryResult(status="sent", order_id="order-1"),
        )
    )

    service = FakeRelistService.instances[0]
    assert service.kwargs["api_client"] is live.xianyu
    assert service.kwargs["allow_playwright"] is True
    assert service.kwargs["relist_executor"] is None
    assert service.kwargs["playwright_required_reason"] == "auto_relist_confirmation_required"
    assert FakePlaywrightExecutor.instances == []
    assert service.requests[0]["target_stock"] == 7


def test_post_delivery_relist_confirm_playwright_creates_authorized_executor(tmp_path, monkeypatch):
    FakeRelistService.instances = []
    FakePlaywrightExecutor.instances = []
    monkeypatch.setenv("DB_PATH", str(tmp_path / "listing.db"))
    monkeypatch.setenv("AUTO_RELIST_ENABLED", "true")
    monkeypatch.setenv("AUTO_RELIST_ALLOW_PLAYWRIGHT", "true")
    monkeypatch.setenv("AUTO_RELIST_CONFIRM_PLAYWRIGHT", "true")
    monkeypatch.setattr(main, "RelistService", FakeRelistService)
    monkeypatch.setattr(main, "PlaywrightRelistExecutor", FakePlaywrightExecutor, raising=False)

    live = XianyuLive("unb=seller-1; _m_h5_tk=token_123", reply_bot=object())
    ListingStore(db_path=str(tmp_path / "listing.db")).upsert_auto_relist_config(
        item_id="item-1",
        target_stock=7,
        expected_title="资料包",
        enabled=True,
        allow_playwright=True,
    )

    asyncio.run(
        live.handle_post_delivery_relist(
            OrderInfo(order_id="order-1", item_id="item-1", buyer_id="buyer-1", chat_id="chat-1"),
            DeliveryResult(status="sent", order_id="order-1"),
        )
    )

    service = FakeRelistService.instances[0]
    assert service.kwargs["api_client"] is live.xianyu
    assert service.kwargs["allow_playwright"] is True
    assert isinstance(service.kwargs["relist_executor"], FakePlaywrightExecutor)
    assert service.kwargs["relist_executor"].kwargs["cookies_str"]
    assert service.kwargs["relist_executor"].kwargs["management_url"] == SELLER_PUBLISH_RELIST_URL
    assert service.requests[0]["target_stock"] == 7


def test_post_delivery_relist_skips_non_sent_delivery_result(tmp_path, monkeypatch):
    FakeRelistService.instances = []
    FakePlaywrightExecutor.instances = []
    monkeypatch.setenv("DB_PATH", str(tmp_path / "listing.db"))
    monkeypatch.setenv("AUTO_RELIST_ENABLED", "true")
    monkeypatch.setenv("AUTO_RELIST_ALLOW_PLAYWRIGHT", "true")
    monkeypatch.setenv("AUTO_RELIST_CONFIRM_PLAYWRIGHT", "true")
    monkeypatch.setattr(main, "RelistService", FakeRelistService)
    monkeypatch.setattr(main, "PlaywrightRelistExecutor", FakePlaywrightExecutor, raising=False)

    live = XianyuLive("unb=seller-1; _m_h5_tk=token_123", reply_bot=object())
    ListingStore(db_path=str(tmp_path / "listing.db")).upsert_auto_relist_config(
        item_id="item-1",
        target_stock=7,
        expected_title="资料包",
        enabled=True,
        allow_playwright=True,
    )

    asyncio.run(
        live.handle_post_delivery_relist(
            OrderInfo(order_id="order-1", item_id="item-1", buyer_id="buyer-1", chat_id="chat-1"),
            DeliveryResult(status="failed_retryable", order_id="order-1"),
        )
    )

    assert FakeRelistService.instances == []
    assert FakePlaywrightExecutor.instances == []
