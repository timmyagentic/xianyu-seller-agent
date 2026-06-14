import inspect
import json
from pathlib import Path
from typing import Any

from services.delivery.store import DeliveryStore, VALID_DELIVERY_TYPES

from .models import ItemSnapshot, RelistApiResult, RelistDeliveryConfig, RelistRequest, RelistResult
from .playwright_relist import build_playwright_relist_command
from .store import ListingStore


class LocalItemProvider:
    def __init__(self, store: ListingStore):
        self.store = store

    async def get_item(self, item_id: str) -> ItemSnapshot | None:
        return self.store.get_item_snapshot(item_id)


class RelistService:
    def __init__(
        self,
        *,
        listing_store: ListingStore,
        delivery_store: DeliveryStore,
        item_provider=None,
        api_client=None,
        allow_playwright: bool = False,
        relist_executor=None,
    ):
        self.listing_store = listing_store
        self.delivery_store = delivery_store
        self.item_provider = item_provider or LocalItemProvider(listing_store)
        self.api_client = api_client
        self.allow_playwright = allow_playwright
        self.relist_executor = relist_executor

    async def relist(self, request: RelistRequest | dict[str, Any] | str) -> RelistResult:
        request = load_relist_request(request)
        item = await self._get_live_item(request.item_id)
        if not item:
            item = await self._get_item(request.item_id)
        if not item:
            return self._record_result(
                request=request,
                status="item_not_found",
                failed_reason=f"商品 {request.item_id} 不属于当前账号或本地商品快照不存在",
            )

        if request.expected_title and request.expected_title not in item.title:
            return self._record_result(
                request=request,
                status="title_mismatch",
                previous_status=item.status,
                failed_reason=f"商品标题不匹配: expected={request.expected_title}, actual={item.title}",
            )

        if item.status == "active":
            self._bind_delivery(request)
            return self._record_result(
                request=request,
                status="already_active",
                previous_status=item.status,
                final_status="active",
                item_url=item.item_url,
                response_summary="item already active; delivery binding refreshed",
            )

        if self.api_client:
            api_result = await self._call_api(request)
            if api_result.success:
                self._save_relisted_snapshot(item, request, api_result)
                self._bind_delivery(request)
                return self._record_result(
                    request=request,
                    status="relisted",
                    previous_status=item.status,
                    final_status=api_result.final_status or "active",
                    item_url=api_result.item_url,
                    screenshot_path=api_result.screenshot_path,
                    response_summary=api_result.response_summary,
                )

            if self.allow_playwright:
                executor_result = await self._call_relist_executor(request)
                if executor_result:
                    if executor_result.success:
                        self._save_relisted_snapshot(item, request, executor_result)
                        self._bind_delivery(request)
                        return self._record_result(
                            request=request,
                            status="relisted",
                            previous_status=item.status,
                            final_status=executor_result.final_status or "active",
                            item_url=executor_result.item_url,
                            screenshot_path=executor_result.screenshot_path,
                            response_summary=executor_result.response_summary,
                        )
                    return self._record_result(
                        request=request,
                        status="playwright_required",
                        previous_status=item.status,
                        response_summary=executor_result.response_summary,
                        failed_reason=executor_result.failed_reason or "playwright_relist_failed",
                    )
                return self._record_playwright_required(
                    request=request,
                    previous_status=item.status,
                    failed_reason=api_result.failed_reason
                    or "relist API unavailable; authorized Playwright/manual run required",
                )

            return self._record_result(
                request=request,
                status="manual_required",
                previous_status=item.status,
                response_summary=api_result.response_summary,
                failed_reason=api_result.failed_reason or "relist_api_failed",
            )

        if self.allow_playwright:
            executor_result = await self._call_relist_executor(request)
            if executor_result:
                if executor_result.success:
                    self._save_relisted_snapshot(item, request, executor_result)
                    self._bind_delivery(request)
                    return self._record_result(
                        request=request,
                        status="relisted",
                        previous_status=item.status,
                        final_status=executor_result.final_status or "active",
                        item_url=executor_result.item_url,
                        screenshot_path=executor_result.screenshot_path,
                        response_summary=executor_result.response_summary,
                    )
                return self._record_result(
                    request=request,
                    status="playwright_required",
                    previous_status=item.status,
                    response_summary=executor_result.response_summary,
                    failed_reason=executor_result.failed_reason or "playwright_relist_failed",
                )

            command = build_playwright_relist_command(
                item_id=request.item_id,
                expected_title=request.expected_title,
                target_stock=request.target_stock,
            )
            return self._record_result(
                request=request,
                status="playwright_required",
                previous_status=item.status,
                response_summary=json.dumps(command.__dict__, ensure_ascii=False),
                failed_reason="relist API unavailable; authorized Playwright/manual run required",
            )

        return self._record_result(
            request=request,
            status="manual_required",
            previous_status=item.status,
            failed_reason="relist API unavailable; manual verification required",
        )

    async def _get_item(self, item_id: str) -> ItemSnapshot | None:
        result = self.item_provider.get_item(item_id)
        if inspect.isawaitable(result):
            return await result
        return result

    async def _get_live_item(self, item_id: str) -> ItemSnapshot | None:
        if not self.api_client or not hasattr(self.api_client, "get_item_status"):
            return None
        result = self.api_client.get_item_status(item_id)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, dict) or not result.get("success"):
            return None
        live_item = result.get("item")
        if not isinstance(live_item, dict):
            return None
        self.listing_store.save_item_snapshot(live_item)
        return self.listing_store.get_item_snapshot(item_id)

    async def _call_api(self, request: RelistRequest) -> RelistApiResult:
        kwargs: dict[str, Any] = {}
        if request.target_stock is not None:
            try:
                signature = inspect.signature(self.api_client.relist_item)
                parameters = signature.parameters
                accepts_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters.values())
                if accepts_kwargs or "stock" in parameters:
                    kwargs["stock"] = request.target_stock
                elif "target_stock" in parameters:
                    kwargs["target_stock"] = request.target_stock
            except (TypeError, ValueError):
                pass

        result = self.api_client.relist_item(request.item_id, **kwargs)
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, RelistApiResult):
            return result
        return parse_relist_api_response(result)

    async def _call_relist_executor(self, request: RelistRequest) -> RelistApiResult | None:
        if not self.relist_executor:
            return None
        result = self.relist_executor.relist(request)
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, RelistApiResult):
            return result
        if isinstance(result, dict):
            return parse_relist_api_response(result)
        return RelistApiResult(
            success=False,
            response_summary=str(result),
            failed_reason="playwright_relist_failed",
        )

    def _save_relisted_snapshot(
        self,
        item: ItemSnapshot,
        request: RelistRequest,
        api_result: RelistApiResult,
    ) -> None:
        snapshot_data = dict(item.raw or {})
        snapshot_data.update(
            {
                "item_id": request.item_id,
                "itemId": request.item_id,
                "id": request.item_id,
                "title": item.title,
                "status": api_result.final_status or "active",
            }
        )
        if api_result.item_url:
            snapshot_data["item_url"] = api_result.item_url
            snapshot_data["itemUrl"] = api_result.item_url
        self.listing_store.save_item_snapshot(snapshot_data)

    def _record_playwright_required(
        self,
        *,
        request: RelistRequest,
        previous_status: str,
        failed_reason: str,
    ) -> RelistResult:
        command = build_playwright_relist_command(
            item_id=request.item_id,
            expected_title=request.expected_title,
            target_stock=request.target_stock,
        )
        return self._record_result(
            request=request,
            status="playwright_required",
            previous_status=previous_status,
            response_summary=json.dumps(command.__dict__, ensure_ascii=False),
            failed_reason=failed_reason,
        )

    def _bind_delivery(self, request: RelistRequest) -> None:
        if not request.delivery:
            return
        delivery = request.delivery
        self.delivery_store.upsert_config_for_item(
            item_id=request.item_id,
            name=delivery.name or request.item_id,
            delivery_type=delivery.delivery_type,
            content=delivery.content,
            api_config=delivery.api_config,
            enabled=delivery.enabled,
        )

    def _record_result(
        self,
        *,
        request: RelistRequest,
        status: str,
        previous_status: str = "",
        final_status: str = "",
        item_url: str = "",
        screenshot_path: str = "",
        response_summary: str = "",
        failed_reason: str = "",
    ) -> RelistResult:
        job_id = self.listing_store.record_job(
            request=request,
            result_status=status,
            previous_status=previous_status,
            final_status=final_status,
            item_url=item_url,
            screenshot_path=screenshot_path,
            response_summary=response_summary,
            failed_reason=failed_reason,
        )
        return RelistResult(
            status=status,
            item_id=request.item_id,
            job_id=job_id,
            target_stock=request.target_stock,
            previous_status=previous_status,
            final_status=final_status,
            item_url=item_url,
            screenshot_path=screenshot_path,
            response_summary=response_summary,
            failed_reason=failed_reason,
        )


def load_relist_request(value: RelistRequest | dict[str, Any] | str) -> RelistRequest:
    if isinstance(value, RelistRequest):
        return value
    if isinstance(value, str):
        data = json.loads(Path(value).read_text(encoding="utf-8"))
    elif isinstance(value, dict):
        data = value
    else:
        raise ValueError("relist request must be a JSON path or object")

    item_id = str(data.get("item_id") or data.get("itemId") or "").strip()
    if not item_id:
        raise ValueError("item_id is required")

    target_stock = _load_target_stock(data.get("target_stock", data.get("stock")))
    delivery = _load_delivery_config(data.get("delivery"), default_name=item_id)
    return RelistRequest(
        item_id=item_id,
        expected_title=str(data.get("expected_title") or data.get("expectedTitle") or "").strip(),
        target_stock=target_stock,
        delivery=delivery,
    )


def _load_target_stock(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        target_stock = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("stock must be a positive integer") from exc
    if target_stock <= 0:
        raise ValueError("stock must be a positive integer")
    return target_stock


def _load_delivery_config(value: Any, *, default_name: str) -> RelistDeliveryConfig | None:
    if value in (None, ""):
        return None
    if not isinstance(value, dict):
        raise ValueError("delivery must be an object")

    delivery_type = str(value.get("type") or value.get("delivery_type") or "").strip()
    if delivery_type not in VALID_DELIVERY_TYPES:
        raise ValueError(f"delivery.type must be one of {sorted(VALID_DELIVERY_TYPES)}")

    api_config = value.get("api_config")
    if isinstance(api_config, dict):
        api_config = json.dumps(api_config, ensure_ascii=False)
    elif api_config is not None:
        api_config = str(api_config)

    return RelistDeliveryConfig(
        delivery_type=delivery_type,
        content=str(value.get("content") or ""),
        name=str(value.get("name") or default_name),
        api_config=api_config,
        enabled=bool(value.get("enabled", True)),
    )


def parse_relist_api_response(response: dict[str, Any]) -> RelistApiResult:
    ret = response.get("ret", []) if isinstance(response, dict) else []
    data = response.get("data", {}) if isinstance(response, dict) else {}
    summary = json.dumps(response, ensure_ascii=False)[:800]
    if any("SUCCESS" in str(item) for item in ret):
        if data.get("success") is True or data.get("data") is True or data.get("code") == "success":
            return RelistApiResult(
                success=True,
                final_status="active",
                item_url=str(data.get("itemUrl") or data.get("item_url") or ""),
                response_summary=summary,
            )
        return RelistApiResult(
            success=False,
            response_summary=summary,
            failed_reason=str(data.get("msg") or data or "relist_api_failed"),
        )
    return RelistApiResult(
        success=False,
        response_summary=summary,
        failed_reason=map_relist_failure_reason(ret or data or response),
    )


def map_relist_failure_reason(value: object) -> str:
    if isinstance(value, dict):
        text = json.dumps(value, ensure_ascii=False)
    elif isinstance(value, (list, tuple)):
        text = " ".join(str(item) for item in value)
    else:
        text = str(value or "")

    if "FAIL_SYS_TOKEN_EXOIRED" in text or "FAIL_SYS_TOKEN_EXPIRED" in text or "令牌过期" in text:
        return "cookie_expired"
    if "RGV587_ERROR" in text or "滑块" in text or "风控" in text or "被挤爆" in text:
        return "risk_control"
    if "::" in text:
        return text.split("::", 1)[1].strip() or "relist_api_failed"
    return text.strip() or "relist_api_failed"
