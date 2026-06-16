from services.delivery.content import replace_delivery_params


def test_replace_delivery_params_replaces_known_order_variables():
    result = replace_delivery_params(
        "订单 {order_id} 商品 {item_id} 买家 {buyer_id}/{buyer_name} 标题 {item_title} 数量 {order_quantity}",
        {
            "order_id": "order-1",
            "item_id": "item-1",
            "buyer_id": "buyer-1",
            "buyer_name": "张三",
            "item_title": "虚拟资料",
            "order_quantity": "2",
        },
    )

    assert result == "订单 order-1 商品 item-1 买家 buyer-1/张三 标题 虚拟资料 数量 2"


def test_replace_delivery_params_keeps_unknown_variables():
    result = replace_delivery_params("hello {missing}", {"order_id": "order-1"})

    assert result == "hello {missing}"


def test_replace_delivery_params_uses_empty_string_for_none_values():
    result = replace_delivery_params("买家 {buyer_name}", {"buyer_name": None})

    assert result == "买家 "
