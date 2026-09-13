import { useEffect, useState } from "react";
import { adminRead, downloadBillingCsv } from "../api.admin";
import { type BillingService, billingUnit } from "./BillingRatesManager";

type Metric = { period: string | null; operation_count: number; charged_credits: number; known_revenue_fen: number | string | null; known_cost_fen: number | string | null; profit_fen: number | string | null; unknown_cost_count: number; unknown_revenue_count: number; pending_count: number; refunded_credits: number; seconds: string | null; images: string | null; calls: string | null; platform_cost_fen: string | null };
type Report = { totals: Metric; periods: Metric[]; basis: string };
type Operation = { id: string; username: string; service: string; unit: keyof typeof billingUnit; budget_units: string; actual_units: string | null; charged_credits: number; reserved_credits: number; revenue_fen: string | null; nominal_revenue_fen: string | null; cost_fen: string | null; profit_fen: string | null; state: string; completed_at: string | null; created_at: string; pricing_snapshot_json: string; attempts?: Attempt[] };
type Attempt = { id: string; service: string; provider: string; unit: keyof typeof billingUnit; unit_cost_fen: string | null; usage: string | null; cost_fen: string | null; state: string };
const money = (value: string | number | null | undefined) => value == null ? "待核对" : `¥${(Number(value) / 100).toFixed(8).replace(/0+$/, "").replace(/\.$/, ".00")}`;
const modules: Record<string, string> = { video: "视频生成", replica: "视频分析", replacement: "首帧制作", people: "人物与声音", copy: "文案创作", oral: "数字人口播", viral: "爆款数据", workbench: "链接导入", internal: "内部检查", platform: "平台后台", infrastructure: "基础服务" };
const states: Record<string, string> = { PENDING: "处理中 / 待核对", SUCCEEDED: "已完成", FAILED: "失败已退回", CANCELLED: "取消已退回", ACTUAL: "已确认", UNKNOWN: "待核对" };
function today() { return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date()); }
const initialFilters = () => ({ start: `${today().slice(0, 7)}-01`, end: today(), grain: "day", user_id: "", service: "", module: "", provider: "" });
function params(filters: ReturnType<typeof initialFilters>) { return new URLSearchParams(Object.entries(filters).filter(([, value]) => value)).toString(); }

export function BillingEconomics() {
  const [filters, setFilters] = useState(initialFilters);
  const [query, setQuery] = useState(() => params(initialFilters()));
  const [revision, setRevision] = useState(0);
  const [offset, setOffset] = useState(0);
  const [catalog, setCatalog] = useState<BillingService[]>([]);
  const [report, setReport] = useState<Report>();
  const [operations, setOperations] = useState<{ items: Operation[]; total: number }>();
  const [detail, setDetail] = useState<Operation>();
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const name = (key: string) => catalog.find((item) => item.service === key)?.name ?? key;
  useEffect(() => {
    let active = true;
    void adminRead<{ services: BillingService[] }>("/api/control/billing/catalog", "读取科目失败").then((result) => { if (active) setCatalog(result.services); }).catch((cause: unknown) => { if (active) setError(cause instanceof Error ? cause.message : "读取科目失败"); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    void revision;
    let active = true;
    setBusy(true);
    setError("");
    setDetail(undefined);
    void Promise.all([
      adminRead<Report>(`/api/control/billing/statistics?${query}`, "读取经营统计失败"),
      adminRead<{ items: Operation[]; total: number }>(`/api/control/billing/operations?${query}&limit=100&offset=${offset}`, "读取请求明细失败"),
    ]).then(([summary, items]) => { if (active) { setReport(summary); setOperations(items); } })
      .catch((cause: unknown) => { if (active) { setReport(undefined); setOperations(undefined); setError(cause instanceof Error ? cause.message : "读取失败"); } })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [query, offset, revision]);
  async function inspect(id: string) {
    try { setDetail(await adminRead<Operation>(`/api/control/billing/operations/${encodeURIComponent(id)}`, "读取请求详情失败")); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "读取失败"); }
  }
  async function exportRows() {
    try { setNotice(await downloadBillingCsv(query)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "导出失败"); }
  }
  const snapshot = detail ? JSON.parse(detail.pricing_snapshot_json) as { unit_credits: string; unit_rounding: string; discount_basis_points: number; enabled: boolean; version: number } : undefined;
  return <section className="admin-panel" aria-label="逐项经营核算">
    <h2>逐项经营核算</h2>
    <p>每次请求分别核算积分、消费收入、供应商成本与利润。赠送积分不计收入；来源或成本未确认时显示待核对。充值到账单独查看，不重复计入消费收入。</p>
    <form onSubmit={(event) => { event.preventDefault(); setQuery(params(filters)); setOffset(0); setRevision((value) => value + 1); }}>
      <label>开始日期<input type="date" value={filters.start} onChange={(event) => setFilters({ ...filters, start: event.target.value })} required /></label>
      <label>结束日期<input type="date" value={filters.end} min={filters.start} onChange={(event) => setFilters({ ...filters, end: event.target.value })} required /></label>
      <label>统计周期<select value={filters.grain} onChange={(event) => setFilters({ ...filters, grain: event.target.value })}><option value="day">天</option><option value="week">周（周一开始）</option><option value="month">月 / 多月</option><option value="year">年</option></select></label>
      <label>用户 ID<input value={filters.user_id} onChange={(event) => setFilters({ ...filters, user_id: event.target.value })} placeholder="全部用户及平台后台" /></label>
      <label>科目<select value={filters.service} onChange={(event) => setFilters({ ...filters, service: event.target.value })}><option value="">全部科目</option>{catalog.map((item) => <option key={item.service} value={item.service}>{item.name}</option>)}</select></label>
      <label>业务模块<select value={filters.module} onChange={(event) => setFilters({ ...filters, module: event.target.value })}><option value="">全部模块</option>{Object.entries(modules).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <label>服务商<select value={filters.provider} onChange={(event) => setFilters({ ...filters, provider: event.target.value })}><option value="">全部服务商</option>{[...new Set(catalog.map((item) => item.provider))].map((key) => <option key={key}>{key}</option>)}</select></label>
      <button type="submit" disabled={busy}>查询</button><button type="button" disabled={busy || !operations} onClick={() => void exportRows()}>导出当前查询 CSV</button>
    </form>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {busy && <p role="status">正在计算…</p>}
    {report && <><p>{report.basis} 时区：北京时间。</p>
      <p>请求 {report.totals.operation_count} 次 · 净扣 {report.totals.charged_credits ?? 0} 积分 · 退回 {report.totals.refunded_credits ?? 0} 积分 · 已确认收入 {money(report.totals.known_revenue_fen ?? 0)} · 已确认成本 {money(report.totals.known_cost_fen ?? 0)} · 利润 {money(report.totals.profit_fen)}</p>
      <p>累计用量：{report.totals.seconds ?? 0} 秒 / {report.totals.images ?? 0} 张 / {report.totals.calls ?? 0} 次。平台承担的已确认成本：{money(report.totals.platform_cost_fen ?? 0)}。</p>
      <p>待核对成本 {report.totals.unknown_cost_count} 项 · 待核对收入 {report.totals.unknown_revenue_count} 项 · 未结算 {report.totals.pending_count} 项</p>
      <div className="admin-table-scroll"><table><thead><tr><th>周期起始</th><th>请求数</th><th>净扣积分</th><th>已确认收入</th><th>已确认成本</th><th>利润</th></tr></thead><tbody>{report.periods.map((row) => <tr key={row.period}><td>{row.period}</td><td>{row.operation_count}</td><td>{row.charged_credits}</td><td>{money(row.known_revenue_fen ?? 0)}</td><td>{money(row.known_cost_fen ?? 0)}</td><td>{money(row.profit_fen)}</td></tr>)}</tbody></table></div>
    </>}
    {operations && <><h3>每次请求（共 {operations.total} 条）</h3><div className="admin-table-scroll"><table><thead><tr><th>用户</th><th>科目</th><th>状态</th><th>用量</th><th>积分</th><th>收入</th><th>成本</th><th>利润</th><th>详情</th></tr></thead><tbody>{operations.items.map((row) => <tr key={row.id}><td>{row.username}</td><td>{name(row.service)}</td><td>{states[row.state]}</td><td>{row.actual_units ?? "处理中"} {billingUnit[row.unit]}</td><td>{row.charged_credits}</td><td>{money(row.revenue_fen)}</td><td>{money(row.cost_fen)}</td><td>{money(row.profit_fen)}</td><td><button type="button" onClick={() => void inspect(row.id)}>查看请求</button></td></tr>)}</tbody></table></div>
      {operations.total === 0 && <p>这个时间范围没有请求记录。</p>}
      <button type="button" disabled={busy || offset === 0} onClick={() => setOffset((value) => Math.max(0, value - 100))}>上一页</button><span>第 {Math.floor(offset / 100) + 1} 页</span><button type="button" disabled={busy || offset + 100 >= operations.total} onClick={() => setOffset((value) => value + 100)}>下一页</button>
    </>}
    {detail && snapshot && <aside aria-label="请求核算详情"><button type="button" onClick={() => setDetail(undefined)}>关闭详情</button><h3>{name(detail.service)} · {detail.username}</h3><p>请求编号：{detail.id} · {states[detail.state]}</p><p>受理时售价：{snapshot.enabled ? snapshot.unit_credits : "0"} 积分 / {billingUnit[detail.unit]}；折扣 {snapshot.discount_basis_points / 100}%；价格版本 {snapshot.version}。</p><p>预算 {detail.budget_units} {billingUnit[detail.unit]}，实际 {detail.actual_units ?? "待确认"} {billingUnit[detail.unit]}；预留 {detail.reserved_credits}，净扣 {detail.charged_credits} 积分。</p><p>消费收入 {money(detail.revenue_fen)} · 积分标价折合 {money(detail.nominal_revenue_fen)} · 供应商成本 {money(detail.cost_fen)} · 利润 {money(detail.profit_fen)}</p><h4>供应商调用（重试分别记成本）</h4><table><thead><tr><th>科目</th><th>服务商</th><th>用量</th><th>成本单价</th><th>成本</th><th>状态</th></tr></thead><tbody>{detail.attempts?.map((item) => <tr key={item.id}><td>{name(item.service)}</td><td>{item.provider}</td><td>{item.usage ?? "待确认"} {billingUnit[item.unit]}</td><td>{money(item.unit_cost_fen)} / {billingUnit[item.unit]}</td><td>{money(item.cost_fen)}</td><td>{states[item.state]}</td></tr>)}</tbody></table></aside>}
  </section>;
}
