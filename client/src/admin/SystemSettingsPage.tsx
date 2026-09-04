import { useState } from "react";
import { SettingsPanel } from "../SettingsPanel";
import { PaymentSettingsSection } from "./PaymentSettingsSection";
import { QueueModeSection } from "./QueueModeSection";
import { TabBar } from "./ui/TabBar";

const tabs = [
  { id: "payment", label: "支付与价格" },
  { id: "rates", label: "费率管理" },
  { id: "services", label: "服务配置" },
];

/**
 * v4 导航合并 — 系统设置：支付与价格、费率管理、服务配置合并为一个菜单项。
 * 费率管理（上游成本费率与对外售价）由费率配置任务接入，当前先提供页签。
 */
export function SystemSettingsPage({
  readOnly = false,
}: {
  readOnly?: boolean;
}) {
  const [tab, setTab] = useState("payment");
  return (
    <div>
      <TabBar
        active={tab}
        ariaLabel="系统设置页签"
        items={tabs}
        onChange={setTab}
      />
      {tab === "payment" ? (
        <PaymentSettingsSection readOnly={readOnly} />
      ) : null}
      {tab === "rates" ? (
        <section className="admin-panel" aria-label="费率管理">
          <h2>费率管理</h2>
          <p>上游成本费率与对外售价（按秒计费）的配置即将上线。</p>
        </section>
      ) : null}
      {tab === "services" ? (
        <>
          <QueueModeSection readOnly={readOnly} />
          <section className="admin-panel" aria-label="服务配置">
            <SettingsPanel readOnly={readOnly} source="control" />
          </section>
        </>
      ) : null}
    </div>
  );
}
