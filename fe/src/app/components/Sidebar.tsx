import { LayoutDashboard, Package, ClipboardList, Users, BookMarked, Truck, LogOut, Menu, X, Bell, DollarSign } from "lucide-react";
import { Button } from "./ui/button";
import { type ReactNode, useState } from "react";

export type AdminSection =
  | "overview"
  | "revenue"
  | "notifications"
  | "catalog"
  | "orders"
  | "payment_reviews"
  | "users"
  | "reservations"
  | "fulfillments";

export const NAV_ITEMS: { id: AdminSection; label: string; icon: ReactNode }[] = [
  { id: "overview", label: "Tổng quan", icon: <LayoutDashboard size={18} /> },
  { id: "revenue", label: "Doanh thu", icon: <DollarSign size={18} /> },
  { id: "notifications", label: "Thông báo", icon: <Bell size={18} /> },
  { id: "catalog", label: "Sản phẩm & Kho", icon: <Package size={18} /> },
  { id: "payment_reviews", label: "Thanh toán cần xử lý", icon: <ClipboardList size={18} /> },
  { id: "orders", label: "Đơn hàng", icon: <ClipboardList size={18} /> },
  { id: "users", label: "Khách hàng", icon: <Users size={18} /> },
  { id: "reservations", label: "Giữ hàng", icon: <BookMarked size={18} /> },
  { id: "fulfillments", label: "Giao hàng", icon: <Truck size={18} /> },
];

interface SidebarProps {
  active: AdminSection;
  notifyAlerts?: number;
  reviewAlerts?: number;
  onChange: (s: AdminSection) => void;
  onLogout: () => void;
}

export function Sidebar({ active, notifyAlerts = 0, reviewAlerts = 0, onChange, onLogout }: SidebarProps) {
  const [open, setOpen] = useState(false);

  const navContent = (
    <nav className="flex flex-col h-full">
      <div className="px-5 py-6 border-b border-slate-100 flex gap-3 items-center"><div className="h-10 w-10 rounded-xl bg-emerald-800 text-white flex items-center justify-center text-sm font-bold tracking-tight">VM</div><div><p className="text-sm font-semibold tracking-wide">VM STORE</p><p className="text-[11px] text-slate-400 mt-1">Quản trị cửa hàng</p></div></div>

      <div className="flex-1 px-3 py-5 space-y-1 overflow-y-auto">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            onClick={() => { onChange(item.id); setOpen(false); }}
            className={`w-full flex items-center gap-3 px-3 py-3 rounded-xl text-[13px] transition-colors ${
              active === item.id
                ? "bg-emerald-50 text-emerald-900 font-semibold"
                : "text-slate-500 hover:bg-slate-50 hover:text-slate-900"
            }`}
          >
            {item.icon}
            <span className="flex-1 text-left">{item.label}</span>
            {((item.id === "notifications" && notifyAlerts > 0) || (item.id === "payment_reviews" && reviewAlerts > 0)) && (
              <span className={`min-w-[1.25rem] px-1.5 py-0.5 rounded-full text-xs font-semibold text-center ${
                active === item.id ? "bg-emerald-700 text-white" : "bg-amber-100 text-amber-800"
              }`}>
                {(item.id === "payment_reviews" ? reviewAlerts : notifyAlerts) > 99 ? "99+" : (item.id === "payment_reviews" ? reviewAlerts : notifyAlerts)}
              </span>
            )}
          </button>
        ))}
      </div>

      <div className="p-3 border-t border-border">
        <Button variant="ghost" size="sm" className="w-full gap-2 justify-start" onClick={onLogout}>
          <LogOut size={16} />
          Đăng xuất
        </Button>
      </div>
    </nav>
  );

  return (
    <>
      <aside className="hidden md:flex flex-col w-64 bg-white border-r border-border flex-shrink-0 h-screen sticky top-0">
        {navContent}
      </aside>

      <div className="md:hidden fixed top-3 left-3 z-50">
        <Button variant="outline" size="icon" aria-label={open ? "Đóng menu" : "Mở menu"} aria-expanded={open} onClick={() => setOpen((v) => !v)}>
          {open ? <X size={18} /> : <Menu size={18} />}
        </Button>
      </div>

      {open && (
        <div className="md:hidden fixed inset-0 z-40 flex">
          <div className="w-[82vw] max-w-xs bg-white h-full shadow-xl">{navContent}</div>
          <div className="flex-1 bg-black/30" onClick={() => setOpen(false)} />
        </div>
      )}
    </>
  );
}
