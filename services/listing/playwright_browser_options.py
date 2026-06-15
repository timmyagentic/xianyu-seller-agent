ANTI_DETECTION_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
window.chrome = { runtime: {} };
"""


def build_browser_launch_options(*, headless: bool) -> dict:
    return {
        "headless": headless,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-web-security",
            "--disable-features=IsolateOrigins,site-per-process",
            "--window-size=1920,1080",
            "--start-maximized",
        ],
        "ignore_default_args": ["--enable-automation"],
    }


def build_browser_context_options() -> dict:
    return {
        "viewport": {"width": 1920, "height": 1080},
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "permissions": ["geolocation", "notifications"],
        "java_script_enabled": True,
        "locale": "zh-CN",
        "timezone_id": "Asia/Shanghai",
    }
