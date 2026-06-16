import inspect
from dataclasses import dataclass
from typing import Awaitable, Callable

from .api import ApiDeliveryClient, ApiDeliveryError
from .content import replace_delivery_params
from .models import DeliveryInventoryItem
from .orders import OrderInfo
from .store import DeliveryStore


SendMessage = Callable[..., Awaitable[bool] | bool]
PostDeliveryHook = Callable[[OrderInfo, "DeliveryResult"], Awaitable[None] | None]
ConfirmDelivery = Callable[[OrderInfo], Awaitable[dict] | dict]


@dataclass(frozen=True)
class DeliveryResult:
    status: str
    order_id: str
    message: str = ""
    content: str = ""
    platform_confirm_status: str = ""
    platform_confirm_message: str = ""
    platform_confirm_failed_reason: str = ""


class DeliveryService:
    def __init__(
        self,
        *,
        store: DeliveryStore,
        send_message: SendMessage,
        enabled: bool = False,
        api_client: ApiDeliveryClient | None = None,
        post_delivery_hook: PostDeliveryHook | None = None,
        confirm_delivery: ConfirmDelivery | None = None,
        confirm_delivery_enabled: bool = False,
    ):
        self.store = store
        self.send_message = send_message
        self.enabled = enabled
        self.api_client = api_client or ApiDeliveryClient()
        self.post_delivery_hook = post_delivery_hook
        self.confirm_delivery = confirm_delivery
        self.confirm_delivery_enabled = confirm_delivery_enabled

    async def deliver_order(self, order: OrderInfo) -> DeliveryResult:
        if not self.enabled:
            return DeliveryResult(status="disabled", order_id=order.order_id)
        if self.store.has_sent_order(order.order_id):
            return await self._handle_already_sent_order(order)

        config = self.store.get_enabled_config(order.item_id)
        if not config:
            return DeliveryResult(status="no_config", order_id=order.order_id)

        reserved_rows: list[DeliveryInventoryItem] = []
        if config.delivery_type == "text":
            content = replace_delivery_params(config.content, order.as_params())
        elif config.delivery_type == "data":
            reserved_rows = self.store.reserve_inventory(
                config_id=config.id,
                order_no=order.order_id,
                quantity=order.quantity,
            )
            if len(reserved_rows) < order.quantity:
                return DeliveryResult(
                    status="insufficient_inventory",
                    order_id=order.order_id,
                    message="库存不足",
                )
            content = "\n".join(row.content for row in reserved_rows)
        elif config.delivery_type == "api":
            try:
                content = await self.api_client.fetch_content(config.api_config or config.content, order.as_params())
            except ApiDeliveryError as exc:
                self.store.record_delivery_log(
                    order_no=order.order_id,
                    chat_id=order.chat_id,
                    item_id=order.item_id,
                    buyer_id=order.buyer_id,
                    config_id=config.id,
                    content="",
                    status="failed_retryable",
                    failed_reason=str(exc),
                )
                return DeliveryResult(status="failed_retryable", order_id=order.order_id, message=str(exc))

        try:
            await self._send(order, content)
        except Exception as exc:
            if reserved_rows:
                self.store.mark_inventory_failed([row.id for row in reserved_rows], str(exc))
            self.store.record_delivery_log(
                order_no=order.order_id,
                chat_id=order.chat_id,
                item_id=order.item_id,
                buyer_id=order.buyer_id,
                config_id=config.id,
                content=content,
                status="failed_retryable",
                failed_reason=str(exc),
            )
            return DeliveryResult(
                status="failed_retryable",
                order_id=order.order_id,
                message=str(exc),
                content=content,
            )

        if reserved_rows:
            self.store.mark_inventory_sent([row.id for row in reserved_rows])
        self.store.record_delivery_log(
            order_no=order.order_id,
            chat_id=order.chat_id,
            item_id=order.item_id,
            buyer_id=order.buyer_id,
            config_id=config.id,
            content=content,
            status="sent",
        )
        result = await self._confirm_after_successful_send(order, content=content, config_id=config.id)
        if result.status == "sent":
            await self._run_post_delivery_hook(order, result, config_id=config.id)
        return result

    async def _handle_already_sent_order(self, order: OrderInfo) -> DeliveryResult:
        result = DeliveryResult(status="already_sent", order_id=order.order_id)
        if not self.confirm_delivery_enabled or self.store.has_platform_confirmed_order(order.order_id):
            return result
        confirm_result = await self._confirm_platform_delivery(order)
        self._record_platform_confirm_log(order, config_id=None, content="", confirm_result=confirm_result)
        if confirm_result["success"]:
            return DeliveryResult(
                status="already_sent",
                order_id=order.order_id,
                platform_confirm_status=confirm_result["status"],
                platform_confirm_message=confirm_result["message"],
            )
        return DeliveryResult(
            status="already_sent_confirm_failed",
            order_id=order.order_id,
            message=confirm_result["failed_reason"],
            platform_confirm_status="failed",
            platform_confirm_message=confirm_result["message"],
            platform_confirm_failed_reason=confirm_result["failed_reason"],
        )

    async def _confirm_after_successful_send(
        self,
        order: OrderInfo,
        *,
        content: str,
        config_id: int,
    ) -> DeliveryResult:
        if not self.confirm_delivery_enabled:
            return DeliveryResult(status="sent", order_id=order.order_id, content=content)

        confirm_result = await self._confirm_platform_delivery(order)
        self._record_platform_confirm_log(order, config_id=config_id, content=content, confirm_result=confirm_result)
        if confirm_result["success"]:
            return DeliveryResult(
                status="sent",
                order_id=order.order_id,
                content=content,
                platform_confirm_status=confirm_result["status"],
                platform_confirm_message=confirm_result["message"],
            )
        return DeliveryResult(
            status="sent_confirm_failed",
            order_id=order.order_id,
            message=confirm_result["failed_reason"],
            content=content,
            platform_confirm_status="failed",
            platform_confirm_message=confirm_result["message"],
            platform_confirm_failed_reason=confirm_result["failed_reason"],
        )

    async def _confirm_platform_delivery(self, order: OrderInfo) -> dict:
        if not self.confirm_delivery:
            return {
                "success": False,
                "status": "failed",
                "message": "",
                "failed_reason": "confirm_delivery_not_configured",
            }
        result = self.confirm_delivery(order)
        if inspect.isawaitable(result):
            result = await result
        return self._normalize_confirm_result(result)

    def _normalize_confirm_result(self, result) -> dict:
        if not isinstance(result, dict):
            return {
                "success": False,
                "status": "failed",
                "message": str(result),
                "failed_reason": "confirm_delivery_invalid_response",
            }
        success = bool(result.get("success"))
        already_delivered = bool(result.get("already_delivered"))
        message = str(result.get("message") or result.get("error") or result.get("failed_reason") or "")
        failed_reason = "" if success else str(result.get("error") or result.get("failed_reason") or message or "confirm_delivery_failed")
        return {
            "success": success,
            "status": "already_delivered" if already_delivered else ("confirmed" if success else "failed"),
            "message": message,
            "failed_reason": failed_reason,
        }

    def _record_platform_confirm_log(
        self,
        order: OrderInfo,
        *,
        config_id: int | None,
        content: str,
        confirm_result: dict,
    ) -> None:
        if confirm_result["success"]:
            status = "platform_already_delivered" if confirm_result["status"] == "already_delivered" else "platform_confirmed"
            failed_reason = ""
        else:
            status = "platform_confirm_failed"
            failed_reason = confirm_result["failed_reason"]
        self.store.record_delivery_log(
            order_no=order.order_id,
            chat_id=order.chat_id,
            item_id=order.item_id,
            buyer_id=order.buyer_id,
            config_id=config_id,
            content=content,
            status=status,
            failed_reason=failed_reason,
        )

    async def _run_post_delivery_hook(self, order: OrderInfo, result: DeliveryResult, *, config_id: int | None) -> None:
        if not self.post_delivery_hook:
            return
        try:
            hook_result = self.post_delivery_hook(order, result)
            if inspect.isawaitable(hook_result):
                await hook_result
        except Exception as exc:
            self.store.record_delivery_log(
                order_no=order.order_id,
                chat_id=order.chat_id,
                item_id=order.item_id,
                buyer_id=order.buyer_id,
                config_id=config_id,
                content=result.content,
                status="post_delivery_hook_failed",
                failed_reason=str(exc),
            )

    async def _send(self, order: OrderInfo, content: str) -> None:
        result = self.send_message(
            chat_id=order.chat_id,
            buyer_id=order.buyer_id,
            content=content,
        )
        if inspect.isawaitable(result):
            result = await result
        if result is False:
            raise RuntimeError("send_message returned False")
