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


@dataclass(frozen=True)
class OrderDetail:
    spec_name: str = ""
    spec_value: str = ""
    quantity: int = 1
    amount: str = ""
    receiver_name: str = ""
    receiver_phone: str = ""
    receiver_address: str = ""


def parse_order_detail_response(response: dict) -> OrderDetail:
    result = {
        "spec_name": "",
        "spec_value": "",
        "quantity": 1,
        "amount": "",
        "receiver_name": "",
        "receiver_phone": "",
        "receiver_address": "",
    }
    for component in response.get("data", {}).get("components", []):
        render_type = component.get("render", "")
        data = component.get("data", {})
        if render_type == "orderInfoVO":
            item_info = data.get("itemInfo", {})
            result["quantity"] = int(item_info.get("buyAmount") or 1)
            result["amount"] = str(item_info.get("price") or "")
            sku_info = item_info.get("skuInfo") or ""
            if ":" in sku_info:
                spec_name, spec_value = sku_info.split(":", 1)
                result["spec_name"] = spec_name.strip()
                result["spec_value"] = spec_value.strip()
        elif render_type == "addressInfoVO":
            result["receiver_name"] = data.get("name", "") or ""
            result["receiver_phone"] = data.get("phoneNumber", "") or ""
            result["receiver_address"] = data.get("address", "") or ""
    return OrderDetail(**result)


def is_token_expired_ret(ret: list) -> bool:
    ret_str = str(ret)
    return (
        "FAIL_SYS_TOKEN_EXOIRED" in ret_str
        or "FAIL_SYS_TOKEN_EXPIRED" in ret_str
        or "令牌过期" in ret_str
    )


def is_session_expired_ret(ret: list) -> bool:
    ret_str = str(ret)
    return "FAIL_SYS_SESSION_EXPIRED" in ret_str or "Session过期" in ret_str
