import type { AdminSnapshot, AnyRow } from "./api";

export interface RevenuePeriod {
  orders: number;
  revenue: number;
}

export interface RevenueStats {
  today: RevenuePeriod;
  month: RevenuePeriod;
  year: RevenuePeriod;
}

export const PAID_STATUSES = new Set(["PAID", "DELIVERED"]);

export type RevenuePeriodKey = "today" | "month" | "year" | "all";

export function isPaidOrder(order: AnyRow): boolean {
  return PAID_STATUSES.has(String(order.status ?? "").toUpperCase());
}

function periodStarts(now = new Date()) {
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return {
    todayStart,
    monthStart: new Date(now.getFullYear(), now.getMonth(), 1),
    yearStart: new Date(now.getFullYear(), 0, 1),
  };
}

export function filterPaidOrdersByPeriod(orders: AnyRow[], period: RevenuePeriodKey): AnyRow[] {
  const paid = orders.filter(isPaidOrder);
  if (period === "all") {
    return paid.sort((a, b) => String(b.delivered_at || b.paid_at || b.created_at).localeCompare(String(a.delivered_at || a.paid_at || a.created_at)));
  }
  const { todayStart, monthStart, yearStart } = periodStarts();
  const start = period === "today" ? todayStart : period === "month" ? monthStart : yearStart;
  return paid
    .filter((o) => {
      const dt = orderDt(o);
      return dt && dt >= start;
    })
    .sort((a, b) => String(b.delivered_at || b.paid_at || b.created_at).localeCompare(String(a.delivered_at || a.paid_at || a.created_at)));
}

function parseDt(value: string): Date | null {
  const s = (value || "").trim();
  if (!s) return null;
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/);
  if (!m) return null;
  return new Date(
    Number(m[1]),
    Number(m[2]) - 1,
    Number(m[3]),
    Number(m[4]),
    Number(m[5]),
    Number(m[6]),
  );
}

function orderDt(order: AnyRow): Date | null {
  for (const key of ["delivered_at", "paid_at", "created_at"]) {
    const dt = parseDt(String(order[key] ?? ""));
    if (dt) return dt;
  }
  return null;
}

export function computeRevenueStatsFromOrders(orders: AnyRow[]): RevenueStats {
  const buckets: RevenueStats = {
    today: { orders: 0, revenue: 0 },
    month: { orders: 0, revenue: 0 },
    year: { orders: 0, revenue: 0 },
  };
  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);
  const yearStart = new Date(now.getFullYear(), 0, 1);

  for (const order of orders) {
    const status = String(order.status ?? "").toUpperCase();
    if (!PAID_STATUSES.has(status)) continue;
    const total = Number(order.total) || 0;
    const dt = orderDt(order);
    if (!dt) continue;
    if (dt >= todayStart) {
      buckets.today.orders += 1;
      buckets.today.revenue += total;
    }
    if (dt >= monthStart) {
      buckets.month.orders += 1;
      buckets.month.revenue += total;
    }
    if (dt >= yearStart) {
      buckets.year.orders += 1;
      buckets.year.revenue += total;
    }
  }
  return buckets;
}

export function getRevenueStats(data: AdminSnapshot): RevenueStats {
  const raw = (data.summary as any).revenue_stats;
  if (raw?.today && raw?.month && raw?.year) {
    return {
      today: { orders: Number(raw.today.orders) || 0, revenue: Number(raw.today.revenue) || 0 },
      month: { orders: Number(raw.month.orders) || 0, revenue: Number(raw.month.revenue) || 0 },
      year: { orders: Number(raw.year.orders) || 0, revenue: Number(raw.year.revenue) || 0 },
    };
  }
  return computeRevenueStatsFromOrders(data.orders || []);
}

export function formatRevenueDateLabel(): string {
  return new Date().toLocaleDateString("vi-VN", {
    weekday: "long",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}
