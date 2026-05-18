import { useState } from "react";
import { Card, CardContent } from "../ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../ui/table";
import { Input } from "../ui/input";
import { Truck, Search } from "lucide-react";
import { text, type AdminSnapshot } from "../../api";

interface Props {
  data: AdminSnapshot | null;
}

export function Fulfillments({ data }: Props) {
  const [search, setSearch] = useState("");
  const rows = data?.deliveries || data?.fulfillments || [];
  const visible = rows.filter((f) => {
    const hay = `${text(f.order_id)} ${text(f.item_id)} ${text(f.stock_code)}`.toLowerCase();
    return !search || hay.includes(search.toLowerCase());
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="flex items-center gap-2"><Truck size={20} /> Lịch sử giao hàng</h2>
        <span className="text-sm text-muted-foreground">{rows.length} dòng</span>
      </div>
      <div className="relative max-w-xs">
        <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <Input className="pl-8" placeholder="Order ID / Item ID / Code" value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>
      <Card className="shadow-sm">
        <CardContent className="p-0 overflow-x-auto">
          <Table className="min-w-[760px]">
            <TableHeader>
              <TableRow>
                <TableHead>Order ID</TableHead>
                <TableHead>Item ID</TableHead>
                <TableHead>Stock Code</TableHead>
                <TableHead>Delivered</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((f, idx) => (
                <TableRow key={`${text(f.order_id)}-${text(f.item_id)}-${idx}`}>
                  <TableCell><code className="text-xs bg-muted px-1.5 py-0.5 rounded">{text(f.order_id)}</code></TableCell>
                  <TableCell className="text-xs text-muted-foreground">{text(f.item_id)}</TableCell>
                  <TableCell><code className="text-xs bg-muted px-1.5 py-0.5 rounded">{text(f.stock_code)}</code></TableCell>
                  <TableCell className="text-xs text-muted-foreground whitespace-nowrap">{text(f.delivered_at)}</TableCell>
                </TableRow>
              ))}
              {visible.length === 0 && <TableRow><TableCell colSpan={4} className="text-center text-muted-foreground py-8">Không có lịch sử giao hàng</TableCell></TableRow>}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
