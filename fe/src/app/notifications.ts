import { money, text } from "./api";

export type NotifyKind = "new" | "cancelled" | "expired" | "delivered" | "paid";

export interface OrderNotification {
  id: string;
  kind: NotifyKind;
  /** Tiêu đề từ sheet (ưu tiên hiển thị). */
  title?: string;
  /** Một dòng mô tả từ sheet. */
  message?: string;
  orderId: string;
  stockCode?: string;
  total?: string;
  userId?: string;
  status?: string;
  at: string;
  read: boolean;
}

let _seq = 0;

export function buildNotifications(kind: NotifyKind, orders: any[]): OrderNotification[] {
  const at = new Date().toISOString();
  return orders.map((order) => {
    _seq += 1;
    const orderId = text(order.order_id);
    return {
      id: `${kind}_${orderId}_${_seq}`,
      kind,
      orderId,
      stockCode: text(order.stock_code),
      total: money(order.total),
      userId: text(order.user_id),
      status: text(order.status).toUpperCase(),
      at,
      read: false,
    };
  });
}

export const NOTIFY_META: Record<
  NotifyKind,
  { title: string; description: string; tone: "success" | "error" | "info" | "default" }
> = {
  new: {
    title: "Đơn mới",
    description: "Khách vừa tạo đơn, chờ thanh toán",
    tone: "success",
  },
  cancelled: {
    title: "Đơn đã huỷ",
    description: "Khách hoặc hệ thống đã huỷ đơn",
    tone: "error",
  },
  expired: {
    title: "Đơn hết hạn",
    description: "Quá thời gian thanh toán",
    tone: "error",
  },
  delivered: {
    title: "Đã giao hàng",
    description: "Đơn đã giao cho khách",
    tone: "info",
  },
  paid: {
    title: "Đã thanh toán",
    description: "Tiền đã về, chờ giao / lỗi kho",
    tone: "info",
  },
};

export const MAX_NOTIFICATIONS = 500;

/** API / sheet trả về (snake_case). */
export interface SheetNotificationRow {
  id: string;
  type: string;
  title?: string;
  message: string;
  order_id: string;
  is_read: string;
  created_at: string;
}

function normKind(t: string): NotifyKind {
  const k = (t || "").toLowerCase();
  if (k === "new" || k === "cancelled" || k === "expired" || k === "delivered" || k === "paid") {
    return k;
  }
  return "new";
}

function parseRead(raw: string): boolean {
  const s = (raw || "").trim().toLowerCase();
  return s === "1" || s === "true" || s === "yes";
}

export function mapSheetNotification(row: SheetNotificationRow): OrderNotification {
  const kind = normKind(row.type);
  const msg = (row.message || "").trim();
  const parts = msg.split("·").map((x) => x.trim());
  let stockCode = "";
  let total = "";
  for (const p of parts) {
    if (p.startsWith("Stock:")) stockCode = p.replace(/^Stock:\s*/i, "").trim();
    if (p.startsWith("Tổng:")) total = p.replace(/^Tổng:\s*/i, "").trim();
  }
  return {
    id: (row.id || "").trim() || `row_${row.created_at}`,
    kind,
    title: (row.title || "").trim() || undefined,
    message: msg || undefined,
    orderId: (row.order_id || "").trim(),
    stockCode: stockCode || undefined,
    total: total || undefined,
    at: (row.created_at || "").trim() || new Date().toISOString(),
    read: parseRead(row.is_read),
  };
}

export function mergeNotifications(
  prev: OrderNotification[],
  batch: OrderNotification[],
): OrderNotification[] {
  const seen = new Set(prev.map((n) => n.id));
  const added = batch.filter((n) => !seen.has(n.id));
  return [...added, ...prev].slice(0, MAX_NOTIFICATIONS);
}
