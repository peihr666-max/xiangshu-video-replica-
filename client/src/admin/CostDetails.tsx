import { useCallback, useEffect, useMemo, useState } from "react";

import {
  type CostFilters,
  type CostOverview,
  listOperationCosts,
  operationCostsCsvUrl,
} from "./api.economics";
import { PageBanner } from "./ui/PageBanner";

const SUBJECT_OPTIONS = [
  ["", "全部操作"],
  ["video_generation_768p", "视频生成 · 768P"],
  ["video_generation_2k", "视频生成 · 2K"],
  ["video_analysis_768p", "视频解析 · 768P"],
  ["video_analysis_2k", "视频解析 · 2K"],
  ["first_frame_image", "首帧图片"],
  ["character_sheet_image", "人物五视图"],
  ["context_ir", "Context IR"],
] as const;

function yuan(fen: number): string {
  return `¥${(fen / 100).toFixed(2)}`;
}

export function CostDetails() {
  const [draft, setDraft] = useState<CostFilters>({ lookbackDays: 30 });
  const [filters, setFilters] = useState<CostFilters>({ lookbackDays: 30 });
  const [data, setData] = useState<CostOverview | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setError("");
      setData(await listOperationCosts(filters));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "读取成本明细失败");
    }
  }, [filters]);

  useEffect(() => {
    void load();
  }, [load]);

  const maxCost = useMemo(
    () => Math.max(1, ...(data?.days.map((day) => day.total_cost_fen) ?? [])),
    [data],
  );

  if (error) return <PageBanner tone="error">{error}</PageBanner>;
  if (!data)
    return <section className="admin-panel">正在加载成本明细…</section>;
  const chartDays = data.days
    .slice()
    .sort((a, b) => a.day.localeCompare(b.day));

  return (
    <div className="economics-page">
      <div className="economics-kpis economics-kpis--four">
        <article>
          <span>{data.unknown_count > 0 ? "已确认成本" : "区间总成本"}</span>
          <strong>{yuan(data.total_cost_fen)}</strong>
          {data.unknown_count > 0 ? <small>另有未知用量未计入</small> : null}
        </article>
        <article>
          <span>输出总秒数</span>
          <strong>{data.total_output_seconds.toLocaleString()} 秒</strong>
        </article>
        <article>
          <span>
            {data.unknown_count > 0 ? "平均已确认视频成本" : "平均视频成本"}
          </span>
          <strong>
            {data.average_video_cost_per_second_fen === null
              ? "用量未知"
              : yuan(data.average_video_cost_per_second_fen)}
          </strong>
        </article>
        <article className={data.unknown_count > 0 ? "is-warning" : ""}>
          <span>待核对用量</span>
          <strong>{data.unknown_count} 项</strong>
        </article>
      </div>

      <section className="admin-panel economics-filter" aria-label="成本筛选">
        <label>
          时间范围
          <select
            value={draft.lookbackDays}
            onChange={(event) =>
              setDraft({ ...draft, lookbackDays: Number(event.target.value) })
            }
          >
            <option value={7}>近 7 日</option>
            <option value={30}>近 30 日</option>
            <option value={90}>近 90 日</option>
          </select>
        </label>
        <label>
          操作类型
          <select
            value={draft.subject ?? ""}
            onChange={(event) =>
              setDraft({ ...draft, subject: event.target.value || undefined })
            }
          >
            {SUBJECT_OPTIONS.map(([value, label]) => (
              <option key={value || "all"} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          分辨率
          <select
            value={draft.resolution ?? ""}
            onChange={(event) =>
              setDraft({
                ...draft,
                resolution: event.target.value || undefined,
              })
            }
          >
            <option value="">全部</option>
            <option value="768P">768P</option>
            <option value="2K">2K</option>
          </select>
        </label>
        <button type="button" onClick={() => setFilters(draft)}>
          查询
        </button>
        <button
          type="button"
          onClick={() => {
            const reset = { lookbackDays: 30 };
            setDraft(reset);
            setFilters(reset);
          }}
        >
          重置
        </button>
        <a
          className="admin-button-link"
          href={operationCostsCsvUrl(filters)}
          download
        >
          导出成本 CSV
        </a>
      </section>

      <section className="admin-panel" aria-label="近 30 日成本构成">
        <div className="panel-title-row cost-chart-heading">
          <h2>近 {filters.lookbackDays} 日成本构成</h2>
          <div className="cost-chart-legend">
            <span className="is-768">768P 生成</span>
            <span className="is-2k">2K 生成</span>
            <span className="is-analysis">视频解析</span>
            <span className="is-image">图片与 Context IR</span>
          </div>
        </div>
        {data.days.length === 0 ? (
          <p>暂无成本记录。</p>
        ) : (
          <div className="cost-bars" role="img" aria-label="成本构成堆叠柱状图">
            {chartDays.map((day) => (
              <div
                className="cost-bars__column"
                key={day.day}
                title={`${day.day} ${yuan(day.total_cost_fen)}`}
              >
                {day.total_cost_fen > 0 ? (
                  <div
                    className="cost-bars__stack"
                    style={{
                      height: `${(day.total_cost_fen / maxCost) * 100}%`,
                    }}
                  >
                    {day.video_768p_fen > 0 ? (
                      <i
                        className="is-768"
                        style={{ flex: day.video_768p_fen }}
                      />
                    ) : null}
                    {day.video_2k_fen > 0 ? (
                      <i className="is-2k" style={{ flex: day.video_2k_fen }} />
                    ) : null}
                    {day.analysis_fen > 0 ? (
                      <i
                        className="is-analysis"
                        style={{ flex: day.analysis_fen }}
                      />
                    ) : null}
                    {day.image_fen + day.context_ir_fen > 0 ? (
                      <i
                        className="is-image"
                        style={{ flex: day.image_fen + day.context_ir_fen }}
                      />
                    ) : null}
                  </div>
                ) : (
                  <div className="cost-bars__empty" aria-hidden="true" />
                )}
                <span>{day.day.slice(5)}</span>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="admin-panel" aria-label="成本日明细">
        <h2>成本日明细</h2>
        {data.records_truncated ? (
          <PageBanner tone="notice">
            操作记录仅加载最近 1,000 条，共 {data.record_total.toLocaleString()}{" "}
            条。
          </PageBanner>
        ) : null}
        <div className="admin-table-wrap">
          <table className="admin-data-table">
            <thead>
              <tr>
                <th>日期</th>
                <th>视频数</th>
                <th>输出秒数</th>
                <th>768P 成本</th>
                <th>2K 成本</th>
                <th>解析成本</th>
                <th>图片成本</th>
                <th>当日合计</th>
                <th>核对</th>
              </tr>
            </thead>
            <tbody>
              {data.days.map((day) => (
                <tr key={day.day}>
                  <td>{day.day}</td>
                  <td>{day.video_count}</td>
                  <td>{day.output_seconds}</td>
                  <td>{yuan(day.video_768p_fen)}</td>
                  <td>{yuan(day.video_2k_fen)}</td>
                  <td>{yuan(day.analysis_fen)}</td>
                  <td>{yuan(day.image_fen + day.context_ir_fen)}</td>
                  <td>{yuan(day.total_cost_fen)}</td>
                  <td>
                    {day.unknown_count ? `${day.unknown_count} 项未知` : "完整"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="admin-hint">
          成本 = 实际输出秒数 ×
          提交时费率快照；解析成本按参考视频秒数计价；供应商未返回真实用量时标记为未知。
        </p>
      </section>
    </div>
  );
}
