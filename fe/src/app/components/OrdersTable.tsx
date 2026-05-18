import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Badge } from "./ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "./ui/table";
import { ClipboardList } from "lucide-react";

export interface Order {
  order_id: string;
  user_id: string;
  stock_code: string;
  qty: number;
  total: number;
  status: "PENDING" | "PAID" | "DELIVERED" | "EXPIRED" | "CANCELLED";
  created_at: string;
  paid_at: string | null;
  delivered_at: string | null;
}

interface OrdersTableProps {
  orders: Order[];
}

const statusConfig: Record<Order["status"], { label: string; variant: "default" | "secondary" | "destructive" | "outline" }> = {
  PENDING:   { label: "Chờ thanh toán", variant: "outline" },
  PAID:      { label: "Đã thanh toán",  variant: "secondary" },
  DELIVERED: { label: "Đã giao",        variant: "default" },
  EXPIRED:   { label: "Hết hạn",        variant: "destructive" },
  CANCELLED: { label: "Đã huỷ",         variant: "destructive" },
};

function fmt(dateStr: string | null) {
  if (!dateStr) return "—";
  return new Date(dateStr).toLocaleString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh", hour12: false });
}

export function OrdersTable({ orders }: OrdersTableProps) {
  return (
    <Card className="shadow-sm">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2">
          <ClipboardList size={18} />
          Đơn hàng mới nhất
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0 overflow-x-auto">
        <Table className="min-w-[800px]">
          <TableHeader>
            <TableRow>
              <TableHead>Order ID</TableHead>
              <TableHead>User ID</TableHead>
              <TableHead>Stock Code</TableHead>
              <TableHead className="text-center">SL</TableHead>
              <TableHead className="text-right">Tổng tiền</TableHead>
              <TableHead className="text-center">Trạng thái</TableHead>
              <TableHead>Tạo lúc</TableHead>
              <TableHead>Thanh toán</TableHead>
              <TableHead>Giao hàng</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {orders.length === 0 ? (
              <TableRow>
                <TableCell colSpan={9} className="text-center text-muted-foreground py-8">
                  Không có đơn hàng nào
                </TableCell>
              </TableRow>
            ) : (
              orders.map((o) => (
                <TableRow key={o.order_id}>
                  <TableCell>
                    <code className="text-xs bg-muted px-1.5 py-0.5 rounded">{o.order_id}</code>
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">{o.user_id}</TableCell>
                  <TableCell>
                    <code className="text-xs bg-muted px-1.5 py-0.5 rounded">{o.stock_code}</code>
                  </TableCell>
                  <TableCell className="text-center">{o.qty}</TableCell>
                  <TableCell className="text-right text-emerald-700">
                    {o.total.toLocaleString("vi-VN")}đ
                  </TableCell>
                  <TableCell className="text-center">
                    <Badge variant={statusConfig[o.status].variant}>
                      {statusConfig[o.status].label}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground whitespace-nowrap">{fmt(o.created_at)}</TableCell>
                  <TableCell className="text-xs text-muted-foreground whitespace-nowrap">{fmt(o.paid_at)}</TableCell>
                  <TableCell className="text-xs text-muted-foreground whitespace-nowrap">{fmt(o.delivered_at)}</TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
