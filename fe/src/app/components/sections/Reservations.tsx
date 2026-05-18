import { useState } from "react";
import { Card, CardContent } from "../ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../ui/table";
import { Input } from "../ui/input";
import { BookMarked, Search } from "lucide-react";
import { text, type AdminSnapshot } from "../../api";

interface Props {
  data: AdminSnapshot | null;
}

export function Reservations({ data }: Props) {
  const [search, setSearch] = useState("");
  const rows = data?.reservations || [];
  const visible = rows.filter((r) => {
    const hay = `${text(r.order_id)} ${text(r.item_id)} ${text(r.stock_code)}`.toLowerCase();
    return !search || hay.includes(search.toLowerCase());
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="flex items-center gap-2"><BookMarked size={20} /> Lịch sử giữ hàng</h2>
        <span className="text-sm text-muted-foreground">{rows.length} dòng</span>
      </div>
      <div className="relative max-w-xs">
        <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <Input className="pl-8" placeholder="Order ID / Item ID / Code" value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>
      <Card className="shadow-sm">
        <CardContent className="p-0 overflow-x-auto">
          <Table className="min-w-[860px]">
            <TableHeader>
              <TableRow>
                <TableHead>Order ID</TableHead>
                <TableHead>Item ID</TableHead>
                <TableHead>Stock Code</TableHead>
                <TableHead>Reserved</TableHead>
                <TableHead>Expires</TableHead>
                <TableHead>Released</TableHead>
                <TableHead>Sold</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((r, idx) => (
                <TableRow key={`${text(r.order_id)}-${text(r.item_id)}-${idx}`}>
                  <TableCell><code className="text-xs bg-muted px-1.5 py-0.5 rounded">{text(r.order_id)}</code></TableCell>
                  <TableCell className="text-xs text-muted-foreground">{text(r.item_id)}</TableCell>
                  <TableCell><code className="text-xs bg-muted px-1.5 py-0.5 rounded">{text(r.stock_code)}</code></TableCell>
                  <TableCell className="text-xs text-muted-foreground whitespace-nowrap">{text(r.reserved_at)}</TableCell>
                  <TableCell className="text-xs text-muted-foreground whitespace-nowrap">{text(r.expires_at)}</TableCell>
                  <TableCell className="text-xs text-muted-foreground whitespace-nowrap">{text(r.released_at)}</TableCell>
                  <TableCell className="text-xs text-muted-foreground whitespace-nowrap">{text(r.sold_at)}</TableCell>
                </TableRow>
              ))}
              {visible.length === 0 && <TableRow><TableCell colSpan={7} className="text-center text-muted-foreground py-8">Không có lịch sử giữ hàng</TableCell></TableRow>}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
