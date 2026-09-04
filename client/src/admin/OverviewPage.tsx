/**
 * v4 导航合并 — 总览仪表盘（骨架占位）。
 * KPI、生成与成本趋势、待办事项与快捷操作由经营统计任务接入；
 * 当前先落地导航与布局骨架，避免阻塞合并式信息架构。
 */
export function OverviewPage() {
  return (
    <div className="admin-placeholder-grid">
      <section className="admin-panel" aria-label="经营指标">
        <h2>经营指标</h2>
        <p>今日生成、成功率、在线设备、活跃客户与充值汇总即将上线。</p>
      </section>
      <section className="admin-panel" aria-label="生成与成本趋势">
        <h2>生成与成本趋势</h2>
        <p>近 7 日生成趋势与每日成本构成正在接入。</p>
      </section>
      <section className="admin-panel" aria-label="待办事项">
        <h2>待办事项</h2>
        <p>待批准配对、失败任务、对账不一致与即将过期激活码将在此汇总。</p>
      </section>
    </div>
  );
}
