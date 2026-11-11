import { useCallback, useEffect, useState } from "react";
import { adminApi } from "../../api";
import { Button } from "../ui/button";

type Review = { event_id: string; order_id: string; kind: string; status: string; attempts: string; error: string };

export function PaymentReviews({ adminKey }: { adminKey: string }) {
  const [items, setItems] = useState<Review[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try {
      const result = await adminApi<{ items: Review[] }>("/admin/api/payment-reviews", adminKey);
      setItems(result.items);
      setError("");
    } catch { setError("Không tải được danh sách. Hãy thử làm mới."); }
  }, [adminKey]);
  useEffect(() => { void load(); }, [load]);
  async function retry(id: string) {
    setBusy(true);
    try {
      await adminApi("/admin/api/payment-reviews/retry", adminKey, {
        method: "POST", body: JSON.stringify({ event_id: id }),
      });
      await load();
    } catch { setError("Chưa thể yêu cầu thử lại. Hãy thử sau."); }
    finally { setBusy(false); }
  }
  return <div className="space-y-4">
    <div className="flex items-center justify-between gap-3">
      <h2>Thanh toán và giao hàng cần xử lý</h2>
      <Button variant="outline" onClick={() => void load()}>Làm mới</Button>
    </div>
    <p className="text-sm text-muted-foreground">Kiểm tra giao dịch, đơn và kho trước khi yêu cầu thử lại. Nút thử lại sẽ kiểm tra lại điều kiện thanh toán và hàng tồn.</p>
    {error && <p role="alert" className="text-red-600">{error}</p>}
    {!items.length && !error && <p>Không có trường hợp cần xử lý.</p>}
    {items.map(item => <div key={item.event_id} className="rounded-lg border bg-white p-4 space-y-2">
      <p className="font-medium">{item.kind === "backup" ? "Backup" : item.kind === "delivery" ? "Giao hàng" : "Thanh toán"} · {item.status === "REVIEW" ? "Cần kiểm tra" : "Đang tự thử lại"}</p>
      <p className="text-sm">{item.error || "Đang chờ xử lý"}</p>
      {item.order_id && <p className="text-sm">Đơn: {item.order_id}</p>}
      <p className="text-xs text-muted-foreground break-all">Mã tra cứu: {item.event_id} · Số lần: {item.attempts}</p>
      <Button disabled={busy} onClick={() => void retry(item.event_id)}>Kiểm tra và thử lại</Button>
    </div>)}
  </div>;
}
