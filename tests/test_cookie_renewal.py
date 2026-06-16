from XianyuApis import XianyuApis
from utils.xianyu_utils import generate_sign
from dotenv import dotenv_values


class FakeCookie:
    def __init__(self, name, value):
        self.name = name
        self.value = value


class FakeResponse:
    def __init__(self, payload, cookies=None, status_code=200, text=""):
        self._payload = payload
        self.cookies = cookies or []
        self.headers = {"Set-Cookie": "1"} if cookies else {}
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._payload


def test_renew_login_cookies_merges_set_cookie_on_token_expired(monkeypatch):
    api = XianyuApis()
    api.session.cookies.update({"_m_h5_tk": "oldtoken_123", "unb": "seller-1"})
    monkeypatch.setattr(api, "update_env_cookies", lambda *args, **kwargs: None)
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
    monkeypatch.setattr(api, "update_env_cookies", lambda *args, **kwargs: None)

    def fake_post(url, params, data, headers=None):
        return FakeResponse({"ret": ["FAIL_SYS_SESSION_EXPIRED::Session过期"]})

    api.session.post = fake_post

    result = api.renew_login_cookies()

    assert result["status"] == "session_expired"
    assert result["message"] == "Session过期，需要重新登录"


def test_renew_login_cookies_reports_token_empty_without_request(monkeypatch):
    api = XianyuApis()
    api.session.cookies.update({"unb": "seller-1"})
    monkeypatch.setattr(api, "update_env_cookies", lambda *args, **kwargs: None)
    called = False

    def fake_post(url, params, data, headers=None):
        nonlocal called
        called = True
        return FakeResponse({"ret": ["SUCCESS::调用成功"]})

    api.session.post = fake_post

    result = api.renew_login_cookies()

    assert result["status"] == "token_empty"
    assert called is False


def test_renew_login_cookies_runs_passport_cookie_chain_on_success(monkeypatch):
    api = XianyuApis()
    api.session.cookies.update(
        {
            "_m_h5_tk": "token_123",
            "unb": "seller-1",
            "cookie2": "cookie2-value",
            "_tb_token_": "tb-token",
            "XSRF-TOKEN": "xsrf-token",
        }
    )
    monkeypatch.setattr(api, "update_env_cookies", lambda *args, **kwargs: None)
    calls = []

    def fake_post(url, params=None, data=None, headers=None, **kwargs):
        calls.append({"url": url, "params": dict(params or {}), "data": data, "headers": dict(headers or {})})
        if "mtop.taobao.idlemessage.pc.loginuser.get" in url:
            return FakeResponse({"ret": ["SUCCESS::调用成功"]})
        if "hasLogin.do" in url:
            return FakeResponse(
                {"content": {"success": True}},
                cookies=[
                    FakeCookie("last_u_xianyu_web", "seller-1"),
                    FakeCookie("last_cc", "cc-value"),
                ],
            )
        if "silentHasLogin.do" in url:
            return FakeResponse({"content": {"success": True}}, cookies=[FakeCookie("sdkSilent", "silent")])
        if "setLoginSettings.do" in url:
            return FakeResponse({"code": 0}, cookies=[FakeCookie("havana_lgc2_77", "long-login")])
        raise AssertionError(url)

    api.session.post = fake_post

    result = api.renew_login_cookies()

    assert result["status"] == "cookie_updated"
    assert result["updated_cookie_names"] == [
        "last_u_xianyu_web",
        "last_cc",
        "sdkSilent",
        "havana_lgc2_77",
    ]
    assert [call["url"] for call in calls] == [
        "https://h5api.m.goofish.com/h5/mtop.taobao.idlemessage.pc.loginuser.get/1.0/",
        "https://passport.goofish.com/newlogin/hasLogin.do",
        "https://passport.goofish.com/newlogin/silentHasLogin.do",
        "https://passport.goofish.com/ac/account/setLoginSettings.do",
    ]
    assert api._cookie_value("last_u_xianyu_web") == "seller-1"
    assert api._cookie_value("sdkSilent") == "silent"
    assert api._cookie_value("havana_lgc2_77") == "long-login"


def test_update_env_cookies_merges_partial_updates_without_regressing_current_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    env_path = tmp_path / ".env"
    env_path.write_text("COOKIES_STR=unb=seller-1; _m_h5_tk=newtoken_456\n", encoding="utf-8")

    api = XianyuApis()
    api.session.cookies.update({"unb": "seller-1", "_m_h5_tk": "oldtoken_123", "cookie2": "stable"})

    api.update_env_cookies({"x5sec": "fresh"})

    saved = dotenv_values(env_path)["COOKIES_STR"]
    assert "_m_h5_tk=newtoken_456" in saved
    assert "_m_h5_tk=oldtoken_123" not in saved
    assert "cookie2=stable" in saved
    assert "x5sec=fresh" in saved
