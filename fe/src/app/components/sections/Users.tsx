import { useMemo, useState } from "react";
import { Card, CardContent } from "../ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../ui/table";
import { Input } from "../ui/input";
import { Button } from "../ui/button";
import { ArrowDownWideNarrow, ArrowUpNarrowWide, Search, Users as UsersIcon } from "lucide-react";
import { money, text, type AdminSnapshot, type AnyRow } from "../../api";

interface Props {
  data: AdminSnapshot | null;
}

type SpendSort = "default" | "desc" | "asc";

const spentValue = (user: AnyRow) => Number(user.spent || 0);

export function Users({ data }: Props) {
  const [search, setSearch] = useState("");
  const [spendSort, setSpendSort] = useState<SpendSort>("default");
  const users = data?.users || [];

  const visible = useMemo(() => {
    const filtered = users.filter((u) => {
      const hay = `${text(u.chat_id)} ${text(u.user_id)} ${text(u.username)} ${text(u.full_name)}`.toLowerCase();
      return !search || hay.includes(search.toLowerCase());
    });
    if (spendSort === "default") return filtered;
    return [...filtered].sort((a, b) => {
      const diff = spentValue(a) - spentValue(b);
      return spendSort === "asc" ? diff : -diff;
    });
  }, [search, spendSort, users]);

  const toggleSpendSort = (next: SpendSort) => {
    setSpendSort((current) => (current === next ? "default" : next));
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="flex items-center gap-2"><UsersIcon size={20} /> Khách hàng</h2>
        <span className="text-sm text-muted-foreground">{users.length} người dùng đã bấm bot</span>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative max-w-xs">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input className="pl-8 w-64" placeholder="User ID / username / tên" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <Button
          type="button"
          variant={spendSort === "desc" ? "secondary" : "outline"}
          size="sm"
          className="gap-1.5"
          title="Sắp xếp tổng chi từ lớn đến bé"
          onClick={() => toggleSpendSort("desc")}
        >
          <ArrowDownWideNarrow size={15} /> Tổng chi cao → thấp
        </Button>
        <Button
          type="button"
          variant={spendSort === "asc" ? "secondary" : "outline"}
          size="sm"
          className="gap-1.5"
          title="Sắp xếp tổng chi từ bé đến lớn"
          onClick={() => toggleSpendSort("asc")}
        >
          <ArrowUpNarrowWide size={15} /> Tổng chi thấp → cao
        </Button>
      </div>

      <Card className="shadow-sm">
        <CardContent className="p-0 overflow-x-auto">
          <Table className="min-w-[780px]">
            <TableHeader>
              <TableRow>
                <TableHead>Chat ID</TableHead>
                <TableHead>Username</TableHead>
                <TableHead>Họ tên</TableHead>
                <TableHead className="text-center">Tổng đơn</TableHead>
                <TableHead className="text-right">Tổng chi</TableHead>
                <TableHead>Cập nhật</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((u, idx) => (
                <TableRow key={text(u.chat_id || u.user_id || idx)}>
                  <TableCell className="text-xs font-mono">{text(u.chat_id || u.user_id)}</TableCell>
                  <TableCell className="text-sm text-blue-600">{text(u.username)}</TableCell>
                  <TableCell className="text-sm">{text(u.full_name || u.name)}</TableCell>
                  <TableCell className="text-center">{text(u.orders)}</TableCell>
                  <TableCell className="text-right text-emerald-700 text-sm">{money(u.spent)}</TableCell>
                  <TableCell className="text-xs text-muted-foreground whitespace-nowrap">{text(u.updated_at)}</TableCell>
                </TableRow>
              ))}
              {visible.length === 0 && <TableRow><TableCell colSpan={6} className="text-center text-muted-foreground py-8">Không tìm thấy khách hàng nào</TableCell></TableRow>}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
