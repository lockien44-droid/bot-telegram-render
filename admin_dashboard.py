import asyncio
import logging
import os
import secrets
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from admin_services import (
    add_stock,
    delete_product,
    notifications_clear_all,
    notifications_list,
    notifications_mark_read,
    release_holds,
    release_order,
    run_backup,
    save_product,
    snapshot,
    update_order,
)
from sepay_webhook import process_payment

logger = logging.getLogger(__name__)


ADMIN_HTML = """<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>VM STORE</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f7fb;
      --panel: #ffffff;
      --panel-soft: #f8fafc;
      --line: #dfe4ea;
      --line-strong: #cfd7e2;
      --text: #101828;
      --muted: #667085;
      --accent: #0f9f6e;
      --accent-soft: #e8f8f1;
      --blue: #2563eb;
      --blue-soft: #eef4ff;
      --warn: #f59e0b;
      --warn-soft: #fff7e6;
      --bad: #e11d48;
      --bad-soft: #fff1f3;
      --shadow: 0 10px 28px rgba(16, 24, 40, 0.08);
      --radius: 8px;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
      font-size: 14px;
    }
    header {
      background: rgba(255,255,255,.92);
      border-bottom: 1px solid var(--line);
      position: sticky;
      top: 0;
      z-index: 10;
      backdrop-filter: blur(12px);
    }
    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      max-width: 1420px;
      margin: 0 auto;
      padding: 16px 18px;
    }
    .brand h1 { margin: 0; font-size: 22px; letter-spacing: 0; }
    .brand .sub { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .toolbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }
    input, textarea, select, button {
      border: 1px solid var(--line-strong);
      border-radius: 7px;
      padding: 10px 11px;
      background: #fff;
      color: var(--text);
      font: inherit;
      min-height: 40px;
    }
    input:focus, textarea:focus, select:focus {
      outline: 2px solid rgba(15,159,110,.18);
      border-color: var(--accent);
    }
    textarea { min-height: 118px; width: 100%; resize: vertical; line-height: 1.45; }
    button {
      cursor: pointer;
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
      font-weight: 700;
      white-space: nowrap;
    }
    button.secondary { background: #fff; color: var(--text); border-color: var(--line-strong); }
    button.danger { background: var(--bad); border-color: var(--bad); }
    main { padding: 18px; max-width: 1420px; margin: auto; }
    .msg {
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      min-height: 24px;
      margin: 6px 0 14px;
    }
    .tabs {
      display: flex;
      gap: 8px;
      overflow-x: auto;
      padding: 0 0 8px;
      margin: 0 0 12px;
      scrollbar-width: thin;
    }
    .tab {
      background: #fff;
      border-color: var(--line);
      color: var(--muted);
      flex: 0 0 auto;
    }
    .tab.active {
      background: var(--text);
      border-color: var(--text);
      color: #fff;
    }
    .panel { display: none; }
    .panel.active { display: block; }
    .grid {
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }
    .card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 15px;
      min-height: 96px;
      box-shadow: var(--shadow);
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }
    .label { color: #475467; font-size: 12px; font-weight: 700; text-transform: uppercase; }
    .value { font-size: 25px; margin-top: 12px; font-weight: 800; letter-spacing: 0; }
    .blue { color: var(--blue); }
    .green { color: var(--accent); }
    .orange { color: #d97706; }
    .red { color: var(--bad); }
    .section-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin: 18px 0 10px;
    }
    h2 { margin: 0; font-size: 18px; }
    .panel-card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      padding: 14px;
      margin-bottom: 14px;
    }
    .form {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
    }
    .form .wide { grid-column: span 2; }
    .form .full { grid-column: 1 / -1; }
    .scroll {
      max-height: 580px;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: #fff;
    }
    table { width: 100%; border-collapse: collapse; background: #fff; min-width: 880px; }
    th, td {
      border-bottom: 1px solid var(--line);
      padding: 10px 9px;
      text-align: left;
      font-size: 13px;
      vertical-align: top;
      line-height: 1.35;
    }
    th {
      position: sticky;
      top: 0;
      background: var(--panel-soft);
      z-index: 2;
      color: #344054;
      font-size: 12px;
      text-transform: uppercase;
    }
    tr:hover td { background: #fbfdff; }
    .pill {
      display: inline-flex;
      align-items: center;
      min-height: 22px;
      padding: 3px 8px;
      border-radius: 999px;
      background: #eef2f7;
      color: #344054;
      font-weight: 800;
      font-size: 12px;
      white-space: nowrap;
    }
    .READY, .DELIVERED, .PAID { background: var(--accent-soft); color: #08734f; }
    .HELD, .PENDING { background: var(--warn-soft); color: #a15c00; }
    .SOLD { background: var(--blue-soft); color: #1849a9; }
    .CANCELLED, .EXPIRED { background: var(--bad-soft); color: var(--bad); }
    .muted { color: var(--muted); }
    .mobile-cards { display: none; }
    .mobile-card {
      background: #fff;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      padding: 12px;
      margin-bottom: 10px;
    }
    .mobile-card .row { display: flex; justify-content: space-between; gap: 10px; padding: 5px 0; border-bottom: 1px solid #f0f2f5; }
    .mobile-card .row:last-child { border-bottom: 0; }
    .mobile-card .k { color: var(--muted); font-size: 12px; }
    .mobile-card .v { text-align: right; font-weight: 700; word-break: break-word; }
    @media (max-width: 1100px) { .grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
    @media (max-width: 760px) {
      .topbar { align-items: stretch; flex-direction: column; padding: 13px; }
      .toolbar { justify-content: stretch; }
      .toolbar input { flex: 1 1 180px; min-width: 0; }
      .toolbar button { flex: 1 0 auto; }
      main { padding: 12px; }
      .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; }
      .card { min-height: 86px; padding: 12px; }
      .value { font-size: 21px; }
      .form { grid-template-columns: 1fr; }
      .form .wide { grid-column: auto; }
      .desktop-table.mobile-switch { display: none; }
      .mobile-cards { display: block; }
      .section-head { align-items: flex-start; flex-direction: column; }
    }
  </style>
</head>
<body>
  <header>
    <div class="topbar">
      <div class="brand">
        <h1>VM STORE</h1>
        <div class="sub">bot-telegram-1-mgsf.onrender.com</div>
      </div>
      <div class="toolbar">
        <input id="key" placeholder="ADMIN_PASSWORD" type="password" />
        <button onclick="loadData()">Lam moi</button>
      </div>
    </div>
  </header>
  <main>
    <div id="message" class="msg">Nhap ADMIN_PASSWORD roi bam Lam moi.</div>
    <div class="tabs">
      <button class="tab active" onclick="showTab('dashboard', this)">Tong quan</button>
      <button class="tab" onclick="showTab('products', this)">San pham</button>
      <button class="tab" onclick="showTab('stock', this)">Kho</button>
      <button class="tab" onclick="showTab('orders', this)">Don hang</button>
      <button class="tab" onclick="showTab('users', this)">Khach hang</button>
      <button class="tab" onclick="showTab('reservations', this)">Lich su</button>
    </div>

    <section id="dashboard" class="panel active">
      <div class="grid" id="summary"></div>
      <div class="section-head"><h2>San pham dang ban</h2><span class="muted">Cham vao san pham de sua nhanh</span></div>
      <div class="scroll desktop-table mobile-switch"><table id="productsTableDash"></table></div>
      <div class="mobile-cards" id="productsCardsDash"></div>
      <div class="section-head"><h2>Don hang moi nhat</h2><span class="muted">150 dong gan nhat</span></div>
      <div class="scroll desktop-table mobile-switch"><table id="ordersTableDash"></table></div>
      <div class="mobile-cards" id="ordersCardsDash"></div>
    </section>

    <section id="products" class="panel">
      <div class="section-head"><h2>Them / sua san pham</h2></div>
      <div class="panel-card form">
        <input id="p_product_id" placeholder="product_id (bo trong se tu tao)" />
        <input id="p_name" placeholder="Ten san pham" />
        <input id="p_stock_code" placeholder="stock_code" />
        <input id="p_price" placeholder="Gia" type="number" />
        <textarea class="full" id="p_description" placeholder="Mo ta"></textarea>
        <button onclick="saveProduct()">Luu san pham</button>
      </div>
      <div class="scroll desktop-table mobile-switch"><table id="productsTable"></table></div>
      <div class="mobile-cards" id="productsCards"></div>
    </section>

    <section id="stock" class="panel">
      <div class="section-head"><h2>Nhap stock/account</h2></div>
      <div class="panel-card form">
        <input id="s_stock_code" placeholder="stock_code" />
        <textarea class="full" id="s_items" placeholder="Moi dong la 1 account/secret"></textarea>
        <button onclick="addStockItems()">Them vao kho</button>
      </div>
      <div class="scroll desktop-table mobile-switch"><table id="stockTable"></table></div>
      <div class="mobile-cards" id="stockCards"></div>
    </section>

    <section id="orders" class="panel">
      <div class="section-head"><h2>Don hang</h2></div>
      <div class="panel-card form">
        <input id="o_order_id" placeholder="order_id" />
        <select id="o_status"><option value="EXPIRED">EXPIRED</option><option value="CANCELLED">CANCELLED</option><option value="PENDING">PENDING</option><option value="PAID">PAID</option><option value="DELIVERED">DELIVERED</option></select>
        <button onclick="releaseHeld()">Release HELD -> READY</button>
        <button class="secondary" onclick="setOrderStatus()">Doi status don</button>
      </div>
      <div class="scroll desktop-table mobile-switch"><table id="ordersTable"></table></div>
      <div class="mobile-cards" id="ordersCards"></div>
    </section>

    <section id="users" class="panel">
      <div class="section-head"><h2>Khach hang da bam bot</h2></div>
      <div class="scroll desktop-table mobile-switch"><table id="usersTable"></table></div>
      <div class="mobile-cards" id="usersCards"></div>
    </section>

    <section id="reservations" class="panel">
      <div class="section-head"><h2>Reservations</h2></div>
      <div class="scroll desktop-table mobile-switch"><table id="reservationsTable"></table></div>
      <div class="mobile-cards" id="reservationsCards"></div>
      <div class="section-head"><h2>Fulfillments</h2></div>
      <div class="scroll desktop-table mobile-switch"><table id="fulfillmentsTable"></table></div>
      <div class="mobile-cards" id="fulfillmentsCards"></div>
    </section>
  </main>

<script>
let DATA = null;
const saved = localStorage.getItem("admin_key") || "";
document.getElementById("key").value = saved;
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[c]));
const fmt = n => Number(n || 0).toLocaleString("vi-VN");
const key = () => document.getElementById("key").value.trim();
function msg(t){ document.getElementById("message").textContent = t; }
function showTab(id, btn){ document.querySelectorAll(".panel").forEach(x=>x.classList.remove("active")); document.querySelectorAll(".tab").forEach(x=>x.classList.remove("active")); document.getElementById(id).classList.add("active"); btn.classList.add("active"); }
async function api(path, options={}){
  const sep = path.includes("?") ? "&" : "?";
  const res = await fetch(`${path}${sep}key=${encodeURIComponent(key())}`, {headers: {"content-type":"application/json"}, ...options});
  if(!res.ok) throw new Error(await res.text());
  return res.json();
}
async function loadData(){
  localStorage.setItem("admin_key", key());
  msg("Dang tai du lieu...");
  try {
    DATA = await api("/admin/api/snapshot?limit=150");
    render();
    msg(`Cap nhat luc: ${DATA.generated_at} (${DATA.timezone})`);
  } catch(e) { msg(e.message); }
}
function render(){
  const s = DATA.summary, c = s.status_counts || {};
  document.getElementById("summary").innerHTML = [
    ["Tong don", s.orders, "blue"], ["Doanh thu", fmt(s.revenue)+" d", "green"], ["Users", s.users, "blue"],
    ["Ready", s.stock_ready, "green"], ["Held", s.stock_held, "orange"], ["Sold", s.stock_sold, "blue"],
    ["Pending", c.PENDING||0, "orange"], ["Delivered", c.DELIVERED||0, "green"], ["Expired", c.EXPIRED||0, "red"], ["Cancelled", c.CANCELLED||0, "red"]
  ].map(([a,b,cls])=>`<div class="card"><div class="label">${a}</div><div class="value ${cls}">${b}</div></div>`).join("");
  const productCols = ["product_id","name","stock_code","price","READY","HELD","SOLD","description"];
  const orderCols = ["order_id","user_id","stock_code","qty","total","status","created_at","paid_at","tx_id","delivered_at"];
  setTable("productsTableDash", DATA.products, productCols, true); setCards("productsCardsDash", DATA.products, productCols, fillProduct);
  setTable("ordersTableDash", DATA.orders, orderCols); setCards("ordersCardsDash", DATA.orders, orderCols);
  setTable("productsTable", DATA.products, productCols, true); setCards("productsCards", DATA.products, productCols, fillProduct);
  setTable("stockTable", DATA.pool, ["item_id","stock_code","status","hold_order_id","hold_at","hold_expires_at","sold_order_id","sold_at"]); setCards("stockCards", DATA.pool, ["item_id","stock_code","status","hold_order_id","hold_at","hold_expires_at","sold_order_id","sold_at"]);
  setTable("ordersTable", DATA.orders, orderCols); setCards("ordersCards", DATA.orders, orderCols);
  setTable("usersTable", DATA.users, ["chat_id","username","full_name","orders","spent","updated_at"]); setCards("usersCards", DATA.users, ["chat_id","username","full_name","orders","spent","updated_at"]);
  setTable("reservationsTable", DATA.reservations, ["order_id","item_id","stock_code","reserved_at","expires_at","released_at","sold_at"]); setCards("reservationsCards", DATA.reservations, ["order_id","item_id","stock_code","reserved_at","expires_at","released_at","sold_at"]);
  setTable("fulfillmentsTable", DATA.fulfillments, ["order_id","item_id","stock_code","delivered_at"]); setCards("fulfillmentsCards", DATA.fulfillments, ["order_id","item_id","stock_code","delivered_at"]);
}
function displayValue(k, v){
  if(k === "price" || k === "total" || k === "spent") return fmt(v);
  if(k === "status") return `<span class="pill ${esc(v)}">${esc(v)}</span>`;
  return esc(v);
}
function setTable(id, rows, cols, clickable=false){
  document.getElementById(id).innerHTML = `<tr>${cols.map(c=>`<th>${esc(c)}</th>`).join("")}</tr>` + (rows||[]).map((r,i)=>`<tr ${clickable ? `onclick="fillProduct(DATA.products[${i}])"` : ""}>${cols.map(c=>`<td>${displayValue(c, r[c] ?? "")}</td>`).join("")}</tr>`).join("");
}
function setCards(id, rows, cols, onClick){
  document.getElementById(id).innerHTML = (rows||[]).map((r,i)=>`<div class="mobile-card" ${onClick ? `onclick="fillProduct(DATA.products[${i}])"` : ""}>${cols.map(c=>`<div class="row"><span class="k">${esc(c)}</span><span class="v">${displayValue(c, r[c] ?? "")}</span></div>`).join("")}</div>`).join("");
}
function fillProduct(p){
  showTab("products", document.querySelector(".tabs .tab:nth-child(2)"));
  document.getElementById("p_product_id").value = p.product_id || "";
  document.getElementById("p_name").value = p.name || "";
  document.getElementById("p_stock_code").value = p.stock_code || "";
  document.getElementById("p_price").value = p.price || "";
  document.getElementById("p_description").value = p.description || "";
  window.scrollTo({top: 0, behavior: "smooth"});
}
async function saveProduct(){
  try {
    await api("/admin/api/products", {method:"POST", body: JSON.stringify({
      product_id: document.getElementById("p_product_id").value,
      name: document.getElementById("p_name").value,
      stock_code: document.getElementById("p_stock_code").value,
      price: document.getElementById("p_price").value,
      description: document.getElementById("p_description").value,
    })});
    msg("Da luu san pham."); await loadData();
  } catch(e) { msg(e.message); }
}
async function addStockItems(){
  try {
    const r = await api("/admin/api/stock", {method:"POST", body: JSON.stringify({stock_code: document.getElementById("s_stock_code").value, items: document.getElementById("s_items").value})});
    msg(`Da them ${r.added} item.`); document.getElementById("s_items").value = ""; await loadData();
  } catch(e) { msg(e.message); }
}
async function releaseHeld(){
  try {
    const r = await api("/admin/api/orders/release", {method:"POST", body: JSON.stringify({order_id: document.getElementById("o_order_id").value, status: document.getElementById("o_status").value})});
    msg(`Da tra kho ${r.released} item.`); await loadData();
  } catch(e) { msg(e.message); }
}
async function setOrderStatus(){
  try {
    await api("/admin/api/orders/update", {method:"POST", body: JSON.stringify({order_id: document.getElementById("o_order_id").value, status: document.getElementById("o_status").value})});
    msg("Da doi status don."); await loadData();
  } catch(e) { msg(e.message); }
}
</script>
</body>
</html>"""


def require_admin(request: Request) -> None:
    expected = os.environ.get("ADMIN_PASSWORD", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Set ADMIN_PASSWORD in Render Environment first.")
    provided = (
        request.headers.get("x-admin-key")
        or request.query_params.get("key")  # giữ tương thích cũ; nên gỡ sau khi FE chuyển hết
        or ""
    ).strip()
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


def register_admin_routes(app: FastAPI) -> None:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    fe_dist_dir = os.path.join(base_dir, "fe", "dist")
    fe_assets_dir = os.path.join(fe_dist_dir, "assets")
    fe_index = os.path.join(fe_dist_dir, "index.html")
    if os.path.isdir(fe_assets_dir):
        app.mount("/admin/assets", StaticFiles(directory=fe_assets_dir), name="admin_assets")

    @app.get("/admin", response_class=HTMLResponse)
    async def admin_page():
        if os.path.exists(fe_index):
            return FileResponse(fe_index)
        return ADMIN_HTML

    @app.get("/admin/api/login")
    async def admin_login(request: Request):
        require_admin(request)
        return {"ok": True}

    @app.get("/admin/api/notifications")
    async def admin_notifications_list(request: Request, limit: int = 200):
        require_admin(request)
        return await asyncio.to_thread(notifications_list, limit)

    @app.post("/admin/api/notifications/read")
    async def admin_notifications_read(request: Request):
        require_admin(request)
        data: Dict[str, Any] = await request.json()
        return await asyncio.to_thread(notifications_mark_read, data)

    @app.post("/admin/api/notifications/clear")
    async def admin_notifications_clear(request: Request):
        require_admin(request)
        return await asyncio.to_thread(notifications_clear_all)

    @app.get("/admin/api/snapshot")
    async def admin_snapshot(
        request: Request,
        limit: int = 100,
        pool_limit: int = 2000,
        reveal_secrets: int = 0,
    ):
        require_admin(request)
        return await asyncio.to_thread(snapshot, limit, pool_limit, bool(reveal_secrets))

    @app.post("/admin/api/backup")
    async def admin_backup(request: Request):
        require_admin(request)
        return await asyncio.to_thread(run_backup)

    @app.post("/admin/api/inventory/broadcast")
    async def admin_broadcast_inventory(request: Request):
        require_admin(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        only_in_stock = bool(body.get("only_in_stock", True))
        from bot_shop import broadcast_inventory_update
        return await broadcast_inventory_update(only_in_stock=only_in_stock)

    @app.post("/admin/api/products")
    async def admin_save_product(request: Request):
        require_admin(request)
        return await asyncio.to_thread(save_product, await request.json())

    @app.post("/admin/api/products/delete")
    async def admin_delete_product(request: Request):
        require_admin(request)
        return await asyncio.to_thread(delete_product, await request.json())

    @app.post("/admin/api/stock")
    async def admin_add_stock(request: Request):
        require_admin(request)
        result = await asyncio.to_thread(add_stock, await request.json())
        added = int(result.get("added") or 0)
        stock_code = (result.get("stock_code") or "").strip()
        if added > 0 and stock_code:
            try:
                from bot_shop import broadcast_stock_update

                result["notify"] = await broadcast_stock_update(stock_code, added)
            except Exception as e:
                logger.exception("broadcast_stock_update failed")
                result["notify"] = {"ok": 0, "fail": 0, "error": str(e)}
        return result

    @app.post("/admin/api/orders/release")
    async def admin_release_order(request: Request):
        require_admin(request)
        data: Dict[str, Any] = await request.json()
        return await asyncio.to_thread(release_order, data.get("order_id", ""), data.get("status", "EXPIRED"))

    @app.post("/admin/api/stock/release-held")
    async def admin_release_holds(request: Request):
        require_admin(request)
        data: Dict[str, Any] = await request.json()
        return await asyncio.to_thread(
            release_holds,
            bool(data.get("expired_only", True)),
            data.get("status", "EXPIRED"),
        )

    @app.post("/admin/api/orders/update")
    async def admin_update_order(request: Request):
        require_admin(request)
        data: Dict[str, Any] = await request.json()
        order_id = data.pop("order_id", "")
        return await asyncio.to_thread(update_order, order_id, data)

    @app.post("/admin/api/orders/reconcile-payment")
    async def admin_reconcile_payment(request: Request):
        """Xử lý lại thanh toán SePay cho đơn (khi webhook không tới bot)."""
        require_admin(request)
        data: Dict[str, Any] = await request.json()
        order_id = (data.get("order_id") or "").strip()
        if not order_id:
            raise HTTPException(status_code=400, detail="order_id required")
        amount = int(data.get("amount") or 0)
        tx_id = (data.get("tx_id") or f"manual-{order_id}").strip()
        payload = {
            "transferType": "in",
            "description": f"BankAPINotify {order_id}",
            "transferAmount": amount,
            "referenceCode": tx_id,
            "id": data.get("id") or 0,
        }
        await process_payment(payload)
        return {"ok": True, "order_id": order_id, "queued": False}
