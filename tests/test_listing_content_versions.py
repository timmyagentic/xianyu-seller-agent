import json

import main
from services.listing.store import ListingStore


def test_listing_store_records_content_versions_locally(tmp_path):
    store = ListingStore(db_path=str(tmp_path / "listing.db"))

    version_id = store.record_content_version(
        item_id="1030573156061",
        title="智谱 GLM coding plan",
        description="本地记录的新版商品说明",
        price="39.90",
        stock=7,
        version_label="v3",
        notes="发布前草稿",
        source="manual",
    )

    versions = store.list_content_versions(item_id="1030573156061")
    assert len(versions) == 1
    assert versions[0].id == version_id
    assert versions[0].item_id == "1030573156061"
    assert versions[0].version_label == "v3"
    assert versions[0].title == "智谱 GLM coding plan"
    assert versions[0].description == "本地记录的新版商品说明"
    assert versions[0].price == "39.90"
    assert versions[0].stock == 7
    assert versions[0].notes == "发布前草稿"
    assert versions[0].source == "manual"
    assert versions[0].created_at


def test_listing_content_version_cli_adds_local_db_record(tmp_path, capsys):
    db_path = str(tmp_path / "listing.db")

    exit_code = main.run_cli(
        [
            "listing",
            "--db-path",
            db_path,
            "content-version",
            "add",
            "--item-id",
            "1030573156061",
            "--label",
            "v3",
            "--title",
            "智谱 GLM coding plan",
            "--description",
            "CLI 写入的商品信息版本",
            "--price",
            "39.90",
            "--stock",
            "7",
            "--notes",
            "只保存在本地 SQLite",
            "--source",
            "manual",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["item_id"] == "1030573156061"
    assert payload["version_id"]
    version = ListingStore(db_path=db_path).list_content_versions(item_id="1030573156061")[0]
    assert version.id == payload["version_id"]
    assert version.description == "CLI 写入的商品信息版本"


def test_listing_content_version_cli_lists_versions(tmp_path, capsys):
    db_path = str(tmp_path / "listing.db")
    store = ListingStore(db_path=db_path)
    store.record_content_version(
        item_id="item-1",
        title="标题一",
        description="说明一",
        price="9.90",
        stock=1,
        version_label="v1",
    )
    store.record_content_version(
        item_id="item-2",
        title="标题二",
        description="说明二",
        price="19.90",
        stock=2,
        version_label="v2",
    )

    exit_code = main.run_cli(
        [
            "listing",
            "--db-path",
            db_path,
            "content-version",
            "list",
            "--item-id",
            "item-1",
            "--limit",
            "10",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert len(payload) == 1
    assert payload[0]["item_id"] == "item-1"
    assert payload[0]["title"] == "标题一"
