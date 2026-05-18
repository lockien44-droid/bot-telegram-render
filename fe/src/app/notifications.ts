import { money, text } from "./api";

export type NotifyKind = "new" | "cancelled" | "expired" | "delivered";

export interface OrderNotification {
  id: string;
  kind: NotifyKind;
  orderId: string;
  stockCode: string;
  total: string;
  userId: string;
  status: string;
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
};

export const MAX_NOTIFICATIONS = 200;
