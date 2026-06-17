import re
from typing import Any


def format_yuan_price(price: Any) -> str | None:
    if price is None:
        return None
    text = str(price).strip()
    if not text:
        return None
    if text.startswith("¥"):
        return text
    try:
        value = float(text)
    except ValueError:
        return text
    return f"¥{value:g}"


def item_price_display(item_info: dict[str, Any] | None) -> str:
    if not isinstance(item_info, dict):
        return "unknown"

    for key in ("price_text", "priceText"):
        price_text = str(item_info.get(key) or "").strip()
        if price_text:
            return price_text

    detail_params = item_info.get("detail_params")
    sources = [item_info]
    if isinstance(detail_params, dict):
        sources.append(detail_params)

    for source in sources:
        for key in ("soldPrice", "price"):
            display = format_yuan_price(source.get(key))
            if display:
                return display

    return "unknown"


def normalize_stock_quantity(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)

    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        match = re.search(r"\d+", text)
        return int(match.group(0)) if match else None


def collect_stock_values(item_info: dict[str, Any] | None) -> list[int]:
    if not isinstance(item_info, dict):
        return []

    values = []
    if "quantity" in item_info:
        quantity = normalize_stock_quantity(item_info.get("quantity"))
        if quantity is not None:
            values.append(quantity)

    sku_list = item_info.get("skuList") or []
    if isinstance(sku_list, list):
        for sku in sku_list:
            if not isinstance(sku, dict) or "quantity" not in sku:
                continue
            quantity = normalize_stock_quantity(sku.get("quantity"))
            if quantity is not None:
                values.append(quantity)
    return values


def stock_state(item_info: dict[str, Any] | None) -> str:
    values = collect_stock_values(item_info)
    if not values:
        return "unknown"
    if any(value > 0 for value in values):
        return "available"
    return "empty"


def item_is_active(item_info: dict[str, Any] | None) -> bool:
    if not isinstance(item_info, dict):
        return False
    status = str(item_info.get("status") or "").strip().lower()
    status_text = str(
        item_info.get("platform_status_text")
        or item_info.get("statusText")
        or item_info.get("itemStatusText")
        or ""
    ).strip()
    item_status_value = item_info.get("item_status")
    if item_status_value in (None, ""):
        item_status_value = item_info.get("itemStatus")
    item_status = "" if item_status_value is None else str(item_status_value).strip()

    return status == "active" or status_text in {"在售", "出售中", "已上架"} or item_status == "0"


def item_is_available_for_reply(item_info: dict[str, Any] | None) -> bool:
    state = stock_state(item_info)
    if state == "available":
        return True
    if state == "empty":
        return False
    return item_is_active(item_info)


def item_text_for_fact_checks(item_info: dict[str, Any] | None) -> str:
    if not isinstance(item_info, dict):
        return ""
    parts = [
        str(item_info.get("title") or ""),
        str(item_info.get("desc") or ""),
        str(item_info.get("description") or ""),
        str(item_info.get("detail") or ""),
    ]
    detail_params = item_info.get("detail_params")
    if isinstance(detail_params, dict):
        parts.extend(str(value or "") for value in detail_params.values())
    return "\n".join(parts)


def item_mentions_new_user(item_info: dict[str, Any] | None) -> bool:
    text = item_text_for_fact_checks(item_info)
    return any(keyword in text for keyword in ("新用户", "新号", "新账号", "新账户", "新人", "首次"))


def item_mentions_discount(item_info: dict[str, Any] | None) -> bool:
    text = item_text_for_fact_checks(item_info)
    return any(keyword in text for keyword in ("优惠", "折扣", "减免", "赠品", "券", "特价"))


def asks_availability(user_msg: str | None) -> bool:
    text = re.sub(r"\s+", "", user_msg or "")
    return any(
        keyword in text
        for keyword in (
            "还有不",
            "还有吗",
            "还有货",
            "有货",
            "能拍",
            "可以拍",
            "能下单",
            "还在吗",
            "现货",
            "有吗",
        )
    )


def asks_new_account(user_msg: str | None) -> bool:
    text = re.sub(r"\s+", "", user_msg or "")
    return any(keyword in text for keyword in ("新号", "新用户", "新账号", "新账户", "刚注册", "刚刚注册", "新人"))


def reply_claims_unavailable(reply: str | None) -> bool:
    return any(keyword in (reply or "") for keyword in ("没货", "缺货", "无货", "售罄", "卖完", "补货"))


def reply_claims_discount(reply: str | None) -> bool:
    return any(keyword in (reply or "") for keyword in ("优惠", "折扣", "减免", "赠品", "券", "特价"))
