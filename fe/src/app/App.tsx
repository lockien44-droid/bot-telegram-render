import { useCallback, useEffect, useRef, useState } from "react";
import { Bell, RefreshCw } from "lucide-react";
import { toast, Toaster } from "sonner";
import { AdminLogin } from "./components/AdminLogin";
import { NAV_ITEMS, Sidebar, type AdminSection } from "./components/Sidebar";
import { Overview } from "./components/sections/Overview";
import { Products } from "./components/sections/Products";
import { Inventory } from "./components/sections/Inventory";
import { Orders } from "./components/sections/Orders";
import { Users } from "./components/sections/Users";
import { Reservations } from "./components/sections/Reservations";
import { Fulfillments } from "./components/sections/Fulfillments";
import { Notifications } from "./components/sections/Notifications";
import { Revenue } from "./components/sections/Revenue";
import { Button } from "./components/ui/button";
import { adminApi, type AdminSnapshot } from "./api";
import {
  mapSheetNotification,
  NOTIFY_META,
  type OrderNotification,
  type SheetNotificationRow,
} from "./notifications";

const POLL_MS = 15_000;

export default function App() {
  const [adminKey, setAdminKey] = useState(() => sessionStorage.getItem("admin_key") || "");
  const [section, setSection] = useState<AdminSection>("overview");
  const [data, setData] = useState<AdminSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [notifications, setNotifications] = useState<OrderNotification[]>([]);
  const [inventoryPreset, setInventoryPreset] = useState<{ status?: string; stockCode?: string; nonce: number }>({ nonce: 0 });
  const [orderPreset, setOrderPreset] = useState<{ status?: string; orderId?: string; nonce: number }>({ nonce: 0 });

  const unreadCount = notifications.filter((n) => !n.read).length;

  const notifHydratedRef = useRef(false);
  const prevNotifIdsRef = useRef<Set<string>>(new Set());
  const audioRef = useRef<AudioContext | null>(null);

  const isAuthenticated = Boolean(adminKey);

  const playNotifySound = useCallback(() => {
    try {
      const Ctx = window.AudioContext || (window as any).webkitAudioContext;
      if (!Ctx) return;
      const ctx = audioRef.current || new Ctx();
      audioRef.current = ctx;
      if (ctx.state === "suspended") void ctx.resume();

      const oscillator = ctx.createOscillator();
      const gain = ctx.createGain();
      oscillator.type = "sine";
      oscillator.frequency.value = 880;
      gain.gain.setValueAtTime(0.001, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.12, ctx.currentTime + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.22);
      oscillator.connect(gain);
      gain.connect(ctx.destination);
      oscillator.start();
      oscillator.stop(ctx.currentTime + 0.24);
    } catch {
      // Browser may block audio until the page has a user gesture.
    }
  }, []);

  const fetchNotifications = useCallback(
    async (key: string) => {
      if (!key) return;
      try {
        const res = await adminApi<{ items: SheetNotificationRow[] }>(`/admin/api/notifications?limit=300`, key);
        const rows = Array.isArray(res.items) ? res.items : [];
        const mapped = rows.map(mapSheetNotification);
        const prev = prevNotifIdsRef.current;
        if (notifHydratedRef.current) {
          for (const n of mapped) {
            if (prev.has(n.id)) continue;
            playNotifySound();
            const meta = NOTIFY_META[n.kind];
            const desc = (n.message && n.message.trim()) || [n.stockCode, n.total, n.orderId].filter(Boolean).join(" · ");
            if (n.kind === "new") toast.success(meta.title, { description: desc || n.orderId, duration: 7000 });
            else if (n.kind === "cancelled" || n.kind === "expired") {
              toast.error(meta.title, { description: desc || n.orderId, duration: 7000 });
            } else {
              toast(meta.title, { description: desc || n.orderId, duration: 7000 });
            }
          }
        }
        notifHydratedRef.current = true;
        prevNotifIdsRef.current = new Set(mapped.map((n) => n.id));
        setNotifications(mapped);
      } catch {
        // offline / lỗi tạm — giữ danh sách cũ
      }
    },
    [playNotifySound],
  );

  const refresh = useCallback(
    async (key = adminKey, options: { silent?: boolean } = {}) => {
      if (!key) return;
      if (!options.silent) {
        setLoading(true);
        setMessage("Đang tải dữ liệu...");
      }
      try {
        const next = await adminApi<AdminSnapshot>("/admin/api/snapshot?limit=300&pool_limit=20000", key);
        setData(next);
        setMessage(`Cập nhật lúc ${next.generated_at} (${next.timezone})`);
        await fetchNotifications(key);
      } catch (err) {
        if (!options.silent) {
          setMessage(err instanceof Error ? err.message : "Không tải được dữ liệu");
        }
        throw err;
      } finally {
        if (!options.silent) setLoading(false);
      }
    },
    [adminKey, fetchNotifications],
  );

  useEffect(() => {
    if (adminKey) refresh(adminKey).catch(() => undefined);
  }, [adminKey, refresh]);

  useEffect(() => {
    if (!adminKey) return;
    const timer = window.setInterval(() => {
      refresh(adminKey, { silent: true }).catch(() => undefined);
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [adminKey, refresh]);

  useEffect(() => {
    const onPageShow = (e: PageTransitionEvent) => {
      if (!e.persisted) return;
      const k = sessionStorage.getItem("admin_key") || "";
      if (k) void fetchNotifications(k);
    };
    window.addEventListener("pageshow", onPageShow);
    return () => window.removeEventListener("pageshow", onPageShow);
  }, [fetchNotifications]);

  useEffect(() => {
    document.title = unreadCount ? `(${unreadCount}) VM STORE` : "VM STORE";
  }, [unreadCount]);

  const handleLogin = async (key: string) => {
    await adminApi("/admin/api/login", key);
    sessionStorage.setItem("admin_key", key);
    setAdminKey(key);
    notifHydratedRef.current = false;
    prevNotifIdsRef.current = new Set();
  };

  const handleLogout = () => {
    sessionStorage.removeItem("admin_key");
    setAdminKey("");
    setData(null);
    setNotifications([]);
    notifHydratedRef.current = false;
    prevNotifIdsRef.current = new Set();
  };

  const markAllNotificationsRead = useCallback(async () => {
    if (!adminKey) return;
    try {
      await adminApi("/admin/api/notifications/read", adminKey, {
        method: "POST",
        body: JSON.stringify({ all: true }),
      });
      await fetchNotifications(adminKey);
    } catch {
      toast.error("Không đánh dấu đã đọc được");
    }
  }, [adminKey, fetchNotifications]);

  const clearAllNotifications = useCallback(async () => {
    if (!adminKey) return;
    try {
      await adminApi("/admin/api/notifications/clear", adminKey, { method: "POST", body: "{}" });
      setNotifications([]);
      prevNotifIdsRef.current = new Set();
      notifHydratedRef.current = false;
      await fetchNotifications(adminKey);
    } catch {
      toast.error("Không xóa được thông báo trên sheet");
    }
  }, [adminKey, fetchNotifications]);

  if (!isAuthenticated) {
    return <AdminLogin onLogin={handleLogin} />;
  }

  const common = { data, adminKey, refresh };
  const renderSection = () => {
    switch (section) {
      case "overview":
        return (
          <Overview
            data={data}
            notifications={notifications}
            onOpenOrders={(status) => {
              setOrderPreset({ status, nonce: Date.now() });
              setSection("orders");
            }}
            onOpenInventory={(status, stockCode) => {
              setInventoryPreset({ status, stockCode, nonce: Date.now() });
              setSection("inventory");
            }}
            onOpenUsers={() => setSection("users")}
            onOpenNotifications={() => setSection("notifications")}
            onOpenNotificationOrder={(orderId, status) => {
              setOrderPreset({ orderId, status, nonce: Date.now() });
              setSection("orders");
            }}
            onMarkNotificationsRead={markAllNotificationsRead}
            onOpenRevenue={() => setSection("revenue")}
          />
        );
      case "revenue":
        return <Revenue data={data} />;
      case "notifications":
        return (
          <Notifications
            items={notifications}
            onMarkAllRead={markAllNotificationsRead}
            onClearAll={clearAllNotifications}
            onOpenOrder={(orderId, status) => {
              setOrderPreset({ orderId, status, nonce: Date.now() });
              setSection("orders");
            }}
          />
        );
      case "products":
        return <Products {...common} />;
      case "inventory":
        return <Inventory {...common} preset={inventoryPreset} />;
      case "orders":
        return <Orders {...common} preset={orderPreset} />;
      case "users":
        return <Users data={data} />;
      case "reservations":
        return <Reservations data={data} />;
      case "fulfillments":
        return <Fulfillments data={data} />;
    }
  };

  return (
    <div className="flex h-screen bg-slate-50 overflow-hidden">
      <Toaster richColors position="top-right" />
      <Sidebar
        active={section}
        notifyAlerts={unreadCount}
        onChange={setSection}
        onLogout={handleLogout}
      />
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-7xl mx-auto px-4 py-6 pt-16 md:pt-6">
          <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h1 className="text-xl font-semibold tracking-tight">VM STORE</h1>
              <p className="text-xs text-muted-foreground">{message || "Sẵn sàng quản lý bot bán hàng"}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              {unreadCount > 0 && (
                <Button
                  size="sm"
                  variant="secondary"
                  className="gap-2"
                  onClick={() => setSection("notifications")}
                >
                  <Bell size={15} />
                  {unreadCount} thông báo mới
                </Button>
              )}
              <Button size="sm" variant="outline" className="gap-2" onClick={() => refresh()} disabled={loading}>
                <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
                Làm mới
              </Button>
            </div>
          </div>
          <div className="mb-4 md:hidden">
            <select
              className="w-full h-11 rounded-md border border-border bg-white px-3 text-sm font-medium shadow-sm"
              value={section}
              onChange={(event) => setSection(event.target.value as AdminSection)}
            >
              {NAV_ITEMS.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>
          {renderSection()}
        </div>
      </main>
    </div>
  );
}
