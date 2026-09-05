import { useCallback, useEffect, useState } from "react";

import {
  AdminActivationError,
  type DailyPriceRow,
  listProfitOverview,
  type ProfitDayRow,
  upsertDailyPrice,
} from "../api.admin";
import { ConfirmDialog } from "./ui/ConfirmDialog";

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

type EconomicsProfitDay = ProfitDayRow & { cost_unknown_count?: number };

function shanghaiToday(): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((item) => item.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

type ChartPoint = { x: number; y: number };

function chartPoint(
  value: number,
  index: number,
  count: number,
  maximum: number,
): ChartPoint {
  return {
    x: count === 1 ? 50 : (index / (count - 1)) * 100,
    y: 92 - (value / maximum) * 80,
  };
}

function smoothPath(points: ChartPoint[]): string {
  return points
    .map((point, index) => {
      if (index === 0) return `M ${point.x} ${point.y}`;
      const previous = points[index - 1];
      const middleX = (previous.x + point.x) / 2;
      return `C ${middleX} ${previous.y}, ${middleX} ${point.y}, ${point.x} ${point.y}`;
    })
    .join(" ");
}

/**
 * W8 — 经营分析·利润总览：每日对外售价录入 + 日维度收入/成本/毛利/利润率。
 * 收入口径（2026-09-05 裁决）：标准收入 = 当日对外售价 × 结算秒数；
 * 成本来自任务费率快照（W9）；日界为 Asia/Shanghai；历史无成本数据不回填。
 */
export function ProfitOverview({ readOnly = false }: { readOnly?: boolean }) {
  const [prices, setPrices] = useState<DailyPriceRow[]>([]);
  const [days, setDays] = useState<EconomicsProfitDay[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);
  const [priceConfirmOpen, setPriceConfirmOpen] = useState(false);
  const [priceSaveError, setPriceSaveError] = useState("");
  const [priceKey, setPriceKey] = useState<string | null>(null);
  const [selectedDay, setSelectedDay] = useState<EconomicsProfitDay | null>(
    null,
  );
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
      setDays(payload.days as EconomicsProfitDay[]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "读取经营分析失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function requestPriceSave() {
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
    setError("");
    setPriceSaveError("");
    setPriceConfirmOpen(true);
  }

  async function savePrice() {
    const p768 = Number(form.price768pYuan);
    const p2k = Number(form.price2kYuan);
    const key = priceKey ?? crypto.randomUUID();
    setPriceKey(key);
    try {
      setSaving(true);
      const updated = await upsertDailyPrice(
        {
          price_date: form.priceDate,
          price_768p_fen: Math.round(p768 * 100),
          price_2k_fen: Math.round(p2k * 100),
          note: form.note,
        },
        form.reason.trim(),
        key,
      );
      setPrices(updated);
      setNotice(`已保存 ${form.priceDate} 的对外售价`);
      setForm((current) => ({ ...current, reason: "" }));
      setPriceKey(null);
      setPriceConfirmOpen(false);
    } catch (cause) {
      setPriceSaveError(
        cause instanceof Error ? cause.message : "保存每日售价失败",
      );
      if (cause instanceof AdminActivationError && cause.status !== undefined) {
        setPriceKey(null);
      }
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

  const currentPrice = prices.reduce<DailyPriceRow | null>((current, price) => {
    if (price.price_date > shanghaiToday()) return current;
    if (!current || price.price_date > current.price_date) return price;
    return current;
  }, null);
  const chronologicalDays = days.slice().reverse();
  const chartMaximum = Math.max(
    1,
    ...chronologicalDays.map((day) => day.revenue_fen),
    ...chronologicalDays.map((day) => day.cost_fen ?? 0),
  );
  const revenuePath = smoothPath(
    chronologicalDays.map((day, index) =>
      chartPoint(
        day.revenue_fen,
        index,
        chronologicalDays.length,
        chartMaximum,
      ),
    ),
  );
  const costPath = smoothPath(
    chronologicalDays.flatMap((day, index) =>
      day.cost_fen === null
        ? []
        : [
            chartPoint(
              day.cost_fen,
              index,
              chronologicalDays.length,
              chartMaximum,
            ),
          ],
    ),
  );

  return (
    <div className="economics-page profit-page">
      <section
        className="admin-panel profit-price-card"
        aria-label="每日对外售价录入"
      >
        <h2>每日对外售价录入</h2>
        <div className="admin-form profit-price-form">
          <label>
            生效日期
            <input
              disabled={readOnly}
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
              disabled={readOnly}
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
              disabled={readOnly}
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
              disabled={readOnly}
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
              disabled={readOnly}
              autoComplete="off"
              type="text"
              value={form.reason}
              onChange={(event) =>
                setForm({ ...form, reason: event.target.value })
              }
            />
          </label>
          {readOnly ? null : (
            <button disabled={saving} type="button" onClick={requestPriceSave}>
              保存售价
            </button>
          )}
        </div>
        <p className="admin-hint">
          当前生效：
          {currentPrice
            ? `768P ${fenToYuan(currentPrice.price_768p_fen)} 元/秒 · 2K ${fenToYuan(currentPrice.price_2k_fen)} 元/秒（自 ${currentPrice.price_date}）`
            : "尚未录入"}
          ；写操作需填写原因并二次确认，全程审计留痕。
        </p>
      </section>

      {error ? <p role="alert">{error}</p> : null}
      {notice ? <p role="status">{notice}</p> : null}

      <div className="profit-main-grid">
        <section className="admin-panel" aria-label="日利润表">
          <div className="panel-title-row">
            <h2>日利润表</h2>
            <a
              className="admin-button-link"
              href="/api/control/profit/overview.csv?lookback_days=30"
              download
            >
              导出 CSV
            </a>
          </div>
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
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {days.map((row) => (
                  <tr key={row.day}>
                    <td>{row.day}</td>
                    <td>{fenToYuan(row.revenue_fen)}</td>
                    <td>
                      {(row.cost_unknown_count ?? 0) > 0 ? (
                        <span
                          title={`${row.cost_unknown_count ?? 0} 项真实用量未知`}
                        >
                          待核对
                        </span>
                      ) : row.cost_fen === null ? (
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
                    <td>
                      <button
                        type="button"
                        className="table-link-button"
                        onClick={() => setSelectedDay(row)}
                      >
                        查看明细
                      </button>
                    </td>
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
        <div className="profit-side-stack">
          <aside className="admin-panel profit-basis" aria-label="收入口径">
            <h2>收入口径</h2>
            <label>
              <input type="radio" checked readOnly />
              标准收入
            </label>
            <small>每日对外售价 × 结算秒数</small>
            <label className="is-disabled">
              <input type="radio" disabled />
              实收收入
            </label>
            <small>客户实际单价口径留待后续增强</small>
          </aside>
          <aside
            className="admin-panel profit-trend-card"
            aria-label="收入与成本趋势"
          >
            <div className="panel-title-row">
              <h2>近 30 日收入 vs 成本</h2>
              <div className="profit-chart-legend">
                <span className="is-revenue">收入</span>
                <span className="is-cost">已确认成本</span>
              </div>
            </div>
            <div
              className="profit-mini-chart"
              role="img"
              aria-label="收入与已确认成本趋势"
            >
              <svg viewBox="0 0 100 100" preserveAspectRatio="none">
                <title>近 30 日收入与已确认成本曲线</title>
                <path d={revenuePath} className="is-revenue" fill="none" />
                <path d={costPath} className="is-cost" fill="none" />
                {chronologicalDays.map((row, index) => (
                  <circle
                    key={row.day}
                    cx={
                      chronologicalDays.length === 1
                        ? 50
                        : (index / (chronologicalDays.length - 1)) * 100
                    }
                    cy={92 - (row.revenue_fen / chartMaximum) * 80}
                    r="1.5"
                    className="is-revenue"
                  >
                    <title>{`${row.day} 收入 ${fenToYuan(row.revenue_fen)} 成本 ${row.cost_fen == null ? "未知" : fenToYuan(row.cost_fen)}`}</title>
                  </circle>
                ))}
              </svg>
            </div>
          </aside>
        </div>
      </div>
      {selectedDay ? (
        <div className="admin-dialog-overlay" role="presentation">
          <section
            aria-label={`${selectedDay.day} 利润明细`}
            aria-modal="true"
            className="admin-dialog"
            role="dialog"
          >
            <h2>{selectedDay.day} 利润明细</h2>
            <p>结算秒数 {selectedDay.settled_seconds} 秒</p>
            <p>视频数 {selectedDay.video_count}</p>
            <p>收入 {fenToYuan(selectedDay.revenue_fen)} 元</p>
            <p>
              成本{" "}
              {selectedDay.cost_fen === null
                ? "未知"
                : `${fenToYuan(selectedDay.cost_fen)} 元`}
            </p>
            <p>
              毛利{" "}
              {selectedDay.gross_fen === null
                ? "未知"
                : `${fenToYuan(selectedDay.gross_fen)} 元`}
            </p>
            {(selectedDay.cost_unknown_count ?? 0) > 0 ? (
              <p>
                {selectedDay.cost_unknown_count}{" "}
                项真实用量未知，成本与毛利待核对。
              </p>
            ) : selectedDay.cost_fen === null ? (
              <p>该日期没有可用的成本快照，不能推算实际成本。</p>
            ) : null}
            <button type="button" onClick={() => setSelectedDay(null)}>
              关闭
            </button>
          </section>
        </div>
      ) : null}
      <ConfirmDialog
        busy={saving}
        confirmLabel="确认保存"
        description={`将保存 ${form.priceDate} 的对外售价：768P ${form.price768pYuan} 元/秒，2K ${form.price2kYuan} 元/秒。原因：${form.reason.trim()}`}
        error={priceSaveError}
        level="standard"
        open={priceConfirmOpen && !readOnly}
        title="确认保存每日售价"
        onClose={() => {
          setPriceConfirmOpen(false);
          setPriceSaveError("");
          setPriceKey(null);
        }}
        onConfirm={() => void savePrice()}
      />
    </div>
  );
}
