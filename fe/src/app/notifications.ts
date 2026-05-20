import { money, text } from "./api";

export type NotifyKind = "new" | "cancelled" | "expired" | "delivered" | "paid" | "start";

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
  start: {
    title: "Khách hàng",
    description: "Vừa bấm /start bot",
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

function normKind(t: string, message = ""): NotifyKind {
  const k = (t || "").trim().toLowerCase();
  if (k === "start" || k === "customer" || k === "user" || k === "user_start") {
    return "start";
  }
  const m = (message || "").toLowerCase();
  if (m.includes("khách start bot") || m.startsWith("khách hàng:")) {
    return "start";
  }
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
  const rawMsg = (row.message || "").trim();
  const kind = normKind(row.type, rawMsg);
  const meta = NOTIFY_META[kind];

  let title = (row.title || "").trim() || undefined;
  let message = rawMsg;
  const colon = rawMsg.indexOf(":");
  if (colon > 0 && colon < 48) {
    const head = rawMsg.slice(0, colon).trim();
    const rest = rawMsg.slice(colon + 1).trim();
    if (kind === "start" || /khách/i.test(head)) {
      title = "Khách hàng";
      message = rest || rawMsg;
    }
  }

  const parts = message.split("·").map((x) => x.trim());
  let stockCode = "";
  let total = "";
  let userId = "";
  for (const p of parts) {
    if (p.startsWith("Stock:")) stockCode = p.replace(/^Stock:\s*/i, "").trim();
    if (p.startsWith("Tổng:")) total = p.replace(/^Tổng:\s*/i, "").trim();
    if (p.startsWith("ID:")) userId = p.replace(/^ID:\s*/i, "").trim();
  }

  return {
    id: (row.id || "").trim() || `row_${row.created_at}`,
    kind,
    title: title || meta.title,
    message: message || undefined,
    orderId: (row.order_id || "").trim(),
    stockCode: stockCode || undefined,
    total: total || undefined,
    userId: userId || undefined,
    at: (row.created_at || "").trim() || new Date().toISOString(),
    read: parseRead(row.is_read),
  };
}

/** Parse thời gian thông báo (ISO hoặc id dạng NYYYYMMDDHHMMSS…). */
export function notificationTimeMs(n: OrderNotification): number {
  const fromAt = Date.parse(n.at);
  if (!Number.isNaN(fromAt)) return fromAt;
  const m = /^N(\d{14})/.exec(n.id);
  if (m) {
    const s = m[1];
    const iso = `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}T${s.slice(8, 10)}:${s.slice(10, 12)}:${s.slice(12, 14)}`;
    const t = Date.parse(iso);
    if (!Number.isNaN(t)) return t;
  }
  return 0;
}

/** Mới nhất ở đầu danh sách (dashboard + overview). */
export function sortNotificationsNewestFirst(items: OrderNotification[]): OrderNotification[] {
  return [...items].sort((a, b) => notificationTimeMs(b) - notificationTimeMs(a));
}

export function mergeNotifications(
  prev: OrderNotification[],
  batch: OrderNotification[],
): OrderNotification[] {
  const seen = new Set(prev.map((n) => n.id));
  const added = batch.filter((n) => !seen.has(n.id));
  return sortNotificationsNewestFirst([...added, ...prev]).slice(0, MAX_NOTIFICATIONS);
}
