import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { ShoppingCart, DollarSign, Clock, CheckCircle, XCircle, RefreshCw } from "lucide-react";

export interface StatsData {
  totalOrders: number;
  revenue: number;
  pendingOrders: number;
  deliveredOrders: number;
  expiredCancelledOrders: number;
  lastUpdated: string;
}

interface StatsCardsProps {
  data: StatsData;
}

export function StatsCards({ data }: StatsCardsProps) {
  const cards = [
    {
      title: "Tổng đơn",
      value: data.totalOrders.toLocaleString(),
      icon: <ShoppingCart size={20} />,
      color: "text-blue-600",
      bg: "bg-blue-50",
    },
    {
      title: "Doanh thu",
      value: `${data.revenue.toLocaleString("vi-VN")}đ`,
      icon: <DollarSign size={20} />,
      color: "text-emerald-600",
      bg: "bg-emerald-50",
    },
    {
      title: "Đơn PENDING",
      value: data.pendingOrders.toLocaleString(),
      icon: <Clock size={20} />,
      color: "text-amber-600",
      bg: "bg-amber-50",
    },
    {
      title: "Đơn DELIVERED",
      value: data.deliveredOrders.toLocaleString(),
      icon: <CheckCircle size={20} />,
      color: "text-green-600",
      bg: "bg-green-50",
    },
    {
      title: "EXPIRED / CANCELLED",
      value: data.expiredCancelledOrders.toLocaleString(),
      icon: <XCircle size={20} />,
      color: "text-red-600",
      bg: "bg-red-50",
    },
  ];

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-muted-foreground text-sm">
        <RefreshCw size={14} />
        <span>Cập nhật lúc: {data.lastUpdated}</span>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {cards.map((card) => (
          <Card key={card.title} className="shadow-sm">
            <CardHeader className="pb-2 pt-4 px-4">
              <div className="flex items-center justify-between">
                <CardTitle className="text-xs text-muted-foreground">{card.title}</CardTitle>
                <div className={`${card.bg} ${card.color} p-1.5 rounded-md`}>
                  {card.icon}
                </div>
              </div>
            </CardHeader>
            <CardContent className="px-4 pb-4">
              <p className={`text-lg ${card.color} truncate`}>{card.value}</p>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
