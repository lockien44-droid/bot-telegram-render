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
    "x-admin-key": key,
    ...(options.headers as Record<string, string> | undefined),
  };
  const res = await fetch(path, { ...options, headers });
  if (res.status === 401) {
    onUnauthorized?.();
    throw new AdminUnauthorizedError();
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json();
}

export const money = (value: any) => `${Number(value || 0).toLocaleString("vi-VN")}đ`;

export const text = (value: any) => (value === null || value === undefined || value === "" ? "—" : String(value));
