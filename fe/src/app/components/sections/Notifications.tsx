import { useMemo, useState } from "react";
import { Bell, CheckCheck, Trash2 } from "lucide-react";
import { Card, CardContent } from "../ui/card";
import { Button } from "../ui/button";
import { Badge } from "../ui/badge";
import type { OrderNotification } from "../../notifications";
import { NotificationFeed } from "../NotificationFeed";

interface Props {
  items: OrderNotification[];
  onMarkAllRead: () => void;
  onClearAll: () => void;
  onOpenOrder: (orderId: string, status?: string) => void;
}

export function Notifications({ items, onMarkAllRead, onClearAll, onOpenOrder }: Props) {
  const [filter, setFilter] = useState<"all" | "unread">("all");
  const unread = items.filter((n) => !n.read).length;
  const visible = useMemo(
    () => (filter === "unread" ? items.filter((n) => !n.read) : items),
    [items, filter],
  );

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
          {items.length > 0 && (
            <Button size="sm" variant="outline" className="gap-1.5 text-red-600" onClick={onClearAll}>
              <Trash2 size={15} />
              Xóa tất cả
            </Button>
          )}
        </div>
      </div>

      <Card>
        <CardContent className="pt-4">
          <NotificationFeed items={visible} onOpenOrder={onOpenOrder} />
        </CardContent>
      </Card>
    </div>
  );
}
