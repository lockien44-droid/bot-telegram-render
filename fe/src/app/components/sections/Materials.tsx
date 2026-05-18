import { useCallback, useEffect, useMemo, useState } from "react";
import { Clipboard, Copy, PackageCheck, RotateCcw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { adminApi, text, type AdminSnapshot } from "../../api";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Card, CardContent } from "../ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../ui/tabs";
import { Textarea } from "../ui/textarea";

type MaterialStatus = "NEW" | "OK" | "BAD";
type MaterialItem = { id: string; value: string; status: MaterialStatus; note?: string };

interface Props {
  data: AdminSnapshot | null;
  adminKey: string;
  refresh: () => Promise<void>;
}

const STORAGE_KEY = "admin_material_items_v1";
const BACKUP_KEY = "admin_material_items_backup_v1";

function makeId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function loadItems(): MaterialItem[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
    if (Array.isArray(parsed) && parsed.length > 0) return parsed;

    const backup = JSON.parse(localStorage.getItem(BACKUP_KEY) || "[]");
    return Array.isArray(backup) ? backup : [];
  } catch {
    return [];
  }
}

function saveItems(items: MaterialItem[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
  if (items.length > 0) {
    localStorage.setItem(BACKUP_KEY, JSON.stringify(items));
  }
}

function normalizeItems(rows: any[]): MaterialItem[] {
  return (rows || [])
    .map((row) => {
      const status = String(row.status || "NEW").toUpperCase();
      return {
        id: String(row.id || makeId()),
        value: String(row.value || "").trim(),
        status: (status === "OK" || status === "BAD" ? status : "NEW") as MaterialStatus,
        note: row.note ? String(row.note) : undefined,
      };
    })
    .filter((item) => item.value);
}

export function Materials({ data, adminKey, refresh }: Props) {
  const [raw, setRaw] = useState("");
  const [stockCode, setStockCode] = useState("");
  const [items, setItems] = useState<MaterialItem[]>(loadItems);
  const [busy, setBusy] = useState(false);
  const [loadedRemote, setLoadedRemote] = useState(false);

  const productCodes = useMemo(() => {
    const codes = (data?.products || []).map((p) => text(p.stock_code)).filter((x) => x !== "—");
    return Array.from(new Set(codes)).sort();
  }, [data]);

  const counts = useMemo(() => ({
    NEW: items.filter((x) => x.status === "NEW").length,
    OK: items.filter((x) => x.status === "OK").length,
    BAD: items.filter((x) => x.status === "BAD").length,
  }), [items]);

  const saveRemote = useCallback(async (next: MaterialItem[]) => {
    try {
      const result = await adminApi<{ items?: any[] }>("/admin/api/materials", adminKey, {
        method: "POST",
        body: JSON.stringify({ items: next, force_clear: next.length === 0 }),
      });
      if (result.items) {
        const synced = normalizeItems(result.items);
        if (synced.length > 0 || next.length === 0) {
          setItems(synced);
          saveItems(synced);
        }
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Không lưu được nguyên liệu lên server");
    }
  }, [adminKey]);

  useEffect(() => {
    if (!data) return;
    const remoteItems = normalizeItems(data.materials || []);
    if (remoteItems.length > 0) {
      setItems(remoteItems);
      saveItems(remoteItems);
      setLoadedRemote(true);
      return;
    }

    const localItems = loadItems();
    const candidateItems = items.length > 0 ? items : localItems;
    if (!loadedRemote && candidateItems.length > 0) {
      setItems(candidateItems);
      saveItems(candidateItems);
      setLoadedRemote(true);
      void saveRemote(candidateItems);
      return;
    }

    // Empty remote means the shared MATERIALS sheet has no rows yet. Do not
    // overwrite local/browser data with an empty list.
    setLoadedRemote(true);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.generated_at, saveRemote]);

  const setAndSave = (next: MaterialItem[]) => {
    setItems(next);
    saveItems(next);
    void saveRemote(next);
  };

  const importRaw = () => {
    const lines = raw.split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
    if (!lines.length) return;
    const existed = new Set(items.map((x) => x.value));
    const next = [
      ...items,
      ...lines.filter((line) => !existed.has(line)).map((line) => ({ id: makeId(), value: line, status: "NEW" as const })),
    ];
    setRaw("");
    setAndSave(next);
    toast.success(`Đã nhập ${next.length - items.length} dòng nguyên liệu`);
  };

  const updateStatus = (id: string, status: MaterialStatus) => {
    setAndSave(items.map((item) => item.id === id ? { ...item, status } : item));
  };

  const clearStatus = (status?: MaterialStatus) => {
    const next = status ? items.filter((item) => item.status !== status) : [];
    setAndSave(next);
  };

  const copyItems = async (status: MaterialStatus) => {
    const content = items.filter((item) => item.status === status).map((item) => item.value).join("\n");
    if (!content) return toast.info("Không có dòng nào để copy");
    await navigator.clipboard.writeText(content);
    toast.success(`Đã copy ${status === "OK" ? "dòng OK" : status === "BAD" ? "dòng lỗi" : "dòng mới"}`);
  };

  const copyOne = async (value: string) => {
    await navigator.clipboard.writeText(value);
    toast.success("Đã copy 1 dòng");
  };

  const addOkToStock = async () => {
    const okItems = items.filter((item) => item.status === "OK");
    if (!stockCode || !okItems.length) return;
    setBusy(true);
    try {
      await adminApi("/admin/api/stock", adminKey, {
        method: "POST",
        body: JSON.stringify({ stock_code: stockCode, items: okItems.map((item) => item.value).join("\n") }),
      });
      const next = items.filter((item) => item.status !== "OK");
      setItems(next);
      saveItems(next);
      await saveRemote(next);
      toast.success(`Đã thêm ${okItems.length} dòng OK vào kho ${stockCode}`);
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const renderRows = (status: MaterialStatus) => {
    const visible = items.filter((item) => item.status === status);
    return (
      <Card className="shadow-sm">
        <CardContent className="p-0 overflow-x-auto">
          <Table className="min-w-[760px]">
            <TableHeader>
              <TableRow>
                <TableHead className="w-[90px]">Trạng thái</TableHead>
                <TableHead>Nguyên liệu</TableHead>
                <TableHead className="w-[300px] text-right">Thao tác</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((item) => (
                <TableRow key={item.id}>
                  <TableCell><StatusBadge status={item.status} /></TableCell>
                  <TableCell
                    className="font-mono text-xs max-w-[520px] truncate cursor-pointer select-none active:bg-muted"
                    title="Chạm để copy"
                    onClick={() => copyOne(item.value)}
                  >
                    {item.value}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-1">
                      <Button size="sm" variant="outline" className="gap-1" onClick={() => copyOne(item.value)}><Copy size={14} /> Copy</Button>
                      <Button size="sm" variant="outline" onClick={() => updateStatus(item.id, "OK")}>OK</Button>
                      <Button size="sm" variant="outline" onClick={() => updateStatus(item.id, "BAD")}>Lỗi</Button>
                      <Button size="sm" variant="ghost" onClick={() => updateStatus(item.id, "NEW")}><RotateCcw size={14} /></Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
              {visible.length === 0 && <TableRow><TableCell colSpan={3} className="text-center py-8 text-muted-foreground">Chưa có dữ liệu</TableCell></TableRow>}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    );
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2"><Clipboard size={20} /> Nguyên liệu</h2>
        <div className="flex flex-wrap gap-2">
          <Badge variant="secondary">Mới {counts.NEW}</Badge>
          <Badge variant="default">OK {counts.OK}</Badge>
          <Badge variant="destructive">Lỗi {counts.BAD}</Badge>
        </div>
      </div>

      <Card className="shadow-sm">
        <CardContent className="p-4 space-y-3">
          <Textarea
            className="min-h-28 font-mono text-xs"
            placeholder="Dán list nguyên liệu vào đây, mỗi dòng là 1 account/secret..."
            value={raw}
            onChange={(e) => setRaw(e.target.value)}
          />
          <div className="flex flex-wrap gap-2">
            <Button onClick={importRaw} disabled={!raw.trim()}>Thêm vào danh sách</Button>
            <Button variant="outline" className="gap-2" onClick={() => copyItems("OK")}><Copy size={15} /> Copy OK</Button>
            <Button variant="outline" className="gap-2" onClick={() => copyItems("BAD")}><Copy size={15} /> Copy lỗi</Button>
            <Button variant="ghost" className="gap-2" onClick={() => clearStatus()}><Trash2 size={15} /> Xóa tất cả</Button>
          </div>
        </CardContent>
      </Card>

      <Card className="shadow-sm">
        <CardContent className="p-4 flex flex-wrap items-center gap-2">
          <Select value={stockCode || "__empty"} onValueChange={(value) => setStockCode(value === "__empty" ? "" : value)}>
            <SelectTrigger className="w-56"><SelectValue placeholder="Chọn stock để nhập kho" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="__empty">Chọn stock</SelectItem>
              {productCodes.map((code) => <SelectItem key={code} value={code}>{code}</SelectItem>)}
            </SelectContent>
          </Select>
          <Button className="gap-2" onClick={addOkToStock} disabled={busy || !stockCode || counts.OK === 0}>
            <PackageCheck size={16} /> Đẩy OK vào kho bán
          </Button>
          <p className="text-sm text-muted-foreground">Sau khi đẩy vào kho, các dòng OK sẽ tự xóa khỏi danh sách nguyên liệu.</p>
        </CardContent>
      </Card>

      <Tabs defaultValue="NEW">
        <TabsList>
          <TabsTrigger value="NEW">Chưa phân loại</TabsTrigger>
          <TabsTrigger value="OK">Dùng được</TabsTrigger>
          <TabsTrigger value="BAD">Không dùng được</TabsTrigger>
        </TabsList>
        <TabsContent value="NEW" className="pt-3">{renderRows("NEW")}</TabsContent>
        <TabsContent value="OK" className="pt-3">{renderRows("OK")}</TabsContent>
        <TabsContent value="BAD" className="pt-3">{renderRows("BAD")}</TabsContent>
      </Tabs>
    </div>
  );
}

function StatusBadge({ status }: { status: MaterialStatus }) {
  if (status === "OK") return <Badge>OK</Badge>;
  if (status === "BAD") return <Badge variant="destructive">Lỗi</Badge>;
  return <Badge variant="secondary">Mới</Badge>;
}
