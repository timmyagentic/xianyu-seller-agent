import re
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Callable

from .models import PublishRequest, PublishResult


SELLER_HOME_URL = "https://seller.goofish.com"
LOGIN_CONTEXT_URL = "https://login.taobao.com/member/login.jhtml"
PROMOTION_PUBLISH_URL = "https://seller.goofish.com/?site=COMMONPRO&spm=a21107h.42826273.0.0#/seller-item/publish"
COOKIE_DOMAINS = (".goofish.com", ".taobao.com", ".alipay.com", ".seller.goofish.com")
RISK_CONTROL_SELECTORS = (".nc-container", "#nc_1_n1z", ".captcha-container", ".nc_scale")
RISK_CONTROL_KEYWORDS = ("滑块", "验证码", "captcha", "nc_1_n1z", "风控", "请拖动", "请按住")
LOGIN_KEYWORDS = ("请登录", "扫码登录", "login.taobao.com", "密码登录")
PERMISSION_KEYWORDS = ("暂无权限", "无权限", "没有权限", "no-permission")
SUCCESS_KEYWORDS = ("发布成功", "已发布", "上架成功", "成功")
TITLE_SELECTORS = (
    'input[placeholder*="标题"]',
    'textarea[placeholder*="标题"]',
    'input[aria-label*="标题"]',
    'textarea[aria-label*="标题"]',
    'input[name*="title"]',
    'textarea[name*="title"]',
)
DESCRIPTION_SELECTORS = (
    'textarea[placeholder*="描述"]',
    'textarea[placeholder*="详情"]',
    'textarea[aria-label*="描述"]',
    'textarea[name*="desc"]',
    '[contenteditable="true"]',
)
PRICE_SELECTORS = (
    'input[placeholder*="价格"]',
    'input[placeholder*="售价"]',
    'input[aria-label*="价格"]',
    'input[name*="price"]',
    'xpath=//*[contains(normalize-space(.), "价格")]/following::input[1]',
)
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
IMAGE_INPUT_SELECTORS = (
    'input[type="file"]',
    'input[accept*="image"]',
)
PUBLISH_BUTTON_SELECTORS = (
    '.publish-button--KBpTVopQ',
    'button.publish-button--KBpTVopQ',
    'button:has-text("发布")',
    'button:has-text("立即发布")',
    'button.publish-btn',
    '.publish-btn button',
    'button[type="submit"]',
)


class PlaywrightPublishExecutor:
    """Publish a new seller item through the Goofish seller page.

    This intentionally follows the reference project's page warm-up sequence:
    seller home -> Taobao login page -> seller publish page. It stops on login,
    slider, captcha, permission, or missing platform confirmation.
    """

    def __init__(
        self,
        *,
        cookies_str: str,
        headless: bool = True,
        publish_url: str = PROMOTION_PUBLISH_URL,
        timeout_ms: int = 30000,
        screenshot_dir: str | None = None,
        page_provider: Callable[[], object] | None = None,
    ):
        self.cookies_str = cookies_str
        self.headless = headless
        self.publish_url = publish_url
        self.timeout_ms = timeout_ms
        self.screenshot_dir = Path(screenshot_dir) if screenshot_dir else None
        self.page_provider = page_provider

    async def publish(self, request: PublishRequest) -> PublishResult:
        if not self.cookies_str:
            return PublishResult(
                success=False,
                failed_reason="cookie_missing",
                response_summary="COOKIES_STR is required for Playwright publish",
            )

        validation_error = self._validate_request(request)
        if validation_error:
            return PublishResult(success=False, failed_reason=validation_error, response_summary=validation_error)

        if self.page_provider:
            page = self.page_provider()
            return await self._execute_on_page(page, request)

        try:
            from playwright.async_api import async_playwright
        except Exception as exc:
            return PublishResult(
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
            return PublishResult(
                success=False,
                failed_reason="playwright_publish_exception",
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

    async def _execute_on_page(self, page, request: PublishRequest) -> PublishResult:
        await self._open_publish_page_with_cookie(page)
        page_text = await self._body_text(page)
        pre_action_page = await self._page_evidence(page, page_text)
        blocker = await self._detect_blocker(page, page_text)
        if blocker:
            screenshot_path = await self._save_screenshot(page, "publish", blocker)
            return PublishResult(
                success=False,
                failed_reason=blocker,
                screenshot_path=screenshot_path,
                response_summary=self._blocker_summary(blocker),
                evidence=self._execution_evidence(pre_action_page=pre_action_page),
            )

        try:
            await self._fill_first(page, TITLE_SELECTORS, request.title, "title_input_not_found")
            await self._fill_first(page, DESCRIPTION_SELECTORS, request.description, "description_input_not_found")
            await self._fill_first(page, PRICE_SELECTORS, request.price, "price_input_not_found")
            await self._fill_first(page, STOCK_SELECTORS, str(request.stock), "stock_input_not_found")
            await self._upload_images(page, request.images)
        except PublishPageError as exc:
            screenshot_path = await self._save_screenshot(page, "publish", exc.reason)
            return PublishResult(
                success=False,
                failed_reason=exc.reason,
                screenshot_path=screenshot_path,
                response_summary=str(exc),
                evidence=self._execution_evidence(pre_action_page=pre_action_page),
            )

        publish_button = await self._find_first_visible_enabled(page, PUBLISH_BUTTON_SELECTORS)
        if not publish_button:
            screenshot_path = await self._save_screenshot(page, "publish", "publish_button_not_found")
            return PublishResult(
                success=False,
                failed_reason="publish_button_not_found",
                screenshot_path=screenshot_path,
                response_summary="未找到发布按钮",
                evidence=self._execution_evidence(pre_action_page=pre_action_page),
            )

        await publish_button.click()
        await self._wait(page, 5000)
        await self._wait(page, 3000)

        page_text_after = await self._body_text(page)
        post_action_page = await self._page_evidence(page, page_text_after)
        blocker = await self._detect_blocker(page, page_text_after)
        if blocker:
            screenshot_path = await self._save_screenshot(page, "publish", blocker)
            return PublishResult(
                success=False,
                failed_reason=blocker,
                screenshot_path=screenshot_path,
                response_summary=self._blocker_summary(blocker),
                evidence=self._execution_evidence(pre_action_page=pre_action_page, post_action_page=post_action_page),
            )

        current_url = str(getattr(page, "url", "") or "")
        item_id = self._extract_item_id(current_url)
        if self._is_publish_success(current_url, page_text_after):
            screenshot_path = await self._save_screenshot(page, item_id or "publish", "published")
            return PublishResult(
                success=True,
                item_id=item_id,
                item_url=current_url,
                screenshot_path=screenshot_path,
                response_summary=page_text_after[:800],
                evidence=self._execution_evidence(pre_action_page=pre_action_page, post_action_page=post_action_page),
            )

        screenshot_path = await self._save_screenshot(page, "publish", "confirmation_missing")
        return PublishResult(
            success=False,
            failed_reason="publish_confirmation_missing",
            screenshot_path=screenshot_path,
            response_summary=page_text_after[:800] or "发布后未检测到平台确认结果",
            evidence=self._execution_evidence(pre_action_page=pre_action_page, post_action_page=post_action_page),
        )

    async def _open_publish_page_with_cookie(self, page) -> None:
        await page.goto(SELLER_HOME_URL, wait_until="domcontentloaded", timeout=self.timeout_ms)
        await self._wait(page, 1000)
        await page.goto(LOGIN_CONTEXT_URL, wait_until="domcontentloaded", timeout=self.timeout_ms)
        await self._wait(page, 1000)
        await page.goto(self.publish_url, wait_until="networkidle", timeout=max(self.timeout_ms, 60000))
        await self._wait(page, 3000)

    def _validate_request(self, request: PublishRequest) -> str:
        if not request.title.strip():
            return "title_required"
        if not request.description.strip():
            return "description_required"
        if not str(request.price).strip():
            return "price_required"
        try:
            if int(request.stock) <= 0:
                return "stock_required"
        except (TypeError, ValueError):
            return "stock_required"
        if not request.images:
            return "images_required"
        return ""

    async def _fill_first(self, page, selectors: tuple[str, ...], value: str, missing_reason: str) -> None:
        element = await self._find_first_visible_enabled(page, selectors)
        if not element:
            raise PublishPageError(missing_reason, missing_reason)
        try:
            await element.click()
        except Exception:
            pass
        try:
            await element.fill("")
        except Exception:
            try:
                await element.press("Control+A")
                await element.press("Backspace")
            except Exception:
                pass
        await element.fill(str(value))

    async def _upload_images(self, page, images: tuple[str, ...]) -> None:
        input_element = await self._find_first_visible_enabled(page, IMAGE_INPUT_SELECTORS, allow_invisible=True)
        if not input_element:
            raise PublishPageError("image_input_not_found", "image_input_not_found")
        try:
            await input_element.set_input_files(list(images))
        except AttributeError as exc:
            raise PublishPageError("image_input_not_found", "image_input_not_found") from exc

    async def _find_first_visible_enabled(self, page, selectors: tuple[str, ...], *, allow_invisible: bool = False):
        for selector in selectors:
            element = await self._query_selector(page, selector)
            if not element:
                continue
            if not allow_invisible and not await self._element_visible(element):
                continue
            if await self._element_enabled(element):
                return element
        return None

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

    async def _page_evidence(self, page, page_text: str) -> dict:
        page_url = str(getattr(page, "url", "") or "")
        try:
            title = str(await page.title() or "")
        except Exception:
            title = ""
        return {
            "url": page_url[:300],
            "title": title[:120],
            "body_text_length": len(page_text),
            "detected_markers": self._markers(page_url, page_text),
            "element_counts": {
                "input": await self._selector_count(page, "input"),
                "button": await self._selector_count(page, "button"),
            },
        }

    def _markers(self, page_url: str, page_text: str) -> list[str]:
        lower_url = page_url.lower()
        lower_text = page_text.lower()
        markers = []
        if "seller-item/publish" in lower_url:
            markers.append("publish_route")
        if any(keyword.lower() in lower_text or keyword.lower() in lower_url for keyword in LOGIN_KEYWORDS):
            markers.append("login_text")
        if any(keyword.lower() in lower_text or keyword.lower() in lower_url for keyword in PERMISSION_KEYWORDS):
            markers.append("permission_text")
        if any(keyword.lower() in lower_text for keyword in RISK_CONTROL_KEYWORDS):
            markers.append("risk_control_text")
        if any(keyword in page_text for keyword in ("发布", "发闲置", "库存", "价格", "描述")):
            markers.append("publish_text")
        return markers

    async def _selector_count(self, page, selector: str) -> int:
        try:
            return len(await page.query_selector_all(selector))
        except Exception:
            return 0

    async def _save_screenshot(self, page, item_id: str, suffix: str) -> str:
        if not self.screenshot_dir:
            return ""
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        safe_suffix = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in suffix)
        path = self.screenshot_dir / f"publish-{item_id}-{safe_suffix}.png"
        try:
            await page.screenshot(path=str(path), full_page=True)
            return str(path)
        except Exception:
            return ""

    async def _wait(self, page, ms: int) -> None:
        try:
            await page.wait_for_timeout(ms)
        except Exception:
            pass

    def _execution_evidence(self, *, pre_action_page: dict, post_action_page: dict | None = None) -> dict:
        evidence = {
            "executor": "playwright_publish",
            "warmup_urls": [SELLER_HOME_URL, LOGIN_CONTEXT_URL, self.publish_url],
            "pre_action_page": pre_action_page,
        }
        if post_action_page is not None:
            evidence["post_action_page"] = post_action_page
        return evidence

    def _build_cookie_payload(self) -> list[dict[str, str]]:
        parsed = SimpleCookie()
        parsed.load(self.cookies_str)
        payload = []
        for name, morsel in parsed.items():
            if not name or morsel.value is None:
                continue
            for domain in COOKIE_DOMAINS:
                payload.append({"name": name, "value": morsel.value, "domain": domain, "path": "/"})
        return payload

    def _blocker_summary(self, reason: str) -> str:
        if reason == "risk_control":
            return "检测到滑块/验证码/风控提示，停止自动发布"
        if reason == "login_required":
            return "检测到登录页或登录提示，需要人工重新登录"
        if reason == "permission_required":
            return "检测到商品发布页权限不足，需要人工确认账号权限"
        return reason

    def _is_publish_success(self, current_url: str, page_text: str) -> bool:
        if "/item/" in current_url or re.search(r"[?&]id=\d+", current_url):
            return True
        if "publish" in current_url and "发闲置" in page_text:
            return False
        return any(keyword in page_text for keyword in SUCCESS_KEYWORDS) and (
            "发布" in page_text or "上架" in page_text
        )

    def _extract_item_id(self, current_url: str) -> str:
        match = re.search(r"[?&]id=(\d+)", current_url)
        if match:
            return match.group(1)
        match = re.search(r"/item/(\d+)", current_url)
        if match:
            return match.group(1)
        return ""


class PublishPageError(Exception):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
