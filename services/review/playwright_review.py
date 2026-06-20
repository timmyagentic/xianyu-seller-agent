from http.cookies import SimpleCookie
from pathlib import Path
from typing import Callable

from services.listing.playwright_browser_options import (
    ANTI_DETECTION_INIT_SCRIPT,
    build_browser_context_options,
    build_browser_launch_options,
)

from .models import ReviewSubmissionRequest, ReviewSubmissionResult


SELLER_HOME_URL = "https://www.goofish.com"
LOGIN_CONTEXT_URL = "https://login.taobao.com/member/login.jhtml"
COOKIE_DOMAINS = (".goofish.com", ".taobao.com", ".alipay.com")
RISK_CONTROL_SELECTORS = (".nc-container", "#nc_1_n1z", ".captcha-container", ".nc_scale")
RISK_CONTROL_KEYWORDS = (
    "滑块",
    "验证码",
    "captcha",
    "nc_1_n1z",
    "风控",
    "请拖动",
    "请按住",
    "非法访问",
    "正常浏览器",
    "保障您的体验",
)
LOGIN_KEYWORDS = ("请登录", "扫码登录", "login.taobao.com", "密码登录")
PERMISSION_KEYWORDS = ("暂无权限", "无权限", "没有权限", "no-permission")
SUCCESS_KEYWORDS = ("评价成功", "已评价", "提交成功", "发表成功", "感谢评价")
RATING_SELECTORS = (
    'button[aria-label*="5"]',
    '[role="button"][aria-label*="5"]',
    '[data-rate="5"]',
    '[data-score="5"]',
    '[data-value="5"]',
    'input[value="5"]',
    'button:has-text("五星")',
    '[role="button"]:has-text("五星")',
    'text="五星"',
    'xpath=(//*[contains(@class, "star") or contains(@class, "rate") or contains(@class, "score")])[5]',
)
TEXTAREA_SELECTORS = (
    "textarea",
    '[contenteditable="true"]',
    'input[placeholder*="评价"]',
    'textarea[placeholder*="评价"]',
    'xpath=//*[contains(normalize-space(.), "评价")]/following::textarea[1]',
)
SUBMIT_BUTTON_SELECTORS = (
    'button:has-text("提交")',
    'button:has-text("发表")',
    'button:has-text("确认")',
    '[role="button"]:has-text("提交")',
    '[role="button"]:has-text("发表")',
    'button[type="submit"]',
)


class PlaywrightReviewExecutor:
    """Submit one manually confirmed order review through a browser page.

    The executor intentionally stops on login, slider, captcha, permission
    errors, missing controls, or missing page confirmation.
    """

    def __init__(
        self,
        *,
        cookies_str: str,
        headless: bool = True,
        timeout_ms: int = 30000,
        screenshot_dir: str | None = None,
        order_url_template: str = "",
        page_provider: Callable[[], object] | None = None,
    ):
        self.cookies_str = cookies_str
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.screenshot_dir = Path(screenshot_dir) if screenshot_dir else None
        self.order_url_template = order_url_template
        self.page_provider = page_provider

    async def submit(self, request: ReviewSubmissionRequest) -> ReviewSubmissionResult:
        if not self.cookies_str:
            return ReviewSubmissionResult(
                success=False,
                failed_reason="cookie_missing",
                response_summary="COOKIES_STR is required for Playwright review",
            )
        review_url = self._review_url(request)
        if not review_url:
            return ReviewSubmissionResult(
                success=False,
                failed_reason="review_url_missing",
                response_summary="review_url or AUTO_REVIEW_ORDER_URL_TEMPLATE is required",
            )

        if self.page_provider:
            page = self.page_provider()
            return await self._submit_on_page(page, request, review_url)

        try:
            from playwright.async_api import async_playwright
        except Exception as exc:
            return ReviewSubmissionResult(
                success=False,
                failed_reason="playwright_unavailable",
                response_summary=f"Playwright is unavailable: {exc}",
            )

        playwright = None
        browser = None
        context = None
        try:
            playwright = await async_playwright().start()
            browser = await playwright.chromium.launch(**build_browser_launch_options(headless=self.headless))
            context = await browser.new_context(**build_browser_context_options())
            await context.add_cookies(self._build_cookie_payload())
            page = await context.new_page()
            await self._add_anti_detection_script(page)
            return await self._submit_on_page(page, request, review_url)
        except Exception as exc:
            return ReviewSubmissionResult(
                success=False,
                failed_reason="playwright_review_exception",
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

    async def preflight(self, request: ReviewSubmissionRequest) -> dict:
        if not self.cookies_str:
            return {
                "success": False,
                "failed_reason": "cookie_missing",
                "response_summary": "COOKIES_STR is required for Playwright review preflight",
            }
        review_url = self._review_url(request)
        if not review_url:
            return {
                "success": False,
                "failed_reason": "review_url_missing",
                "response_summary": "review_url or AUTO_REVIEW_ORDER_URL_TEMPLATE is required",
            }

        if self.page_provider:
            page = self.page_provider()
            return await self._preflight_on_page(page, request, review_url)

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
            browser = await playwright.chromium.launch(**build_browser_launch_options(headless=self.headless))
            context = await browser.new_context(**build_browser_context_options())
            await context.add_cookies(self._build_cookie_payload())
            page = await context.new_page()
            await self._add_anti_detection_script(page)
            return await self._preflight_on_page(page, request, review_url)
        except Exception as exc:
            return {
                "success": False,
                "failed_reason": "playwright_review_preflight_exception",
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

    async def _submit_on_page(self, page, request: ReviewSubmissionRequest, review_url: str) -> ReviewSubmissionResult:
        await self._open_review_page_with_cookie(page, review_url)

        page_text = await self._body_text(page)
        pre_action_page = await self._page_evidence(page, page_text, request)
        blocker = await self._detect_blocker(page, page_text)
        if blocker:
            screenshot_path = await self._save_screenshot(page, request.order_id, blocker)
            return ReviewSubmissionResult(
                success=False,
                failed_reason=blocker,
                screenshot_path=screenshot_path,
                response_summary=self._blocker_summary(blocker),
                evidence=self._execution_evidence(pre_action_page=pre_action_page, review_url=review_url),
            )

        rating = await self._find_rating_control(page, request.rating)
        if not rating:
            screenshot_path = await self._save_screenshot(page, request.order_id, "rating_control_not_found")
            return ReviewSubmissionResult(
                success=False,
                failed_reason="rating_control_not_found",
                screenshot_path=screenshot_path,
                response_summary="评价页未找到五星控件，未提交评价",
                evidence=self._execution_evidence(pre_action_page=pre_action_page, review_url=review_url),
            )

        textarea = await self._find_review_textarea(page)
        if not textarea:
            screenshot_path = await self._save_screenshot(page, request.order_id, "review_textarea_not_found")
            return ReviewSubmissionResult(
                success=False,
                failed_reason="review_textarea_not_found",
                screenshot_path=screenshot_path,
                response_summary="评价页未找到评价文本框，未提交评价",
                evidence=self._execution_evidence(pre_action_page=pre_action_page, review_url=review_url),
            )

        submit_button = await self._find_submit_button(page)
        if not submit_button:
            screenshot_path = await self._save_screenshot(page, request.order_id, "submit_button_not_found")
            return ReviewSubmissionResult(
                success=False,
                failed_reason="submit_button_not_found",
                screenshot_path=screenshot_path,
                response_summary="评价页未找到提交按钮，未提交评价",
                evidence=self._execution_evidence(pre_action_page=pre_action_page, review_url=review_url),
            )

        await rating.click()
        await self._fill_review_text(textarea, request.content)
        await submit_button.click()
        await self._wait(page, 1000)

        page_text_after = await self._body_text(page)
        post_action_page = await self._page_evidence(page, page_text_after, request)
        blocker = await self._detect_blocker(page, page_text_after)
        if blocker:
            screenshot_path = await self._save_screenshot(page, request.order_id, blocker)
            return ReviewSubmissionResult(
                success=False,
                failed_reason=blocker,
                screenshot_path=screenshot_path,
                response_summary=self._blocker_summary(blocker),
                evidence=self._execution_evidence(
                    pre_action_page=pre_action_page,
                    post_action_page=post_action_page,
                    review_url=review_url,
                ),
            )

        if any(keyword in page_text_after for keyword in SUCCESS_KEYWORDS):
            screenshot_path = await self._save_screenshot(page, request.order_id, "submitted")
            return ReviewSubmissionResult(
                success=True,
                status="submitted",
                screenshot_path=screenshot_path,
                response_summary=page_text_after[:800],
                evidence=self._execution_evidence(
                    pre_action_page=pre_action_page,
                    post_action_page=post_action_page,
                    review_url=review_url,
                ),
            )

        screenshot_path = await self._save_screenshot(page, request.order_id, "confirmation_missing")
        return ReviewSubmissionResult(
            success=False,
            failed_reason="review_confirmation_missing",
            screenshot_path=screenshot_path,
            response_summary=page_text_after[:800] or "评价提交后未检测到平台确认结果",
            evidence=self._execution_evidence(
                pre_action_page=pre_action_page,
                post_action_page=post_action_page,
                review_url=review_url,
            ),
        )

    async def _preflight_on_page(self, page, request: ReviewSubmissionRequest, review_url: str) -> dict:
        await self._open_review_page_with_cookie(page, review_url)

        page_text = await self._body_text(page)
        page_evidence = await self._page_evidence(page, page_text, request)
        blocker = await self._detect_blocker(page, page_text)
        if blocker:
            screenshot_path = await self._save_screenshot(page, request.order_id, f"preflight-{blocker}")
            return {
                "success": False,
                "failed_reason": blocker,
                "screenshot_path": screenshot_path,
                "response_summary": self._blocker_summary(blocker),
                "warmup_urls": self._warmup_urls(review_url),
                "page_evidence": page_evidence,
            }

        rating_found = bool(await self._find_rating_control(page, request.rating))
        textarea_found = bool(await self._find_review_textarea(page))
        submit_found = bool(await self._find_submit_button(page))
        screenshot_path = await self._save_screenshot(page, request.order_id, "preflight")
        success = rating_found and textarea_found and submit_found
        missing = []
        if not rating_found:
            missing.append("rating_control_not_found")
        if not textarea_found:
            missing.append("review_textarea_not_found")
        if not submit_found:
            missing.append("submit_button_not_found")
        return {
            "success": success,
            "failed_reason": "" if success else ",".join(missing),
            "task_id": request.task_id,
            "order_id": request.order_id,
            "item_id": request.item_id,
            "rating_control_found": rating_found,
            "textarea_found": textarea_found,
            "submit_button_found": submit_found,
            "screenshot_path": screenshot_path,
            "response_summary": "preflight only; no rating, text fill, or submit executed",
            "warmup_urls": self._warmup_urls(review_url),
            "page_evidence": page_evidence,
        }

    async def _open_review_page_with_cookie(self, page, review_url: str) -> None:
        await page.goto(SELLER_HOME_URL, wait_until="domcontentloaded", timeout=self.timeout_ms)
        await self._wait(page, 1000)
        await page.goto(LOGIN_CONTEXT_URL, wait_until="domcontentloaded", timeout=self.timeout_ms)
        await self._wait(page, 1000)
        await page.goto(review_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        await self._wait(page, 1000)

    def _review_url(self, request: ReviewSubmissionRequest) -> str:
        if request.review_url:
            return request.review_url
        if self.order_url_template and "{order_id}" in self.order_url_template:
            return self.order_url_template.format(order_id=request.order_id)
        return ""

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

    async def _find_rating_control(self, page, rating: int):
        if int(rating) != 5:
            return None
        for selector in RATING_SELECTORS:
            element = await self._query_selector(page, selector)
            if element and await self._element_visible(element) and await self._element_enabled(element):
                return element
        return None

    async def _find_review_textarea(self, page):
        for selector in TEXTAREA_SELECTORS:
            element = await self._query_selector(page, selector)
            if element and await self._element_visible(element) and await self._element_enabled(element):
                return element
        return None

    async def _find_submit_button(self, page):
        for selector in SUBMIT_BUTTON_SELECTORS:
            element = await self._query_selector(page, selector)
            if element and await self._element_visible(element) and await self._element_enabled(element):
                return element
        return None

    async def _fill_review_text(self, element, content: str) -> None:
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
        await element.fill(content)

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

    async def _page_evidence(self, page, page_text: str, request: ReviewSubmissionRequest) -> dict:
        page_url = str(getattr(page, "url", "") or "")
        title = ""
        try:
            title = str(await page.title() or "")
        except Exception:
            title = ""

        lower_text = page_text.lower()
        lower_url = page_url.lower()
        markers: list[str] = []
        if any(keyword.lower() in lower_text or keyword.lower() in lower_url for keyword in LOGIN_KEYWORDS):
            markers.append("login_text")
        if any(keyword.lower() in lower_text or keyword.lower() in lower_url for keyword in PERMISSION_KEYWORDS):
            markers.append("permission_text")
        if any(keyword.lower() in lower_text for keyword in RISK_CONTROL_KEYWORDS):
            markers.append("risk_control_text")
        if request.order_id and request.order_id in page_text:
            markers.append("order_id_text")
        if any(keyword in page_text for keyword in ("评价", "五星", "提交", "发表")):
            markers.append("review_text")
        if any(keyword in page_text for keyword in SUCCESS_KEYWORDS):
            markers.append("success_text")

        return {
            "url": page_url[:300],
            "title": title[:120],
            "body_text_length": len(page_text),
            "detected_markers": markers,
            "element_counts": {
                "textarea": await self._selector_count(page, "textarea"),
                "button": await self._selector_count(page, "button"),
            },
        }

    async def _selector_count(self, page, selector: str) -> int:
        try:
            return len(await page.query_selector_all(selector))
        except Exception:
            return 0

    def _execution_evidence(
        self,
        *,
        pre_action_page: dict,
        review_url: str,
        post_action_page: dict | None = None,
    ) -> dict:
        evidence = {
            "executor": "playwright_review",
            "review_url": review_url[:300],
            "warmup_urls": self._warmup_urls(review_url),
            "pre_action_page": pre_action_page,
        }
        if post_action_page is not None:
            evidence["post_action_page"] = post_action_page
        return evidence

    def _warmup_urls(self, review_url: str) -> list[str]:
        return [SELLER_HOME_URL, LOGIN_CONTEXT_URL, review_url]

    async def _wait(self, page, ms: int) -> None:
        try:
            await page.wait_for_timeout(ms)
        except Exception:
            pass

    async def _add_anti_detection_script(self, page) -> None:
        try:
            await page.add_init_script(ANTI_DETECTION_INIT_SCRIPT)
        except Exception:
            pass

    async def _save_screenshot(self, page, order_id: str, suffix: str) -> str:
        if not self.screenshot_dir:
            return ""
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        safe_order_id = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in order_id)
        safe_suffix = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in suffix)
        path = self.screenshot_dir / f"review-{safe_order_id}-{safe_suffix}.png"
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
            return "检测到滑块/验证码/风控提示，停止自动评价"
        if reason == "login_required":
            return "检测到登录页或登录提示，需要人工重新登录"
        if reason == "permission_required":
            return "检测到评价页权限不足，需要人工确认账号权限"
        return reason
