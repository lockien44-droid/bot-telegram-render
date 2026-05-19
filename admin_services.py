import logging
import os
import random
import string
from typing import Any, Dict, List, Optional

from gspread.cell import Cell

import bot_shop as shop

logger = logging.getLogger(__name__)


_SECRET_FIELDS = ("secret", "deliver_text")


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    s = str(value)
    if len(s) <= 4:
        return "•" * len(s)
    return f"{s[:2]}{'•' * max(4, len(s) - 4)}{s[-2:]}"


def _redact_rows(rows: List[Dict[str, Any]], fields: tuple = _SECRET_FIELDS) -> List[Dict[str, Any]]:
    out = []
    for row in rows:
        copy = dict(row)
        for field in fields:
            if field in copy and copy[field]:
                copy[field] = _mask_secret(copy[field])
        out.append(copy)
    return out

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


def _revenue_period_stats(orders: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    """Doanh thu theo đơn PAID/DELIVERED — nhóm hôm nay / tháng / năm (timezone shop)."""
    paid_statuses = {"PAID", "DELIVERED"}
    buckets = {
        "today": {"orders": 0, "revenue": 0},
        "month": {"orders": 0, "revenue": 0},
        "year": {"orders": 0, "revenue": 0},
    }
    now = shop.now_dt()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = today_start.replace(day=1)
    year_start = today_start.replace(month=1, day=1)

    for order in orders:
        status = (order.get("status") or "").strip().upper()
        if status not in paid_statuses:
            continue
        total = shop.normalize_int(order.get("total"), 0)
        dt = None
        for key in ("delivered_at", "paid_at", "created_at"):
            dt = shop.parse_dt((order.get(key) or "").strip())
            if dt:
                break
        if not dt:
            continue
        if dt >= today_start:
            buckets["today"]["orders"] += 1
            buckets["today"]["revenue"] += total
        if dt >= month_start:
            buckets["month"]["orders"] += 1
            buckets["month"]["revenue"] += total
        if dt >= year_start:
            buckets["year"]["orders"] += 1
            buckets["year"]["revenue"] += total
    return buckets


def snapshot(limit: int = 100, pool_limit: int = 2000, reveal_secrets: bool = False) -> Dict[str, Any]:
    shop.init_sheets()
    products = shop.load_products()
    pool = _records(shop._ws_pool)
    orders = _records(shop._ws_orders)
    users = _records(shop._ws_users)
    reservations = _records(shop._ws_res)
    fulfillments = _records(shop._ws_ful)

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
        code = shop.normalize_stock_code(item.get("stock_code"))
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
        code = shop.normalize_stock_code(product.get("stock_code", ""))
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

    revenue_stats = _revenue_period_stats(orders)

    pool_out = pool[:pool_limit]
    deliveries_out = delivery_rows[:limit]
    fulfillments_out = fulfillments[:limit]
    if not reveal_secrets:
        pool_out = _redact_rows(pool_out)
        deliveries_out = _redact_rows(deliveries_out)
        fulfillments_out = _redact_rows(fulfillments_out)

    return {
        "generated_at": shop.now_str(),
        "timezone": shop.APP_TIMEZONE,
        "secrets_revealed": bool(reveal_secrets),
        "summary": {
            "orders": len(orders),
            "revenue": revenue_stats["today"]["revenue"],
            "revenue_all": revenue,
            "revenue_stats": revenue_stats,
            "status_counts": status_counts,
            "users": len(users),
            "stock_ready": sum(v.get("READY", 0) for v in stock_counts.values()),
            "stock_held": sum(v.get("HELD", 0) for v in stock_counts.values()),
            "stock_sold": sum(v.get("SOLD", 0) for v in stock_counts.values()),
        },
        "products": product_rows,
        "orders": orders[:limit],
        "users": user_rows[:limit],
        "pool": pool_out,
        "reservations": reservations[:limit],
        "fulfillments": fulfillments_out,
        "deliveries": deliveries_out,
    }


def save_product(data: Dict[str, Any]) -> Dict[str, Any]:
    shop.init_sheets()
    headers = _headers(shop._ws_products)
    if not headers:
        raise RuntimeError("PRODUCTS thieu header")

    product_id = (data.get("product_id") or "").strip()
    stock_code = shop.normalize_stock_code(data.get("stock_code") or "")
    name = (data.get("name") or "").strip()
    if not product_id:
        product_id = stock_code or f"P{shop.now_dt().strftime('%Y%m%d%H%M%S')}"
    if not stock_code or not name:
        raise ValueError("Can co name va stock_code")
    if shop.normalize_int(data.get("price"), 0) <= 0:
        raise ValueError("Gia phai > 0")

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


def delete_product(data: Dict[str, Any]) -> Dict[str, Any]:
    shop.init_sheets()
    headers = _headers(shop._ws_products)
    if not headers:
        raise RuntimeError("PRODUCTS thieu header")

    product_id = (data.get("product_id") or "").strip()
    stock_code = shop.normalize_stock_code(data.get("stock_code") or "")
    if not product_id and not stock_code:
        raise ValueError("Can co product_id hoac stock_code")

    values = shop._ws_products.get_all_values()
    id_col = headers.get("product_id")
    code_col = headers.get("stock_code")
    target_row = None
    matched_id = ""
    for idx, row in enumerate(values[1:], start=2):
        row_id = row[id_col - 1].strip() if id_col and id_col - 1 < len(row) else ""
        row_code = shop.normalize_stock_code(row[code_col - 1]) if code_col and code_col - 1 < len(row) else ""
        if product_id and row_id == product_id:
            target_row = idx
            matched_id = row_id
            break
        if stock_code and row_code == stock_code:
            target_row = idx
            matched_id = row_id or stock_code
            break

    if not target_row:
        raise ValueError("Khong tim thay san pham")

    shop._ws_products.delete_rows(target_row)
    shop._CACHE["products"]["ts"] = 0.0
    return {"ok": True, "product_id": matched_id}


def add_stock(data: Dict[str, Any]) -> Dict[str, Any]:
    shop.init_sheets()
    headers = _headers(shop._ws_pool)
    if not headers:
        raise RuntimeError("POOL thieu header")

    stock_code = shop.normalize_stock_code(data.get("stock_code"))
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
    total_ready = shop.stock_count_ready_by_code().get(stock_code, 0) if rows else 0
    return {"ok": True, "added": len(rows), "stock_code": stock_code, "total_ready": total_ready}


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
    st = (payload.get("status") or "").strip().upper()
    if st in ("PAID", "DELIVERED", "CANCELLED", "EXPIRED"):
        row = shop.get_order_sheet(order_id)
        if row:
            evt_map = {"DELIVERED": "delivered", "CANCELLED": "cancelled", "EXPIRED": "expired", "PAID": "paid"}
            evt = evt_map.get(st)
            if evt:
                try:
                    merged = dict(row)
                    merged["status"] = st
                    shop.append_dashboard_notification_row_sync(evt, merged)
                except Exception:
                    pass
    return {"ok": True, "order_id": order_id, "updates": payload}


def notifications_list(limit: int = 200) -> Dict[str, Any]:
    shop.init_sheets()
    items = shop.list_dashboard_notifications_sync(limit)
    return {"items": items}


def notifications_mark_read(data: Dict[str, Any]) -> Dict[str, Any]:
    mark_all = bool(data.get("all"))
    ids = data.get("ids")
    if not mark_all:
        if not isinstance(ids, list) or not ids:
            raise ValueError("Cần ids (mảng) hoặc all: true")
    n = shop.mark_dashboard_notifications_read_sync(ids if isinstance(ids, list) else None, mark_all)
    return {"updated": n}


def notifications_clear_all() -> Dict[str, Any]:
    n = shop.clear_dashboard_notifications_sync()
    return {"deleted": n}


def run_backup() -> Dict[str, Any]:
    """Backup tất cả worksheet vào thư mục `backups/` (gzip JSON).
    Trả về danh sách file đã backup. Có thể gọi qua cron-job.org để chạy hằng ngày."""
    from backup_manager import BackupManager

    gsheet_id = os.getenv("GSHEET_ID", "").strip()
    if not gsheet_id:
        raise RuntimeError("GSHEET_ID is not configured")
    gsvc_json = os.getenv("GSVC_JSON", "service_account.json")
    backup_dir = os.getenv("BACKUP_DIR", "backups")

    manager = BackupManager(gsheet_id=gsheet_id, gsvc_json=gsvc_json, backup_dir=backup_dir)
    files = manager.backup_all_sheets(compress=True)
    keep_days = int(os.getenv("BACKUP_KEEP_DAYS", "14"))
    try:
        deleted = manager.cleanup_old_backups(keep_days=keep_days)
    except Exception as e:
        logger.warning("backup cleanup failed: %s", e)
        deleted = 0
    return {
        "ok": True,
        "backed_up": [os.path.basename(f) for f in files],
        "count": len(files),
        "cleaned_up": deleted,
        "keep_days": keep_days,
    }
