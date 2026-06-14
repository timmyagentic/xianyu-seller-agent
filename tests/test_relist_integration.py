import asyncio
import json

import main
from main import XianyuLive, run_cli
from services.delivery.orders import OrderInfo
from services.listing.models import RelistResult
from services.listing.store import ListingStore


class FakeSession:
    def __init__(self):
        self.cookies = {}


class FakeApi:
    def __init__(self):
        self.session = FakeSession()


class FakePlaywrightExecutor:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


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


def test_post_delivery_relist_uses_live_api_and_authorized_executor(tmp_path, monkeypatch):
    FakeRelistService.instances = []
    monkeypatch.setenv("DB_PATH", str(tmp_path / "listing.db"))
    monkeypatch.setenv("AUTO_RELIST_ENABLED", "true")
    monkeypatch.setenv("AUTO_RELIST_ALLOW_PLAYWRIGHT", "true")
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
            object(),
        )
    )

    service = FakeRelistService.instances[0]
    assert service.kwargs["api_client"] is live.xianyu
    assert isinstance(service.kwargs["relist_executor"], FakePlaywrightExecutor)
    assert service.kwargs["relist_executor"].kwargs["cookies_str"]
    assert service.requests[0]["target_stock"] == 7
