import { useEffect, useMemo, useState } from "react";
import { Card, CardContent } from "../ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../ui/table";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Badge } from "../ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../ui/tabs";
import { Textarea } from "../ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../ui/select";
import { Warehouse, Plus, RotateCcw, ChevronDown, ChevronRight, LayoutGrid, List } from "lucide-react";
import { toast } from "sonner";
import { adminApi, text, type AdminSnapshot, type AnyRow } from "../../api";

interface Props {
  data: AdminSnapshot | null;
  adminKey: string;
  refresh: () => Promise<void>;
  preset?: { status?: string; stockCode?: string; nonce: number };
}

const normalizeCode = (value: any) => text(value).trim().toUpperCase();
const isRealCode = (value: string) => value !== "—" && value !== "â€”";

type StockGroup = {
  stockCode: string;
  productName: string;
  productId: string;
  items: AnyRow[];
  counts: { READY: number; HELD: number; SOLD: number; OTHER: number; total: number };
};

function countByStatus(items: AnyRow[]) {
  const counts = { READY: 0, HELD: 0, SOLD: 0, OTHER: 0, total: items.length };
  for (const item of items) {
    const st = text(item.status).toUpperCase();
    if (st === "READY" || st === "HELD" || st === "SOLD") counts[st] += 1;
    else counts.OTHER += 1;
  }
  return counts;
}

export function Inventory({ data, adminKey, refresh, preset }: Props) {
  const [addCode, setAddCode] = useState("");
  const [addData, setAddData] = useState("");
  const [filterStatus, setFilterStatus] = useState("ALL");
  const [filterCode, setFilterCode] = useState("ALL");
  const [releaseOrderId, setReleaseOrderId] = useState("");
  const [busy, setBusy] = useState(false);
  const [viewMode, setViewMode] = useState<"group" | "detail">("group");
  const [expandedCodes, setExpandedCodes] = useState<Set<string>>(new Set());

  const pool = data?.pool || [];
  const productCodes = useMemo(
    () => {
      const fromProducts = (data?.products || []).map((p) => normalizeCode(p.stock_code));
      const fromPool = (data?.pool || []).map((p) => normalizeCode(p.stock_code));
      return Array.from(new Set([...fromProducts, ...fromPool].filter(isRealCode))).sort();
    },
    [data],
  );
  const counts = {
    READY: pool.filter((i) => text(i.status).toUpperCase() === "READY").length,
    HELD: pool.filter((i) => text(i.status).toUpperCase() === "HELD").length,
    SOLD: pool.filter((i) => text(i.status).toUpperCase() === "SOLD").length,
  };

  const visible = pool.filter((p) => {
    if (filterStatus !== "ALL" && text(p.status).toUpperCase() !== filterStatus) return false;
    if (filterCode !== "ALL" && normalizeCode(p.stock_code) !== normalizeCode(filterCode)) return false;
    return true;
  });

  const productByCode = useMemo(() => {
    const map = new Map<string, AnyRow>();
    for (const p of data?.products || []) {
      const code = normalizeCode(p.stock_code);
      if (isRealCode(code)) map.set(code, p);
    }
    return map;
  }, [data?.products]);

  const groups = useMemo((): StockGroup[] => {
    const map = new Map<string, AnyRow[]>();
    for (const item of visible) {
      const code = normalizeCode(item.stock_code);
      if (!isRealCode(code)) continue;
      const list = map.get(code) || [];
      list.push(item);
      map.set(code, list);
    }
    return Array.from(map.entries())
      .map(([stockCode, items]) => {
        const product = productByCode.get(stockCode);
        return {
          stockCode,
          productName: product ? text(product.name) : "",
          productId: product ? text(product.product_id) : "",
          items,
          counts: countByStatus(items),
        };
      })
      .sort((a, b) => b.counts.total - a.counts.total || a.stockCode.localeCompare(b.stockCode));
  }, [visible, productByCode]);

  const toggleGroup = (code: string) => {
    setExpandedCodes((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  useEffect(() => {
    if (!preset?.nonce) return;
    const status = (preset.status || "ALL").toUpperCase();
    setFilterStatus(["ALL", "READY", "HELD", "SOLD"].includes(status) ? status : "ALL");
    setFilterCode(preset.stockCode ? normalizeCode(preset.stockCode) : "ALL");
    if (preset.stockCode) {
      const code = normalizeCode(preset.stockCode);
      setAddCode(code);
      setViewMode("group");
      setExpandedCodes(new Set([code]));
    }
  }, [preset?.nonce, preset?.status, preset?.stockCode]);

  const addStock = async () => {
    setBusy(true);
    try {
      await adminApi("/admin/api/stock", adminKey, { method: "POST", body: JSON.stringify({ stock_code: addCode, items: addData }) });
      setAddData("");
      toast.success("Đã thêm stock vào kho");
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const releaseHeld = async () => {
    setBusy(true);
    try {
      const result = await adminApi<{ released: number }>("/admin/api/orders/release", adminKey, {
        method: "POST",
        body: JSON.stringify({ order_id: releaseOrderId, status: "EXPIRED" }),
      });
      setReleaseOrderId("");
      toast.success(`Đã trả ${result.released || 0} item về READY`);
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const releaseHeldBulk = async (expiredOnly: boolean) => {
    if (!expiredOnly && !window.confirm("Trả toàn bộ HELD về READY? Chỉ dùng khi chắc chắn các đơn này không cần giữ nữa.")) return;
    setBusy(true);
    try {
      const result = await adminApi<{ released: number; orders: number }>("/admin/api/stock/release-held", adminKey, {
        method: "POST",
        body: JSON.stringify({ expired_only: expiredOnly, status: "EXPIRED" }),
      });
      toast.success(`Đã trả ${result.released || 0} item từ ${result.orders || 0} đơn về READY`);
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <h2 className="flex items-center gap-2"><Warehouse size={20} /> Kho hàng</h2>

      <div className="grid grid-cols-3 gap-3">
        {(["READY", "HELD", "SOLD"] as const).map((s) => (
          <Card key={s} className="shadow-sm">
            <CardContent className="p-4 flex items-center justify-between">
              <span className="text-sm text-muted-foreground">{s}</span>
              <Badge variant={s === "READY" ? "default" : s === "HELD" ? "secondary" : "outline"} className="text-base px-3">{counts[s]}</Badge>
            </CardContent>
          </Card>
        ))}
      </div>

      <Tabs defaultValue="view">
        <TabsList>
          <TabsTrigger value="view">Xem kho</TabsTrigger>
          <TabsTrigger value="add">Thêm stock</TabsTrigger>
          <TabsTrigger value="release">Trả HELD</TabsTrigger>
        </TabsList>

        <TabsContent value="view" className="space-y-3 pt-2">
          <div className="flex flex-wrap gap-2 items-center">
            <Select value={filterStatus} onValueChange={setFilterStatus}>
              <SelectTrigger className="w-36"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="ALL">Tất cả</SelectItem>
                <SelectItem value="READY">READY</SelectItem>
                <SelectItem value="HELD">HELD</SelectItem>
                <SelectItem value="SOLD">SOLD</SelectItem>
              </SelectContent>
            </Select>
            <Select value={filterCode} onValueChange={setFilterCode}>
              <SelectTrigger className="w-40"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="ALL">Tất cả code</SelectItem>
                {productCodes.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
              </SelectContent>
            </Select>
            <div className="flex rounded-md border overflow-hidden h-9">
              <Button
                type="button"
                size="sm"
                variant={viewMode === "group" ? "default" : "ghost"}
                className="h-9 rounded-none gap-1.5"
                onClick={() => setViewMode("group")}
              >
                <LayoutGrid size={14} /> Theo SP
              </Button>
              <Button
                type="button"
                size="sm"
                variant={viewMode === "detail" ? "default" : "ghost"}
                className="h-9 rounded-none gap-1.5"
                onClick={() => setViewMode("detail")}
              >
                <List size={14} /> Chi tiết
              </Button>
            </div>
            <Badge variant="outline" className="h-9 px-3">
              {viewMode === "group"
                ? `${groups.length} sản phẩm · ${visible.length} dòng`
                : `Đang hiện ${visible.length}/${pool.length}`}
            </Badge>
          </div>

          {viewMode === "group" ? (
            <div className="space-y-2">
              {groups.length === 0 && (
                <Card className="shadow-sm">
                  <CardContent className="py-10 text-center text-muted-foreground">Không có stock nào</CardContent>
                </Card>
              )}
              {groups.map((group) => {
                const open = expandedCodes.has(group.stockCode);
                return (
                  <Card key={group.stockCode} className="shadow-sm overflow-hidden">
                    <button
                      type="button"
                      className="w-full text-left px-4 py-3 flex items-center gap-3 hover:bg-muted/40 transition-colors"
                      onClick={() => toggleGroup(group.stockCode)}
                    >
                      {open ? <ChevronDown size={18} className="shrink-0 text-muted-foreground" /> : <ChevronRight size={18} className="shrink-0 text-muted-foreground" />}
                      <div className="flex-1 min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <code className="text-sm font-semibold bg-muted px-2 py-0.5 rounded">{group.stockCode}</code>
                          {group.productName && group.productName !== "—" && (
                            <span className="text-sm text-muted-foreground truncate">{group.productName}</span>
                          )}
                          {group.productId && group.productId !== "—" && (
                            <span className="text-xs text-muted-foreground">ID: {group.productId}</span>
                          )}
                        </div>
                        <p className="text-xs text-muted-foreground mt-1">
                          {group.counts.total} sản phẩm · bấm để {open ? "thu gọn" : "xem chi tiết"}
                        </p>
                      </div>
                      <div className="flex flex-wrap gap-1.5 justify-end shrink-0">
                        <Badge>{group.counts.READY} READY</Badge>
                        {group.counts.HELD > 0 && <Badge variant="secondary">{group.counts.HELD} HELD</Badge>}
                        {group.counts.SOLD > 0 && <Badge variant="outline">{group.counts.SOLD} SOLD</Badge>}
                      </div>
                    </button>
                    {open && (
                      <CardContent className="p-0 pt-0 border-t overflow-x-auto">
                        <PoolItemsTable items={group.items} showStockCode={false} />
                      </CardContent>
                    )}
                  </Card>
                );
              })}
            </div>
          ) : (
            <Card className="shadow-sm">
              <CardContent className="p-0 overflow-x-auto">
                <PoolItemsTable items={visible} showStockCode />
              </CardContent>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="add" className="space-y-3 pt-2">
          <Card className="shadow-sm max-w-2xl">
            <CardContent className="p-4 space-y-3">
              <Select value={addCode || "__custom"} onValueChange={(value) => setAddCode(value === "__custom" ? "" : value)}>
                <SelectTrigger><SelectValue placeholder="Chọn stock code có sẵn" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="__custom">Nhập mã khác</SelectItem>
                  {productCodes.map((code) => <SelectItem key={code} value={code}>{code}</SelectItem>)}
                </SelectContent>
              </Select>
              <Input placeholder="Stock code, ví dụ GPT1M" value={addCode} onChange={(e) => setAddCode(e.target.value.toUpperCase())} />
              <Textarea placeholder="Mỗi dòng là 1 account/secret" value={addData} onChange={(e) => setAddData(e.target.value)} />
              <Button className="gap-2" onClick={addStock} disabled={busy || !addCode || !addData.trim()}><Plus size={15} /> Thêm vào kho</Button>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="release" className="space-y-3 pt-2">
          <Card className="shadow-sm max-w-2xl">
            <CardContent className="p-4 space-y-3">
              <p className="text-sm text-muted-foreground">
                Bình thường bot sẽ tự trả HELD về READY sau thời gian hết hạn. Nếu bị kẹt do restart/deploy, dùng nút bên dưới.
              </p>
              <div className="flex flex-wrap gap-2">
                <Button className="gap-2" variant="outline" onClick={() => releaseHeldBulk(true)} disabled={busy}>
                  <RotateCcw size={15} /> Trả HELD quá hạn
                </Button>
                <Button className="gap-2" variant="destructive" onClick={() => releaseHeldBulk(false)} disabled={busy}>
                  <RotateCcw size={15} /> Trả toàn bộ HELD
                </Button>
              </div>
              <div className="border-t pt-3 space-y-2">
                <p className="text-sm text-muted-foreground">Hoặc nhập riêng Order ID đang HELD để trả các item của đơn về READY.</p>
                <Input placeholder="ORD..." value={releaseOrderId} onChange={(e) => setReleaseOrderId(e.target.value)} />
                <Button variant="outline" onClick={releaseHeld} disabled={busy || !releaseOrderId}>Trả Order ID này về READY</Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

function PoolItemsTable({ items, showStockCode }: { items: AnyRow[]; showStockCode: boolean }) {
  const colSpan = showStockCode ? 7 : 6;
  return (
    <Table className="min-w-[920px]">
      <TableHeader>
        <TableRow>
          <TableHead>Item ID</TableHead>
          {showStockCode && <TableHead>Stock Code</TableHead>}
          <TableHead>Secret</TableHead>
          <TableHead className="text-center">Status</TableHead>
          <TableHead>Hold Order</TableHead>
          <TableHead>Hết hạn giữ</TableHead>
          <TableHead>Sold Order</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((item, index) => (
          <TableRow key={`${text(item.item_id)}-${normalizeCode(item.stock_code)}-${index}-${text(item.secret).slice(0, 24)}`}>
            <TableCell><code className="text-xs bg-muted px-1.5 py-0.5 rounded">{text(item.item_id)}</code></TableCell>
            {showStockCode && (
              <TableCell><code className="text-xs bg-muted px-1.5 py-0.5 rounded">{text(item.stock_code)}</code></TableCell>
            )}
            <TableCell className="text-xs font-mono max-w-[260px] truncate">{text(item.secret)}</TableCell>
            <TableCell className="text-center"><StockBadge status={text(item.status)} /></TableCell>
            <TableCell className="text-xs text-muted-foreground">{text(item.hold_order_id)}</TableCell>
            <TableCell className="text-xs text-muted-foreground whitespace-nowrap">{text(item.hold_expires_at)}</TableCell>
            <TableCell className="text-xs text-muted-foreground">{text(item.sold_order_id)}</TableCell>
          </TableRow>
        ))}
        {items.length === 0 && (
          <TableRow>
            <TableCell colSpan={colSpan} className="text-center text-muted-foreground py-8">Không có stock nào</TableCell>
          </TableRow>
        )}
      </TableBody>
    </Table>
  );
}

function StockBadge({ status }: { status: string }) {
  return <Badge variant={status === "READY" ? "default" : status === "HELD" ? "secondary" : "outline"}>{status}</Badge>;
}
