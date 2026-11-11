export const STATUS_LABELS: Record<string, string> = {
  PENDING: "Chờ thanh toán", PAID: "Đã thanh toán", DELIVERY_PENDING: "Chờ giao hàng",
  DELIVERED: "Đã giao", EXPIRED: "Hết hạn", CANCELLED: "Đã huỷ",
  READY: "Có sẵn", HELD: "Đang giữ", SOLD: "Đã bán", OTHER: "Khác",
  AWAITING_DELIVERY: "Chờ giao hàng", FAILED: "Huỷ / hết hạn",
};
export const statusLabel = (value: string) => STATUS_LABELS[value] || value;
export function StatusBadge({ status }: { status: string }) {
  const tone = ["DELIVERED", "READY", "SOLD"].includes(status) ? "bg-emerald-50 text-emerald-800 ring-emerald-600/15"
    : ["PAID", "DELIVERY_PENDING", "HELD", "PENDING"].includes(status) ? "bg-amber-50 text-amber-800 ring-amber-600/15"
    : "bg-slate-100 text-slate-600 ring-slate-500/10";
  return <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium whitespace-nowrap ring-1 ring-inset ${tone}`}>
    <span className="h-1.5 w-1.5 rounded-full bg-current opacity-65" />{statusLabel(status)}
  </span>;
}
