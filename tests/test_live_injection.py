import inspect

from main import XianyuLive


def test_xianyu_live_accepts_reply_bot_injection():
    signature = inspect.signature(XianyuLive)

    assert "reply_bot" in signature.parameters
