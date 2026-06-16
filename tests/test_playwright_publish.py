import asyncio

from services.listing.models import PublishRequest
from services.listing.playwright_publish import (
    LOGIN_CONTEXT_URL,
    PROMOTION_PUBLISH_URL,
    SELLER_HOME_URL,
    PlaywrightPublishExecutor,
)


class FakeElement:
    def __init__(self, *, on_click=None):
        self.on_click = on_click
        self.clicked = False
        self.filled_values = []
        self.uploaded_files = []

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

    async def press(self, key):
        return None

    async def set_input_files(self, files):
        self.uploaded_files.extend(files)


class FakePublishPage:
    def __init__(
        self,
        *,
        body_text="发闲置 标题 描述 价格 库存 发布",
        url=PROMOTION_PUBLISH_URL,
        title="闲鱼发布",
        risk_control=False,
        permission_required=False,
        confirm_after_click=True,
        rendered_body_text=None,
        form_rendered=True,
    ):
        self.body_text = body_text
        self.rendered_body_text = rendered_body_text or body_text
        self.form_rendered = form_rendered
        self.url = url
        self.title_text = title
        self.risk_control = risk_control
        self.permission_required = permission_required
        self.confirm_after_click = confirm_after_click
        self.goto_urls = []
        self.waits = []
        self.waited_selectors = []
        self.title_input = FakeElement()
        self.description_input = FakeElement()
        self.price_input = FakeElement()
        self.stock_input = FakeElement()
        self.image_input = FakeElement()
        self.publish_button = FakeElement(on_click=self._after_publish_click)

    def _after_publish_click(self):
        if self.confirm_after_click:
            self.body_text = "发布成功 已上架"
            self.url = "https://www.goofish.com/item?id=1234567890"

    async def goto(self, url, **kwargs):
        self.goto_urls.append(url)
        self.url = url
        if self.permission_required and "publish" in url:
            self.url = "https://www.goofish.com/no-permission?redirectUrl=x"
            self.body_text = "暂无权限"

    async def wait_for_timeout(self, ms):
        self.waits.append(ms)

    async def wait_for_selector(self, selector, **kwargs):
        self.waited_selectors.append(selector)
        if selector == "input, button, textarea":
            self.form_rendered = True
            self.body_text = self.rendered_body_text
            return self.title_input
        return None

    async def title(self):
        return self.title_text

    async def text_content(self, selector):
        if selector == "body":
            return self.body_text
        return ""

    async def query_selector_all(self, selector):
        if not self.form_rendered:
            return []
        if selector == "input":
            return [self.title_input, self.price_input, self.stock_input, self.image_input]
        if selector == "button":
            return [self.publish_button]
        return []

    async def query_selector(self, selector):
        if self.risk_control and any(key in selector for key in (".nc-container", "#nc_1_n1z", ".captcha")):
            return FakeElement()
        if not self.form_rendered:
            return None
        if "type=\"file\"" in selector or "accept*=\"image\"" in selector:
            return self.image_input
        if any(key in selector for key in ("标题", "title")):
            return self.title_input
        if any(key in selector for key in ("描述", "详情", "desc", "contenteditable")):
            return self.description_input
        if any(key in selector for key in ("价格", "售价", "price")):
            return self.price_input
        if any(key in selector for key in ("库存", "数量", "stock", "inventory")):
            return self.stock_input
        if "发布" in selector or "submit" in selector or "publish" in selector:
            return self.publish_button
        return None


def _request():
    return PublishRequest(
        title="智谱 GLM coding plan",
        description="发货说明",
        price="9.90",
        stock=7,
        images=("/tmp/item.png",),
    )


def test_publish_executor_warms_login_context_before_publish_page():
    page = FakePublishPage()
    executor = PlaywrightPublishExecutor(
        cookies_str="unb=seller-1; _m_h5_tk=token_123",
        page_provider=lambda: page,
    )

    result = asyncio.run(executor.publish(_request()))

    assert result.success is True
    assert page.goto_urls == [SELLER_HOME_URL, LOGIN_CONTEXT_URL, PROMOTION_PUBLISH_URL]
    assert page.title_input.filled_values[-1] == "智谱 GLM coding plan"
    assert page.description_input.filled_values[-1] == "发货说明"
    assert page.price_input.filled_values[-1] == "9.90"
    assert page.stock_input.filled_values[-1] == "7"
    assert page.image_input.uploaded_files == ["/tmp/item.png"]
    assert page.publish_button.clicked is True
    assert result.item_id == "1234567890"
    assert result.evidence["warmup_urls"] == [SELLER_HOME_URL, LOGIN_CONTEXT_URL, PROMOTION_PUBLISH_URL]


def test_publish_executor_waits_for_publish_form_render():
    page = FakePublishPage(
        body_text="发闲置",
        rendered_body_text="发闲置 标题 描述 价格 库存 发布",
        form_rendered=False,
    )
    executor = PlaywrightPublishExecutor(
        cookies_str="unb=seller-1; _m_h5_tk=token_123",
        page_provider=lambda: page,
    )

    result = asyncio.run(executor.publish(_request()))

    assert result.success is True
    assert page.waited_selectors == ["input, button, textarea"]
    assert page.title_input.filled_values[-1] == "智谱 GLM coding plan"


def test_publish_executor_stops_on_no_permission_after_warmup():
    page = FakePublishPage(permission_required=True)
    executor = PlaywrightPublishExecutor(
        cookies_str="unb=seller-1; _m_h5_tk=token_123",
        page_provider=lambda: page,
    )

    result = asyncio.run(executor.publish(_request()))

    assert result.success is False
    assert result.failed_reason == "permission_required"
    assert page.goto_urls == [SELLER_HOME_URL, LOGIN_CONTEXT_URL, PROMOTION_PUBLISH_URL]
    assert page.publish_button.clicked is False


def test_publish_executor_treats_illegal_access_page_as_risk_control():
    page = FakePublishPage(body_text="非法访问 为了保障您的体验，请使用正常浏览器访问闲鱼")
    executor = PlaywrightPublishExecutor(
        cookies_str="unb=seller-1; _m_h5_tk=token_123",
        page_provider=lambda: page,
    )

    result = asyncio.run(executor.publish(_request()))

    assert result.success is False
    assert result.failed_reason == "risk_control"
    assert page.publish_button.clicked is False


def test_publish_executor_requires_images_before_touching_browser():
    page = FakePublishPage()
    executor = PlaywrightPublishExecutor(
        cookies_str="unb=seller-1; _m_h5_tk=token_123",
        page_provider=lambda: page,
    )

    result = asyncio.run(
        executor.publish(
            PublishRequest(title="资料包", description="说明", price="9.90", stock=7, images=())
        )
    )

    assert result.success is False
    assert result.failed_reason == "images_required"
    assert page.goto_urls == []


def test_publish_executor_does_not_report_success_without_confirmation():
    page = FakePublishPage(confirm_after_click=False)
    executor = PlaywrightPublishExecutor(
        cookies_str="unb=seller-1; _m_h5_tk=token_123",
        page_provider=lambda: page,
    )

    result = asyncio.run(executor.publish(_request()))

    assert result.success is False
    assert result.failed_reason == "publish_confirmation_missing"
    assert page.publish_button.clicked is True
