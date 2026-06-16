SUPPORTED_VARIABLES = {
    "order_id",
    "item_id",
    "buyer_id",
    "buyer_name",
    "seller_name",
    "item_title",
    "order_quantity",
    "spec_name",
    "spec_value",
}


def replace_delivery_params(content: str, values: dict[str, object]) -> str:
    result = content
    for key in SUPPORTED_VARIABLES:
        placeholder = "{" + key + "}"
        if placeholder in result:
            value = values.get(key, "")
            result = result.replace(placeholder, "" if value is None else str(value))
    return result
