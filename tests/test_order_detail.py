from services.delivery.orders import is_token_expired_ret, parse_order_detail_response
from XianyuApis import XianyuApis


def test_parse_order_detail_response_extracts_quantity_amount_spec_and_receiver():
    response = {
        "data": {
            "components": [
                {
                    "render": "orderInfoVO",
                    "data": {
                        "itemInfo": {
                            "buyAmount": 2,
                            "price": "19.90",
                            "skuInfo": "套餐:高级版",
                        }
                    },
                },
                {
                    "render": "addressInfoVO",
                    "data": {
                        "name": "张三",
                        "phoneNumber": "13800000000",
                        "address": "上海市",
                    },
                },
            ]
        }
    }

    detail = parse_order_detail_response(response)

    assert detail.quantity == 2
    assert detail.amount == "19.90"
    assert detail.spec_name == "套餐"
    assert detail.spec_value == "高级版"
    assert detail.receiver_name == "张三"
    assert detail.receiver_phone == "13800000000"
    assert detail.receiver_address == "上海市"


def test_token_expired_detection_handles_known_variants():
    assert is_token_expired_ret(["FAIL_SYS_TOKEN_EXOIRED::令牌过期"]) is True
    assert is_token_expired_ret(["FAIL_SYS_TOKEN_EXPIRED::token expired"]) is True
    assert is_token_expired_ret(["SUCCESS::调用成功"]) is False


def test_xianyu_apis_exposes_order_detail_helpers():
    response = {"data": {"components": [{"render": "orderInfoVO", "data": {"itemInfo": {"buyAmount": 3}}}]}}

    assert XianyuApis.parse_order_detail_response(response).quantity == 3
    assert XianyuApis.is_token_expired_ret(["FAIL_SYS_TOKEN_EXPIRED"]) is True
