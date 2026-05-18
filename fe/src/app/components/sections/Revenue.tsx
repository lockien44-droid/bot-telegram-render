import { useMemo, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Badge } from "../ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../ui/tabs";
import { DollarSign, TrendingUp } from "lucide-react";
import { money, text, type AdminSnapshot, type AnyRow } from "../../api";
import {
  filterPaidOrdersByPeriod,
  formatRevenueDateLabel,
  getRevenueStats,
  isPaidOrder,
  type RevenuePeriodKey,
} from "../../revenue";

interface RevenueProps {
  data: AdminSnapshot | null;
}

export function Revenue({ data }: RevenueProps) {
  const [period, setPeriod] = useState<RevenuePeriodKey>("today");

  const stats = useMemo(() => (data ? getRevenueStats(data) : null), [data]);
  const allOrders = data?.orders || [];

  const allTime = useMemo(() => {
    const paid = allOrders.filter(isPaidOrder);
    const revenue =
      data?.summary.revenue_all ??
      paid.reduce((sum, o) => sum + (Number(o.total) || 0), 0);
    return { orders: paid.length, revenue };
  }, [allOrders, data?.summary.revenue_all]);

  const orders = useMemo(
    () => filterPaidOrdersByPeriod(allOrders, period),
    [allOrders, period],
  );

  if (!data || !stats) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-muted-foreground">Đang tải dữ liệu...</CardContent>
      </Card>
    );
  }

  const periodStats: Record<RevenuePeriodKey, { label: string; orders: number; revenue: number }> = {
    today: { label: "Hôm nay", ...stats.today },
    month: { label: "Tháng này", ...stats.month },
    year: { label: "Năm nay", ...stats.year },
    all: { label: "Tất cả", ...allTime },
  };

  const active = periodStats[period];

  return (
    <div className="space-y-5">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-semibold">
          <DollarSign size={22} className="text-emerald-600" />
          Doanh thu
        </h2>
        <p className="text-xs text-muted-foreground mt-1">
          Đơn PAID / DELIVERED · {formatRevenueDateLabel()} · {data.timezone}. Bảng đơn theo snapshot (tối đa {allOrders.length} đơn mới nhất); tổng &quot;mọi thời&quot; lấy từ server.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <SummaryCard label="Hôm nay" highlight {...stats.today} />
        <SummaryCard label="Tháng này" {...stats.month} />
        <SummaryCard label="Năm nay" {...stats.year} />
      </div>

      <Card className="shadow-sm border-emerald-100">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2 text-muted-foreground font-medium">
            <TrendingUp size={16} className="text-emerald-600" />
            Tổng doanh thu (mọi thời)
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          <p className="text-2xl font-bold text-emerald-700">{money(allTime.revenue)}</p>
          <p className="text-xs text-muted-foreground mt-1">{allTime.orders} đơn đã thanh toán / giao</p>
        </CardContent>
      </Card>

      <Tabs value={period} onValueChange={(v) => setPeriod(v as RevenuePeriodKey)}>
        <TabsList className="w-full flex flex-wrap h-auto gap-1">
          <TabsTrigger value="today">Hôm nay</TabsTrigger>
          <TabsTrigger value="month">Tháng</TabsTrigger>
          <TabsTrigger value="year">Năm</TabsTrigger>
          <TabsTrigger value="all">Tất cả</TabsTrigger>
        </TabsList>

        {(["today", "month", "year", "all"] as RevenuePeriodKey[]).map((key) => (
          <TabsContent key={key} value={key} className="mt-4 space-y-3">
            <div className="flex flex-wrap items-end justify-between gap-2 rounded-lg border bg-emerald-50/50 px-4 py-3">
              <div>
                <p className="text-sm font-semibold text-emerald-900">{periodStats[key].label}</p>
                <p className="text-xs text-muted-foreground">{periodStats[key].orders} đơn</p>
              </div>
              <p className="text-xl font-bold text-emerald-700">{money(periodStats[key].revenue)}</p>
            </div>

            {key === period && (
              <Card className="shadow-sm">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">Danh sách đơn ({orders.length})</CardTitle>
                </CardHeader>
                <CardContent className="p-0 overflow-x-auto">
                  <RevenueOrdersTable
                    orders={orders}
                    emptyLabel={`Chưa có đơn trong kỳ "${active.label}"`}
                  />
                </CardContent>
              </Card>
            )}
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}

function SummaryCard({
  label,
  orders,
  revenue,
  highlight = false,
}: {
  label: string;
  orders: number;
  revenue: number;
  highlight?: boolean;
}) {
  return (
    <Card className={highlight ? "border-emerald-200 bg-emerald-50/40 shadow-sm" : "shadow-sm"}>
      <CardHeader className="pb-1 pt-4 px-4">
        <CardTitle className="text-xs text-muted-foreground">{label}</CardTitle>
      </CardHeader>
      <CardContent className="px-4 pb-4">
        <p className={`text-xl font-bold ${highlight ? "text-emerald-700" : "text-emerald-600"}`}>
          {money(revenue)}
        </p>
        <p className="text-xs text-muted-foreground mt-1">{orders} đơn</p>
      </CardContent>
    </Card>
  );
}

function RevenueOrdersTable({ orders, emptyLabel }: { orders: AnyRow[]; emptyLabel: string }) {
  if (!orders.length) {
    return <p className="py-8 text-center text-sm text-muted-foreground">{emptyLabel}</p>;
  }

  return (
    <Table className="min-w-[720px]">
      <TableHeader>
        <TableRow>
          <TableHead>Order ID</TableHead>
          <TableHead>Stock</TableHead>
          <TableHead className="text-right">Tổng tiền</TableHead>
          <TableHead className="text-center">Trạng thái</TableHead>
          <TableHead>Thanh toán / giao</TableHead>
          <TableHead>Tạo lúc</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {orders.map((o) => {
          const status = text(o.status).toUpperCase();
          const paidAt = text(o.delivered_at) !== "—" ? text(o.delivered_at) : text(o.paid_at);
          return (
            <TableRow key={text(o.order_id)}>
              <TableCell>
                <code className="bg-muted px-1.5 py-0.5 rounded text-xs">{text(o.order_id)}</code>
              </TableCell>
              <TableCell>{text(o.stock_code)}</TableCell>
              <TableCell className="text-right font-medium text-emerald-700">{money(o.total)}</TableCell>
              <TableCell className="text-center">
                <Badge variant={status === "DELIVERED" ? "default" : "secondary"}>{status}</Badge>
              </TableCell>
              <TableCell className="text-xs text-muted-foreground whitespace-nowrap">{paidAt}</TableCell>
              <TableCell className="text-xs text-muted-foreground whitespace-nowrap">{text(o.created_at)}</TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
