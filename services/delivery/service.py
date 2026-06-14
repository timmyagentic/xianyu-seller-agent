import inspect
from dataclasses import dataclass
from typing import Awaitable, Callable

from .api import ApiDeliveryClient, ApiDeliveryError
from .content import replace_delivery_params
from .models import DeliveryInventoryItem
from .orders import OrderInfo
from .store import DeliveryStore


SendMessage = Callable[..., Awaitable[bool] | bool]


@dataclass(frozen=True)
class DeliveryResult:
    status: str
    order_id: str
    message: str = ""
    content: str = ""


class DeliveryService:
    def __init__(
        self,
        *,
        store: DeliveryStore,
        send_message: SendMessage,
        enabled: bool = False,
        api_client: ApiDeliveryClient | None = None,
    ):
        self.store = store
        self.send_message = send_message
        self.enabled = enabled
        self.api_client = api_client or ApiDeliveryClient()

    async def deliver_order(self, order: OrderInfo) -> DeliveryResult:
        if not self.enabled:
            return DeliveryResult(status="disabled", order_id=order.order_id)
        if self.store.has_sent_order(order.order_id):
            return DeliveryResult(status="already_sent", order_id=order.order_id)

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
        return DeliveryResult(status="sent", order_id=order.order_id, content=content)

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
