import json

from main import run_cli
from services.review.store import ReviewStore


def test_review_cli_sets_and_lists_fixed_item_config(tmp_path, capsys):
    db_path = tmp_path / "review.db"

    assert run_cli(
        [
            "review",
            "--db-path",
            str(db_path),
            "config",
            "set",
            "--item-id",
            "item-1",
            "--content",
            "交易顺利，感谢支持。",
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["item_id"] == "item-1"
    assert payload["rating"] == 5
    assert payload["enabled"] is True

    assert run_cli(["review", "--db-path", str(db_path), "config", "list"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == [
        {
            "id": 1,
            "item_id": "item-1",
            "content": "交易顺利，感谢支持。",
            "rating": 5,
            "enabled": True,
        }
    ]


def test_review_cli_submit_requires_explicit_real_review_confirmation(tmp_path, capsys):
    db_path = tmp_path / "review.db"
    store = ReviewStore(db_path=str(db_path))
    store.upsert_config(item_id="item-1", content="交易顺利，感谢支持。")
    task = store.enqueue_task(
        order_id="order-1",
        item_id="item-1",
        buyer_id="buyer-1",
        buyer_name="买家",
        chat_id="chat-1",
        review_url="https://www.goofish.com/review?orderId=order-1",
    )

    exit_code = run_cli(["review", "--db-path", str(db_path), "submit", "--task-id", str(task.id)])

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is False
    assert payload["failed_reason"] == "real_review_confirmation_required"
    assert store.get_task(task.id).status == "pending_confirmation"


def test_review_cli_does_not_submit_task_without_configured_content(tmp_path, capsys):
    db_path = tmp_path / "review.db"
    store = ReviewStore(db_path=str(db_path))
    task = store.enqueue_task(
        order_id="order-1",
        item_id="item-no-config",
        buyer_id="buyer-1",
        buyer_name="买家",
        chat_id="chat-1",
        review_url="https://www.goofish.com/review?orderId=order-1",
    )

    exit_code = run_cli(
        [
            "review",
            "--db-path",
            str(db_path),
            "submit",
            "--task-id",
            str(task.id),
            "--confirm-real-review",
        ]
    )

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is False
    assert payload["failed_reason"] == "review_task_not_ready"


def test_review_cli_lists_pending_queue_and_sets_review_url(tmp_path, capsys):
    db_path = tmp_path / "review.db"
    store = ReviewStore(db_path=str(db_path))
    store.upsert_config(item_id="item-1", content="交易顺利，感谢支持。")
    task = store.enqueue_task(
        order_id="order-1",
        item_id="item-1",
        buyer_id="buyer-1",
        buyer_name="买家",
        chat_id="chat-1",
    )

    assert run_cli(
        [
            "review",
            "--db-path",
            str(db_path),
            "queue",
            "set-url",
            "--task-id",
            str(task.id),
            "--review-url",
            "https://www.goofish.com/review?orderId=order-1",
        ]
    ) == 0
    capsys.readouterr()

    assert run_cli(["review", "--db-path", str(db_path), "queue", "list", "--status", "pending_confirmation"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["id"] == task.id
    assert payload[0]["review_url"] == "https://www.goofish.com/review?orderId=order-1"
    assert payload[0]["content"] == "交易顺利，感谢支持。"
