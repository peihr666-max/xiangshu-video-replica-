import { useState } from "react";

import { AuditEventsPage } from "./AuditEventsPage";
import { PageBanner } from "./ui/PageBanner";
import { TabBar } from "./ui/TabBar";

const tabs = [
  { id: "audit", label: "审计日志" },
  { id: "adjustments", label: "调账记录" },
];

/**
 * v4 导航合并 — 审计中心：审计日志与调账记录合并为一个菜单项。
 * 调账记录当前按客户归档（从客户详情进入），全局调账检索
 * 依赖服务端全局查询端点，就绪前此页签给出指引。
 */
export function AuditCenterPage() {
  const [tab, setTab] = useState("audit");
  return (
    <div>
      <TabBar
        active={tab}
        ariaLabel="审计中心页签"
        items={tabs}
        onChange={setTab}
      />
      {tab === "audit" ? <AuditEventsPage /> : null}
      {tab === "adjustments" ? (
        <section className="admin-panel" aria-label="调账记录">
          <h2>调账记录</h2>
          <PageBanner tone="notice">
            调账记录按客户归档：请从「客户列表 → 查看详情 → 调账历史」查看指定
            客户的调账历史；支持操作人与来源单筛选的全局调账检索即将上线。
          </PageBanner>
        </section>
      ) : null}
    </div>
  );
}
