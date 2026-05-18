import { useEffect, useState } from "react";
import { Card, CardContent } from "../ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../ui/table";
import { Button } from "../ui/button";
import { Badge } from "../ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../ui/dialog";
import { Input } from "../ui/input";
import { ClipboardList, Search } from "lucide-react";
import { adminApi, money, text, type AdminSnapshot, type AnyRow } from "../../api";

type OrderStatus = "PENDING" | "PAID" | "DELIVERED" | "EXPIRED" | "CANCELLED";
type OrderFilter = OrderStatus | "ALL" | "FAILED";

interface Props {
  data: AdminSnapshot | null;
  adminKey: string;
  refresh: () => Promise<void>;
  preset?: { status?: string; orderId?: string; nonce: number };
}

const ALL_STATUSES: OrderStatus[] = ["PENDING", "PAID", "DELIVERED", "EXPIRED", "CANCELLED"];

export function Orders({ data, adminKey, refresh, preset }: Props) {
  const [search, setSearch] = useState("");
  const [filterStatus, setFilterStatus] = useState<OrderFilter>("ALL");
  const [changeModal, setChangeModal] = useState<{ open: boolean; order: AnyRow | null }>({ open: false, order: null });
  const [newStatus, setNewStatus] = useState<OrderStatus>("DELIVERED");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!preset?.nonce) return;
    if (preset.orderId) setSearch(preset.orderId);
    const status = (preset.status || "ALL").toUpperCase() as OrderFilter;
    setFilterStatus(status === "FAILED" || ALL_STATUSES.includes(status as OrderStatus) ? status : "ALL");
  }, [preset?.nonce, preset?.status, preset?.orderId]);

  const orders = data?.orders || [];
  const visible = orders.filter((o) => {
    const status = text(o.status).toUpperCase();
    if (filterStatus === "FAILED" && !["EXPIRED", "CANCELLED"].includes(status)) return false;
    if (filterStatus !== "ALL" && filterStatus !== "FAILED" && status !== filterStatus) return false;
    const hay = `${text(o.order_id)} ${text(o.user_id)} ${text(o.stock_code)}`.toLowerCase();
    return !search || hay.includes(search.toLowerCase());
  });

  const openChange = (o: AnyRow) => {
    setNewStatus((text(o.status) === "—" ? "DELIVERED" : text(o.status)) as OrderStatus);
    setChangeModal({ open: true, order: o });
  };

  const applyChange = async () => {
    if (!changeModal.order) return;
    setBusy(true);
    try {
      await adminApi("/admin/api/orders/update", adminKey, { method: "POST", body: JSON.stringify({ order_id: changeModal.order.order_id, status: newStatus }) });
      setChangeModal({ open: false, order: null });
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <h2 className="flex items-center gap-2"><ClipboardList size={20} /> Đơn hàng</h2>

      <div className="flex flex-wrap gap-2">
        <div className="relative">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input className="pl-8 w-64" placeholder="Order ID / User ID / Code" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <Select value={filterStatus} onValueChange={(v) => setFilterStatus(v as OrderFilter)}>
          <SelectTrigger className="w-40"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="ALL">Tất cả</SelectItem>
            <SelectItem value="FAILED">Lỗi / hủy</SelectItem>
            {ALL_STATUSES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>

      <Card className="shadow-sm">
        <CardContent className="p-0 overflow-x-auto">
          <Table className="min-w-[960px]">
            <TableHeader>
              <TableRow>
                <TableHead>Order ID</TableHead>
                <TableHead>User ID</TableHead>
                <TableHead>Stock Code</TableHead>
                <TableHead className="text-center">SL</TableHead>
                <TableHead className="text-right">Tổng tiền</TableHead>
                <TableHead className="text-center">Trạng thái</TableHead>
                <TableHead>Tạo lúc</TableHead>
                <TableHead>Thanh toán</TableHead>
                <TableHead>Giao hàng</TableHead>
                <TableHead className="text-center">Sửa</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((o) => (
                <TableRow key={text(o.order_id)}>
                  <TableCell><code className="text-xs bg-muted px-1.5 py-0.5 rounded">{text(o.order_id)}</code></TableCell>
                  <TableCell className="text-sm text-muted-foreground">{text(o.user_id)}</TableCell>
                  <TableCell><code className="text-xs bg-muted px-1.5 py-0.5 rounded">{text(o.stock_code)}</code></TableCell>
                  <TableCell className="text-center">{text(o.qty)}</TableCell>
                  <TableCell className="text-right text-emerald-700">{money(o.total)}</TableCell>
                  <TableCell className="text-center"><OrderBadge status={text(o.status)} /></TableCell>
                  <TableCell className="text-xs text-muted-foreground whitespace-nowrap">{text(o.created_at)}</TableCell>
                  <TableCell className="text-xs text-muted-foreground whitespace-nowrap">{text(o.paid_at)}</TableCell>
                  <TableCell className="text-xs text-muted-foreground whitespace-nowrap">{text(o.delivered_at)}</TableCell>
                  <TableCell className="text-center"><Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => openChange(o)}>Đổi</Button></TableCell>
                </TableRow>
              ))}
              {visible.length === 0 && <TableRow><TableCell colSpan={10} className="text-center text-muted-foreground py-8">Không có đơn hàng nào</TableCell></TableRow>}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog open={changeModal.open} onOpenChange={(v) => setChangeModal({ open: v, order: null })}>
        <DialogContent className="max-w-sm">
          <DialogHeader><DialogTitle>Đổi trạng thái đơn</DialogTitle></DialogHeader>
          {changeModal.order && (
            <div className="space-y-3 py-2">
              <p className="text-sm text-muted-foreground">Order: <strong>{text(changeModal.order.order_id)}</strong></p>
              <Select value={newStatus} onValueChange={(v) => setNewStatus(v as OrderStatus)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>{ALL_STATUSES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
              </Select>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setChangeModal({ open: false, order: null })}>Hủy</Button>
            <Button onClick={applyChange} disabled={busy}>Xác nhận</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function OrderBadge({ status }: { status: string }) {
  const bad = status === "EXPIRED" || status === "CANCELLED";
  const good = status === "DELIVERED" || status === "PAID";
  return <Badge variant={bad ? "destructive" : good ? "default" : "secondary"}>{status}</Badge>;
}
