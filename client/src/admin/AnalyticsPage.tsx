import { useState } from "react";
import { CostDetails } from "./CostDetails";
import { ProfitOverview } from "./ProfitOverview";
import "./economics.css";
import { TabBar } from "./ui/TabBar";

const tabs = [
  { id: "profit", label: "利润总览" },
  { id: "cost", label: "成本明细" },
];

/**
 * v4 导航合并 — 经营分析：利润总览（每日对外售价 + 收入/成本/毛利报表）
 * 与成本明细（按日成本构成，随成本统计任务接入）。
 */
export function AnalyticsPage({
  readOnly = false,
  initialTab = "profit",
}: {
  readOnly?: boolean;
  initialTab?: "profit" | "cost";
}) {
  const [tab, setTab] = useState<string>(initialTab);
  return (
    <div>
      <TabBar
        active={tab}
        ariaLabel="经营分析页签"
        items={tabs}
        onChange={setTab}
      />
      {tab === "profit" ? <ProfitOverview readOnly={readOnly} /> : null}
      {tab === "cost" ? <CostDetails /> : null}
    </div>
  );
}
