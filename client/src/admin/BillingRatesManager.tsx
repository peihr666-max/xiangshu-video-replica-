import { useEffect, useRef, useState } from "react";
import { adminRead, adminWrite } from "../api.admin";

export type BillingTariff = {
  enabled: boolean;
  unit_credits: string | null;
  unit_cost_fen: string | null;
  unit_rounding: "ceil" | "exact";
  version: number;
};
export type BillingService = {
  service: string;
  name: string;
  unit: "second" | "image" | "call";
  provider: string;
  module: string;
  customer_charge_allowed: boolean;
  configured: boolean;
  tariff: BillingTariff;
};
export const billingUnit = { second: "秒", image: "张", call: "次" };
type Catalog = { services: BillingService[] };

export function BillingRatesManager({ readOnly = false }: { readOnly?: boolean }) {
  const [catalog, setCatalog] = useState<Catalog>();
  const [selected, setSelected] = useState<BillingService>();
  const [price, setPrice] = useState("");
  const [cost, setCost] = useState("");
  const [enabled, setEnabled] = useState(false);
  const [rounding, setRounding] = useState<"ceil" | "exact">("ceil");
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const saving = useRef(false);
  const retry = useRef<{ fingerprint: string; key: string } | undefined>(undefined);
  useEffect(() => {
    void refresh;
    let active = true;
    setError("");
    void adminRead<Catalog>("/api/control/billing/catalog", "读取费用科目失败")
      .then((result) => { if (active) setCatalog(result); })
      .catch((cause: unknown) => { if (active) setError(cause instanceof Error ? cause.message : "读取失败"); });
    return () => { active = false; };
  }, [refresh]);
  function select(service: BillingService) {
    setSelected(service);
    setPrice(service.tariff.unit_credits ?? "");
    setCost(service.tariff.unit_cost_fen ?? "");
    setEnabled(service.tariff.enabled);
    setRounding(service.tariff.unit_rounding);
    setReason("");
    setNotice("");
  }
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!selected || readOnly || saving.current) return;
    const valid = (value: string) => !value || /^\d+(\.\d{1,6})?$/.test(value);
    if (!valid(price) || !valid(cost) || !reason.trim() || (enabled && !price)) {
      setError("请填写非负单价（最多 6 位小数）和调整原因；启用收费必须填写售价。");
      return;
    }
    const payload = { service: selected.service, expected_version: selected.tariff.version,
      tariff: { enabled, unit_credits: price || null, unit_cost_fen: cost || null, unit_rounding: rounding } };
    const fingerprint = JSON.stringify([payload, reason]);
    if (retry.current?.fingerprint !== fingerprint) retry.current = { fingerprint, key: crypto.randomUUID() };
    saving.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await adminWrite<Catalog>("/api/control/billing/tariff", payload, reason.trim(), "保存费用科目失败", retry.current.key, "PUT");
      setCatalog(result);
      setSelected(undefined);
      setNotice("已保存。新请求使用本次配置，已受理请求保留原价格。");
      retry.current = undefined;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存失败");
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }
  return <section className="admin-panel" aria-label="逐项成本与售价">
    <h2>逐项成本与售价</h2>
    <p>管理员启用并填写售价后，用户按每项实际用量扣分。未配置、停用或零售价均由平台承担；成本留空表示待核对。</p>
    <p>成本以分为单位，支持 6 位小数；售价以积分为单位。云存储和 ZPay 按零费用核算。</p>
    {error && <p role="alert">{error} <button type="button" onClick={() => setRefresh((value) => value + 1)}>重新读取</button></p>}
    {notice && <p role="status">{notice}</p>}
    {!catalog ? <p>正在读取科目…</p> : <div className="admin-table-scroll"><table>
      <thead><tr><th>费用科目</th><th>服务商</th><th>单位</th><th>成本（分）</th><th>售价（积分）</th><th>状态</th><th>操作</th></tr></thead>
      <tbody>{catalog.services.map((service) => <tr key={service.service}>
        <td>{service.name}</td><td>{service.provider}</td><td>{billingUnit[service.unit]}</td>
        <td>{service.tariff.unit_cost_fen ?? (service.service === "cos" || service.service === "zpay" ? "0" : "待配置")}</td>
        <td>{service.tariff.enabled ? service.tariff.unit_credits : "0"}</td>
        <td>{service.tariff.enabled && Number(service.tariff.unit_credits) > 0 ? "用户承担" : "平台承担"}</td>
        <td><button type="button" disabled={readOnly || busy} onClick={() => select(service)}>配置 {service.name}</button></td>
      </tr>)}</tbody>
    </table></div>}
    {selected && <form onSubmit={save} aria-label={`配置 ${selected.name}`}>
      <h3>{selected.name} · 每{billingUnit[selected.unit]}</h3>
      <label>成本（分 / {billingUnit[selected.unit]}，留空待核对）<input value={cost} onChange={(event) => setCost(event.target.value)} inputMode="decimal" disabled={busy || readOnly} /></label>
      <label>售价（积分 / {billingUnit[selected.unit]}）<input value={price} onChange={(event) => setPrice(event.target.value)} inputMode="decimal" disabled={busy || readOnly || !selected.customer_charge_allowed} /></label>
      <label><input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} disabled={busy || readOnly || !selected.customer_charge_allowed} />启用用户扣分</label>
      {selected.unit === "second" && <label>不足一秒的计费方式<select value={rounding} onChange={(event) => setRounding(event.target.value as "ceil" | "exact")} disabled={busy || readOnly}><option value="ceil">每次请求向上取整到秒</option><option value="exact">按实际小数秒</option></select></label>}
      <label>调整原因<input value={reason} onChange={(event) => setReason(event.target.value)} required disabled={busy || readOnly} /></label>
      <button type="submit" disabled={busy || readOnly}>{busy ? "正在保存…" : "确认并保存"}</button>
      <button type="button" disabled={busy} onClick={() => setSelected(undefined)}>取消</button>
    </form>}
  </section>;
}
