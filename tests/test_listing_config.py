import json

import pytest

from services.listing.relist import load_relist_request, map_relist_failure_reason


def test_load_relist_request_validates_json_config(tmp_path):
    config_path = tmp_path / "item-001.json"
    config_path.write_text(
        json.dumps(
            {
                "item_id": "item-1",
                "expected_title": "资料包",
                "delivery": {
                    "type": "text",
                    "content": "订单 {order_id}",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    request = load_relist_request(str(config_path))

    assert request.item_id == "item-1"
    assert request.expected_title == "资料包"
    assert request.delivery.delivery_type == "text"
    assert request.delivery.content == "订单 {order_id}"


def test_load_relist_request_rejects_missing_item_id(tmp_path):
    config_path = tmp_path / "bad.json"
    config_path.write_text(json.dumps({"delivery": {"type": "text", "content": "x"}}), encoding="utf-8")

    with pytest.raises(ValueError, match="item_id"):
        load_relist_request(str(config_path))


def test_load_relist_request_rejects_invalid_delivery_type(tmp_path):
    config_path = tmp_path / "bad-delivery.json"
    config_path.write_text(
        json.dumps({"item_id": "item-1", "delivery": {"type": "image", "content": "x"}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="delivery.type"):
        load_relist_request(str(config_path))


def test_relist_failure_reason_mapping_uses_safe_platform_reasons():
    assert map_relist_failure_reason(["FAIL_SYS_TOKEN_EXPIRED::令牌过期"]) == "cookie_expired"
    assert map_relist_failure_reason(["RGV587_ERROR::哎哟喂,被挤爆啦"]) == "risk_control"
    assert map_relist_failure_reason(["FAIL::按钮不可用"]) == "按钮不可用"
