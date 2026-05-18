import random
import string
from typing import Any, Dict, List

from gspread.cell import Cell

import bot_shop as shop

MATERIALS_TAB = "MATERIALS"
MATERIALS_HEADERS = ["id", "value", "status", "note", "created_at", "updated_at"]


def _records(ws) -> List[Dict[str, str]]:
    return shop.get_all_records(ws) if ws else []


def _headers(ws) -> Dict[str, int]:
    return shop.headers_map(ws) if ws else {}


def _row_from_headers(headers: Dict[str, int], data: Dict[str, Any]) -> List[str]:
    row = [""] * len(headers)
    for key, value in data.items():
        col = headers.get(key.lower())
        if col:
            row[col - 1] = "" if value is None else str(value)
    return row


def _make_item_id(stock_code: str) -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"{stock_code.strip().upper()}-{shop.now_dt().strftime('%Y%m%d%H%M%S')}-{suffix}"


def _materials_ws():
    shop.init_sheets()
    try:
        ws = shop._gs_sheet.worksheet(MATERIALS_TAB)
    except Exception:
        ws = shop._gs_sheet.add_worksheet(title=MATERIALS_TAB, rows=1000, cols=len(MATERIALS_HEADERS))
        ws.update("A1:F1", [MATERIALS_HEADERS], value_input_option="USER_ENTERED")
        return ws

    headers = [str(h).strip().lower() for h in ws.row_values(1)]
    if headers != MATERIALS_HEADERS:
        ws.update("A1:F1", [MATERIALS_HEADERS], value_input_option="USER_ENTERED")
    return ws


def load_materials() -> List[Dict[str, str]]:
    rows = _records(_materials_ws())
    rows.sort(key=lambda x: x.get("updated_at") or x.get("created_at") or "", reverse=True)
    return rows


def save_materials(data: Dict[str, Any]) -> Dict[str, Any]:
    ws = _materials_ws()
    raw_items = data.get("items") or []
    if not isinstance(raw_items, list):
        raise ValueError("items must be a list")
    force_clear = bool(data.get("force_clear"))
    existing_items = _records(ws)

    now = shop.now_str()
    rows = [MATERIALS_HEADERS]
    seen = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        value = str(raw.get("value") or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        status = str(raw.get("status") or "NEW").strip().upper()
        if status not in ("NEW", "OK", "BAD"):
            status = "NEW"
        item_id = str(raw.get("id") or "").strip() or f"MAT-{shop.now_dt().strftime('%Y%m%d%H%M%S')}-{len(rows)}"
        rows.append([
            item_id,
            value,
            status,
            str(raw.get("note") or ""),
            str(raw.get("created_at") or now),
            now,
        ])

    if len(rows) == 1 and existing_items and not force_clear:
        return {"ok": True, "saved": len(existing_items), "items": load_materials(), "skipped_empty_save": True}

    ws.clear()
    ws.update(f"A1:F{len(rows)}", rows, value_input_option="USER_ENTERED")
    return {"ok": True, "saved": len(rows) - 1, "items": load_materials()}


def snapshot(limit: int = 100, pool_limit: int = 2000) -> Dict[str, Any]:
    shop.init_sheets()
    products = shop.load_products()
    pool = _records(shop._ws_pool)
    orders = _records(shop._ws_orders)
    users = _records(shop._ws_users)
    reservations = _records(shop._ws_res)
    fulfillments = _records(shop._ws_ful)
    materials = load_materials()

    orders.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    limit = max(1, min(int(limit or 100), 300))
    pool_limit = max(1, min(int(pool_limit or 2000), 30000))

    status_counts: Dict[str, int] = {}
    revenue = 0
    user_stats: Dict[str, Dict[str, int]] = {}
    for order in orders:
        status = (order.get("status") or "UNKNOWN").strip().upper()
        uid = (order.get("user_id") or "").strip()
        total = shop.normalize_int(order.get("total"), 0)
        status_counts[status] = status_counts.get(status, 0) + 1
        if status in ("PAID", "DELIVERED"):
            revenue += total
            if uid:
                user_stats.setdefault(uid, {"orders": 0, "spent": 0})
                user_stats[uid]["orders"] += 1
                user_stats[uid]["spent"] += total

    stock_counts: Dict[str, Dict[str, int]] = {}
    for item in pool:
        code = (item.get("stock_code") or "").strip()
        status = (item.get("status") or "UNKNOWN").strip().upper()
        if not code:
            continue
        stock_counts.setdefault(code, {"READY": 0, "HELD": 0, "SOLD": 0, "OTHER": 0})
        if status in stock_counts[code]:
            stock_counts[code][status] += 1
        else:
            stock_counts[code]["OTHER"] += 1

    product_rows = []
    for product in products:
        code = product.get("stock_code", "")
        counts = stock_counts.get(code, {"READY": 0, "HELD": 0, "SOLD": 0, "OTHER": 0})
        product_rows.append({
            "product_id": product.get("product_id", ""),
            "name": product.get("name", ""),
            "stock_code": code,
            "price": product.get("price", 0),
            "description": product.get("description", ""),
            **counts,
        })

    user_rows = []
    for user in users:
        uid = (user.get("chat_id") or user.get("user_id") or "").strip()
        stats = user_stats.get(uid, {"orders": 0, "spent": 0})
        row = dict(user)
        row["orders"] = stats["orders"]
        row["spent"] = stats["spent"]
        user_rows.append(row)
    user_rows.sort(key=lambda x: x.get("updated_at", ""), reverse=True)

    delivery_rows = []
    seen_delivery_orders = set()
    for row in fulfillments:
        delivery_rows.append(dict(row))
        oid = (row.get("order_id") or "").strip()
        if oid:
            seen_delivery_orders.add(oid)

    for order in orders:
        oid = (order.get("order_id") or "").strip()
        status = (order.get("status") or "").strip().upper()
        if not oid or oid in seen_delivery_orders or status != "DELIVERED":
            continue
        delivery_rows.append({
            "order_id": oid,
            "item_id": "",
            "stock_code": order.get("stock_code", ""),
            "secret": order.get("deliver_text", ""),
            "delivered_at": order.get("delivered_at", ""),
            "user_id": order.get("user_id", ""),
            "qty": order.get("qty", ""),
        })

    delivery_rows.sort(key=lambda x: x.get("delivered_at", ""), reverse=True)

    return {
        "generated_at": shop.now_str(),
        "timezone": shop.APP_TIMEZONE,
        "summary": {
            "orders": len(orders),
            "revenue": revenue,
            "status_counts": status_counts,
            "users": len(users),
            "stock_ready": sum(v.get("READY", 0) for v in stock_counts.values()),
            "stock_held": sum(v.get("HELD", 0) for v in stock_counts.values()),
            "stock_sold": sum(v.get("SOLD", 0) for v in stock_counts.values()),
        },
        "products": product_rows,
        "orders": orders[:limit],
        "users": user_rows[:limit],
        "pool": pool[:pool_limit],
        "reservations": reservations[:limit],
        "fulfillments": fulfillments[:limit],
        "deliveries": delivery_rows[:limit],
        "materials": materials[:pool_limit],
    }


def save_product(data: Dict[str, Any]) -> Dict[str, Any]:
    shop.init_sheets()
    headers = _headers(shop._ws_products)
    if not headers:
        raise RuntimeError("PRODUCTS thieu header")

    product_id = (data.get("product_id") or "").strip()
    stock_code = (data.get("stock_code") or "").strip()
    name = (data.get("name") or "").strip()
    if not product_id:
        product_id = stock_code or f"P{shop.now_dt().strftime('%Y%m%d%H%M%S')}"
    if not stock_code or not name:
        raise ValueError("Can co name va stock_code")

    payload = {
        "product_id": product_id,
        "name": name,
        "stock_code": stock_code,
        "price": shop.normalize_int(data.get("price"), 0),
        "description": data.get("description", ""),
    }

    values = shop._ws_products.get_all_values()
    id_col = headers.get("product_id")
    target_row = None
    if id_col:
        for idx, row in enumerate(values[1:], start=2):
            if id_col - 1 < len(row) and row[id_col - 1].strip() == product_id:
                target_row = idx
                break

    if target_row:
        cells = []
        for key, value in payload.items():
            col = headers.get(key.lower())
            if col:
                cells.append(Cell(target_row, col, str(value)))
        if cells:
            shop._ws_products.update_cells(cells, value_input_option="USER_ENTERED")
    else:
        shop._ws_products.append_row(_row_from_headers(headers, payload), value_input_option="USER_ENTERED")

    shop._CACHE["products"]["ts"] = 0.0
    return {"ok": True, "product_id": product_id}


def add_stock(data: Dict[str, Any]) -> Dict[str, Any]:
    shop.init_sheets()
    headers = _headers(shop._ws_pool)
    if not headers:
        raise RuntimeError("POOL thieu header")

    stock_code = (data.get("stock_code") or "").strip()
    raw_items = (data.get("items") or data.get("secret") or "").strip()
    if not stock_code or not raw_items:
        raise ValueError("Can co stock_code va items")

    secrets = [line.strip() for line in raw_items.splitlines() if line.strip()]
    rows = []
    for secret in secrets:
        rows.append(_row_from_headers(headers, {
            "item_id": _make_item_id(stock_code),
            "stock_code": stock_code,
            "secret": secret,
            "status": "READY",
            "hold_order_id": "",
            "hold_at": "",
            "hold_expires_at": "",
            "sold_order_id": "",
            "sold_at": "",
        }))
    if rows:
        shop._ws_pool.append_rows(rows, value_input_option="USER_ENTERED")
        shop.invalidate_stock_cache()
    return {"ok": True, "added": len(rows)}


def release_order(order_id: str, status: str = "EXPIRED") -> Dict[str, Any]:
    if not order_id:
        raise ValueError("Missing order_id")
    released = shop.release_hold_by_order_sheet(order_id, status or "EXPIRED")
    return {"ok": True, "released": released}


def _is_expired_hold(value: str) -> bool:
    dt = shop.parse_dt(value)
    return bool(dt and dt <= shop.now_dt())


def release_holds(expired_only: bool = True, status: str = "EXPIRED") -> Dict[str, Any]:
    shop.init_sheets()
    headers = _headers(shop._ws_pool)
    if not headers:
        raise RuntimeError("POOL thieu header")

    c_status = headers.get("status")
    c_hold_oid = headers.get("hold_order_id")
    c_hold_exp = headers.get("hold_expires_at")
    if not c_status:
        raise RuntimeError("POOL thieu cot status")
    if expired_only and not c_hold_exp:
        raise RuntimeError("POOL thieu cot hold_expires_at")

    values = shop._ws_pool.get_all_values()
    order_ids: set[str] = set()
    orphan_cells: List[Cell] = []
    orphan_released = 0

    for idx, row in enumerate(values[1:], start=2):
        current_status = row[c_status - 1].strip().upper() if c_status - 1 < len(row) else ""
        if current_status != "HELD":
            continue

        expires_at = row[c_hold_exp - 1].strip() if c_hold_exp and c_hold_exp - 1 < len(row) else ""
        if expired_only and not _is_expired_hold(expires_at):
            continue

        order_id = row[c_hold_oid - 1].strip() if c_hold_oid and c_hold_oid - 1 < len(row) else ""
        if order_id:
            order_ids.add(order_id)
            continue

        orphan_cells.append(Cell(idx, c_status, "READY"))
        for key in ("hold_order_id", "hold_at", "hold_expires_at"):
            col = headers.get(key)
            if col:
                orphan_cells.append(Cell(idx, col, ""))
        orphan_released += 1

    released = orphan_released
    for order_id in sorted(order_ids):
        released += shop.release_hold_by_order_sheet(order_id, status or "EXPIRED")

    if orphan_cells:
        shop._ws_pool.update_cells(orphan_cells, value_input_option="USER_ENTERED")

    if released:
        shop.invalidate_stock_cache()

    return {
        "ok": True,
        "expired_only": expired_only,
        "orders": len(order_ids),
        "released": released,
        "orphan_released": orphan_released,
    }


def update_order(order_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    if not order_id:
        raise ValueError("Missing order_id")
    allowed = {"status", "tx_id", "paid_at", "delivered_at", "deliver_text"}
    payload = {k: v for k, v in updates.items() if k in allowed}
    if not payload:
        raise ValueError("No allowed updates")
    shop.set_order_fields_sheet(order_id, payload)
    return {"ok": True, "order_id": order_id, "updates": payload}
