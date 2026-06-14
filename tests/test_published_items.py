import json

from XianyuApis import XianyuApis
from main import run_cli
from services.listing.fetch_items import sync_published_items
from services.listing.store import ListingStore
from utils.xianyu_utils import generate_sign


class FakeResponse:
    headers = {}
    cookies = []

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _card(item_id, title, price="12.30", item_status=0):
    return {
        "cardType": 1,
        "cardData": {
            "id": item_id,
            "title": title,
            "priceInfo": {"preText": "¥", "price": price},
            "categoryId": "cat-1",
            "auctionType": "a",
            "itemStatus": item_status,
            "detailUrl": f"https://www.goofish.com/item?id={item_id}",
        },
    }


def test_get_published_items_page_posts_signed_item_list_request():
    api = XianyuApis()
    api.session.cookies.update({"_m_h5_tk": "token_123", "unb": "seller-1"})
    calls = []

    def fake_post(url, params, data, headers=None):
        calls.append({"url": url, "params": dict(params), "data": dict(data), "headers": dict(headers or {})})
        return FakeResponse(
            {
                "ret": ["SUCCESS::调用成功"],
                "data": {"cardList": [_card("item-1", "已发布商品")]},
            }
        )

    api.session.post = fake_post

    result = api.get_published_items_page(page_number=2, page_size=10)

    assert result["success"] is True
    assert result["items"][0]["id"] == "item-1"
    assert result["items"][0]["title"] == "已发布商品"
    assert result["items"][0]["price_text"] == "¥12.30"
    assert calls[0]["url"].endswith("/mtop.idle.web.xyh.item.list/1.0/")
    assert calls[0]["params"]["api"] == "mtop.idle.web.xyh.item.list"
    payload = json.loads(calls[0]["data"]["data"])
    assert payload["groupName"] == "在售"
    assert payload["pageNumber"] == 2
    assert payload["pageSize"] == 10
    assert payload["userId"] == "seller-1"
    assert calls[0]["params"]["sign"] == generate_sign(calls[0]["params"]["t"], "token", calls[0]["data"]["data"])


def test_get_item_status_returns_active_when_item_is_in_published_list():
    api = XianyuApis()
    api.session.cookies.update({"_m_h5_tk": "token_123", "unb": "seller-1"})

    def fake_post(url, params, data, headers=None):
        return FakeResponse(
            {
                "ret": ["SUCCESS::调用成功"],
                "data": {"cardList": [_card("item-1", "已发布商品")]},
            }
        )

    api.session.post = fake_post

    result = api.get_item_status("item-1", page_size=10, max_pages=1)

    assert result["success"] is True
    assert result["item"]["item_id"] == "item-1"
    assert result["item"]["status"] == "active"
    assert result["item"]["status_source"] == "published_list"


def test_relist_item_posts_signed_configured_mtop_request(monkeypatch):
    api = XianyuApis()
    api.session.cookies.update({"_m_h5_tk": "token_123", "unb": "seller-1"})
    calls = []

    monkeypatch.setenv("XIANXY_RELIST_API", "mtop.alibaba.idle.seller.pc.item.republish")

    def fake_post(url, params, data, headers=None):
        calls.append({"url": url, "params": dict(params), "data": dict(data), "headers": dict(headers or {})})
        return FakeResponse(
            {
                "ret": ["SUCCESS::调用成功"],
                "data": {"code": "success", "itemUrl": "https://www.goofish.com/item?id=item-1"},
            }
        )

    api.session.post = fake_post

    result = api.relist_item("item-1", stock=7)

    assert result["ret"] == ["SUCCESS::调用成功"]
    assert calls[0]["url"].endswith("/mtop.alibaba.idle.seller.pc.item.republish/1.0/")
    assert calls[0]["params"]["api"] == "mtop.alibaba.idle.seller.pc.item.republish"
    payload = json.loads(calls[0]["data"]["data"])
    assert payload == {"itemId": "item-1", "stock": 7}
    assert calls[0]["params"]["sign"] == generate_sign(calls[0]["params"]["t"], "token", calls[0]["data"]["data"])


def test_sync_published_items_fetches_all_pages_and_saves_snapshots(tmp_path):
    store = ListingStore(db_path=str(tmp_path / "listing.db"))

    class FakeApi:
        def __init__(self):
            self.calls = []

        def get_all_published_items(self, *, page_size, max_pages=None, myid=None):
            self.calls.append({"page_size": page_size, "max_pages": max_pages, "myid": myid})
            return {
                "success": True,
                "items": [_card("item-1", "商品一")["cardData"], _card("item-2", "商品二")["cardData"]],
                "total_count": 2,
                "total_pages": 1,
                "page_size": page_size,
            }

    api = FakeApi()

    result = sync_published_items(api=api, listing_store=store, page_size=10, max_pages=1, myid="seller-1")

    assert result["success"] is True
    assert result["saved_count"] == 2
    assert result["changed_count"] == 2
    assert api.calls == [{"page_size": 10, "max_pages": 1, "myid": "seller-1"}]
    snapshot = store.get_item_snapshot("item-1")
    assert snapshot.title == "商品一"
    assert snapshot.status == "active"
    assert snapshot.item_url.endswith("item-1")


def test_listing_fetch_items_cli_syncs_current_account_items(tmp_path, monkeypatch, capsys):
    db_path = str(tmp_path / "listing.db")

    class FakeSession:
        def __init__(self):
            self.cookies = {}

    class FakeApi:
        def __init__(self):
            self.session = FakeSession()

        def get_all_published_items(self, *, page_size, max_pages=None, myid=None):
            return {
                "success": True,
                "items": [_card("item-cli", "CLI商品")["cardData"]],
                "total_count": 1,
                "total_pages": 1,
                "page_size": page_size,
            }

    monkeypatch.setenv("COOKIES_STR", "unb=seller-1; _m_h5_tk=token_123")
    monkeypatch.setattr("main.XianyuApis", FakeApi)

    exit_code = run_cli(["listing", "--db-path", db_path, "fetch-items", "--page-size", "10", "--max-pages", "1"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["success"] is True
    assert payload["saved_count"] == 1
    assert ListingStore(db_path=db_path).get_item_snapshot("item-cli").title == "CLI商品"
