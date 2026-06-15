import json

import main
from services.listing.models import PublishResult
from services.listing.store import ListingStore


class FakePublishExecutor:
    instances = []

    def __init__(self):
        self.requests = []
        FakePublishExecutor.instances.append(self)

    async def publish(self, request):
        self.requests.append(request)
        return PublishResult(
            success=True,
            item_id="item-published-1",
            item_url="https://www.goofish.com/item?id=item-published-1",
            response_summary="发布成功",
        )


def test_listing_publish_requires_explicit_real_publish_confirmation(tmp_path, monkeypatch, capsys):
    FakePublishExecutor.instances = []
    monkeypatch.setenv("COOKIES_STR", "unb=seller-1; _m_h5_tk=token_123")
    monkeypatch.setattr(main, "_build_playwright_publish_executor", lambda **kwargs: None)

    exit_code = main.run_cli(
        [
            "listing",
            "--db-path",
            str(tmp_path / "listing.db"),
            "publish",
            "--title",
            "资料包",
            "--description",
            "说明",
            "--price",
            "9.90",
            "--stock",
            "7",
            "--image",
            "/tmp/item.png",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["failed_reason"] == "real_publish_confirmation_required"
    assert FakePublishExecutor.instances == []


def test_listing_publish_with_confirmation_invokes_executor_and_saves_snapshot(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "listing.db"
    executor = FakePublishExecutor()
    monkeypatch.setenv("COOKIES_STR", "unb=seller-1; _m_h5_tk=token_123")
    monkeypatch.setattr(main, "_build_playwright_publish_executor", lambda **kwargs: executor)

    exit_code = main.run_cli(
        [
            "listing",
            "--db-path",
            str(db_path),
            "publish",
            "--title",
            "资料包",
            "--description",
            "说明",
            "--price",
            "9.90",
            "--stock",
            "7",
            "--image",
            "/tmp/item.png",
            "--confirm-real-publish",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["success"] is True
    assert executor.requests[0].title == "资料包"
    assert executor.requests[0].stock == 7
    assert executor.requests[0].images == ("/tmp/item.png",)
    snapshot = ListingStore(db_path=str(db_path)).get_item_snapshot("item-published-1")
    assert snapshot is not None
    assert snapshot.title == "资料包"
    assert snapshot.status == "active"
