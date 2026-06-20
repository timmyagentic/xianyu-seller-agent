from services.delivery.store import DeliveryStore
from services.listing.store import ListingStore
from services.review.store import ReviewStore
from services.web_app import (
    auto_relist_payload,
    create_auto_relist_config,
    create_delivery_config,
    delivery_configs_payload,
    run_publish,
    summary_payload,
)


def test_web_summary_does_not_expose_cookie_value(tmp_path, monkeypatch):
    db_path = str(tmp_path / "app.db")
    monkeypatch.setenv("COOKIES_STR", "unb=seller-1; _m_h5_tk=secret_token")
    DeliveryStore(db_path=db_path).add_config(item_id="item-1", name="文本", delivery_type="text", content="secret")
    ListingStore(db_path=db_path).upsert_auto_relist_config(
        item_id="item-1",
        target_stock=7,
        expected_title="资料包",
        enabled=True,
        allow_playwright=True,
    )
    review_store = ReviewStore(db_path=db_path)
    review_store.upsert_config(item_id="item-1", content="交易顺利，感谢支持。")
    review_store.enqueue_task(
        order_id="order-1",
        item_id="item-1",
        buyer_id="buyer-1",
        buyer_name="买家",
        chat_id="chat-1",
    )

    payload = summary_payload(db_path)

    assert payload["success"] is True
    assert payload["env"]["cookies_present"] is True
    assert "secret_token" not in str(payload)
    assert payload["counts"]["delivery_configs"] == 1
    assert payload["counts"]["auto_relist_configs"] == 1
    assert payload["counts"]["review_configs"] == 1
    assert payload["counts"]["review_tasks"] == 1


def test_web_api_creates_delivery_and_auto_relist_configs(tmp_path):
    db_path = str(tmp_path / "app.db")

    delivery = create_delivery_config(
        db_path,
        {
            "item_id": "item-1",
            "name": "统一文本",
            "delivery_type": "text",
            "content": "发货内容",
            "enabled": True,
        },
    )
    relist = create_auto_relist_config(
        db_path,
        {
            "item_id": "item-1",
            "target_stock": 7,
            "expected_title": "资料包",
            "enabled": True,
            "allow_playwright": True,
        },
    )

    assert delivery["success"] is True
    assert relist["success"] is True
    assert delivery_configs_payload(db_path)["configs"][0]["item_id"] == "item-1"
    assert auto_relist_payload(db_path)["configs"][0]["target_stock"] == 7


def test_web_publish_requires_explicit_confirmation(tmp_path):
    payload, status = run_publish(
        str(tmp_path / "app.db"),
        {
            "title": "资料包",
            "description": "说明",
            "price": "9.90",
            "stock": 7,
            "images": ["/tmp/item.png"],
            "confirm_real_publish": False,
        },
    )

    assert status == 400
    assert payload["success"] is False
    assert payload["failed_reason"] == "real_publish_confirmation_required"
