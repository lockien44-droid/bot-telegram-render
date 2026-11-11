import { ShoppingBag, Wallet, Clock3, AlertCircle, ArrowUpRight, Package, CheckCircle2, Users } from "lucide-react";
import { money, text, sortOrdersNewestFirst, type AdminSnapshot } from "../../api";
import type { OrderNotification } from "../../notifications";
import { NotificationFeed, NotificationFeedHeader } from "../NotificationFeed";
import { StatusBadge } from "../StatusBadge";
import { getRevenueStats } from "../../revenue";

type Props = {
  data: AdminSnapshot | null; notifications?: OrderNotification[];
  onOpenOrders?: (status?: string) => void; onOpenInventory?: (status?: string, code?: string) => void;
  onOpenUsers?: () => void; onOpenNotifications?: () => void; onMarkNotificationsRead?: () => void;
  onOpenNotificationOrder?: (id: string, status?: string) => void;
  onOpenRevenue?: () => void; onOpenReviews?: () => void;
};
export function Overview({ data, notifications = [], onOpenOrders, onOpenInventory, onOpenUsers, onOpenNotifications, onMarkNotificationsRead, onOpenNotificationOrder, onOpenRevenue, onOpenReviews }: Props) {
  if (!data) return <div role="status" className="grid grid-cols-2 lg:grid-cols-4 gap-4">{[1,2,3,4].map(i => <div key={i} className="surface h-36 animate-pulse bg-slate-100" />)}<span className="sr-only">Đang tải tổng quan</span></div>;
  const stats = getRevenueStats(data);
  const counts = data.summary.status_counts;
  const cards = [
    { title: "Doanh thu hôm nay", value: money(stats.today.revenue), note: `${stats.today.orders} đơn đã thanh toán`, icon: Wallet, action: onOpenRevenue, featured: true },
    { title: "Chờ thanh toán", value: counts.PENDING || 0, note: "Đơn đang giữ hàng", icon: Clock3, action: () => onOpenOrders?.("PENDING") },
    { title: "Chờ giao hàng", value: (counts.PAID || 0) + (counts.DELIVERY_PENDING || 0), note: "Đã nhận tiền, chưa giao xong", icon: ShoppingBag, action: () => onOpenOrders?.("AWAITING_DELIVERY") },
    { title: "Cần xử lý", value: data.summary.review_count ?? "—", note: "Thanh toán và vận hành", icon: AlertCircle, action: onOpenReviews },
  ];
  const latest = sortOrdersNewestFirst(data.orders).slice(0,6);
  const lowStock = data.products.filter(p => Number(p.READY || 0) < 3);
  return <div className="space-y-6">
    <div><p className="eyebrow">GÓC NHÌN HÔM NAY</p><h2 className="page-title">Tổng quan cửa hàng</h2><p className="page-subtitle">Các chỉ số chính và công việc cần chú ý.</p></div>
    <div className="grid grid-cols-2 xl:grid-cols-4 gap-3 sm:gap-4">{cards.map(({title,value,note,icon:Icon,action,featured}) => <button key={title} onClick={action} className={`rounded-2xl p-4 sm:p-5 text-left border transition hover:-translate-y-0.5 hover:shadow-md ${featured ? "bg-emerald-800 border-emerald-800 text-white shadow-sm" : "bg-white border-slate-200/80"}`}><div className="flex justify-between gap-2 items-start"><span className={`text-xs sm:text-sm font-medium ${featured ? "text-emerald-100" : "text-slate-500"}`}>{title}</span><Icon size={19} className={featured ? "text-emerald-200" : "text-emerald-700"} /></div><p className="mt-5 text-2xl sm:text-3xl font-semibold tracking-tight tabular-nums break-words">{value}</p><p className={`text-[11px] sm:text-xs mt-2 ${featured ? "text-emerald-100/80" : "text-slate-400"}`}>{note}</p></button>)}</div>
    <div className="surface flex flex-wrap gap-x-8 gap-y-3 px-5 py-4 text-sm"><button onClick={() => onOpenOrders?.()} className="flex gap-2 items-center"><ShoppingBag size={16} className="text-slate-400" /><strong>{data.summary.orders}</strong><span className="text-slate-500">tổng đơn</span></button><button onClick={() => onOpenInventory?.("READY")} className="flex gap-2 items-center"><Package size={16} className="text-slate-400" /><strong>{data.summary.stock_ready}</strong><span className="text-slate-500">hàng có sẵn</span></button><button onClick={onOpenUsers} className="flex gap-2 items-center"><Users size={16} className="text-slate-400" /><strong>{data.summary.users}</strong><span className="text-slate-500">khách hàng</span></button><button onClick={() => onOpenOrders?.("DELIVERED")} className="flex gap-2 items-center"><CheckCircle2 size={16} className="text-slate-400" /><strong>{counts.DELIVERED || 0}</strong><span className="text-slate-500">đã giao</span></button></div>
    <div className="grid xl:grid-cols-[1.6fr_1fr] gap-5">
      <section className="surface overflow-hidden"><div className="flex justify-between items-center px-5 py-4 border-b border-slate-100"><h3 className="font-semibold">Đơn hàng gần đây</h3><button className="text-sm text-emerald-700 flex items-center gap-1" onClick={() => onOpenOrders?.()}>Xem tất cả<ArrowUpRight size={15} /></button></div>{latest.length ? latest.map(o => <button key={o.order_id} className="w-full text-left px-5 py-4 border-b last:border-b-0 border-slate-100 flex flex-wrap justify-between items-center gap-3 hover:bg-slate-50" onClick={() => onOpenNotificationOrder?.(o.order_id,o.status)}><div className="min-w-0"><p className="text-sm font-medium break-all">{o.order_id}</p><p className="text-xs text-slate-400 mt-1">{o.stock_code} × {o.qty} · {o.created_at}</p></div><div className="text-right space-y-1.5"><p className="text-sm font-semibold">{money(o.total)}</p><StatusBadge status={o.status} /></div></button>) : <p className="p-8 text-center text-slate-400 text-sm">Chưa có đơn hàng.</p>}</section>
      <section className="surface overflow-hidden"><div className="px-5 py-4 border-b border-slate-100"><h3 className="font-semibold">Tồn kho cần chú ý</h3><p className="text-xs text-slate-400 mt-1">Sản phẩm còn dưới 3 hàng có sẵn.</p></div>{lowStock.length ? lowStock.slice(0,6).map(p => <button key={p.stock_code} onClick={() => onOpenInventory?.("READY",p.stock_code)} className="w-full px-5 py-4 border-b last:border-b-0 border-slate-100 flex items-center justify-between gap-3 text-left hover:bg-slate-50"><div><p className="text-sm font-medium">{p.name}</p><p className="text-xs text-slate-400 mt-1">{money(p.price)}</p></div><span className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${Number(p.READY) ? "bg-amber-50 text-amber-800" : "bg-rose-50 text-rose-700"}`}>{Number(p.READY) ? `Còn ${p.READY}` : "Hết hàng"}</span></button>) : <p className="p-8 text-sm text-emerald-700">Tồn kho đang đủ để phục vụ.</p>}</section>
    </div>
    <section className="surface p-5"><NotificationFeedHeader unread={notifications.filter(n => !n.read).length} total={notifications.length} onViewAll={onOpenNotifications} onMarkAllRead={onMarkNotificationsRead} /><div className="mt-4"><NotificationFeed items={notifications} limit={5} compact onOpenOrder={(id,status) => onOpenNotificationOrder?.(id,status)} /></div></section>
  </div>;
}
