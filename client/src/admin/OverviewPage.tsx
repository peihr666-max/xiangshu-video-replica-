import { useCallback, useEffect, useState } from "react";

import { type DashboardSummary, getDashboardSummary } from "../api.admin";
import { PageBanner } from "./ui/PageBanner";

function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2);
}

function KpiCard({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "warn" | "danger";
}) {
  return (
    <section
      className={`admin-summary-card${tone === "warn" ? " is-warning" : ""}${tone === "danger" ? " is-danger" : ""}`}
      aria-label={label}
    >
      <strong>{value}</strong>
      <span>{label}</span>
      {sub ? <small>{sub}</small> : null}
    </section>
  );
}

function TodoRow({
  label,
  count,
  tone,
  onOpen,
}: {
  label: string;
  count: number;
  tone: "warn" | "danger" | "info";
  onOpen?: () => void;
}) {
  return (
    <li>
      <span>{label}</span>
      <span className={`status-badge status-badge--${tone}`}>{count}</span>
      {onOpen ? (
        <button type="button" onClick={onOpen}>
          去处理
        </button>
      ) : null}
    </li>
  );
}

/**
 * W15 — 总览仪表盘：KPI、近 7 日生成趋势、待办事项与快捷操作。
 * 数据来自 GET /api/control/dashboard/summary（AdminReader）。
 */
export function OverviewPage({
  readOnly = false,
  onNavigate,
}: {
  readOnly?: boolean;
  onNavigate?: (tab: string) => void;
}) {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setError("");
      setSummary(await getDashboardSummary());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "读取仪表盘失败");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) {
    return <PageBanner tone="error">{error}</PageBanner>;
  }
  if (!summary) {
    return (
      <section className="admin-panel" aria-label="总览仪表盘">
        <p>正在加载仪表盘…</p>
      </section>
    );
  }

  const { today, trend, todos, device_slots } = summary;
  const maxTrend = Math.max(
    1,
    ...trend.map((point) => point.succeeded + point.failed),
  );
  const todoItems: Array<{
    key: string;
    label: string;
    count: number;
    tone: "warn" | "danger" | "info";
    tab: string;
  }> = [
    {
      key: "pairings",
      label: "待批准配对",
      count: todos.pending_pairings,
      tone: "warn",
      tab: "customersMgmt",
    },
    {
      key: "failed",
      label: "失败任务待处理",
      count: todos.failed_tasks_7d,
      tone: "danger",
      tab: "generationRecords",
    },
    {
      key: "recon",
      label: "对账不一致",
      count: todos.reconciliation_problems,
      tone: "warn",
      tab: "funds",
    },
    {
      key: "expiring",
      label: "即将过期激活码",
      count: todos.expiring_codes_7d,
      tone: "info",
      tab: "customersMgmt",
    },
  ];

  return (
    <div className="dashboard-page">
      <div className="admin-summary-grid">
        <KpiCard
          label="今日生成"
          value={String(today.generation_count)}
          sub={`成功 ${today.succeeded}`}
        />
        <KpiCard
          label="在线设备"
          value={String(today.online_devices)}
          sub={`活跃客户 ${today.active_customers}`}
        />
        <KpiCard label="今日充值" value={`¥${fenToYuan(today.recharge_fen)}`} />
        <KpiCard
          label="设备槽位占用"
          value={`${device_slots.bound} / ${device_slots.total}`}
          sub="已绑定 / 总槽位"
        />
      </div>

      <section className="admin-panel" aria-label="近 7 日生成趋势">
        <h2>近 7 日生成趋势</h2>
        {trend.length === 0 ? (
          <p>暂无数据。</p>
        ) : (
          <div className="dashboard-trend" aria-label="趋势柱状图">
            {trend.map((point) => (
              <div
                className="dashboard-trend__col"
                key={point.day}
                title={`${point.day}：成功 ${point.succeeded} / 失败 ${point.failed}`}
              >
                <div className="dashboard-trend__bars">
                  <div
                    className="dashboard-trend__bar dashboard-trend__bar--ok"
                    style={{
                      height: `${Math.round((point.succeeded / maxTrend) * 100)}%`,
                    }}
                  />
                  <div
                    className="dashboard-trend__bar dashboard-trend__bar--bad"
                    style={{
                      height: `${Math.round((point.failed / maxTrend) * 100)}%`,
                    }}
                  />
                </div>
                <span>{point.day.slice(5)}</span>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="admin-panel" aria-label="待办事项">
        <h2>待办事项</h2>
        <ul className="dashboard-todos">
          {todoItems.map((item) => (
            <TodoRow
              key={item.key}
              count={item.count}
              label={item.label}
              tone={item.tone}
              onOpen={
                !readOnly && item.count > 0
                  ? () => onNavigate?.(item.tab)
                  : undefined
              }
            />
          ))}
        </ul>
      </section>

      {!readOnly ? (
        <section className="admin-panel" aria-label="快捷操作">
          <h2>快捷操作</h2>
          <div className="dashboard-quick-actions">
            <button type="button" onClick={() => onNavigate?.("customersMgmt")}>
              快速发码
            </button>
            <button type="button" onClick={() => onNavigate?.("funds")}>
              充值订单
            </button>
            <button type="button" onClick={() => onNavigate?.("auditCenter")}>
              审计中心
            </button>
            <button type="button" onClick={() => onNavigate?.("analytics")}>
              经营分析
            </button>
          </div>
        </section>
      ) : null}
    </div>
  );
}
