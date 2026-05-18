export type AnyRow = Record<string, any>;

export interface AdminSnapshot {
  generated_at: string;
  timezone: string;
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

export async function adminApi<T>(path: string, key: string, options: RequestInit = {}): Promise<T> {
  const sep = path.includes("?") ? "&" : "?";
  const res = await fetch(`${path}${sep}key=${encodeURIComponent(key)}`, {
    headers: { "content-type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json();
}

export const money = (value: any) => `${Number(value || 0).toLocaleString("vi-VN")}đ`;

export const text = (value: any) => (value === null || value === undefined || value === "" ? "—" : String(value));
