import { useCallback, useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, LoaderCircle, ArrowUpRight, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { adminApi, money } from "../../api";
import { Button } from "../ui/button";

type Review = { event_id: string; order_id: string; kind: string; status: string; attempts: string; error: string; received_amount?: number; transaction_date?: string };
export function PaymentReviews({ adminKey, onOpenOrder }: { adminKey: string; onOpenOrder?: (id: string) => void }) {
  const [items, setItems] = useState<Review[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const load = useCallback(async () => {
    setLoading(true); setError("");
    try { const result = await adminApi<{ items: Review[] }>("/admin/api/payment-reviews", adminKey); setItems(result.items); }
    catch { setError("Không tải được danh sách. Hãy thử làm mới."); }
    finally { setLoading(false); }
  }, [adminKey]);
  useEffect(() => { void load(); }, [load]);
  async function retry(id: string) {
    setBusy(id);
    try { await adminApi("/admin/api/payment-reviews/retry", adminKey, { method: "POST", body: JSON.stringify({ event_id: id }) }); toast.success("Đã yêu cầu kiểm tra lại. Kết quả sẽ được cập nhật sau khi xử lý."); await load(); }
    catch { toast.error("Chưa thể yêu cầu thử lại. Hãy thử sau."); }
    finally { setBusy(""); }
  }
  return <div className="space-y-5"><div className="flex flex-wrap items-end justify-between gap-3"><div><p className="eyebrow">CÔNG VIỆC CẦN CHÚ Ý</p><h2 className="page-title">Thanh toán cần xử lý</h2><p className="page-subtitle">Kiểm tra nguyên nhân, đối chiếu đơn và xử lý từng trường hợp.</p></div><Button variant="outline" onClick={() => void load()} disabled={loading}><RefreshCw size={15} className={loading ? "animate-spin" : ""} />Làm mới</Button></div>
    {loading ? <div role="status" className="surface p-10 flex justify-center gap-3 text-slate-500"><LoaderCircle className="animate-spin" size={20} />Đang kiểm tra danh sách…</div>
    : error ? <div role="alert" className="surface p-8 text-center text-red-700">{error}</div>
    : !items.length ? <div className="surface p-12 text-center"><CheckCircle2 className="mx-auto mb-4 text-emerald-600" size={40} /><h3 className="font-semibold">Mọi việc đã được xử lý</h3><p className="text-sm text-slate-500 mt-2">Không có giao dịch hay tác vụ cần kiểm tra lúc này.</p></div>
    : items.map(item => <article key={item.event_id} className="surface overflow-hidden"><div className="p-5 space-y-4"><div className="flex flex-wrap items-start justify-between gap-3"><div className="flex gap-3 min-w-0"><div className="rounded-xl p-2.5 bg-amber-50 text-amber-700 self-start"><AlertCircle size={20} /></div><div><p className="font-semibold">{item.kind === "backup" ? "Sao lưu dữ liệu" : item.kind === "delivery" ? "Giao hàng" : "Thanh toán"}</p>{item.order_id && <button className="mt-1 text-sm text-emerald-700 inline-flex items-center gap-1 break-all text-left" onClick={() => onOpenOrder?.(item.order_id)}>{item.order_id}<ArrowUpRight className="shrink-0" size={14} /></button>}</div></div><span className="rounded-full bg-amber-50 text-amber-800 text-xs font-medium px-3 py-1.5">{item.status === "REVIEW" ? "Cần kiểm tra" : "Đang tự thử lại"}</span></div><p className="rounded-lg bg-slate-50 p-3 text-sm text-slate-600">{item.error === "TimeoutError" ? "Kết nối bị gián đoạn trong lúc xử lý." : item.error || "Đang chờ xử lý"}</p><div className="flex flex-wrap justify-between items-center gap-4"><div className="text-sm"><span className="text-slate-400">{item.received_amount != null ? "Số tiền nhận: " : ""}</span>{item.received_amount != null && <strong>{money(item.received_amount)}</strong>}{item.transaction_date && <p className="text-xs text-slate-400 mt-1">{item.transaction_date}</p>}</div><Button disabled={Boolean(busy)} onClick={() => void retry(item.event_id)}>{busy === item.event_id ? "Đang gửi yêu cầu…" : "Kiểm tra và thử lại"}</Button></div><details className="text-xs text-slate-400"><summary className="cursor-pointer">Thông tin tra cứu</summary><p className="break-all mt-2">Mã sự kiện: {item.event_id}</p><p className="mt-1">Đã xử lý {item.attempts} lần</p></details></div></article>)}
  </div>;
}
