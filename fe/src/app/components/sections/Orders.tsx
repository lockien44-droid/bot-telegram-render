import { useEffect, useState } from "react";
import { Search, ChevronLeft, ChevronRight, Eye, Copy, ArrowUpRight, LoaderCircle, PackageCheck, XCircle } from "lucide-react";
import { toast } from "sonner";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../ui/dialog";
import { StatusBadge, statusLabel } from "../StatusBadge";
import { adminApi, money, text, type AdminSnapshot, type AnyRow } from "../../api";

type Props = { data: AdminSnapshot | null; adminKey: string; refresh: () => Promise<void>; preset?: { status?: string; orderId?: string; nonce: number } };
type Results = { items: AnyRow[]; total: number; page: number; pages: number };
const statuses = ["PENDING", "AWAITING_DELIVERY", "DELIVERED", "FAILED"];

export function Orders({ data, adminKey, refresh, preset }: Props) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("ALL");
  const [stock, setStock] = useState("");
  const [from, setFrom] = useState("");
  const [until, setUntil] = useState("");
  const [page, setPage] = useState(1);
  const [result, setResult] = useState<Results>({ items: [], total: 0, page: 1, pages: 1 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<AnyRow | null>(null);
  const [detailError, setDetailError] = useState("");
  const [busy, setBusy] = useState(false);
  const [action, setAction] = useState("");
  const [txId, setTxId] = useState("");
  const [revealed, setRevealed] = useState(false);
  useEffect(() => {
    if (!preset?.nonce) return;
    setQuery(preset.orderId || ""); setStatus(preset.status || "ALL"); setPage(1);
    setStock(""); setFrom(""); setUntil("");
  }, [preset?.nonce]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError("");
    const timer = window.setTimeout(async () => {
      try {
        const params = new URLSearchParams({ q: query, status, stock_code: stock, page: String(page), page_size: "20" });
        if (from) params.set("date_from", from);
        if (until) params.set("date_to", until);
        const next = await adminApi<Results>(`/admin/api/orders?${params}`, adminKey, { signal: controller.signal });
        if (!controller.signal.aborted) setResult(next);
      } catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "Không tải được đơn hàng."); }
      finally { if (!controller.signal.aborted) setLoading(false); }
    }, 250);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [query, status, stock, from, until, page, revision, data?.generated_at, adminKey]);
  useEffect(() => {
    const controller = new AbortController();
    setDetail(null); setDetailError(""); setRevealed(false); setAction(""); setTxId("");
    if (selected) adminApi<AnyRow>(`/admin/api/orders/${encodeURIComponent(selected)}`, adminKey, { signal: controller.signal })
      .then(row => { if (!controller.signal.aborted) setDetail(row); })
      .catch(() => { if (!controller.signal.aborted) setDetailError("Không tải được chi tiết. Hãy đóng và mở lại đơn."); });
    return () => controller.abort();
  }, [selected, adminKey]);
  async function reveal() {
    if (!selected) return;
    setBusy(true);
    try { setDetail(await adminApi<AnyRow>(`/admin/api/orders/${encodeURIComponent(selected)}?reveal=true`, adminKey)); setRevealed(true); }
    catch { toast.error("Không tải được thông tin giao hàng."); }
    finally { setBusy(false); }
  }
  async function runAction() {
    if (!selected || !detail) return;
    setBusy(true);
    try {
      if (action === "retry") await adminApi(`/admin/api/orders/${encodeURIComponent(selected)}/retry-delivery`, adminKey, { method: "POST" });
      if (action === "cancel") await adminApi("/admin/api/orders/release", adminKey, { method: "POST", body: JSON.stringify({ order_id: selected, status: "CANCELLED" }) });
      if (action === "paid") await adminApi("/admin/api/orders/reconcile-payment", adminKey, { method: "POST", body: JSON.stringify({ order_id: selected, amount: Number(detail.total), tx_id: txId.trim() }) });
      toast.success(action === "cancel" ? "Đã huỷ đơn và trả kho." : "Đã tiếp nhận. Hệ thống sẽ kiểm tra và xử lý giao hàng.");
      setAction(""); setSelected(null); setRevision(v => v + 1); await refresh();
    } catch (e) { toast.error(e instanceof Error ? e.message : "Chưa thể xử lý đơn."); }
    finally { setBusy(false); }
  }
  const update = (setter: (value: string) => void, value: string) => { setter(value); setPage(1); };
  return <div className="space-y-5">
    <div className="flex items-end justify-between gap-3"><div><p className="eyebrow">QUẢN LÝ BÁN HÀNG</p><h2 className="page-title">Đơn hàng</h2><p className="page-subtitle">Tìm và theo dõi toàn bộ đơn, kể cả lịch sử cũ.</p></div><span className="rounded-full bg-white px-3 py-1.5 text-sm font-medium border shrink-0 whitespace-nowrap">{result.total} đơn</span></div>
    <div className="surface p-4 space-y-4">
      <div className="relative"><Search size={17} className="absolute left-3 top-3 text-slate-400" /><Input aria-label="Tìm đơn hàng" className="pl-10 h-11" placeholder="Tìm mã đơn, khách hàng hoặc sản phẩm…" value={query} onChange={e => update(setQuery, e.target.value)} /></div>
      <div className="flex flex-wrap gap-2">{["ALL", ...statuses].map(s => <button key={s} onClick={() => update(setStatus, s)} className={`shrink-0 rounded-full px-3.5 py-2 text-sm transition ${status === s ? "bg-emerald-700 text-white shadow-sm" : "bg-slate-50 text-slate-600 hover:bg-slate-100"}`}>{s === "ALL" ? "Tất cả" : statusLabel(s)}</button>)}</div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div className="col-span-2 lg:col-span-1"><Label htmlFor="order-product">Sản phẩm</Label><select id="order-product" className="field-select mt-1" value={stock} onChange={e => update(setStock, e.target.value)}><option value="">Tất cả sản phẩm</option>{data?.products.map(p => <option key={p.stock_code} value={p.stock_code}>{p.name}</option>)}</select></div>
        <div><Label htmlFor="date-from">Từ ngày</Label><Input id="date-from" type="date" value={from} onChange={e => update(setFrom, e.target.value)} className="mt-1" /></div>
        <div><Label htmlFor="date-until">Đến ngày</Label><Input id="date-until" type="date" value={until} min={from || undefined} onChange={e => update(setUntil, e.target.value)} className="mt-1" /></div>
        <Button variant="ghost" className="self-end" onClick={() => { setQuery(""); setStatus("ALL"); setStock(""); setFrom(""); setUntil(""); setPage(1); }}>Xoá bộ lọc</Button>
      </div>
    </div>
    {error ? <div role="alert" className="surface p-6 text-center"><p className="text-red-700">{error}</p><Button className="mt-3" variant="outline" onClick={() => setRevision(v => v + 1)}>Thử lại</Button></div>
    : loading ? <div role="status" className="surface p-12 flex justify-center items-center gap-3 text-slate-500"><LoaderCircle size={20} className="animate-spin" />Đang tải đơn hàng…</div>
    : !result.items.length ? <div className="surface p-12 text-center"><PackageCheck className="mx-auto text-slate-300 mb-3" size={36} /><h3 className="font-semibold">Không tìm thấy đơn phù hợp</h3><p className="text-sm text-slate-500 mt-1">Thử đổi từ khoá hoặc khoảng thời gian.</p></div>
    : <>
      <div className="surface hidden lg:block overflow-hidden"><table className="w-full text-sm"><thead className="bg-slate-50/80 text-slate-500 text-xs"><tr>{["Đơn hàng / Khách", "Sản phẩm", "Tổng tiền", "Trạng thái", ""].map((x,i) => <th key={i} className="px-5 py-3.5 text-left font-medium">{x}</th>)}</tr></thead><tbody>{result.items.map(o => <tr key={o.order_id} className="border-t border-slate-100 hover:bg-emerald-50/30"><td className="px-5 py-4"><button className="text-emerald-800 font-semibold text-left" onClick={() => setSelected(o.order_id)}>{o.order_id}</button><p className="text-xs text-slate-400 mt-1">Khách {o.user_id} · {o.created_at}</p></td><td className="px-5 py-4"><p className="font-medium">{o.product_name}</p><p className="text-xs text-slate-400 mt-1">Số lượng {o.qty}</p></td><td className="px-5 py-4 font-semibold tabular-nums">{money(o.total)}</td><td className="px-5 py-4"><StatusBadge status={o.status} /></td><td className="pr-5"><Button variant="ghost" size="sm" onClick={() => setSelected(o.order_id)}>Chi tiết<ArrowUpRight size={14} /></Button></td></tr>)}</tbody></table></div>
      <div className="lg:hidden space-y-3">{result.items.map(o => <button key={o.order_id} onClick={() => setSelected(o.order_id)} className="surface w-full text-left p-4 space-y-3"><div className="flex items-center justify-between gap-2"><span className="font-semibold text-sm break-all">{o.order_id}</span><ChevronRight size={17} className="shrink-0 text-slate-400" /></div><div className="flex items-center justify-between gap-3"><span className="text-sm">{o.product_name} × {o.qty}</span><strong className="text-sm">{money(o.total)}</strong></div><div className="flex flex-wrap items-center justify-between gap-2"><StatusBadge status={o.status} /><span className="text-xs text-slate-400">{o.created_at}</span></div></button>)}</div>
    </>}
    <div className="flex items-center justify-between text-sm text-slate-500"><span>Trang {result.page} / {result.pages}</span><div className="flex gap-2"><Button aria-label="Trang trước" variant="outline" size="icon" disabled={loading || result.page <= 1} onClick={() => setPage(result.page - 1)}><ChevronLeft size={16} /></Button><Button aria-label="Trang tiếp theo" variant="outline" size="icon" disabled={loading || result.page >= result.pages} onClick={() => setPage(result.page + 1)}><ChevronRight size={16} /></Button></div></div>
    <Dialog open={Boolean(selected)} onOpenChange={open => { if (!open) setSelected(null); }}><DialogContent className="sm:max-w-xl max-h-[90dvh] overflow-y-auto"><DialogHeader><DialogTitle>Chi tiết đơn hàng</DialogTitle><DialogDescription className="break-all">{selected}</DialogDescription></DialogHeader>
      {detailError ? <p role="alert" className="text-red-700">{detailError}</p> : !detail ? <p className="py-8 text-slate-500">Đang tải chi tiết…</p> : <div className="space-y-5">
        <div className="rounded-xl bg-slate-50 p-4 flex justify-between items-center"><StatusBadge status={detail.status} /><strong className="text-xl tabular-nums">{money(detail.total)}</strong></div>
        <dl className="grid grid-cols-2 gap-4 text-sm">{[["Khách hàng", detail.user_id], ["Sản phẩm", detail.stock_code], ["Số lượng", detail.qty], ["Tạo lúc", detail.created_at], ["Thanh toán lúc", detail.paid_at], ["Giao lúc", detail.delivered_at], ["Mã giao dịch", detail.tx_id]].map(([label,value]) => <div key={label}><dt className="text-slate-400 text-xs mb-1">{label}</dt><dd className="break-all font-medium">{text(value)}</dd></div>)}</dl>
        {detail.has_delivery && <div className="border-t pt-4"><div className="flex items-center justify-between gap-2"><h3 className="font-semibold text-sm">Thông tin đã giao</h3><Button variant="outline" size="sm" disabled={busy} onClick={() => revealed ? setRevealed(false) : void reveal()}><Eye size={15} />{revealed ? "Ẩn thông tin" : "Xem thông tin"}</Button></div>{revealed && <div className="mt-3"><pre className="rounded-lg bg-slate-50 p-3 whitespace-pre-wrap break-all text-xs max-h-52 overflow-y-auto">{detail.delivery_text || "Chưa có nội dung"}</pre><Button variant="ghost" size="sm" className="mt-2" onClick={async () => { try { await navigator.clipboard.writeText(detail.delivery_text || ""); toast.success("Đã sao chép."); } catch { toast.error("Trình duyệt không cho phép sao chép."); } }}><Copy size={14} />Sao chép</Button></div>}</div>}
        {!action && ["PENDING", "PAID", "DELIVERY_PENDING", "EXPIRED", "CANCELLED"].includes(detail.status) && <div className="border-t pt-4 flex flex-wrap gap-2">{["PENDING", "EXPIRED", "CANCELLED"].includes(detail.status) && <Button onClick={() => setAction("paid")}>Đối soát thanh toán</Button>}{detail.status === "PENDING" && <Button variant="outline" className="text-red-700" onClick={() => setAction("cancel")}><XCircle size={15} />Huỷ đơn</Button>}{["PAID", "DELIVERY_PENDING"].includes(detail.status) && <Button onClick={() => setAction("retry")}>Thử giao lại</Button>}</div>}
        {action && <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 space-y-3"><p className="text-sm">{action === "cancel" ? "Huỷ đơn này và trả hàng đang giữ về kho?" : action === "retry" ? "Hệ thống sẽ kiểm tra và gửi hàng cho người mua. Tiếp tục?" : `Xác nhận đã kiểm tra khoản chuyển ${money(detail.total)} cho đơn này.`}</p>{action === "paid" && <div><Label htmlFor="bank-tx">Mã giao dịch ngân hàng</Label><Input id="bank-tx" value={txId} onChange={e => setTxId(e.target.value)} placeholder="Nhập mã giao dịch đã đối chiếu" className="mt-1 bg-white" /></div>}<div className="flex gap-2"><Button disabled={busy || (action === "paid" && !txId.trim())} onClick={() => void runAction()}>{busy ? "Đang xử lý…" : "Xác nhận"}</Button><Button variant="ghost" disabled={busy} onClick={() => setAction("")}>Quay lại</Button></div></div>}
      </div>}
    </DialogContent></Dialog>
  </div>;
}
