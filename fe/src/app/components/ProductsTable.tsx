import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Badge } from "./ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "./ui/table";
import { Package } from "lucide-react";

export interface Product {
  name: string;
  stock_code: string;
  price: number;
  ready_qty: number;
}

interface ProductsTableProps {
  products: Product[];
}

export function ProductsTable({ products }: ProductsTableProps) {
  return (
    <Card className="shadow-sm">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2">
          <Package size={18} />
          Sản phẩm đang bán
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Tên sản phẩm</TableHead>
              <TableHead>Stock Code</TableHead>
              <TableHead className="text-right">Giá</TableHead>
              <TableHead className="text-center">Tồn kho (READY)</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {products.length === 0 ? (
              <TableRow>
                <TableCell colSpan={4} className="text-center text-muted-foreground py-8">
                  Không có sản phẩm nào
                </TableCell>
              </TableRow>
            ) : (
              products.map((p) => (
                <TableRow key={p.stock_code}>
                  <TableCell className="font-medium">{p.name}</TableCell>
                  <TableCell>
                    <code className="bg-muted px-1.5 py-0.5 rounded text-xs">{p.stock_code}</code>
                  </TableCell>
                  <TableCell className="text-right text-emerald-700">
                    {p.price.toLocaleString("vi-VN")}đ
                  </TableCell>
                  <TableCell className="text-center">
                    <Badge
                      variant={p.ready_qty > 10 ? "default" : p.ready_qty > 0 ? "secondary" : "destructive"}
                    >
                      {p.ready_qty}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
