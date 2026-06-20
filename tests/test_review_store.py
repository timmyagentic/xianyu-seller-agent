from services.messages.models import IncomingMessage
from services.review.store import ReviewStore


def _reviewable_message(**overrides):
    payload = {
        "chat_id": "chat-1",
        "item_id": "item-1",
        "sender_id": "buyer-1",
        "sender_name": "买家",
        "text": "交易成功，待评价",
        "message_id": "msg-1",
        "message_time": 1,
        "raw": {},
        "is_from_self": False,
        "kind": "reviewable_order",
        "order_id": "order-1",
        "is_paid_order": False,
        "is_reviewable_order": True,
    }
    payload.update(overrides)
    return IncomingMessage(**payload)


def test_review_store_enqueues_pending_task_from_enabled_item_config(tmp_path):
    db_path = tmp_path / "review.db"
    store = ReviewStore(db_path=str(db_path))
    store.upsert_config(item_id="item-1", content="交易顺利，感谢支持。")

    task = store.enqueue_from_message(_reviewable_message())

    assert task.status == "pending_confirmation"
    assert task.order_id == "order-1"
    assert task.item_id == "item-1"
    assert task.content == "交易顺利，感谢支持。"
    assert task.rating == 5


def test_review_store_keeps_order_id_idempotent(tmp_path):
    db_path = tmp_path / "review.db"
    store = ReviewStore(db_path=str(db_path))
    store.upsert_config(item_id="item-1", content="交易顺利，感谢支持。")

    first = store.enqueue_from_message(_reviewable_message(order_id="order-dup"))
    second = store.enqueue_from_message(_reviewable_message(order_id="order-dup", message_id="msg-2"))

    assert second.id == first.id
    assert [task.order_id for task in store.list_tasks()] == ["order-dup"]


def test_review_store_records_skipped_task_without_enabled_config(tmp_path):
    db_path = tmp_path / "review.db"
    store = ReviewStore(db_path=str(db_path))

    task = store.enqueue_from_message(_reviewable_message(item_id="item-no-config"))

    assert task.status == "skipped_no_config"
    assert task.failed_reason == "review_config_missing"
    assert store.list_tasks(status="pending_confirmation") == []
