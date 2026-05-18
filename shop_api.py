"""REST API cho bot shop (products, orders, users)."""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import bot_shop as shop

router = APIRouter(prefix="/api", tags=["shop"])


class CreateOrderBody(BaseModel):
    user_id: int
    stock_code: str
    qty: int = Field(ge=1)


class UserBody(BaseModel):
    chat_id: int
    username: str = ""
    full_name: str = ""


@router.get("/products")
def api_products() -> Dict[str, Any]:
    shop.init_sheets()
    return {
        "products": shop.load_products(),
        "stock": shop.stock_count_ready_by_code(),
    }


@router.post("/orders")
def api_create_order(body: CreateOrderBody) -> Dict[str, Any]:
    shop.init_sheets()
    product = next(
        (p for p in shop.load_products() if p.get("stock_code") == body.stock_code),
        None,
    )
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    ready = shop.stock_count_ready_by_code().get(body.stock_code, 0)
    if body.qty > ready:
        raise HTTPException(status_code=400, detail="Insufficient stock")

    order_id = shop.generate_order_id()
    total = int(product["price"]) * body.qty
    created_at = shop.now_str()

    reserved = shop.reserve_items_from_pool(
        body.stock_code, body.qty, order_id, shop.ORDER_TTL_SECONDS
    )
    if len(reserved) < body.qty:
        raise HTTPException(status_code=400, detail="Cannot reserve stock")

    shop.append_order({
        "order_id": order_id,
        "user_id": body.user_id,
        "stock_code": body.stock_code,
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

    shop.append_dashboard_notification_row_sync(
        "new",
        {
            "order_id": order_id,
            "user_id": str(body.user_id),
            "stock_code": body.stock_code,
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
            "stock_code": body.stock_code,
            "qty": body.qty,
            "total": total,
            "status": "PENDING",
            "created_at": created_at,
        },
    }


@router.get("/orders/{order_id}")
def api_get_order(order_id: str) -> Dict[str, Any]:
    shop.init_sheets()
    order = shop.get_order_sheet(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    order.pop("_rownum", None)
    return {"order": order}


@router.patch("/orders/{order_id}")
def api_patch_order(order_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    shop.init_sheets()
    if not shop.get_order_sheet(order_id):
        raise HTTPException(status_code=404, detail="Order not found")
    shop.set_order_fields_sheet(order_id, updates)
    return {"ok": True}


@router.post("/orders/{order_id}/cancel")
def api_cancel_order(order_id: str) -> Dict[str, Any]:
    shop.init_sheets()
    released = shop.release_hold_by_order_sheet(order_id, "CANCELLED")
    return {"ok": True, "released": released}


@router.post("/users")
def api_upsert_user(body: UserBody) -> Dict[str, Any]:
    shop.init_sheets()
    shop.upsert_user_sheet(body.chat_id, body.username, body.full_name)
    return {"ok": True}


@router.get("/users/{user_id}/orders")
def api_user_orders(user_id: int, limit: int = 10) -> Dict[str, Any]:
    shop.init_sheets()
    orders = shop.list_user_orders_sheet(user_id, max(limit, 10))
    return {"orders": orders}


def register_shop_api_routes(app) -> None:
    app.include_router(router)
