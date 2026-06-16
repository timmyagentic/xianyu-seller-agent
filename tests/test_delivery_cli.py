import json

from main import run_cli
from services.delivery.store import DeliveryStore


def test_delivery_cli_adds_inventory_from_content_file(tmp_path, capsys):
    db_path = tmp_path / "delivery.db"
    key_file = tmp_path / "keys.txt"
    key_file.write_text("KEY-A\n\nKEY-B\n", encoding="utf-8")
    assert run_cli(
        [
            "delivery",
            "--db-path",
            str(db_path),
            "add",
            "--item-id",
            "item-1",
            "--type",
            "data",
            "--name",
            "一次性卡密",
        ]
    ) == 0
    config_id = json.loads(capsys.readouterr().out)["id"]

    assert run_cli(
        [
            "delivery",
            "--db-path",
            str(db_path),
            "inventory",
            "add",
            "--config-id",
            str(config_id),
            "--content-file",
            str(key_file),
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == {"config_id": config_id, "added": 2}
    rows = DeliveryStore(db_path=str(db_path)).list_inventory(config_id)
    assert [row.content for row in rows] == ["KEY-A", "KEY-B"]


def test_delivery_cli_lists_inventory_without_exposing_content_by_default(tmp_path, capsys):
    db_path = tmp_path / "delivery.db"
    store = DeliveryStore(db_path=str(db_path))
    config_id = store.add_config(item_id="item-1", name="一次性卡密", delivery_type="data", content="")
    store.add_inventory(config_id, ["SECRET-KEY"])

    assert run_cli(
        [
            "delivery",
            "--db-path",
            str(db_path),
            "inventory",
            "list",
            "--config-id",
            str(config_id),
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["id"] == 1
    assert payload[0]["status"] == "available"
    assert "content" not in payload[0]
