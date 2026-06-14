from dataclasses import dataclass


@dataclass(frozen=True)
class OrderInfo:
    order_id: str
    item_id: str
    buyer_id: str
    chat_id: str
    buyer_name: str = ""
    item_title: str = ""
    quantity: int = 1
    spec_name: str = ""
    spec_value: str = ""

    def as_params(self) -> dict[str, object]:
        return {
            "order_id": self.order_id,
            "item_id": self.item_id,
            "buyer_id": self.buyer_id,
            "buyer_name": self.buyer_name,
            "item_title": self.item_title,
            "order_quantity": str(self.quantity),
            "spec_name": self.spec_name,
            "spec_value": self.spec_value,
        }
