import { useCallback, useEffect, useState } from "react";

import {
  type DailyPriceRow,
  listProfitOverview,
  type ProfitDayRow,
  upsertDailyPrice,
} from "../api.admin";

function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2);
}

function todayPlus(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

type PriceForm = {
  priceDate: string;
  price768pYuan: string;
  price2kYuan: string;
  note: string;
  reason: string;
};

/**
 * W8 — 经营分析·利润总览：每日对外售价录入 + 日维度收入/成本/毛利/利润率。
 * 收入口径（2026-09-05 裁决）：标准收入 = 当日对外售价 × 结算秒数；
 * 成本来自任务费率快照（W9）；日界为 Asia/Shanghai；历史无成本数据不回填。
 */
export function ProfitOverview({ readOnly = false }: { readOnly?: boolean }) {
  const [prices, setPrices] = useState<DailyPriceRow[]>([]);
  const [days, setDays] = useState<ProfitDayRow[]>([]);
  const [note, setNote] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState<PriceForm>({
    priceDate: todayPlus(1),
    price768pYuan: "0.12",
    price2kYuan: "0.20",
    note: "",
    reason: "",
  });

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setError("");
      const payload = await listProfitOverview(30);
      setPrices(payload.prices);
      setDays(payload.days);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "读取经营分析失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function savePrice() {
    if (!form.reason.trim()) {
      setError("请填写操作原因");
      return;
    }
    const p768 = Number(form.price768pYuan);
    const p2k = Number(form.price2kYuan);
    if (
      !Number.isFinite(p768) ||
      p768 < 0 ||
      !Number.isFinite(p2k) ||
      p2k < 0
    ) {
      setError("售价需为不小于 0 的数值（元）");
      return;
    }
    try {
      setSaving(true);
      setError("");
      const updated = await upsertDailyPrice(
        {
          price_date: form.priceDate,
          price_768p_fen: Math.round(p768 * 100),
          price_2k_fen: Math.round(p2k * 100),
          note: form.note,
        },
        form.reason.trim(),
      );
      setPrices(updated);
      setNotice(`已保存 ${form.priceDate} 的对外售价`);
      setForm((current) => ({ ...current, reason: "" }));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存每日售价失败");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <section className="admin-panel" aria-label="利润总览">
        <p>正在加载经营数据…</p>
      </section>
    );
  }

  return (
    <div>
      <section className="admin-panel" aria-label="每日对外售价录入">
        <h2>每日对外售价录入</h2>
        <div className="admin-form">
          <label>
            生效日期
            <input
              type="date"
              value={form.priceDate}
              onChange={(event) =>
                setForm({ ...form, priceDate: event.target.value })
              }
            />
          </label>
          <label>
            768P 售价（元/秒）
            <input
              autoComplete="off"
              min={0}
              step="0.01"
              type="number"
              value={form.price768pYuan}
              onChange={(event) =>
                setForm({ ...form, price768pYuan: event.target.value })
              }
            />
          </label>
          <label>
            2K 售价（元/秒）
            <input
              autoComplete="off"
              min={0}
              step="0.01"
              type="number"
              value={form.price2kYuan}
              onChange={(event) =>
                setForm({ ...form, price2kYuan: event.target.value })
              }
            />
          </label>
          <label>
            备注（选填）
            <input
              autoComplete="off"
              type="text"
              value={form.note}
              onChange={(event) =>
                setForm({ ...form, note: event.target.value })
              }
            />
          </label>
          <label>
            操作原因（必填）
            <input
              autoComplete="off"
              type="text"
              value={form.reason}
              onChange={(event) =>
                setForm({ ...form, reason: event.target.value })
              }
            />
          </label>
          {readOnly ? null : (
            <button disabled={saving} type="button" onClick={() => void savePrice()}>
              保存售价
            </button>
          )}
        </div>
        <p className="admin-hint">
          当前生效：
          {prices[0]
            ? `768P ${fenToYuan(prices[0].price_768p_fen)} 元/秒 · 2K ${fenToYuan(prices[0].price_2k_fen)} 元/秒（自 ${prices[0].price_date}）`
            : "尚未录入"}
          ；写操作需填写原因并二次确认，全程审计留痕。
        </p>
      </section>

      {error ? <p role="alert">{error}</p> : null}
      {notice ? <p role="status">{notice}</p> : null}

      <section className="admin-panel" aria-label="日利润表">
        <h2>日利润表</h2>
        {days.length === 0 ? (
          <p>暂无结算数据。</p>
        ) : (
          <table className="admin-data-table">
            <thead>
              <tr>
                <th>日期</th>
                <th>收入（元）</th>
                <th>成本（元）</th>
                <th>毛利（元）</th>
                <th>利润率</th>
                <th>视频数</th>
              </tr>
            </thead>
            <tbody>
              {days.map((row) => (
                <tr key={row.day}>
                  <td>{row.day}</td>
                  <td>{fenToYuan(row.revenue_fen)}</td>
                  <td>
                    {row.cost_fen === null ? (
                      <span title={row.day}>口径前</span>
                    ) : (
                      fenToYuan(row.cost_fen)
                    )}
                  </td>
                  <td>
                    {row.gross_fen === null ? (
                      "—"
                    ) : (
                      <span
                        style={{
                          color: row.gross_fen < 0 ? "#e08080" : undefined,
                        }}
                      >
                        {fenToYuan(row.gross_fen)}
                      </span>
                    )}
                  </td>
                  <td>
                    {row.margin_pct === null ? (
                      "—"
                    ) : (
                      <span
                        style={{
                          color: row.margin_pct < 0 ? "#e08080" : undefined,
                        }}
                      >
                        {row.margin_pct}%
                      </span>
                    )}
                  </td>
                  <td>{row.video_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="admin-hint">
          标准收入 = 当日对外售价 × 结算秒数（Asia/Shanghai 日界）；
          成本自费率快照启用起核算，更早区间不回填。
        </p>
      </section>
    </div>
  );
}
