import { useEffect, useRef, useState } from "react";
import type { CustomerCreditConfig, CustomerPricing } from "../api";
import {
  AdminControlError,
  getCustomerPricing,
  updateCustomerPricing,
} from "../api.admin";

const fields = [
  ["points_per_yuan", "每 1 元充值获得积分"],
  ["discount_basis_points", "消费折扣（10000 为原价，8500 为 85%）"],
] as const;
export function CustomerPricingManager({
  readOnly = false,
}: {
  readOnly?: boolean;
}) {
  const [data, setData] = useState<CustomerPricing | null>(null);
  const [values, setValues] = useState<
    Record<(typeof fields)[number][0], string>
  >({
    points_per_yuan: "",
    discount_basis_points: "10000",
  });
  const [rounding, setRounding] = useState<"ceil" | "floor">("ceil");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const retry = useRef<{ fingerprint: string; key: string } | null>(null);
  const saving = useRef(false);
  useEffect(() => {
    void refresh;
    let active = true;
    setData(null);
    setError("");
    void getCustomerPricing()
      .then((value) => {
        if (!active) return;
        setData(value);
        if (value.config) {
          setRounding(value.config.consumption_rounding ?? "ceil");
          setValues({
            points_per_yuan: String(value.config.points_per_yuan),
            discount_basis_points: String(
              value.config.discount_basis_points ?? 10000,
            ),
          });
        }
      })
      .catch((cause) => {
        if (active)
          setError(cause instanceof Error ? cause.message : "读取积分价格失败");
      });
    return () => {
      active = false;
    };
  }, [refresh]);
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!data || readOnly || saving.current) return;
    const config: CustomerCreditConfig = {
      points_per_yuan: Number(values.points_per_yuan),
      discount_basis_points: Number(values.discount_basis_points),
      consumption_rounding: rounding,
    };
    if (
      !confirmed ||
      !reason.trim() ||
      fields.some(
        ([key]) =>
          !Number.isInteger(Number(values[key])) ||
          Number(values[key]) < 1 ||
          Number(values[key]) >
            (key === "discount_basis_points" ? 10000 : 1_000_000),
      )
    ) {
      setError("请填写 1–1000000 的整数积分、调整原因，并确认生效范围。");
      return;
    }
    const fingerprint = JSON.stringify([config, data.version, reason.trim()]);
    if (retry.current?.fingerprint !== fingerprint)
      retry.current = { fingerprint, key: crypto.randomUUID() };
    saving.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await updateCustomerPricing(
        config,
        data.version,
        reason.trim(),
        retry.current.key,
      );
      setData(result);
      setConfirmed(false);
      setReason("");
      retry.current = null;
      setNotice(`积分价格 V${result.version} 已生效。`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存积分价格失败");
      if (
        cause instanceof AdminControlError &&
        cause.status &&
        cause.status < 500
      )
        retry.current = null;
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }
  return (
    <section className="admin-panel" aria-label="充值换算与消费折扣">
      <h2>充值换算与消费折扣</h2>
      <p>
        配置每元充值积分和消费折扣；每项功能的成本与售价在“成本与售价”页设置。已受理请求使用原价格。
      </p>
      {error && (
        <div role="alert">
          {error}{" "}
          <button
            type="button"
            disabled={busy}
            onClick={() => setRefresh((v) => v + 1)}
          >
            刷新配置
          </button>
        </div>
      )}
      {notice && <p role="status">{notice}</p>}
      {!data ? (
        !error && <p role="status">正在读取积分配置…</p>
      ) : (
        <form onSubmit={save}>
          <p>
            {data.configured
              ? `当前版本：V${data.version}`
              : "尚未配置充值换算；未配置售价的功能仍可免费使用。"}
          </p>
          <fieldset disabled={readOnly || busy}>
            {fields.map(([key, label]) => (
              <label key={key} style={{ display: "block", marginBottom: 16 }}>
                {label}
                <input
                  type="number"
                  min="1"
                  max={key === "discount_basis_points" ? "10000" : "1000000"}
                  step="1"
                  required
                  value={values[key]}
                  onChange={(event) =>
                    setValues((previous) => ({
                      ...previous,
                      [key]: event.target.value,
                    }))
                  }
                />
              </label>
            ))}
            <label style={{ display: "block", marginBottom: 16 }}>
              消费取整方式（逐任务折后取整，最低 1 积分）
              <select
                value={rounding}
                onChange={(event) =>
                  setRounding(event.target.value === "floor" ? "floor" : "ceil")
                }
              >
                <option value="ceil">向上取整</option>
                <option value="floor">向下取整</option>
              </select>
            </label>
            <label>
              调整原因
              <textarea
                required
                maxLength={500}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              />
            </label>
            <label style={{ display: "block", margin: "16px 0" }}>
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
              />
              确认对后续新任务和新充值订单生效
            </label>
            {!readOnly && (
              <button type="submit" disabled={busy}>
                {busy ? "正在保存…" : "保存积分价格"}
              </button>
            )}
          </fieldset>
        </form>
      )}
    </section>
  );
}
