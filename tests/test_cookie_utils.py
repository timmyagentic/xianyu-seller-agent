from utils.xianyu_utils import trans_cookies


def test_trans_cookies_accepts_semicolon_without_space():
    cookies = trans_cookies("unb=seller-1;_m_h5_tk=token_123;cookie2=value=with=equals")

    assert cookies["unb"] == "seller-1"
    assert cookies["_m_h5_tk"] == "token_123"
    assert cookies["cookie2"] == "value=with=equals"


def test_trans_cookies_accepts_semicolon_with_space():
    cookies = trans_cookies("unb=seller-1; _m_h5_tk=token_123")

    assert cookies == {"unb": "seller-1", "_m_h5_tk": "token_123"}
