from dataclasses import dataclass


@dataclass(frozen=True)
class DeliveryConfig:
    id: int
    item_id: str
    name: str
    delivery_type: str
    content: str
    enabled: bool
    api_config: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class DeliveryInventoryItem:
    id: int
    config_id: int
    content: str
    status: str
    reserved_order_no: str | None
    reservation_id: str | None
    reservation_line_no: int | None
    reserved_at: str | None
    sent_at: str | None
    failed_reason: str | None
