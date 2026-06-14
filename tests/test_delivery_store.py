from services.delivery.store import DeliveryStore


def test_delivery_store_creates_and_lists_text_config(tmp_path):
    store = DeliveryStore(db_path=str(tmp_path / "delivery.db"))

    config_id = store.add_config(
        item_id="item-1",
        name="下载码",
        delivery_type="text",
        content="订单 {order_id}",
        enabled=True,
    )

    configs = store.list_configs(item_id="item-1")
    assert len(configs) == 1
    assert configs[0].id == config_id
    assert configs[0].item_id == "item-1"
    assert configs[0].delivery_type == "text"
    assert configs[0].enabled is True
    assert store.get_enabled_config("item-1").id == config_id


def test_delivery_store_can_disable_config(tmp_path):
    store = DeliveryStore(db_path=str(tmp_path / "delivery.db"))
    config_id = store.add_config(
        item_id="item-1",
        name="下载码",
        delivery_type="text",
        content="content",
    )

    store.set_config_enabled(config_id, False)

    assert store.list_configs("item-1")[0].enabled is False
    assert store.get_enabled_config("item-1") is None


def test_delivery_store_adds_data_inventory_rows(tmp_path):
    store = DeliveryStore(db_path=str(tmp_path / "delivery.db"))
    config_id = store.add_config(
        item_id="item-1",
        name="库存",
        delivery_type="data",
        content="",
    )

    row_ids = store.add_inventory(config_id, ["A", "B"])
    rows = store.list_inventory(config_id)

    assert len(row_ids) == 2
    assert [row.content for row in rows] == ["A", "B"]
    assert [row.status for row in rows] == ["available", "available"]


def test_delivery_store_rejects_invalid_delivery_type(tmp_path):
    store = DeliveryStore(db_path=str(tmp_path / "delivery.db"))

    try:
        store.add_config(
            item_id="item-1",
            name="bad",
            delivery_type="image",
            content="x",
        )
    except ValueError as exc:
        assert "delivery_type" in str(exc)
    else:
        raise AssertionError("expected ValueError")
