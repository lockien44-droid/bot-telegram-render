"""Admin order search reads the complete sheet, independent of snapshot limits."""
from reliability import serialized

PUBLIC_FIELDS = ("order_id", "user_id", "stock_code", "qty", "total", "status", "created_at", "paid_at", "delivered_at", "tx_id")


@serialized
def search_orders(query="", status="ALL", stock_code="", date_from="", date_to="", page=1, page_size=20):
    import bot_shop as shop
    shop.init_sheets()
    products = {p["stock_code"]: p.get("name", p["stock_code"]) for p in shop.load_products()}
    matched = []
    for raw in shop.get_all_records(shop._ws_orders):
        row = shop.normalize_sheet_row(raw)
        current = row.get("status", "").upper()
        if status == "FAILED" and current not in {"EXPIRED", "CANCELLED"}:
            continue
        if status == "AWAITING_DELIVERY" and current not in {"PAID", "DELIVERY_PENDING"}:
            continue
        if status not in {"ALL", "FAILED", "AWAITING_DELIVERY"} and current != status:
            continue
        if stock_code and row.get("stock_code") != stock_code:
            continue
        day = str(row.get("created_at", ""))[:10]
        if (date_from and day < date_from) or (date_to and (not day or day > date_to)):
            continue
        name = products.get(row.get("stock_code"), row.get("stock_code", ""))
        haystack = " ".join(str(row.get(k, "")) for k in ("order_id", "user_id", "stock_code")) + " " + name
        if query.strip().casefold() not in haystack.casefold():
            continue
        matched.append({**{k: row.get(k, "") for k in PUBLIC_FIELDS}, "product_name": name})
    matched.sort(key=lambda o: (o.get("created_at", ""), o.get("order_id", "")), reverse=True)
    size = max(1, min(page_size, 100))
    total = len(matched)
    pages = max(1, (total + size - 1) // size)
    page = max(1, min(page, pages))
    return {"items": matched[(page - 1) * size:page * size], "total": total, "page": page, "pages": pages, "page_size": size}


@serialized
def order_detail(order_id, reveal=False):
    import bot_shop as shop
    row = shop.get_order_sheet(order_id)
    if not row:
        return None
    result = {k: row.get(k, "") for k in PUBLIC_FIELDS}
    result["has_delivery"] = bool(row.get("deliver_text")) or row.get("status") == "DELIVERED"
    if reveal:
        content = row.get("deliver_text", "")
        if not content or content.startswith("(POOL_"):
            content = "\n".join(shop.get_fulfillment_secrets(order_id))
        result["delivery_text"] = content
    return result


@serialized
def inventory_details():
    import bot_shop as shop
    shop.init_sheets()
    return {"items": shop.get_all_records(shop._ws_pool)}
