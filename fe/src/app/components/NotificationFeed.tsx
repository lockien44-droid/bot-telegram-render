import { Bell, BellOff, PackageCheck, PackagePlus, PackageX, Clock, Banknote } from "lucide-react";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { NOTIFY_META, type NotifyKind, type OrderNotification } from "../notifications";

const KIND_ICON: Record<NotifyKind, React.ReactNode> = {
  new: <PackagePlus size={16} className="text-emerald-600" />,
  cancelled: <PackageX size={16} className="text-red-600" />,
  expired: <Clock size={16} className="text-amber-600" />,
  delivered: <PackageCheck size={16} className="text-blue-600" />,
  paid: <Banknote size={16} className="text-violet-600" />,
};

function formatTime(iso: string) {
  try {
    return new Date(iso).toLocaleString("vi-VN", {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

interface FeedProps {
  items: OrderNotification[];
  limit?: number;
  compact?: boolean;
  emptyHint?: string;
  onOpenOrder: (orderId: string, status?: string) => void;
}

export function NotificationFeed({
  items,
  limit,
  compact = false,
  emptyHint = "Đơn mới, huỷ, hết hạn hoặc đã giao sẽ hiện tại đây.",
  onOpenOrder,
}: FeedProps) {
  const visible = limit ? items.slice(0, limit) : items;

  if (!visible.length) {
    return (
      <div className="py-8 flex flex-col items-center justify-center text-center text-muted-foreground">
        <BellOff size={compact ? 28 : 40} className="mb-2 opacity-40" />
        <p className="text-sm font-medium text-foreground">Chưa có thông báo</p>
        <p className="text-xs mt-1 max-w-sm">{emptyHint}</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {visible.map((item) => {
        const meta = NOTIFY_META[item.kind];
        const lineTitle = (item.title && item.title.trim()) || meta.title;
        const lineDetail =
          item.message && item.message.trim()
            ? item.message.trim()
            : [item.stockCode, item.total, item.orderId].filter(Boolean).join(" · ");
        return (
          <button
            key={item.id}
            type="button"
            onClick={() => onOpenOrder(item.orderId, item.status)}
            className={`w-full text-left rounded-lg border bg-white transition-shadow hover:shadow-md ${
              compact ? "p-3" : "p-4"
            } ${item.read ? "border-border opacity-80" : "border-emerald-200 bg-emerald-50/40"}`}
          >
            <div className="flex gap-2.5">
              <div
                className={`shrink-0 rounded-full bg-white border flex items-center justify-center ${
                  compact ? "w-8 h-8" : "w-9 h-9"
                }`}
              >
                {KIND_ICON[item.kind]}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className={`font-semibold ${compact ? "text-xs" : "text-sm"}`}>{lineTitle}</span>
                  {!item.read && (
                    <span className="text-[10px] uppercase font-bold text-emerald-700 bg-emerald-100 px-1 py-0.5 rounded">
                      Mới
                    </span>
                  )}
                </div>
                <p className={`text-muted-foreground truncate ${compact ? "text-xs" : "text-sm"}`}>
                  {lineDetail}
                </p>
                <p className="text-[11px] text-muted-foreground mt-0.5">{formatTime(item.at)}</p>
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
}

interface HeaderProps {
  unread: number;
  total: number;
  onViewAll?: () => void;
  onMarkAllRead?: () => void;
}

export function NotificationFeedHeader({ unread, total, onViewAll, onMarkAllRead }: HeaderProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="flex items-center gap-2">
        <Bell size={18} className="text-emerald-600" />
        <span className="font-semibold text-sm">Thông báo</span>
        {unread > 0 && (
          <Badge variant="destructive" className="h-5 px-1.5 text-[10px]">
            {unread} mới
          </Badge>
        )}
        {total > 0 && unread === 0 && (
          <span className="text-xs text-muted-foreground">({total})</span>
        )}
      </div>
      <div className="flex gap-2">
        {unread > 0 && onMarkAllRead && (
          <Button size="sm" variant="ghost" className="h-8 text-xs" onClick={onMarkAllRead}>
            Đánh dấu đã đọc
          </Button>
        )}
        {onViewAll && total > 0 && (
          <Button size="sm" variant="outline" className="h-8 text-xs" onClick={onViewAll}>
            Xem tất cả
          </Button>
        )}
      </div>
    </div>
  );
}

