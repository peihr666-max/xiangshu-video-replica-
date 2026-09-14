import { useEffect, useRef, useState } from "react";
import type { CustomerCreditConfig, CustomerPricing } from "../api";
import {
  AdminControlError,
  getCustomerPricing,
  updateCustomerPricing,
} from "../api.admin";

export function CustomerPricingManager({
  readOnly = false,
}: {
  readOnly?: boolean;
}) {
  const [data, setData] = useState<CustomerPricing | null>(null);
  const [pointsPerYuan, setPointsPerYuan] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
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
          setPointsPerYuan(String(value.config.points_per_yuan));
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
      points_per_yuan: Number(pointsPerYuan),
      discount_basis_points: data.config?.discount_basis_points ?? 10000,
      consumption_rounding: data.config?.consumption_rounding ?? "ceil",
    };
    if (
      !Number.isSafeInteger(config.points_per_yuan) ||
      config.points_per_yuan < 1 ||
      config.points_per_yuan > 1_000_000
    ) {
      setError("请输入 1–1000000 的整数积分。");
      return;
    }
    const reason = "更新充值积分兑换比例";
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
      retry.current = null;
      setNotice("充值换算已保存，对新充值订单生效。");
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
    <section className="admin-panel admin-recharge-rate" aria-label="充值换算">
      <h2>充值换算</h2>
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
        <form onSubmit={save} className="admin-recharge-rate__form">
          <label>
            每 1 元充值获得积分
            <input
              type="number"
              min="1"
              max="1000000"
              step="1"
              required
              disabled={readOnly || busy}
              value={pointsPerYuan}
              placeholder="请输入积分数"
              onChange={(event) => setPointsPerYuan(event.target.value)}
            />
          </label>
          {!readOnly && (
            <button type="submit" disabled={busy}>
              {busy ? "正在保存…" : "保存充值换算"}
            </button>
          )}
        </form>
      )}
    </section>
  );
}
