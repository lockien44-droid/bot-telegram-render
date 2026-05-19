import { useEffect, useMemo, useState } from "react";
import { Bell, CheckCheck, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Card, CardContent } from "../ui/card";
import { Button } from "../ui/button";
import { Badge } from "../ui/badge";
import { Checkbox } from "../ui/checkbox";
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
import type { OrderNotification } from "../../notifications";
import { NotificationFeed } from "../NotificationFeed";

interface Props {
  items: OrderNotification[];
  onMarkAllRead: () => void;
  onClearAll: () => void;
  onDeleteSelected: (ids: string[]) => Promise<void>;
  onOpenOrder: (orderId: string, status?: string) => void;
}

export function Notifications({ items, onMarkAllRead, onClearAll, onDeleteSelected, onOpenOrder }: Props) {
  const [filter, setFilter] = useState<"all" | "unread">("all");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [confirmDeleteSelected, setConfirmDeleteSelected] = useState(false);
  const [confirmClearAll, setConfirmClearAll] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const unread = items.filter((n) => !n.read).length;
  const visible = useMemo(
    () => (filter === "unread" ? items.filter((n) => !n.read) : items),
    [items, filter],
  );

  const visibleIds = useMemo(() => new Set(visible.map((n) => n.id)), [visible]);
  const selectedInView = useMemo(
    () => [...selectedIds].filter((id) => visibleIds.has(id)),
    [selectedIds, visibleIds],
  );
  const allVisibleSelected = visible.length > 0 && selectedInView.length === visible.length;

  useEffect(() => {
    setSelectedIds((prev) => {
      const next = new Set([...prev].filter((id) => items.some((n) => n.id === id)));
      return next.size === prev.size ? prev : next;
    });
  }, [items]);

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAllVisible = () => {
    if (allVisibleSelected) {
      setSelectedIds((prev) => {
        const next = new Set(prev);
        for (const id of visibleIds) next.delete(id);
        return next;
      });
    } else {
      setSelectedIds((prev) => new Set([...prev, ...visibleIds]));
    }
  };

  const runDeleteSelected = async () => {
    if (!selectedInView.length) return;
    setDeleting(true);
    try {
      await onDeleteSelected(selectedInView);
      setSelectedIds((prev) => {
        const next = new Set(prev);
        for (const id of selectedInView) next.delete(id);
        return next;
      });
      toast.success(`Đã xóa ${selectedInView.length} thông báo`);
    } catch {
      toast.error("Không xóa được thông báo đã chọn");
    } finally {
      setDeleting(false);
      setConfirmDeleteSelected(false);
    }
  };

  const runClearAll = async () => {
    setDeleting(true);
    try {
      await onClearAll();
      setSelectedIds(new Set());
      toast.success("Đã xóa tất cả thông báo");
    } catch {
      toast.error("Không xóa được thông báo trên sheet");
    } finally {
      setDeleting(false);
      setConfirmClearAll(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h2 className="flex items-center gap-2 text-lg font-semibold">
          <Bell size={20} />
          Thông báo
          {unread > 0 && (
            <Badge variant="destructive" className="ml-1">
              {unread} chưa đọc
            </Badge>
          )}
        </h2>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant={filter === "all" ? "default" : "outline"} onClick={() => setFilter("all")}>
            Tất cả ({items.length})
          </Button>
          <Button size="sm" variant={filter === "unread" ? "default" : "outline"} onClick={() => setFilter("unread")}>
            Chưa đọc ({unread})
          </Button>
          {unread > 0 && (
            <Button size="sm" variant="secondary" className="gap-1.5" onClick={onMarkAllRead}>
              <CheckCheck size={15} />
              Đánh dấu đã đọc
            </Button>
          )}
          {selectedInView.length > 0 && (
            <Button
              size="sm"
              variant="outline"
              className="gap-1.5 text-red-600 border-red-200"
              disabled={deleting}
              onClick={() => setConfirmDeleteSelected(true)}
            >
              <Trash2 size={15} />
              Xóa đã chọn ({selectedInView.length})
            </Button>
          )}
          {items.length > 0 && (
            <Button
              size="sm"
              variant="outline"
              className="gap-1.5 text-red-600"
              disabled={deleting}
              onClick={() => setConfirmClearAll(true)}
            >
              <Trash2 size={15} />
              Xóa tất cả
            </Button>
          )}
        </div>
      </div>

      {visible.length > 0 && (
        <div className="flex items-center gap-2 rounded-lg border bg-white px-3 py-2 text-sm">
          <Checkbox
            id="notif-select-all"
            checked={allVisibleSelected}
            onCheckedChange={toggleSelectAllVisible}
            aria-label="Chọn tất cả thông báo đang hiển thị"
          />
          <label htmlFor="notif-select-all" className="cursor-pointer text-muted-foreground select-none">
            {allVisibleSelected ? "Bỏ chọn tất cả" : "Chọn tất cả"} ({visible.length} đang hiển thị)
            {selectedInView.length > 0 && (
              <span className="ml-2 font-medium text-foreground">· Đã chọn {selectedInView.length}</span>
            )}
          </label>
        </div>
      )}

      <Card>
        <CardContent className="pt-4">
          <NotificationFeed
            items={visible}
            selectable
            selectedIds={selectedIds}
            onToggleSelect={toggleSelect}
            onOpenOrder={onOpenOrder}
          />
        </CardContent>
      </Card>

      <AlertDialog open={confirmDeleteSelected} onOpenChange={setConfirmDeleteSelected}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xóa thông báo đã chọn?</AlertDialogTitle>
            <AlertDialogDescription>
              Sẽ xóa {selectedInView.length} thông báo khỏi sheet. Thao tác này không hoàn tác được.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Huỷ</AlertDialogCancel>
            <AlertDialogAction
              className="bg-red-600 hover:bg-red-700"
              disabled={deleting}
              onClick={(e) => {
                e.preventDefault();
                void runDeleteSelected();
              }}
            >
              Xóa
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={confirmClearAll} onOpenChange={setConfirmClearAll}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xóa tất cả thông báo?</AlertDialogTitle>
            <AlertDialogDescription>
              Sẽ xóa toàn bộ {items.length} thông báo khỏi sheet. Thao tác này không hoàn tác được.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Huỷ</AlertDialogCancel>
            <AlertDialogAction
              className="bg-red-600 hover:bg-red-700"
              disabled={deleting}
              onClick={(e) => {
                e.preventDefault();
                void runClearAll();
              }}
            >
              Xóa tất cả
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
