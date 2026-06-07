import { useMemo, useRef, useState } from "react";
import { Card, CardContent } from "../ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../ui/table";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { Badge } from "../ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "../ui/alert-dialog";
import { ArrowUpDown, ChevronDown, Plus, Pencil, Package, Trash2, Megaphone, Send } from "lucide-react";
import { Textarea } from "../ui/textarea";
import { Checkbox } from "../ui/checkbox";
import { toast } from "sonner";
import { adminApi, money, text, type AdminSnapshot, type AnyRow } from "../../api";

interface Props {
  data: AdminSnapshot | null;
  adminKey: string;
  refresh: () => Promise<void>;
  embedded?: boolean;
  onAddStock?: (stockCode: string) => void;
}

const EMPTY = { product_id: "", name: "", stock_code: "", price: "", category: "", description: "", usage_guide: "" };

function inferCategoryName(p: AnyRow): string {
  const category = text(p.category);
  if (category !== "—" && category.trim()) return category;
  const hay = `${text(p.name)} ${text(p.stock_code)}`.toLowerCase().replace(/\s+/g, "");
  if (hay.includes("capcut")) return "CAPCUT";
  if (hay.includes("kiro")) return "KIRO";
  if (hay.includes("spotify")) return "SPOTIFY";
  if (hay.includes("chatgpt") || hay.includes("gpt") || hay.includes("openai")) return "CHATGPT";
  if (hay.includes("ms365") || hay.includes("365") || hay.includes("office") || hay.includes("microsoft")) return "MICROSOFT";
  return "";
}

export function Products({ data, adminKey, refresh, embedded, onAddStock }: Props) {
  const [modalOpen, setModalOpen] = useState(false);
  const [form, setForm] = useState({ ...EMPTY });
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<AnyRow | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [broadcasting, setBroadcasting] = useState(false);
  const [notifyOpen, setNotifyOpen] = useState(false);
  const [notifyText, setNotifyText] = useState("");
  const [notifySending, setNotifySending] = useState(false);
  const [notifyAddShopBtn, setNotifyAddShopBtn] = useState(true);
  const [notifyConfirmOpen, setNotifyConfirmOpen] = useState(false);
  const [categoryOpen, setCategoryOpen] = useState(false);
  const [sortProducts, setSortProducts] = useState(false);
  const categoryInputRef = useRef<HTMLInputElement | null>(null);

  type BroadcastResult = {
    ok?: number;
    fail?: number;
    recipients?: number;
    skipped?: boolean;
    reason?: string;
    detail?: string;
  };

  const sendUserNotify = async () => {
    const message = notifyText.trim();
    if (!message) {
      toast.error("Nhập nội dung thông báo");
      return;
    }
    setNotifySending(true);
    try {
      const result = await adminApi<BroadcastResult>("/admin/api/users/broadcast", adminKey, {
        method: "POST",
        body: JSON.stringify({
          message,
          parse_mode: "Markdown",
          add_shop_button: notifyAddShopBtn,
        }),
      });
      if (result.skipped) {
        const msg = result.detail || result.reason || "Không gửi được";
        toast.warning(msg);
      } else {
        toast.success(
          `Đã gửi tới ${result.ok ?? 0}/${result.recipients ?? 0} khách${(result.fail ?? 0) ? ` (${result.fail} lỗi)` : ""}`,
        );
        setNotifyOpen(false);
        setNotifyText("");
        setNotifyConfirmOpen(false);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Gửi thông báo thất bại");
    } finally {
      setNotifySending(false);
    }
  };

  const broadcastInventory = async () => {
    if (
      !window.confirm(
        "Gửi danh sách sản phẩm còn hàng tới tất cả khách đã /start bot?",
      )
    ) {
      return;
    }
    setBroadcasting(true);
    try {
      const result = await adminApi<BroadcastResult>("/admin/api/inventory/broadcast", adminKey, {
        method: "POST",
        body: JSON.stringify({ only_in_stock: true }),
      });
      if (result.skipped) {
        toast.warning(`Không gửi được: ${result.reason || "unknown"}`);
      } else {
        toast.success(
          `Đã gửi tới ${result.ok ?? 0}/${result.recipients ?? 0} người${(result.fail ?? 0) ? ` (${result.fail} lỗi)` : ""}`,
        );
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Gửi cập nhật kho thất bại");
    } finally {
      setBroadcasting(false);
    }
  };

  const openAdd = () => { setForm({ ...EMPTY }); setModalOpen(true); };
  const openEdit = (p: AnyRow) => {
    setForm({
      product_id: text(p.product_id) === "—" ? "" : text(p.product_id),
      name: text(p.name) === "—" ? "" : text(p.name),
      stock_code: text(p.stock_code) === "—" ? "" : text(p.stock_code),
      price: String(p.price || ""),
      category: inferCategoryName(p),
      description: text(p.description) === "—" ? "" : text(p.description),
      usage_guide: text(p.usage_guide) === "—" ? "" : text(p.usage_guide),
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

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    const productId = text(deleteTarget.product_id);
    const stockCode = text(deleteTarget.stock_code);
    setDeleting(true);
    try {
      await adminApi("/admin/api/products/delete", adminKey, {
        method: "POST",
        body: JSON.stringify({
          product_id: productId === "—" ? "" : productId,
          stock_code: stockCode === "—" ? "" : stockCode,
        }),
      });
      toast.success("Đã xóa sản phẩm");
      setDeleteTarget(null);
      await refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Không xóa được sản phẩm");
    } finally {
      setDeleting(false);
    }
  };

  const openAddStock = (p: AnyRow) => {
    const code = text(p.stock_code);
    if (code === "—" || !code.trim()) {
      toast.error("Sản phẩm chưa có stock code");
      return;
    }
    onAddStock?.(code.trim().toUpperCase());
  };

  const products = data?.products || [];
  const categories = useMemo(() => {
    const base = ["CAPCUT", "KIRO", "MICROSOFT", "CHATGPT", "SPOTIFY"];
    const seen = new Set<string>();
    const out: string[] = [];
    for (const c of base.concat(products.map(inferCategoryName))) {
      const val = c.trim();
      const key = val.toLowerCase();
      if (!val || seen.has(key)) continue;
      seen.add(key);
      out.push(val);
    }
    return out;
  }, [products]);
  const visibleProducts = useMemo(() => {
    if (!sortProducts) return products;
    return [...products].sort((a, b) => {
      const ca = inferCategoryName(a).toLowerCase();
      const cb = inferCategoryName(b).toLowerCase();
      if (ca !== cb) return ca.localeCompare(cb);
      return text(a.name).localeCompare(text(b.name));
    });
  }, [products, sortProducts]);

  return (
    <div className="space-y-4">
      <div className={`flex items-center gap-2 flex-wrap ${embedded ? "justify-end" : "justify-between"}`}>
        {!embedded && <h2 className="flex items-center gap-2"><Package size={20} /> Sản phẩm</h2>}
        <div className="flex items-center gap-2 flex-wrap">
          <Button
            size="sm"
            variant="outline"
            className="gap-1.5"
            onClick={() => setNotifyOpen(true)}
            disabled={broadcasting || notifySending}
            title="Gửi tin nhắn tùy chỉnh tới khách đã /start bot"
          >
            <Send size={15} /> Thông báo khách
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="gap-1.5"
            onClick={broadcastInventory}
            disabled={broadcasting || notifySending}
            title="Gửi danh sách sản phẩm còn hàng tới tất cả khách đã /start"
          >
            <Megaphone size={15} /> {broadcasting ? "Đang gửi..." : "Cập nhật kho cho khách"}
          </Button>
          <Button
            size="sm"
            variant={sortProducts ? "secondary" : "outline"}
            className="gap-1.5"
            onClick={() => setSortProducts((v) => !v)}
            title="Sắp xếp theo danh mục rồi tên sản phẩm"
          >
            <ArrowUpDown size={15} /> Sắp xếp sản phẩm
          </Button>
          <Button size="sm" className="gap-1.5" onClick={openAdd}><Plus size={15} /> Thêm danh mục</Button>
        </div>
      </div>

      {onAddStock && (
        <p className="text-xs text-muted-foreground">Bấm vào dòng sản phẩm để mở form thêm stock vào kho.</p>
      )}

      <Card className="shadow-sm">
        <CardContent className="p-0 overflow-x-auto">
          <Table className="min-w-[800px]">
            <TableHeader>
              <TableRow>
                <TableHead>Tên sản phẩm</TableHead>
                <TableHead>Danh mục</TableHead>
                <TableHead>Stock Code</TableHead>
                <TableHead className="text-right">Giá</TableHead>
                <TableHead className="text-center">READY</TableHead>
                <TableHead className="text-center">HELD</TableHead>
                <TableHead className="text-center">SOLD</TableHead>
                <TableHead>Mô tả</TableHead>
                <TableHead>Hướng dẫn</TableHead>
                <TableHead className="text-center w-[88px]">Thao tác</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visibleProducts.map((p) => (
                <TableRow
                  key={p.product_id || p.stock_code}
                  className={onAddStock ? "cursor-pointer hover:bg-emerald-50/60" : undefined}
                  onClick={() => onAddStock && openAddStock(p)}
                >
                  <TableCell className="font-medium">{text(p.name)}</TableCell>
                  <TableCell className="text-sm text-muted-foreground">{inferCategoryName(p) || "—"}</TableCell>
                  <TableCell><code className="bg-muted px-1.5 py-0.5 rounded text-xs">{text(p.stock_code)}</code></TableCell>
                  <TableCell className="text-right text-emerald-700">{money(p.price)}</TableCell>
                  <TableCell className="text-center"><Badge variant={Number(p.READY) > 0 ? "default" : "destructive"}>{p.READY || 0}</Badge></TableCell>
                  <TableCell className="text-center"><Badge variant={Number(p.HELD) > 0 ? "secondary" : "outline"}>{p.HELD || 0}</Badge></TableCell>
                  <TableCell className="text-center"><Badge variant="outline">{p.SOLD || 0}</Badge></TableCell>
                  <TableCell className="text-sm text-muted-foreground max-w-[220px] truncate">{text(p.description)}</TableCell>
                  <TableCell className="text-sm text-muted-foreground max-w-[240px] truncate">{text(p.usage_guide)}</TableCell>
                  <TableCell className="text-center" onClick={(e) => e.stopPropagation()}>
                    <div className="flex items-center justify-center gap-0.5">
                      <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => openEdit(p)} title="Sửa">
                        <Pencil size={14} />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-destructive hover:text-destructive"
                        onClick={() => setDeleteTarget(p)}
                        title="Xóa"
                      >
                        <Trash2 size={14} />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
              {products.length === 0 && <TableRow><TableCell colSpan={10} className="text-center text-muted-foreground py-8">Chưa có sản phẩm</TableCell></TableRow>}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog open={modalOpen} onOpenChange={setModalOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader><DialogTitle>{form.product_id ? "Sửa sản phẩm" : "Thêm danh mục"}</DialogTitle></DialogHeader>
          <div className="space-y-3 py-2">
            <div className="space-y-1"><Label>Product ID</Label><Input value={form.product_id} onChange={(e) => setForm({ ...form, product_id: e.target.value })} placeholder="Bỏ trống để tự tạo" /></div>
            <div className="space-y-1">
              <Label>Danh mục</Label>
              <div className="relative">
                <Input
                  ref={categoryInputRef}
                  value={form.category}
                  onFocus={() => setCategoryOpen(true)}
                  onChange={(e) => {
                    setForm({ ...form, category: e.target.value });
                    setCategoryOpen(true);
                  }}
                  placeholder="Nhập danh mục mới hoặc chọn danh mục cũ"
                  className="pr-10"
                />
                <button
                  type="button"
                  className="absolute right-2 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded hover:bg-muted"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => {
                    setCategoryOpen((v) => !v);
                    categoryInputRef.current?.focus();
                  }}
                  aria-label="Chọn danh mục"
                >
                  <ChevronDown size={18} />
                </button>
                {categoryOpen && (
                  <div className="absolute left-0 top-[calc(100%+6px)] z-50 max-h-60 w-full overflow-y-auto rounded-md border bg-white p-1 shadow-lg">
                    {categories.map((c) => (
                      <button
                        key={c}
                        type="button"
                        className="block w-full rounded-sm px-3 py-2 text-left text-sm hover:bg-muted"
                        onClick={() => {
                          setForm({ ...form, category: c });
                          setCategoryOpen(false);
                        }}
                      >
                        {c}
                      </button>
                    ))}
                    <button
                      type="button"
                      className="block w-full rounded-sm px-3 py-2 text-left text-sm font-medium text-emerald-700 hover:bg-emerald-50"
                      onClick={() => {
                        setForm({ ...form, category: "" });
                        setCategoryOpen(false);
                        window.setTimeout(() => categoryInputRef.current?.focus(), 0);
                      }}
                    >
                      Mục khác - nhập danh mục mới
                    </button>
                  </div>
                )}
              </div>
            </div>
            <div className="space-y-1"><Label>Tên sản phẩm</Label><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
            <div className="space-y-1"><Label>Stock Code</Label><Input value={form.stock_code} onChange={(e) => setForm({ ...form, stock_code: e.target.value.toUpperCase() })} /></div>
            <div className="space-y-1"><Label>Giá</Label><Input type="number" value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} /></div>
            <div className="space-y-1"><Label>Mô tả</Label><Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></div>
            <div className="space-y-1"><Label>Hướng dẫn sử dụng</Label><Textarea value={form.usage_guide} onChange={(e) => setForm({ ...form, usage_guide: e.target.value })} placeholder="Ví dụ: https://docs.google.com/document/d/..." /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setModalOpen(false)}>Hủy</Button>
            <Button onClick={save} disabled={saving || !form.category || !form.name || !form.stock_code}>{saving ? "Đang lưu..." : "Lưu"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={notifyOpen} onOpenChange={setNotifyOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Thông báo cho khách dùng bot</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 py-1">
            <p className="text-sm text-muted-foreground">
              Gửi tới mọi user đã từng <strong>/start</strong> bot (sheet USERS). Hỗ trợ Markdown (*in đậm*, _nghiêng_).
              Mỗi lần gửi cách nhau tối thiểu vài phút (chống spam).
            </p>
            <div className="space-y-1">
              <Label htmlFor="notify-message">Nội dung tin nhắn</Label>
              <Textarea
                id="notify-message"
                value={notifyText}
                onChange={(e) => setNotifyText(e.target.value)}
                placeholder="VD: Hàng GPT Trial đã về — mọi người /start để mua nhé!"
                className="min-h-[140px]"
                maxLength={4096}
              />
              <p className="text-xs text-muted-foreground text-right">{notifyText.length}/4096</p>
            </div>
            <div className="flex items-center gap-2">
              <Checkbox
                id="notify-shop-btn"
                checked={notifyAddShopBtn}
                onCheckedChange={(v) => setNotifyAddShopBtn(Boolean(v))}
              />
              <label htmlFor="notify-shop-btn" className="text-sm cursor-pointer select-none">
                Thêm nút &quot;Xem sản phẩm&quot; dưới tin nhắn
              </label>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setNotifyOpen(false)} disabled={notifySending}>
              Huỷ
            </Button>
            <Button
              className="gap-1.5"
              disabled={notifySending || !notifyText.trim()}
              onClick={() => setNotifyConfirmOpen(true)}
            >
              <Send size={15} /> Gửi thông báo
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={notifyConfirmOpen} onOpenChange={setNotifyConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Gửi thông báo cho toàn bộ khách?</AlertDialogTitle>
            <AlertDialogDescription className="whitespace-pre-wrap text-left max-h-48 overflow-y-auto">
              {notifyText.trim() || "(trống)"}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={notifySending}>Huỷ</AlertDialogCancel>
            <AlertDialogAction
              disabled={notifySending}
              onClick={(e) => {
                e.preventDefault();
                void sendUserNotify();
              }}
            >
              {notifySending ? "Đang gửi..." : "Xác nhận gửi"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={Boolean(deleteTarget)} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xóa sản phẩm?</AlertDialogTitle>
            <AlertDialogDescription>
              Xóa <strong>{deleteTarget ? text(deleteTarget.name) : ""}</strong> ({deleteTarget ? text(deleteTarget.stock_code) : ""}) khỏi danh mục.
              Stock trong kho (POOL) không bị xóa — chỉ gỡ dòng trên sheet PRODUCTS.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Hủy</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={deleting}
              onClick={(e) => {
                e.preventDefault();
                void confirmDelete();
              }}
            >
              {deleting ? "Đang xóa..." : "Xóa"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
