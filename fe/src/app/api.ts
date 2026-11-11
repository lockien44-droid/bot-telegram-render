export type AnyRow = Record<string, any>;

export interface AdminSnapshot {
  generated_at: string;
  timezone: string;
  secrets_revealed?: boolean;
  summary: {
    orders: number;
    revenue: number;
    revenue_all?: number;
    revenue_stats?: {
      today: { orders: number; revenue: number };
      month: { orders: number; revenue: number };
      year: { orders: number; revenue: number };
    };
    status_counts: Record<string, number>;
    users: number;
    review_count?: number;
    stock_ready: number;
    stock_held: number;
    stock_sold: number;
  };
  products: AnyRow[];
  orders: AnyRow[];
  users: AnyRow[];
  pool: AnyRow[];
  reservations: AnyRow[];
  fulfillments: AnyRow[];
  deliveries?: AnyRow[];
}

export class AdminUnauthorizedError extends Error {
  constructor(message = "Unauthorized") {
    super(message);
    this.name = "AdminUnauthorizedError";
  }
}

let onUnauthorized: (() => void) | null = null;

export function setAdminUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler;
}

export async function adminApi<T>(path: string, key: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    "content-type": "application/json",
    ...(options.headers as Record<string, string> | undefined),
  };
  let res: Response;
  try { res = await fetch(path, { ...options, headers, credentials: "same-origin" }); }
  catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new Error("Không kết nối được máy chủ. Kiểm tra mạng và thử lại.");
  }
  if (res.status === 401) {
    if (path !== "/admin/api/login") onUnauthorized?.();
    throw new AdminUnauthorizedError(path === "/admin/api/login" ? "Mật khẩu chưa đúng. Vui lòng kiểm tra lại." : "Phiên đăng nhập đã hết hạn.");
  }
  if (!res.ok) {
    let detail = "";
    try { const body = await res.json(); if (typeof body.detail === "string") detail = body.detail; } catch {}
    if (res.status === 429) throw new Error("Bạn đã thử quá nhiều lần. Vui lòng thử lại sau 10 phút.");
    if (res.status >= 500) throw new Error("Máy chủ đang bận hoặc chưa sẵn sàng. Vui lòng thử lại sau.");
    if (res.status === 405) throw new Error("Giao diện đã cũ. Nhấn Ctrl + F5 để tải bản mới.");
    throw new Error(detail || "Chưa thể thực hiện thao tác. Vui lòng kiểm tra và thử lại.");
  }
  return res.json();
}

export const money = (value: any) => `${Number(value || 0).toLocaleString("vi-VN")}đ`;

export const text = (value: any) => (value === null || value === undefined || value === "" ? "—" : String(value));

/** Parse thời gian đơn (created_at hoặc ORDYYYYMMDDHHMMSS… trong order_id). */
export function orderTimeMs(o: AnyRow): number {
  const raw = text(o.created_at);
  if (raw !== "—") {
    const t = Date.parse(raw.includes("T") ? raw : raw.replace(" ", "T"));
    if (!Number.isNaN(t)) return t;
  }
  const m = /^ORD(\d{14})/i.exec(text(o.order_id));
  if (m) {
    const s = m[1];
    const iso = `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}T${s.slice(8, 10)}:${s.slice(10, 12)}:${s.slice(12, 14)}`;
    const t = Date.parse(iso);
    if (!Number.isNaN(t)) return t;
  }
  return 0;
}

/** Đơn mới nhất ở đầu danh sách. */
export function sortOrdersNewestFirst(orders: AnyRow[]): AnyRow[] {
  return [...orders].sort((a, b) => orderTimeMs(b) - orderTimeMs(a));
}
