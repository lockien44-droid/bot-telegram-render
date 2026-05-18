import { useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Badge } from "../ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../ui/table";
import { ShoppingCart, DollarSign, Clock, CheckCircle, XCircle, Users, Package, Warehouse, Bell } from "lucide-react";
import { money, text, type AdminSnapshot } from "../../api";
import type { OrderNotification } from "../../notifications";
import { NotificationFeed, NotificationFeedHeader } from "../NotificationFeed";
import { getRevenueStats } from "../../revenue";

interface OverviewProps {
  data: AdminSnapshot | null;
  notifications?: OrderNotification[];
  onOpenOrders?: (status?: string) => void;
  onOpenInventory?: (status?: string, stockCode?: string) => void;
  onOpenUsers?: () => void;
  onOpenNotifications?: () => void;
  onOpenNotificationOrder?: (orderId: string, status?: string) => void;
  onMarkNotificationsRead?: () => void;
  onOpenRevenue?: () => void;
}

export function Overview({
  data,
  notifications = [],
  onOpenOrders,
  onOpenInventory,
  onOpenUsers,
  onOpenNotifications,
  onOpenNotificationOrder,
  onMarkNotificationsRead,
  onOpenRevenue,
}: OverviewProps) {
  const revenueStats = useMemo(() => (data ? getRevenueStats(data) : null), [data]);

  if (!data) return <EmptyState />;

  const s = data.summary;
  const c = s.status_counts || {};
  const unreadNotify = notifications.filter((n) => !n.read).length;
  const todayRevenue = revenueStats?.today.revenue ?? s.revenue;
  const cards = [
    { title: "Tổng đơn", value: s.orders, icon: <ShoppingCart size={20} />, color: "text-blue-600", bg: "bg-blue-50", onClick: () => onOpenOrders?.() },
    {
      title: "Doanh thu hôm nay",
      value: money(todayRevenue),
      sub: revenueStats ? `${revenueStats.today.orders} đơn` : undefined,
      icon: <DollarSign size={20} />,
      color: "text-emerald-600",
      bg: "bg-emerald-50",
      onClick: () => onOpenRevenue?.(),
    },
    {
      title: "Thông báo",
      value: unreadNotify > 0 ? unreadNotify : notifications.length,
      icon: <Bell size={20} />,
      color: unreadNotify > 0 ? "text-red-600" : "text-emerald-600",
      bg: unreadNotify > 0 ? "bg-red-50" : "bg-emerald-50",
      onClick: () => onOpenNotifications?.(),
    },
    { title: "PENDING", value: c.PENDING || 0, icon: <Clock size={20} />, color: "text-amber-600", bg: "bg-amber-50", onClick: () => onOpenOrders?.("PENDING") },
    { title: "DELIVERED", value: c.DELIVERED || 0, icon: <CheckCircle size={20} />, color: "text-green-600", bg: "bg-green-50", onClick: () => onOpenOrders?.("DELIVERED") },
    { title: "Lỗi / hủy", value: (c.EXPIRED || 0) + (c.CANCELLED || 0), icon: <XCircle size={20} />, color: "text-red-600", bg: "bg-red-50", onClick: () => onOpenOrders?.("FAILED") },
    { title: "Khách", value: s.users, icon: <Users size={20} />, color: "text-sky-600", bg: "bg-sky-50", onClick: () => onOpenUsers?.() },
    { title: "READY", value: s.stock_ready, icon: <Warehouse size={20} />, color: "text-emerald-600", bg: "bg-emerald-50", onClick: () => onOpenInventory?.("READY") },
    { title: "HELD", value: s.stock_held, icon: <Clock size={20} />, color: "text-amber-600", bg: "bg-amber-50", onClick: () => onOpenInventory?.("HELD") },
    { title: "SOLD", value: s.stock_sold, icon: <Package size={20} />, color: "text-indigo-600", bg: "bg-indigo-50", onClick: () => onOpenInventory?.("SOLD") },
  ];

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
        {cards.map((card) => (
          <Card key={card.title} onClick={card.onClick} className="shadow-sm cursor-pointer transition hover:-translate-y-0.5 hover:shadow-md">
            <CardHeader className="pb-1 pt-4 px-4">
              <div className="flex items-center justify-between gap-2">
                <CardTitle className="text-xs text-muted-foreground">{card.title}</CardTitle>
                <div className={`${card.bg} ${card.color} p-1.5 rounded-md`}>{card.icon}</div>
              </div>
            </CardHeader>
            <CardContent className="px-4 pb-4">
              <p className={`text-lg ${card.color} truncate`}>{card.value}</p>
              {"sub" in card && card.sub ? (
                <p className="text-[11px] text-muted-foreground mt-0.5">{card.sub}</p>
              ) : null}
            </CardContent>
          </Card>
        ))}
      </div>


      <Card className="shadow-sm">
        <CardHeader className="pb-3">
          <NotificationFeedHeader
            unread={unreadNotify}
            total={notifications.length}
            onViewAll={onOpenNotifications}
            onMarkAllRead={onMarkNotificationsRead}
          />
        </CardHeader>
        <CardContent>
          <NotificationFeed
            items={notifications}
            limit={6}
            compact
            onOpenOrder={(orderId, status) => onOpenNotificationOrder?.(orderId, status)}
          />
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle className="text-sm">Sản phẩm đang bán</CardTitle>
          </CardHeader>
          <CardContent className="p-0 overflow-x-auto">
            <Table className="min-w-[620px]">
              <TableHeader>
                <TableRow>
                  <TableHead>Tên sản phẩm</TableHead>
                  <TableHead>Stock</TableHead>
                  <TableHead className="text-right">Giá</TableHead>
                  <TableHead className="text-center">READY</TableHead>
                  <TableHead className="text-center">HELD</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.products.map((p) => (
                  <TableRow key={p.product_id || p.stock_code} className="cursor-pointer" onClick={() => onOpenInventory?.("ALL", text(p.stock_code))}>
                    <TableCell className="font-medium">{text(p.name)}</TableCell>
                    <TableCell><code className="bg-muted px-1.5 py-0.5 rounded text-xs">{text(p.stock_code)}</code></TableCell>
                    <TableCell className="text-right text-emerald-700">{money(p.price)}</TableCell>
                    <TableCell className="text-center"><Badge variant={Number(p.READY) > 0 ? "default" : "destructive"}>{p.READY || 0}</Badge></TableCell>
                    <TableCell className="text-center"><Badge variant={Number(p.HELD) > 0 ? "secondary" : "outline"}>{p.HELD || 0}</Badge></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle className="text-sm">Đơn hàng mới nhất</CardTitle>
          </CardHeader>
          <CardContent className="p-0 overflow-x-auto">
            <Table className="min-w-[700px]">
              <TableHeader>
                <TableRow>
                  <TableHead>Order ID</TableHead>
                  <TableHead>Stock</TableHead>
                  <TableHead className="text-right">Tổng tiền</TableHead>
                  <TableHead className="text-center">Trạng thái</TableHead>
                  <TableHead>Tạo lúc</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.orders.slice(0, 10).map((o) => (
                  <TableRow key={o.order_id}>
                    <TableCell><code className="bg-muted px-1.5 py-0.5 rounded text-xs">{text(o.order_id)}</code></TableCell>
                    <TableCell>{text(o.stock_code)}</TableCell>
                    <TableCell className="text-right text-emerald-700">{money(o.total)}</TableCell>
                    <TableCell className="text-center"><StatusBadge status={text(o.status)} /></TableCell>
                    <TableCell className="text-xs text-muted-foreground whitespace-nowrap">{text(o.created_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const bad = status === "EXPIRED" || status === "CANCELLED";
  const good = status === "DELIVERED" || status === "PAID";
  return <Badge variant={bad ? "destructive" : good ? "default" : "secondary"}>{status}</Badge>;
}

function EmptyState() {
  return <Card><CardContent className="py-10 text-center text-muted-foreground">Đang tải dữ liệu...</CardContent></Card>;
}

