import time

from xianyu_qr_login import QRLoginSession, build_qr_login_display_lines


def test_qr_login_display_lines_include_link_and_png_path():
    lines = build_qr_login_display_lines(
        qr_content="https://passport.goofish.com/qrcode",
        png_path="/tmp/xianyu-login-qr.png",
    )

    assert lines == [
        "二维码登录链接: https://passport.goofish.com/qrcode",
        "二维码图片文件: /tmp/xianyu-login-qr.png",
    ]


def test_qr_login_session_expiration():
    session = QRLoginSession(
        session_id="session-1",
        created_time=time.time() - 301,
        expire_time=300,
    )

    assert session.is_expired() is True
