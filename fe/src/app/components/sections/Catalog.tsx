import { useEffect, useState } from "react";
import { Package } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../ui/tabs";
import type { AdminSnapshot } from "../../api";
import { Products } from "./Products";
import { Inventory } from "./Inventory";

interface Props {
  data: AdminSnapshot | null;
  adminKey: string;
  refresh: () => Promise<void>;
  preset?: { status?: string; stockCode?: string; nonce: number };
}

export function Catalog({ data, adminKey, refresh, preset }: Props) {
  const [tab, setTab] = useState<"products" | "inventory">("products");

  useEffect(() => {
    if (!preset?.nonce) return;
    setTab("inventory");
  }, [preset?.nonce, preset?.status, preset?.stockCode]);

  return (
    <div className="space-y-4">
      <h2 className="flex items-center gap-2">
        <Package size={20} />
        Sản phẩm &amp; Kho
      </h2>

      <Tabs value={tab} onValueChange={(v) => setTab(v as "products" | "inventory")}>
        <TabsList>
          <TabsTrigger value="products">Sản phẩm</TabsTrigger>
          <TabsTrigger value="inventory">Kho hàng</TabsTrigger>
        </TabsList>

        <TabsContent value="products" className="mt-4 space-y-0">
          <Products embedded data={data} adminKey={adminKey} refresh={refresh} />
        </TabsContent>

        <TabsContent value="inventory" className="mt-4 space-y-0">
          <Inventory embedded data={data} adminKey={adminKey} refresh={refresh} preset={preset} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
