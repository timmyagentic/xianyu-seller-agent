import json
import time

from services.delivery.orders import is_token_expired_ret, parse_order_detail_response
from XianyuApis import XianyuApis
from utils.xianyu_utils import generate_sign


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


def test_xianyu_apis_get_order_detail_posts_signed_tid_request():
    api = XianyuApis()
    api.session.cookies.set("_m_h5_tk", "token_123")
    calls = []

    class FakeResponse:
        headers = {}

        def json(self):
            return {
                "ret": ["SUCCESS::调用成功"],
                "data": {
                    "components": [
                        {"render": "orderInfoVO", "data": {"itemInfo": {"buyAmount": 2}}},
                    ]
                },
            }

    def fake_post(url, params, data, headers=None):
        calls.append({"url": url, "params": params, "data": data, "headers": headers})
        return FakeResponse()

    api.session.post = fake_post

    response = api.get_order_detail("1234567890126")

    assert XianyuApis.parse_order_detail_response(response).quantity == 2
    assert calls[0]["url"].endswith("/mtop.idle.web.trade.order.detail/1.0/")
    assert calls[0]["params"]["api"] == "mtop.idle.web.trade.order.detail"
    assert calls[0]["params"]["sign"]
    assert json.loads(calls[0]["data"]["data"]) == {"tid": "1234567890126"}


def test_xianyu_apis_retries_order_detail_with_set_cookie_token(monkeypatch):
    api = XianyuApis()
    api.session.cookies.update({"_m_h5_tk": "oldtoken_123", "unb": "seller-1"})
    monkeypatch.setattr(api, "update_env_cookies", lambda: None)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    calls = []

    class FakeCookie:
        def __init__(self, name, value):
            self.name = name
            self.value = value

    class FakeResponse:
        def __init__(self, payload, cookies=None):
            self._payload = payload
            self.cookies = cookies or []
            self.headers = {"Set-Cookie": "1"} if cookies else {}

        def json(self):
            return self._payload

    def fake_post(url, params, data, headers=None):
        calls.append({"params": dict(params), "data": dict(data)})
        expected_new_sign = generate_sign(params["t"], "newtoken", data["data"])
        if len(calls) == 1:
            return FakeResponse(
                {"ret": ["FAIL_SYS_TOKEN_EXOIRED::令牌过期"]},
                cookies=[
                    FakeCookie("_m_h5_tk", "newtoken_456"),
                    FakeCookie("_m_h5_tk_enc", "new_enc"),
                ],
            )
        if params["sign"] == expected_new_sign:
            return FakeResponse(
                {
                    "ret": ["SUCCESS::调用成功"],
                    "data": {"components": [{"render": "orderInfoVO", "data": {"itemInfo": {"buyAmount": 2}}}]},
                }
            )
        return FakeResponse({"ret": ["FAIL_SYS_TOKEN_EXOIRED::令牌过期"]})

    api.session.post = fake_post

    response = api.get_order_detail("1234567890126")

    assert XianyuApis.parse_order_detail_response(response).quantity == 2
    assert len(calls) == 2
    assert calls[0]["params"]["sign"] == generate_sign(calls[0]["params"]["t"], "oldtoken", calls[0]["data"]["data"])
    assert calls[1]["params"]["sign"] == generate_sign(calls[1]["params"]["t"], "newtoken", calls[1]["data"]["data"])


def test_xianyu_apis_confirm_delivery_posts_signed_dummy_consign_request():
    api = XianyuApis()
    api.session.cookies.set("_m_h5_tk", "token_123")
    calls = []

    class FakeResponse:
        headers = {}
        cookies = []

        def json(self):
            return {"ret": ["SUCCESS::调用成功"], "data": {"ok": True}}

    def fake_post(url, params, data, headers=None):
        calls.append({"url": url, "params": params, "data": data, "headers": headers})
        return FakeResponse()

    api.session.post = fake_post

    result = api.confirm_delivery("1234567890126", item_id="item-1")

    assert result["success"] is True
    assert result["order_id"] == "1234567890126"
    assert calls[0]["url"].endswith("/mtop.taobao.idle.logistic.consign.dummy/1.0/")
    assert calls[0]["params"]["api"] == "mtop.taobao.idle.logistic.consign.dummy"
    assert calls[0]["params"]["sign"]
    assert json.loads(calls[0]["data"]["data"]) == {
        "orderId": "1234567890126",
        "tradeText": "",
        "picList": [],
        "newUnconsign": True,
    }


def test_xianyu_apis_confirm_delivery_treats_already_delivered_as_success():
    api = XianyuApis()
    api.session.cookies.set("_m_h5_tk", "token_123")

    class FakeResponse:
        headers = {}
        cookies = []

        def json(self):
            return {"ret": ["FAIL_BIZ_ORDER_ALREADY_DELIVERY::订单已发货成功"]}

    api.session.post = lambda url, params, data, headers=None: FakeResponse()

    result = api.confirm_delivery("1234567890126")

    assert result["success"] is True
    assert result["already_delivered"] is True
    assert "已发货" in result["message"]
