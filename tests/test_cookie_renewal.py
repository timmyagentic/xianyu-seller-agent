from XianyuApis import XianyuApis
from utils.xianyu_utils import generate_sign


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


def test_renew_login_cookies_merges_set_cookie_on_token_expired(monkeypatch):
    api = XianyuApis()
    api.session.cookies.update({"_m_h5_tk": "oldtoken_123", "unb": "seller-1"})
    monkeypatch.setattr(api, "update_env_cookies", lambda: None)
    calls = []

    def fake_post(url, params, data, headers=None):
        calls.append({"url": url, "params": dict(params), "data": dict(data), "headers": dict(headers or {})})
        return FakeResponse(
            {"ret": ["FAIL_SYS_TOKEN_EXOIRED::令牌过期"]},
            cookies=[
                FakeCookie("_m_h5_tk", "newtoken_456"),
                FakeCookie("_m_h5_tk_enc", "new_enc"),
            ],
        )

    api.session.post = fake_post

    result = api.renew_login_cookies()

    assert result["status"] == "token_refreshed"
    assert set(result["updated_cookie_names"]) == {"_m_h5_tk", "_m_h5_tk_enc"}
    assert api._cookie_value("_m_h5_tk") == "newtoken_456"
    assert calls[0]["url"].endswith("/mtop.taobao.idlemessage.pc.loginuser.get/1.0/")
    assert calls[0]["params"]["api"] == "mtop.taobao.idlemessage.pc.loginuser.get"
    assert calls[0]["data"] == {"data": "{}"}
    assert calls[0]["params"]["sign"] == generate_sign(calls[0]["params"]["t"], "oldtoken", "{}")
    assert "_m_h5_tk=oldtoken_123" in calls[0]["headers"]["cookie"]


def test_renew_login_cookies_reports_session_expired(monkeypatch):
    api = XianyuApis()
    api.session.cookies.update({"_m_h5_tk": "token_123", "unb": "seller-1"})
    monkeypatch.setattr(api, "update_env_cookies", lambda: None)

    def fake_post(url, params, data, headers=None):
        return FakeResponse({"ret": ["FAIL_SYS_SESSION_EXPIRED::Session过期"]})

    api.session.post = fake_post

    result = api.renew_login_cookies()

    assert result["status"] == "session_expired"
    assert result["message"] == "Session过期，需要重新登录"


def test_renew_login_cookies_reports_token_empty_without_request(monkeypatch):
    api = XianyuApis()
    api.session.cookies.update({"unb": "seller-1"})
    monkeypatch.setattr(api, "update_env_cookies", lambda: None)
    called = False

    def fake_post(url, params, data, headers=None):
        nonlocal called
        called = True
        return FakeResponse({"ret": ["SUCCESS::调用成功"]})

    api.session.post = fake_post

    result = api.renew_login_cookies()

    assert result["status"] == "token_empty"
    assert called is False
