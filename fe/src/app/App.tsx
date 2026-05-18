import { useCallback, useEffect, useRef, useState } from "react";
import { Bell, RefreshCw } from "lucide-react";
import { toast, Toaster } from "sonner";
import { AdminLogin } from "./components/AdminLogin";
import { NAV_ITEMS, Sidebar, type AdminSection } from "./components/Sidebar";
import { Overview } from "./components/sections/Overview";
import { Products } from "./components/sections/Products";
import { Inventory } from "./components/sections/Inventory";
import { Materials } from "./components/sections/Materials";
import { Orders } from "./components/sections/Orders";
import { Users } from "./components/sections/Users";
import { Reservations } from "./components/sections/Reservations";
import { Fulfillments } from "./components/sections/Fulfillments";
import { Notifications } from "./components/sections/Notifications";
import { Button } from "./components/ui/button";
import { adminApi, money, text, type AdminSnapshot } from "./api";
import {
  buildNotifications,
  MAX_NOTIFICATIONS,
  NOTIFY_META,
  type NotifyKind,
  type OrderNotification,
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

  const pushNotify = useCallback((kind: NotifyKind, orders: any[]) => {
    if (!orders.length) return;
    const batch = buildNotifications(kind, orders);
    setNotifications((prev) => [...batch, ...prev].slice(0, MAX_NOTIFICATIONS));
  }, []);

  const seenOrdersRef = useRef<Set<string>>(new Set());
  const orderStatusRef = useRef<Map<string, string>>(new Map());
  const initializedRef = useRef(false);
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

  const notifyFromSnapshot = useCallback((next: AdminSnapshot) => {
    const nextIds = new Set<string>();
    const newOrders: any[] = [];
    const deliveredOrders: any[] = [];
    const cancelledOrders: any[] = [];

    for (const order of next.orders || []) {
      const id = text(order.order_id);
      if (id === "—") continue;
      const status = text(order.status).toUpperCase();
      nextIds.add(id);

      const prevStatus = orderStatusRef.current.get(id);
      if (initializedRef.current) {
        if (!seenOrdersRef.current.has(id)) {
          newOrders.push(order);
        } else if (prevStatus && prevStatus !== status) {
          if (status === "DELIVERED") deliveredOrders.push(order);
          else if (status === "CANCELLED" || status === "EXPIRED") cancelledOrders.push(order);
        }
      }

      orderStatusRef.current.set(id, status);
    }

    if (initializedRef.current) {
      const toastFor = (kind: NotifyKind, list: any[]) => {
        if (!list.length) return;
        playNotifySound();
        pushNotify(kind, list);
        const meta = NOTIFY_META[kind];
        const first = list[0];
        const desc = `${text(first.stock_code)} - ${money(first.total)} - ${text(first.order_id)}`;
        const count = list.length;
        const title = count > 1 ? `${meta.title} (${count})` : meta.title;
        if (kind === "new") toast.success(title, { description: desc, duration: 7000 });
        else if (kind === "cancelled" || kind === "expired") toast.error(title, { description: desc, duration: 7000 });
        else toast(title, { description: desc, duration: 7000 });
      };

      toastFor("new", newOrders);
      for (const o of cancelledOrders) {
        const st = text(o.status).toUpperCase();
        toastFor(st === "CANCELLED" ? "cancelled" : "expired", [o]);
      }
      toastFor("delivered", deliveredOrders);
    }

    seenOrdersRef.current = nextIds;
    initializedRef.current = true;
  }, [playNotifySound, pushNotify]);

  const refresh = useCallback(async (key = adminKey, options: { silent?: boolean } = {}) => {
    if (!key) return;
    if (!options.silent) {
      setLoading(true);
      setMessage("Đang tải dữ liệu...");
    }
    try {
      const next = await adminApi<AdminSnapshot>("/admin/api/snapshot?limit=300&pool_limit=20000", key);
      notifyFromSnapshot(next);
      setData(next);
      setMessage(`Cập nhật lúc ${next.generated_at} (${next.timezone})`);
    } catch (err) {
      if (!options.silent) {
        setMessage(err instanceof Error ? err.message : "Không tải được dữ liệu");
      }
      throw err;
    } finally {
      if (!options.silent) setLoading(false);
    }
  }, [adminKey, notifyFromSnapshot]);

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
    document.title = unreadCount ? `(${unreadCount}) VM STORE` : "VM STORE";
  }, [unreadCount]);

  const handleLogin = async (key: string) => {
    await adminApi("/admin/api/login", key);
    sessionStorage.setItem("admin_key", key);
    setAdminKey(key);
    setNotifications([]);
  };

  const handleLogout = () => {
    sessionStorage.removeItem("admin_key");
    setAdminKey("");
    setData(null);
    setNotifications([]);
    initializedRef.current = false;
    seenOrdersRef.current = new Set();
    orderStatusRef.current = new Map();
  };

  if (!isAuthenticated) {
    return <AdminLogin onLogin={handleLogin} />;
  }

  const common = { data, adminKey, refresh };
  const renderSection = () => {
    switch (section) {
      case "overview": return (
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
          onMarkNotificationsRead={() => setNotifications((prev) => prev.map((n) => ({ ...n, read: true })))}
        />
      );
      case "notifications": return (
        <Notifications
          items={notifications}
          onMarkAllRead={() => setNotifications((prev) => prev.map((n) => ({ ...n, read: true })))}
          onClearAll={() => setNotifications([])}
          onOpenOrder={(orderId, status) => {
            setOrderPreset({ orderId, status, nonce: Date.now() });
            setSection("orders");
          }}
        />
      );
      case "products": return <Products {...common} />;
      case "inventory": return <Inventory {...common} preset={inventoryPreset} />;
      case "materials": return <Materials {...common} />;
      case "orders": return <Orders {...common} preset={orderPreset} />;
      case "users": return <Users data={data} />;
      case "reservations": return <Reservations data={data} />;
      case "fulfillments": return <Fulfillments data={data} />;
    }
  };

  return (
    <div className="flex h-screen bg-slate-50 overflow-hidden">
      <Toaster richColors position="top-right" />
      <Sidebar
        active={section}
        notifyAlerts={unreadCount}
        onChange={(next) => {
          setSection(next);
          if (next === "notifications") {
            setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
          }
        }}
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
              onChange={(event) => {
                const next = event.target.value as AdminSection;
                setSection(next);
                if (next === "notifications") {
                  setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
                }
              }}
            >
              {NAV_ITEMS.map((item) => (
                <option key={item.id} value={item.id}>{item.label}</option>
              ))}
            </select>
          </div>
          {renderSection()}
        </div>
      </main>
    </div>
  );
}
