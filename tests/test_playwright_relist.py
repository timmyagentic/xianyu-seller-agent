import asyncio

from services.listing.models import RelistRequest
from services.listing.playwright_relist import (
    LOGIN_CONTEXT_URL,
    SELLER_HOME_URL,
    SELLER_MANAGEMENT_URL,
    SELLER_PUBLISH_RELIST_URL,
    PlaywrightRelistExecutor,
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
        body_text,
        risk_control=False,
        confirm_after_click=True,
        url="https://www.goofish.com/publish?itemId=item-1&editScene=rePutOn",
        title="发闲置_闲鱼",
        rendered_body_text=None,
        form_rendered=True,
        post_click_url="",
        post_click_body_text="",
        stock_input_available=True,
    ):
        self.body_text = body_text
        self.rendered_body_text = rendered_body_text or body_text
        self.form_rendered = form_rendered
        self.post_click_url = post_click_url
        self.post_click_body_text = post_click_body_text
        self.stock_input_available = stock_input_available
        self.risk_control = risk_control
        self.confirm_after_click = confirm_after_click
        self.url = url
        self.title_text = title
        self.goto_urls = []
        self.waited_selectors = []
        self.stock_input = FakeElement()
        self.relist_button = FakeElement(on_click=self._after_relist_click)

    def _after_relist_click(self):
        if self.post_click_url:
            self.url = self.post_click_url
            self.body_text = self.post_click_body_text or self.body_text
            return
        if self.confirm_after_click:
            self.body_text = f"{self.body_text}\n操作成功 已上架"

    async def goto(self, url, **kwargs):
        self.goto_urls.append(url)

    async def wait_for_load_state(self, *args, **kwargs):
        return None

    async def wait_for_selector(self, selector, **kwargs):
        self.waited_selectors.append(selector)
        if selector == "input, button, textarea":
            self.form_rendered = True
            self.body_text = self.rendered_body_text
            return self.stock_input
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
        if not self.form_rendered:
            return []
        if selector == "input":
            return [self.stock_input]
        if selector == "button":
            return [self.relist_button]
        return []

    async def query_selector(self, selector):
        if self.risk_control and any(key in selector for key in (".nc-container", "#nc_1_n1z", ".captcha")):
            return FakeElement()
        if not self.form_rendered:
            return None
        if any(key in selector for key in ("库存", "数量", "stock", "inventory")):
            if not self.stock_input_available:
                return None
            return self.stock_input
        if "重新上架" in selector and "重新上架" in self.body_text:
            return self.relist_button
        if "恢复上架" in selector and "恢复上架" in self.body_text:
            return self.relist_button
        if "上架" in selector and "上架" in self.body_text:
            return self.relist_button
        if (
            ("发布" in selector or "submit" in selector)
            and (
                "www.goofish.com/publish" in self.url
                or ("seller.goofish.com" in self.url and "seller-item/publish" in self.url)
            )
            and "editScene=rePutOn" in self.url
            and "发布" in self.body_text
        ):
            return self.relist_button
        return None


def _expected_relist_url(item_id="item-1"):
    return SELLER_MANAGEMENT_URL.format(item_id=item_id)


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
    assert page.goto_urls == [SELLER_HOME_URL, LOGIN_CONTEXT_URL, _expected_relist_url()]
    assert result.evidence["pre_action_page"]["element_counts"]["input"] == 1
    assert result.evidence["post_action_page"]["body_text_length"] >= result.evidence["pre_action_page"]["body_text_length"]


def test_playwright_executor_requires_stock_input_before_clicking_when_target_stock_set():
    page = FakePage(body_text="item-1 资料包 发布", stock_input_available=False)
    executor = PlaywrightRelistExecutor(
        cookies_str="unb=seller-1; _m_h5_tk=token_123",
        page_provider=lambda: page,
    )

    result = asyncio.run(executor.relist(RelistRequest(item_id="item-1", expected_title="资料包", target_stock=7)))

    assert result.success is False
    assert result.failed_reason == "stock_input_not_found"
    assert page.relist_button.clicked is False


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


def test_playwright_executor_returns_success_after_item_detail_redirect():
    page = FakePage(
        body_text="item-1 资料包 发布",
        confirm_after_click=False,
        post_click_url="https://www.goofish.com/item?id=item-1&categoryId=&spm=a21ybx.publish.0.0",
        post_click_body_text="资料包 为你推荐 相关商品",
    )
    executor = PlaywrightRelistExecutor(
        cookies_str="unb=seller-1; _m_h5_tk=token_123",
        page_provider=lambda: page,
    )

    result = asyncio.run(executor.relist(RelistRequest(item_id="item-1", expected_title="资料包")))

    assert result.success is True
    assert result.final_status == "active"
    assert page.relist_button.clicked is True
    assert result.evidence["post_action_page"]["url"].startswith("https://www.goofish.com/item?id=item-1")


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
    assert page.goto_urls == [SELLER_HOME_URL, LOGIN_CONTEXT_URL, _expected_relist_url()]
    assert result["item_found"] is True
    assert result["relist_button_found"] is True
    assert result["publish_button_found"] is False
    assert result["would_fill_stock"] == 7
    assert page.relist_button.clicked is False
    assert page.stock_input.filled_values == []


def test_playwright_preview_requires_stock_input_when_target_stock_set():
    page = FakePage(body_text="item-1 资料包 发布", stock_input_available=False)
    executor = PlaywrightRelistExecutor(
        cookies_str="unb=seller-1; _m_h5_tk=token_123",
        page_provider=lambda: page,
    )

    result = asyncio.run(executor.preview(RelistRequest(item_id="item-1", expected_title="资料包", target_stock=7)))

    assert result["success"] is False
    assert result["failed_reason"] == "stock_input_not_found"
    assert result["item_found"] is True
    assert result["relist_button_found"] is True
    assert result["publish_button_found"] is True
    assert result["stock_input_found"] is False
    assert page.relist_button.clicked is False


def test_playwright_preview_waits_for_reputon_publish_form_render():
    page = FakePage(
        body_text="发闲置",
        rendered_body_text="item-1 资料包 发闲置 宝贝图片 宝贝描述 价格 发布",
        form_rendered=False,
    )
    executor = PlaywrightRelistExecutor(
        cookies_str="unb=seller-1; _m_h5_tk=token_123",
        page_provider=lambda: page,
    )

    result = asyncio.run(executor.preview(RelistRequest(item_id="item-1", expected_title="资料包")))

    assert result["success"] is True
    assert page.waited_selectors == ["input, button, textarea"]
    assert result["page_evidence"]["element_counts"]["input"] == 1
    assert result["page_evidence"]["element_counts"]["button"] == 1


def test_playwright_preview_reports_safe_page_evidence_when_not_actionable():
    page = FakePage(body_text="发闲置 宝贝图片 宝贝描述 价格 发布")
    executor = PlaywrightRelistExecutor(
        cookies_str="unb=seller-1; _m_h5_tk=token_123",
        page_provider=lambda: page,
    )

    result = asyncio.run(executor.preview(RelistRequest(item_id="item-404", expected_title="不存在")))

    assert result["success"] is False
    assert result["failed_reason"] == "preflight_not_actionable"
    assert "page_evidence" in result
    assert result["page_evidence"]["url"] == "https://www.goofish.com/publish?itemId=item-1&editScene=rePutOn"
    assert result["page_evidence"]["title"] == "发闲置_闲鱼"
    assert result["page_evidence"]["body_text_length"] == len(page.body_text)
    assert "management_text" in result["page_evidence"]["detected_markers"]
    assert "publish_text" in result["page_evidence"]["detected_markers"]
    assert result["page_evidence"]["element_counts"]["input"] == 1
    assert result["page_evidence"]["element_counts"]["button"] == 1
    assert "body_text" not in result["page_evidence"]
    assert page.relist_button.clicked is False
    assert page.stock_input.filled_values == []


def test_playwright_preview_does_not_treat_seller_publish_button_as_relist_action():
    page = FakePage(
        body_text="商品管理 商品发布 商品信息 库存 item-1 资料包",
        url="https://seller.goofish.com/?site=COMMONPRO#/seller-item/goods-manage",
        title="商品管理 - 闲鱼卖家工作台",
    )
    executor = PlaywrightRelistExecutor(
        cookies_str="unb=seller-1; _m_h5_tk=token_123",
        page_provider=lambda: page,
    )

    result = asyncio.run(executor.preview(RelistRequest(item_id="item-1", expected_title="资料包")))

    assert result["success"] is False
    assert result["failed_reason"] == "preflight_not_actionable"
    assert result["item_found"] is True
    assert result["relist_button_found"] is False
    assert page.relist_button.clicked is False


def test_playwright_executor_treats_seller_publish_reputon_button_as_relist_action():
    page = FakePage(
        body_text="商品发布 item-1 资料包 库存 发布",
        url=SELLER_PUBLISH_RELIST_URL.format(item_id="item-1"),
        title="商品发布 - 闲鱼卖家工作台",
        confirm_after_click=False,
        post_click_url="https://seller.goofish.com/?site=COMMONPRO#/seller-item/publish/success?itemId=item-1",
        post_click_body_text="查看商品 编辑商品",
    )
    executor = PlaywrightRelistExecutor(
        cookies_str="unb=seller-1; _m_h5_tk=token_123",
        page_provider=lambda: page,
        management_url=SELLER_PUBLISH_RELIST_URL,
    )

    result = asyncio.run(executor.relist(RelistRequest(item_id="item-1", expected_title="资料包", target_stock=4)))

    assert result.success is True
    assert result.final_status == "active"
    assert page.stock_input.filled_values[-1] == "4"
    assert page.relist_button.clicked is True
    assert result.evidence["pre_action_page"]["url"] == SELLER_PUBLISH_RELIST_URL.format(item_id="item-1")


def test_playwright_preview_treats_seller_publish_reputon_button_as_actionable():
    page = FakePage(
        body_text="商品发布 item-1 资料包 库存 发布",
        url=SELLER_PUBLISH_RELIST_URL.format(item_id="item-1"),
        title="商品发布 - 闲鱼卖家工作台",
    )
    executor = PlaywrightRelistExecutor(
        cookies_str="unb=seller-1; _m_h5_tk=token_123",
        page_provider=lambda: page,
        management_url=SELLER_PUBLISH_RELIST_URL,
    )

    result = asyncio.run(executor.preview(RelistRequest(item_id="item-1", expected_title="资料包", target_stock=4)))

    assert result["success"] is True
    assert result["relist_button_found"] is True
    assert result["publish_button_found"] is True
    assert result["stock_input_found"] is True
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


def test_playwright_preview_treats_illegal_access_page_as_risk_control():
    page = FakePage(body_text="非法访问 为了保障您的体验，请使用正常浏览器访问闲鱼")
    executor = PlaywrightRelistExecutor(
        cookies_str="unb=seller-1; _m_h5_tk=token_123",
        page_provider=lambda: page,
    )

    result = asyncio.run(executor.preview(RelistRequest(item_id="item-1", expected_title="资料包")))

    assert result["success"] is False
    assert result["failed_reason"] == "risk_control"
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
