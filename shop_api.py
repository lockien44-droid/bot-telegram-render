"""REST API cho bot shop (products, orders, users).

Auth: nếu env `SHOP_API_KEY` được set thì mọi mutating route phải gửi header
`x-api-key` đúng giá trị (so sánh bằng `secrets.compare_digest`).
Nếu `SHOP_API_KEY` rỗng thì các route mutating bị từ chối (fail-closed) trừ
khi `SHOP_API_ALLOW_ANON=1` được bật ở môi trường dev.
"""

import os
import secrets
from typing import Any, Dict

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

import bot_shop as shop

router = APIRouter(prefix="/api", tags=["shop"])


# ---- Auth helpers --------------------------------------------------------

_ALLOWED_ORDER_PATCH_FIELDS = {
    "status",
    "tx_id",
    "paid_at",
    "delivered_at",
    "deliver_text",
    "qr_msg_id",
}


def _api_key_required() -> str:
    return os.environ.get("SHOP_API_KEY", "").strip()


def _allow_anonymous_writes() -> bool:
    return os.environ.get("SHOP_API_ALLOW_ANON", "").strip() == "1"


def require_api_key(x_api_key: str = Header(default="", alias="x-api-key")) -> None:
    expected = _api_key_required()
    if not expected:
        if _allow_anonymous_writes():
            return
        raise HTTPException(
            status_code=503,
            detail="SHOP_API_KEY chưa được cấu hình. Đặt env SHOP_API_KEY hoặc bật SHOP_API_ALLOW_ANON=1 cho dev.",
        )
    provided = (x_api_key or "").strip()
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


# ---- Schemas -------------------------------------------------------------

class CreateOrderBody(BaseModel):
    user_id: int
    stock_code: str
    qty: int = Field(ge=1, le=20)


class UserBody(BaseModel):
    chat_id: int
    username: str = ""
    full_name: str = ""


# ---- Public read endpoints (catalog) -------------------------------------

@router.get("/products")
def api_products() -> Dict[str, Any]:
    shop.init_sheets()
    return {
        "products": shop.load_products(),
        "stock": shop.stock_count_ready_by_code(),
    }


# ---- Mutating endpoints (require API key) --------------------------------

@router.post("/orders", dependencies=[Depends(require_api_key)])
def api_create_order(body: CreateOrderBody) -> Dict[str, Any]:
    shop.init_sheets()
    stock_code = shop.normalize_stock_code(body.stock_code)
    product = next(
        (p for p in shop.load_products() if p.get("stock_code") == stock_code),
        None,
    )
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    ready = shop.stock_count_ready_by_code().get(stock_code, 0)
    if body.qty > ready:
        raise HTTPException(status_code=400, detail="Insufficient stock")

    order_id = shop.generate_order_id()
    total = int(product["price"]) * body.qty
    created_at = shop.now_str()

    reserved = shop.reserve_items_from_pool(
        stock_code, body.qty, order_id, shop.ORDER_TTL_SECONDS
    )
    if len(reserved) < body.qty:
        raise HTTPException(status_code=400, detail="Cannot reserve stock")

    try:
        shop.append_order({
            "order_id": order_id,
            "user_id": body.user_id,
            "stock_code": stock_code,
            "qty": body.qty,
            "total": total,
            "status": "PENDING",
            "qr_msg_id": "",
            "paid_at": "",
            "tx_id": "",
            "delivered_at": "",
            "deliver_text": "",
            "created_at": created_at,
        })
    except Exception:
        # Đền bù: trả lại các item đã giữ để khỏi sót HELD mồ côi
        try:
            shop.release_hold_by_order_sheet(order_id, "ROLLBACK")
        except Exception:
            pass
        raise

    shop.append_dashboard_notification_row_sync(
        "new",
        {
            "order_id": order_id,
            "user_id": str(body.user_id),
            "stock_code": stock_code,
            "qty": body.qty,
            "total": total,
            "status": "PENDING",
            "created_at": created_at,
        },
    )

    return {
        "ok": True,
        "order": {
            "order_id": order_id,
            "user_id": str(body.user_id),
            "stock_code": stock_code,
            "qty": body.qty,
            "total": total,
            "status": "PENDING",
            "created_at": created_at,
        },
    }


@router.get("/orders/{order_id}", dependencies=[Depends(require_api_key)])
def api_get_order(order_id: str) -> Dict[str, Any]:
    shop.init_sheets()
    order = shop.get_order_sheet(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    order.pop("_rownum", None)
    return {"order": order}


@router.patch("/orders/{order_id}", dependencies=[Depends(require_api_key)])
def api_patch_order(order_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    shop.init_sheets()
    if not shop.get_order_sheet(order_id):
        raise HTTPException(status_code=404, detail="Order not found")
    safe = {k: v for k, v in (updates or {}).items() if k in _ALLOWED_ORDER_PATCH_FIELDS}
    if not safe:
        raise HTTPException(
            status_code=400,
            detail=f"No allowed fields. Allowed: {sorted(_ALLOWED_ORDER_PATCH_FIELDS)}",
        )
    if "status" in safe:
        safe["status"] = str(safe["status"]).strip().upper()
    shop.set_order_fields_sheet(order_id, safe)
    return {"ok": True, "updated": list(safe.keys())}


@router.post("/orders/{order_id}/cancel", dependencies=[Depends(require_api_key)])
def api_cancel_order(order_id: str) -> Dict[str, Any]:
    shop.init_sheets()
    released = shop.release_hold_by_order_sheet(order_id, "CANCELLED")
    return {"ok": True, "released": released}


@router.post("/users", dependencies=[Depends(require_api_key)])
def api_upsert_user(body: UserBody) -> Dict[str, Any]:
    shop.init_sheets()
    shop.upsert_user_sheet(body.chat_id, body.username, body.full_name)
    return {"ok": True}


@router.get("/users/{user_id}/orders", dependencies=[Depends(require_api_key)])
def api_user_orders(user_id: int, limit: int = 10) -> Dict[str, Any]:
    shop.init_sheets()
    capped = max(1, min(int(limit or 10), 50))
    orders = shop.list_user_orders_sheet(user_id, capped)
    return {"orders": orders}


def register_shop_api_routes(app) -> None:
    app.include_router(router)
