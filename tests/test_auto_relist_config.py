import json

from main import run_cli
from services.listing.store import ListingStore


def test_listing_store_upserts_enabled_auto_relist_config(tmp_path):
    store = ListingStore(db_path=str(tmp_path / "listing.db"))

    config_id = store.upsert_auto_relist_config(
        item_id="item-1",
        target_stock=7,
        expected_title="资料包",
        enabled=True,
        allow_playwright=False,
    )

    config = store.get_enabled_auto_relist_config("item-1")
    assert config.id == config_id
    assert config.item_id == "item-1"
    assert config.target_stock == 7
    assert config.expected_title == "资料包"
    assert config.enabled is True
    assert config.allow_playwright is False


def test_listing_auto_relist_cli_sets_item_stock(tmp_path, capsys):
    db_path = str(tmp_path / "listing.db")

    exit_code = run_cli(
        [
            "listing",
            "--db-path",
            db_path,
            "auto-relist",
            "set",
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
    assert payload["item_id"] == "item-1"
    assert payload["target_stock"] == 7
    assert payload["enabled"] is True
    config = ListingStore(db_path=db_path).get_enabled_auto_relist_config("item-1")
    assert config.target_stock == 7
