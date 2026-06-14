from dataclasses import dataclass
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Callable

from .models import RelistApiResult, RelistRequest


SELLER_MANAGEMENT_URL = "https://seller.goofish.com/?site=COMMONPRO#/seller-item"
COOKIE_DOMAINS = (".goofish.com", ".taobao.com", ".alipay.com", ".seller.goofish.com")
RISK_CONTROL_SELECTORS = (".nc-container", "#nc_1_n1z", ".captcha-container", ".nc_scale")
RISK_CONTROL_KEYWORDS = ("滑块", "验证码", "captcha", "nc_1_n1z", "风控", "请拖动", "请按住")
LOGIN_KEYWORDS = ("请登录", "扫码登录", "login.taobao.com", "密码登录")
PERMISSION_KEYWORDS = ("暂无权限", "无权限", "没有权限", "no-permission")
SUCCESS_KEYWORDS = ("操作成功", "重新上架成功", "上架成功", "已上架", "在售")
STOCK_SELECTORS = (
    'input[placeholder*="库存"]',
    'input[aria-label*="库存"]',
    'input[placeholder*="数量"]',
    'input[aria-label*="数量"]',
    'input[name*="stock"]',
    'input[id*="stock"]',
    '[class*="stock"] input',
    '[class*="inventory"] input',
    'xpath=//*[contains(normalize-space(.), "库存")]/following::input[1]',
    'xpath=//*[contains(normalize-space(.), "数量")]/following::input[1]',
)
RELIST_BUTTON_SELECTORS = (
    'button:has-text("重新上架")',
    'a:has-text("重新上架")',
    '[role="button"]:has-text("重新上架")',
    'button:has-text("恢复上架")',
    'a:has-text("恢复上架")',
    '[role="button"]:has-text("恢复上架")',
    'button:has-text("上架")',
    'a:has-text("上架")',
    '[role="button"]:has-text("上架")',
)
CONFIRM_BUTTON_SELECTORS = (
    'button:has-text("确定")',
    'button:has-text("确认")',
    '[role="button"]:has-text("确定")',
    '[role="button"]:has-text("确认")',
)


@dataclass(frozen=True)
class PlaywrightRelistCommand:
    item_id: str
    expected_title: str
    target_stock: int | None
    management_url: str
    cookie_domains: tuple[str, ...]


def build_playwright_relist_command(
    *,
    item_id: str,
    expected_title: str = "",
    target_stock: int | None = None,
    management_url: str = SELLER_MANAGEMENT_URL,
) -> PlaywrightRelistCommand:
    return PlaywrightRelistCommand(
        item_id=str(item_id),
        expected_title=str(expected_title or ""),
        target_stock=target_stock,
        management_url=management_url,
        cookie_domains=COOKIE_DOMAINS,
    )


class PlaywrightRelistExecutor:
    """Use an already-authorized browser session to relist an existing item.

    This executor intentionally stops on login, slider, captcha, or missing
    page confirmation. It never tries to solve platform risk controls.
    """

    def __init__(
        self,
        *,
        cookies_str: str,
        headless: bool = True,
        management_url: str = SELLER_MANAGEMENT_URL,
        timeout_ms: int = 30000,
        screenshot_dir: str | None = None,
        page_provider: Callable[[], object] | None = None,
    ):
        self.cookies_str = cookies_str
        self.headless = headless
        self.management_url = management_url
        self.timeout_ms = timeout_ms
        self.screenshot_dir = Path(screenshot_dir) if screenshot_dir else None
        self.page_provider = page_provider

    async def relist(self, request: RelistRequest) -> RelistApiResult:
        if not self.cookies_str:
            return RelistApiResult(
                success=False,
                failed_reason="cookie_missing",
                response_summary="COOKIES_STR is required for Playwright relist",
            )

        if self.page_provider:
            page = self.page_provider()
            return await self._execute_on_page(page, request)

        try:
            from playwright.async_api import async_playwright
        except Exception as exc:
            return RelistApiResult(
                success=False,
                failed_reason="playwright_unavailable",
                response_summary=f"Playwright is unavailable: {exc}",
            )

        playwright = None
        browser = None
        context = None
        try:
            playwright = await async_playwright().start()
            browser = await playwright.chromium.launch(headless=self.headless)
            context = await browser.new_context()
            await context.add_cookies(self._build_cookie_payload())
            page = await context.new_page()
            return await self._execute_on_page(page, request)
        except Exception as exc:
            return RelistApiResult(
                success=False,
                failed_reason="playwright_relist_exception",
                response_summary=str(exc),
            )
        finally:
            for resource in (context, browser):
                if resource:
                    try:
                        await resource.close()
                    except Exception:
                        pass
            if playwright:
                try:
                    await playwright.stop()
                except Exception:
                    pass

    async def preview(self, request: RelistRequest) -> dict:
        """Open the management page and report whether relist looks actionable.

        This method is intentionally read-only: it never fills stock, clicks the
        relist button, or confirms dialogs. Use it before asking for permission
        to run the real relist path.
        """
        if not self.cookies_str:
            return {
                "success": False,
                "failed_reason": "cookie_missing",
                "response_summary": "COOKIES_STR is required for Playwright relist preview",
            }

        if self.page_provider:
            page = self.page_provider()
            return await self._preview_on_page(page, request)

        try:
            from playwright.async_api import async_playwright
        except Exception as exc:
            return {
                "success": False,
                "failed_reason": "playwright_unavailable",
                "response_summary": f"Playwright is unavailable: {exc}",
            }

        playwright = None
        browser = None
        context = None
        try:
            playwright = await async_playwright().start()
            browser = await playwright.chromium.launch(headless=self.headless)
            context = await browser.new_context()
            await context.add_cookies(self._build_cookie_payload())
            page = await context.new_page()
            return await self._preview_on_page(page, request)
        except Exception as exc:
            return {
                "success": False,
                "failed_reason": "playwright_preview_exception",
                "response_summary": str(exc),
            }
        finally:
            for resource in (context, browser):
                if resource:
                    try:
                        await resource.close()
                    except Exception:
                        pass
            if playwright:
                try:
                    await playwright.stop()
                except Exception:
                    pass

    async def _execute_on_page(self, page, request: RelistRequest) -> RelistApiResult:
        await page.goto(self.management_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

        page_text = await self._body_text(page)
        risk_reason = await self._detect_blocker(page, page_text)
        if risk_reason:
            screenshot_path = await self._save_screenshot(page, request.item_id, risk_reason)
            return RelistApiResult(
                success=False,
                failed_reason=risk_reason,
                screenshot_path=screenshot_path,
                response_summary=self._blocker_summary(risk_reason),
            )

        if request.expected_title and request.expected_title not in page_text:
            return RelistApiResult(
                success=False,
                failed_reason="title_not_found",
                response_summary=f"商品管理页未找到期望标题: {request.expected_title}",
            )
        if request.item_id not in page_text and request.expected_title not in page_text:
            return RelistApiResult(
                success=False,
                failed_reason="item_not_found_on_page",
                response_summary=f"商品管理页未找到商品: {request.item_id}",
            )

        if request.target_stock is not None:
            await self._fill_stock(page, request.target_stock)

        button = await self._find_relist_button(page, request)
        if not button:
            screenshot_path = await self._save_screenshot(page, request.item_id, "relist_button_not_found")
            return RelistApiResult(
                success=False,
                failed_reason="relist_button_not_found",
                screenshot_path=screenshot_path,
                response_summary="商品管理页未找到重新上架按钮",
            )

        await button.click()
        await self._click_optional_confirm(page)
        try:
            await page.wait_for_timeout(1000)
        except Exception:
            pass

        page_text_after = await self._body_text(page)
        risk_reason = await self._detect_blocker(page, page_text_after)
        if risk_reason:
            screenshot_path = await self._save_screenshot(page, request.item_id, risk_reason)
            return RelistApiResult(
                success=False,
                failed_reason=risk_reason,
                screenshot_path=screenshot_path,
                response_summary=self._blocker_summary(risk_reason),
            )
        if any(keyword in page_text_after for keyword in SUCCESS_KEYWORDS):
            screenshot_path = await self._save_screenshot(page, request.item_id, "relisted")
            return RelistApiResult(
                success=True,
                final_status="active",
                screenshot_path=screenshot_path,
                response_summary=page_text_after[:800],
            )

        screenshot_path = await self._save_screenshot(page, request.item_id, "confirmation_missing")
        return RelistApiResult(
            success=False,
            failed_reason="relist_confirmation_missing",
            screenshot_path=screenshot_path,
            response_summary=page_text_after[:800] or "重新上架点击后未检测到平台确认结果",
        )

    async def _preview_on_page(self, page, request: RelistRequest) -> dict:
        await page.goto(self.management_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

        page_text = await self._body_text(page)
        risk_reason = await self._detect_blocker(page, page_text)
        if risk_reason:
            screenshot_path = await self._save_screenshot(page, request.item_id, f"preview-{risk_reason}")
            return {
                "success": False,
                "failed_reason": risk_reason,
                "screenshot_path": screenshot_path,
                "response_summary": self._blocker_summary(risk_reason),
            }

        title_matches = bool(request.expected_title and request.expected_title in page_text)
        item_id_matches = bool(request.item_id and request.item_id in page_text)
        item_found = title_matches or item_id_matches
        button = await self._find_relist_button(page, request)
        button_found = bool(button)
        screenshot_path = await self._save_screenshot(page, request.item_id, "preview")
        return {
            "success": item_found and button_found,
            "item_id": request.item_id,
            "expected_title": request.expected_title,
            "item_found": item_found,
            "title_found": title_matches,
            "item_id_found": item_id_matches,
            "relist_button_found": button_found,
            "would_fill_stock": request.target_stock,
            "screenshot_path": screenshot_path,
            "failed_reason": "" if item_found and button_found else "preflight_not_actionable",
            "response_summary": "preview only; no click or stock fill executed",
        }

    async def _detect_blocker(self, page, page_text: str) -> str:
        page_url = str(getattr(page, "url", "") or "").lower()
        if "no-permission" in page_url:
            return "permission_required"
        for selector in RISK_CONTROL_SELECTORS:
            element = await self._query_selector(page, selector)
            if element and await self._element_visible(element):
                return "risk_control"
        lower_text = page_text.lower()
        if any(keyword.lower() in lower_text for keyword in RISK_CONTROL_KEYWORDS):
            return "risk_control"
        if any(keyword.lower() in lower_text for keyword in LOGIN_KEYWORDS):
            return "login_required"
        if any(keyword.lower() in lower_text for keyword in PERMISSION_KEYWORDS):
            return "permission_required"
        return ""

    async def _fill_stock(self, page, target_stock: int) -> None:
        for selector in STOCK_SELECTORS:
            stock_input = await self._query_selector(page, selector)
            if not stock_input:
                continue
            if not await self._element_visible(stock_input) or not await self._element_enabled(stock_input):
                continue
            try:
                await stock_input.click()
            except Exception:
                pass
            try:
                await stock_input.fill("")
            except Exception:
                try:
                    await stock_input.press("Control+A")
                    await stock_input.press("Backspace")
                except Exception:
                    pass
            await stock_input.fill(str(target_stock))
            return

    async def _find_relist_button(self, page, request: RelistRequest):
        selectors = []
        if request.item_id:
            selectors.extend(
                [
                    (
                        f'xpath=//*[contains(normalize-space(.), "{request.item_id}")]'
                        '//*[self::button or self::a or @role="button"]'
                        '[contains(normalize-space(.), "重新上架") or contains(normalize-space(.), "恢复上架")]'
                    )
                ]
            )
        if request.expected_title:
            selectors.extend(
                [
                    (
                        f'xpath=//*[contains(normalize-space(.), "{request.expected_title}")]'
                        '//*[self::button or self::a or @role="button"]'
                        '[contains(normalize-space(.), "重新上架") or contains(normalize-space(.), "恢复上架")]'
                    )
                ]
            )
        selectors.extend(RELIST_BUTTON_SELECTORS)
        for selector in selectors:
            button = await self._query_selector(page, selector)
            if button and await self._element_visible(button) and await self._element_enabled(button):
                return button
        return None

    async def _click_optional_confirm(self, page) -> None:
        for selector in CONFIRM_BUTTON_SELECTORS:
            button = await self._query_selector(page, selector)
            if not button:
                continue
            if await self._element_visible(button) and await self._element_enabled(button):
                await button.click()
                return

    async def _query_selector(self, page, selector: str):
        try:
            return await page.query_selector(selector)
        except Exception:
            return None

    async def _element_visible(self, element) -> bool:
        try:
            return bool(await element.is_visible())
        except Exception:
            return True

    async def _element_enabled(self, element) -> bool:
        try:
            return bool(await element.is_enabled())
        except Exception:
            return True

    async def _body_text(self, page) -> str:
        try:
            return await page.text_content("body") or ""
        except Exception:
            return ""

    async def _save_screenshot(self, page, item_id: str, suffix: str) -> str:
        if not self.screenshot_dir:
            return ""
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        safe_suffix = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in suffix)
        path = self.screenshot_dir / f"relist-{item_id}-{safe_suffix}.png"
        try:
            await page.screenshot(path=str(path), full_page=True)
            return str(path)
        except Exception:
            return ""

    def _build_cookie_payload(self) -> list[dict[str, str]]:
        parsed = SimpleCookie()
        parsed.load(self.cookies_str)
        payload = []
        for name, morsel in parsed.items():
            if not name or morsel.value is None:
                continue
            for domain in COOKIE_DOMAINS:
                payload.append(
                    {
                        "name": name,
                        "value": morsel.value,
                        "domain": domain,
                        "path": "/",
                    }
                )
        return payload

    def _blocker_summary(self, reason: str) -> str:
        if reason == "risk_control":
            return "检测到滑块/验证码/风控提示，停止自动重新上架"
        if reason == "login_required":
            return "检测到登录页或登录提示，需要人工重新登录"
        if reason == "permission_required":
            return "检测到商品管理页权限不足，需要人工确认账号权限"
        return reason
