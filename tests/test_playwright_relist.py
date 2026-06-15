import asyncio

from services.listing.models import RelistRequest
from services.listing.playwright_relist import (
    LOGIN_CONTEXT_URL,
    SELLER_HOME_URL,
    SELLER_MANAGEMENT_URL,
    PlaywrightRelistExecutor,
)


class FakeElement:
    def __init__(self, *, on_click=None):
        self.on_click = on_click
        self.clicked = False
        self.filled_values = []

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


class FakePage:
    def __init__(
        self,
        *,
        body_text,
        risk_control=False,
        confirm_after_click=True,
        url="https://seller.goofish.com/#/seller-item",
        title="闲鱼管理系统",
    ):
        self.body_text = body_text
        self.risk_control = risk_control
        self.confirm_after_click = confirm_after_click
        self.url = url
        self.title_text = title
        self.goto_urls = []
        self.stock_input = FakeElement()
        self.relist_button = FakeElement(on_click=self._after_relist_click)

    def _after_relist_click(self):
        if self.confirm_after_click:
            self.body_text = f"{self.body_text}\n操作成功 已上架"

    async def goto(self, url, **kwargs):
        self.goto_urls.append(url)

    async def wait_for_load_state(self, *args, **kwargs):
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
        if selector == "input":
            return [self.stock_input]
        if selector == "button":
            return [self.relist_button]
        return []

    async def query_selector(self, selector):
        if self.risk_control and any(key in selector for key in (".nc-container", "#nc_1_n1z", ".captcha")):
            return FakeElement()
        if any(key in selector for key in ("库存", "数量", "stock", "inventory")):
            return self.stock_input
        if "重新上架" in selector or "恢复上架" in selector or "上架" in selector:
            return self.relist_button
        return None


def test_playwright_executor_stops_on_risk_control():
    page = FakePage(body_text="请拖动下方滑块完成验证", risk_control=True)
    executor = PlaywrightRelistExecutor(
        cookies_str="unb=seller-1; _m_h5_tk=token_123",
        page_provider=lambda: page,
    )

    result = asyncio.run(executor.relist(RelistRequest(item_id="item-1", expected_title="资料包")))

    assert result.success is False
    assert result.failed_reason == "risk_control"
    assert "滑块" in result.response_summary
    assert page.relist_button.clicked is False


def test_playwright_executor_fills_stock_and_returns_success_after_page_confirmation():
    page = FakePage(body_text="item-1 资料包 重新上架")
    executor = PlaywrightRelistExecutor(
        cookies_str="unb=seller-1; _m_h5_tk=token_123",
        page_provider=lambda: page,
    )

    result = asyncio.run(executor.relist(RelistRequest(item_id="item-1", expected_title="资料包", target_stock=7)))

    assert result.success is True
    assert result.final_status == "active"
    assert page.stock_input.filled_values[-1] == "7"
    assert page.relist_button.clicked is True
    assert "操作成功" in result.response_summary
    assert result.evidence["executor"] == "playwright"
    assert result.evidence["warmup_urls"] == [SELLER_HOME_URL, LOGIN_CONTEXT_URL, SELLER_MANAGEMENT_URL]
    assert page.goto_urls == [SELLER_HOME_URL, LOGIN_CONTEXT_URL, SELLER_MANAGEMENT_URL]
    assert result.evidence["pre_action_page"]["element_counts"]["input"] == 1
    assert result.evidence["post_action_page"]["body_text_length"] >= result.evidence["pre_action_page"]["body_text_length"]


def test_playwright_executor_does_not_report_success_without_page_confirmation():
    page = FakePage(body_text="item-1 资料包 重新上架", confirm_after_click=False)
    executor = PlaywrightRelistExecutor(
        cookies_str="unb=seller-1; _m_h5_tk=token_123",
        page_provider=lambda: page,
    )

    result = asyncio.run(executor.relist(RelistRequest(item_id="item-1", expected_title="资料包")))

    assert result.success is False
    assert result.failed_reason == "relist_confirmation_missing"
    assert page.relist_button.clicked is True


def test_playwright_preview_detects_item_and_button_without_clicking_or_filling_stock():
    page = FakePage(body_text="item-1 资料包 重新上架")
    executor = PlaywrightRelistExecutor(
        cookies_str="unb=seller-1; _m_h5_tk=token_123",
        page_provider=lambda: page,
    )

    result = asyncio.run(
        executor.preview(RelistRequest(item_id="item-1", expected_title="资料包", target_stock=7))
    )

    assert result["success"] is True
    assert result["warmup_urls"] == [SELLER_HOME_URL, LOGIN_CONTEXT_URL, SELLER_MANAGEMENT_URL]
    assert page.goto_urls == [SELLER_HOME_URL, LOGIN_CONTEXT_URL, SELLER_MANAGEMENT_URL]
    assert result["item_found"] is True
    assert result["relist_button_found"] is True
    assert result["would_fill_stock"] == 7
    assert page.relist_button.clicked is False
    assert page.stock_input.filled_values == []


def test_playwright_preview_reports_safe_page_evidence_when_not_actionable():
    page = FakePage(body_text="商品管理 在售 下架 批量操作", url="https://seller.goofish.com/?site=COMMONPRO#/seller-item")
    executor = PlaywrightRelistExecutor(
        cookies_str="unb=seller-1; _m_h5_tk=token_123",
        page_provider=lambda: page,
    )

    result = asyncio.run(executor.preview(RelistRequest(item_id="item-404", expected_title="不存在")))

    assert result["success"] is False
    assert result["failed_reason"] == "preflight_not_actionable"
    assert "page_evidence" in result
    assert result["page_evidence"]["url"] == "https://seller.goofish.com/?site=COMMONPRO#/seller-item"
    assert result["page_evidence"]["title"] == "闲鱼管理系统"
    assert result["page_evidence"]["body_text_length"] == len(page.body_text)
    assert "management_text" in result["page_evidence"]["detected_markers"]
    assert result["page_evidence"]["element_counts"]["input"] == 1
    assert result["page_evidence"]["element_counts"]["button"] == 1
    assert "body_text" not in result["page_evidence"]
    assert page.relist_button.clicked is False
    assert page.stock_input.filled_values == []


def test_playwright_preview_stops_on_risk_control_without_clicking():
    page = FakePage(body_text="请拖动下方滑块完成验证", risk_control=True)
    executor = PlaywrightRelistExecutor(
        cookies_str="unb=seller-1; _m_h5_tk=token_123",
        page_provider=lambda: page,
    )

    result = asyncio.run(executor.preview(RelistRequest(item_id="item-1", expected_title="资料包")))

    assert result["success"] is False
    assert result["failed_reason"] == "risk_control"
    assert "滑块" in result["response_summary"]
    assert page.relist_button.clicked is False


def test_playwright_preview_reports_no_permission_redirect():
    page = FakePage(
        body_text="当前账号暂无权限",
        url="https://seller.goofish.com/?site=COMMONPRO#/no-permission?redirectUrl=x",
    )
    executor = PlaywrightRelistExecutor(
        cookies_str="unb=seller-1; _m_h5_tk=token_123",
        page_provider=lambda: page,
    )

    result = asyncio.run(executor.preview(RelistRequest(item_id="item-1", expected_title="资料包")))

    assert result["success"] is False
    assert result["failed_reason"] == "permission_required"
    assert "权限" in result["response_summary"]
    assert page.relist_button.clicked is False
