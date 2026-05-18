import { useState } from "react";
import { Card, CardContent } from "../ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../ui/table";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { Badge } from "../ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../ui/dialog";
import { Plus, Pencil, Package } from "lucide-react";
import { adminApi, money, text, type AdminSnapshot, type AnyRow } from "../../api";

interface Props {
  data: AdminSnapshot | null;
  adminKey: string;
  refresh: () => Promise<void>;
  embedded?: boolean;
}

const EMPTY = { product_id: "", name: "", stock_code: "", price: "", description: "" };

export function Products({ data, adminKey, refresh, embedded }: Props) {
  const [modalOpen, setModalOpen] = useState(false);
  const [form, setForm] = useState({ ...EMPTY });
  const [saving, setSaving] = useState(false);

  const openAdd = () => { setForm({ ...EMPTY }); setModalOpen(true); };
  const openEdit = (p: AnyRow) => {
    setForm({
      product_id: text(p.product_id) === "—" ? "" : text(p.product_id),
      name: text(p.name) === "—" ? "" : text(p.name),
      stock_code: text(p.stock_code) === "—" ? "" : text(p.stock_code),
      price: String(p.price || ""),
      description: text(p.description) === "—" ? "" : text(p.description),
    });
    setModalOpen(true);
  };

  const save = async () => {
    setSaving(true);
    try {
      await adminApi("/admin/api/products", adminKey, { method: "POST", body: JSON.stringify(form) });
      setModalOpen(false);
      await refresh();
    } finally {
      setSaving(false);
    }
  };

  const products = data?.products || [];

  return (
    <div className="space-y-4">
      <div className={`flex items-center gap-2 ${embedded ? "justify-end" : "justify-between"}`}>
        {!embedded && <h2 className="flex items-center gap-2"><Package size={20} /> Sản phẩm</h2>}
        <Button size="sm" className="gap-1.5" onClick={openAdd}><Plus size={15} /> Thêm sản phẩm</Button>
      </div>

      <Card className="shadow-sm">
        <CardContent className="p-0 overflow-x-auto">
          <Table className="min-w-[760px]">
            <TableHeader>
              <TableRow>
                <TableHead>Tên sản phẩm</TableHead>
                <TableHead>Stock Code</TableHead>
                <TableHead className="text-right">Giá</TableHead>
                <TableHead className="text-center">READY</TableHead>
                <TableHead className="text-center">HELD</TableHead>
                <TableHead className="text-center">SOLD</TableHead>
                <TableHead>Mô tả</TableHead>
                <TableHead className="text-center">Sửa</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {products.map((p) => (
                <TableRow key={p.product_id || p.stock_code}>
                  <TableCell className="font-medium">{text(p.name)}</TableCell>
                  <TableCell><code className="bg-muted px-1.5 py-0.5 rounded text-xs">{text(p.stock_code)}</code></TableCell>
                  <TableCell className="text-right text-emerald-700">{money(p.price)}</TableCell>
                  <TableCell className="text-center"><Badge variant={Number(p.READY) > 0 ? "default" : "destructive"}>{p.READY || 0}</Badge></TableCell>
                  <TableCell className="text-center"><Badge variant={Number(p.HELD) > 0 ? "secondary" : "outline"}>{p.HELD || 0}</Badge></TableCell>
                  <TableCell className="text-center"><Badge variant="outline">{p.SOLD || 0}</Badge></TableCell>
                  <TableCell className="text-sm text-muted-foreground max-w-[220px] truncate">{text(p.description)}</TableCell>
                  <TableCell className="text-center">
                    <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => openEdit(p)}><Pencil size={14} /></Button>
                  </TableCell>
                </TableRow>
              ))}
              {products.length === 0 && <TableRow><TableCell colSpan={8} className="text-center text-muted-foreground py-8">Chưa có sản phẩm</TableCell></TableRow>}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog open={modalOpen} onOpenChange={setModalOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader><DialogTitle>{form.product_id ? "Sửa sản phẩm" : "Thêm sản phẩm"}</DialogTitle></DialogHeader>
          <div className="space-y-3 py-2">
            <div className="space-y-1"><Label>Product ID</Label><Input value={form.product_id} onChange={(e) => setForm({ ...form, product_id: e.target.value })} placeholder="Bỏ trống để tự tạo" /></div>
            <div className="space-y-1"><Label>Tên sản phẩm</Label><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
            <div className="space-y-1"><Label>Stock Code</Label><Input value={form.stock_code} onChange={(e) => setForm({ ...form, stock_code: e.target.value.toUpperCase() })} /></div>
            <div className="space-y-1"><Label>Giá</Label><Input type="number" value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} /></div>
            <div className="space-y-1"><Label>Mô tả</Label><Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setModalOpen(false)}>Hủy</Button>
            <Button onClick={save} disabled={saving || !form.name || !form.stock_code}>{saving ? "Đang lưu..." : "Lưu"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
