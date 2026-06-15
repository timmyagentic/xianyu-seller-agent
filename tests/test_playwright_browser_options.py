from services.listing.playwright_browser_options import (
    ANTI_DETECTION_INIT_SCRIPT,
    build_browser_context_options,
    build_browser_launch_options,
)


def test_browser_launch_options_match_reference_anti_detection_strategy():
    options = build_browser_launch_options(headless=True)

    assert options["headless"] is True
    assert "--disable-blink-features=AutomationControlled" in options["args"]
    assert "--window-size=1920,1080" in options["args"]
    assert "--enable-automation" in options["ignore_default_args"]


def test_browser_context_options_match_reference_profile():
    options = build_browser_context_options()

    assert options["viewport"] == {"width": 1920, "height": 1080}
    assert "Chrome/" in options["user_agent"]
    assert options["java_script_enabled"] is True
    assert options["locale"] == "zh-CN"
    assert options["timezone_id"] == "Asia/Shanghai"
    assert "geolocation" in options["permissions"]
    assert "notifications" in options["permissions"]


def test_anti_detection_init_script_hides_webdriver_markers():
    assert "navigator, 'webdriver'" in ANTI_DETECTION_INIT_SCRIPT
    assert "navigator, 'plugins'" in ANTI_DETECTION_INIT_SCRIPT
    assert "navigator, 'languages'" in ANTI_DETECTION_INIT_SCRIPT
    assert "window.chrome" in ANTI_DETECTION_INIT_SCRIPT
