import asyncio

from services.review.models import ReviewSubmissionRequest
from services.review.playwright_review import (
    LOGIN_CONTEXT_URL,
    SELLER_HOME_URL,
    PlaywrightReviewExecutor,
)


class FakeElement:
    def __init__(self, *, on_click=None):
        self.on_click = on_click
        self.clicked = False
        self.filled_values = []
        self.value = ""

    async def is_visible(self):
        return True

    async def is_enabled(self):
        return True

    async def click(self):
        self.clicked = True
        if self.on_click:
            self.on_click()

    async def fill(self, value):
        self.filled_values.append(value)
        self.value = value

    async def press(self, key):
        return None

    async def input_value(self):
        return self.value


class FakePage:
    def __init__(
        self,
        *,
        body_text="评价 买家 五星 提交",
        risk_control=False,
        login_required=False,
        confirm_after_click=True,
        rating_available=True,
        textarea_available=True,
        submit_available=True,
        url="https://www.goofish.com/review?orderId=order-1",
        title="评价订单",
    ):
        self.body_text = body_text
        if login_required:
            self.body_text = "请登录 扫码登录"
        self.risk_control = risk_control
        self.confirm_after_click = confirm_after_click
        self.rating_available = rating_available
        self.textarea_available = textarea_available
        self.submit_available = submit_available
        self.url = url
        self.title_text = title
        self.goto_urls = []
        self.rating = FakeElement()
        self.textarea = FakeElement()
        self.submit_button = FakeElement(on_click=self._after_submit)

    def _after_submit(self):
        if self.confirm_after_click:
            self.body_text = f"{self.body_text}\n评价成功 已评价"

    async def goto(self, url, **kwargs):
        self.goto_urls.append(url)
        self.url = url

    async def wait_for_load_state(self, *args, **kwargs):
        return None

    async def wait_for_selector(self, *args, **kwargs):
        return None

    async def wait_for_timeout(self, *args, **kwargs):
        return None

    async def title(self):
        return self.title_text

    async def text_content(self, selector):
        if selector == "body":
            return self.body_text
        return ""

    async def query_selector_all(self, selector):
        if selector == "textarea":
            return [self.textarea] if self.textarea_available else []
        if selector == "button":
            return [self.submit_button] if self.submit_available else []
        return []

    async def query_selector(self, selector):
        if self.risk_control and any(key in selector for key in (".nc-container", "#nc_1_n1z", ".captcha")):
            return FakeElement()
        if "五星" in selector or "5" in selector or "star" in selector.lower():
            return self.rating if self.rating_available else None
        if "textarea" in selector or "评价" in selector or "contenteditable" in selector:
            return self.textarea if self.textarea_available else None
        if "提交" in selector or "发表" in selector or "submit" in selector:
            return self.submit_button if self.submit_available else None
        return None


def _request(**overrides):
    payload = {
        "task_id": 1,
        "order_id": "order-1",
        "item_id": "item-1",
        "review_url": "https://www.goofish.com/review?orderId=order-1",
        "content": "交易顺利，感谢支持。",
        "rating": 5,
    }
    payload.update(overrides)
    return ReviewSubmissionRequest(**payload)


def test_playwright_review_requires_review_url_before_opening_browser():
    executor = PlaywrightReviewExecutor(
        cookies_str="unb=seller-1; _m_h5_tk=token_123",
        page_provider=lambda: FakePage(),
    )

    result = asyncio.run(executor.submit(_request(review_url="")))

    assert result.success is False
    assert result.failed_reason == "review_url_missing"


def test_playwright_review_stops_on_risk_control_without_submitting():
    page = FakePage(body_text="请拖动下方滑块完成验证", risk_control=True)
    executor = PlaywrightReviewExecutor(
        cookies_str="unb=seller-1; _m_h5_tk=token_123",
        page_provider=lambda: page,
    )

    result = asyncio.run(executor.submit(_request()))

    assert result.success is False
    assert result.failed_reason == "risk_control"
    assert page.submit_button.clicked is False


def test_playwright_review_fills_five_star_content_and_requires_confirmation():
    page = FakePage()
    executor = PlaywrightReviewExecutor(
        cookies_str="unb=seller-1; _m_h5_tk=token_123",
        page_provider=lambda: page,
    )

    result = asyncio.run(executor.submit(_request()))

    assert result.success is True
    assert page.goto_urls == [SELLER_HOME_URL, LOGIN_CONTEXT_URL, "https://www.goofish.com/review?orderId=order-1"]
    assert page.rating.clicked is True
    assert page.textarea.filled_values[-1] == "交易顺利，感谢支持。"
    assert page.submit_button.clicked is True
    assert result.evidence["executor"] == "playwright_review"


def test_playwright_review_does_not_report_success_without_page_confirmation():
    page = FakePage(confirm_after_click=False)
    executor = PlaywrightReviewExecutor(
        cookies_str="unb=seller-1; _m_h5_tk=token_123",
        page_provider=lambda: page,
    )

    result = asyncio.run(executor.submit(_request()))

    assert result.success is False
    assert result.failed_reason == "review_confirmation_missing"
    assert page.submit_button.clicked is True


def test_playwright_review_preflight_is_read_only():
    page = FakePage()
    executor = PlaywrightReviewExecutor(
        cookies_str="unb=seller-1; _m_h5_tk=token_123",
        page_provider=lambda: page,
    )

    result = asyncio.run(executor.preflight(_request()))

    assert result["success"] is True
    assert result["rating_control_found"] is True
    assert result["textarea_found"] is True
    assert result["submit_button_found"] is True
    assert page.rating.clicked is False
    assert page.textarea.filled_values == []
    assert page.submit_button.clicked is False
