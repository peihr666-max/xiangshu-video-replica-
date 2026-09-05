import { useState } from "react";

import { ProfitOverview } from "./ProfitOverview";
import { TabBar } from "./ui/TabBar";

const tabs = [
  { id: "profit", label: "利润总览" },
  { id: "cost", label: "成本明细" },
];

/**
 * v4 导航合并 — 经营分析：利润总览（每日对外售价 + 收入/成本/毛利报表）
 * 与成本明细（按日成本构成，随成本统计任务接入）。
 */
export function AnalyticsPage() {
  const [tab, setTab] = useState("profit");
  return (
    <div>
      <TabBar
        active={tab}
        ariaLabel="经营分析页签"
        items={tabs}
        onChange={setTab}
      />
      {tab === "profit" ? <ProfitOverview /> : null}
      {tab === "cost" ? (
        <section className="admin-panel" aria-label="成本明细">
          <h2>成本明细</h2>
          <p>按日的视频生成、视频解析与图片生成成本构成即将上线。</p>
        </section>
      ) : null}
    </div>
  );
}
