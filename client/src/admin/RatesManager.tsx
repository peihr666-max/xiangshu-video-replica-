import { useCallback, useEffect, useState } from "react";

import {
  listOperationRates,
  type OperationRate,
  type OperationRateHistory,
  updateOperationRates,
} from "../api.admin";

const RATE_LABELS: Record<string, string> = {
  video_generation_768p: "视频生成 · 768P",
  video_generation_2k: "视频生成 · 2K",
  video_analysis_768p: "视频解析 · 参考视频 768P",
  video_analysis_2k: "视频解析 · 参考视频 2K",
  first_frame_image: "首帧图片",
  character_sheet_image: "人物五视图",
  context_ir: "Context IR",
  external_price_768p: "对外售价 · 768P",
  external_price_2k: "对外售价 · 2K",
};

const UNIT_LABELS: Record<string, string> = {
  second: "元/秒",
  image: "元/张",
  call: "元/次",
};

const MAX_PRICE_YUAN = 1_000_000;

function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2);
}

function rateLabel(subject: string): string {
  return RATE_LABELS[subject] ?? subject;
}

function unitLabel(unit: string): string {
  return UNIT_LABELS[unit] ?? unit;
}

/** 超过 50% 的调价（含 0→正）要求操作员显式确认。 */
function needsAck(oldFen: number, newFen: number): boolean {
  if (oldFen === 0) return newFen > 0;
  return newFen > oldFen * 1.5 || newFen < oldFen * 0.5;
}

type EditingState = {
  subject: string;
  valueYuan: string;
  reason: string;
  ack: boolean;
};

/**
 * W10 — 费率管理：上游成本费率与对外售价（按秒）。
 * 每次调整走共享管理写契约（原因必填 + 幂等键），服务端同事务写
 * audit（旧值→新值），>50% 变动要求额外确认；任务按提交时费率快照
 * 核算，改价不影响在途任务。
 */
export function RatesManager({ readOnly = false }: { readOnly?: boolean }) {
  const [rates, setRates] = useState<OperationRate[]>([]);
  const [history, setHistory] = useState<OperationRateHistory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [editing, setEditing] = useState<EditingState | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setError("");
      const payload = await listOperationRates();
      setRates(payload.rates);
      setHistory(payload.history);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "读取费率失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function startEdit(rate: OperationRate) {
    setError("");
    setNotice("");
    setEditing({
      subject: rate.subject,
      valueYuan: fenToYuan(rate.unit_price_fen),
      reason: "",
      ack: false,
    });
  }

  function cancelEdit() {
    setEditing(null);
  }

  async function save() {
    if (!editing) return;
    const newYuan = Number(editing.valueYuan);
    if (!Number.isFinite(newYuan) || newYuan < 0 || newYuan > MAX_PRICE_YUAN) {
      setError(`单价需为 0-${MAX_PRICE_YUAN} 之间的数值（元）`);
      return;
    }
    if (!editing.reason.trim()) {
      setError("请填写操作原因");
      return;
    }
    const rate = rates.find((r) => r.subject === editing.subject);
    if (!rate) return;
    const newFen = Math.round(newYuan * 100);
    if (needsAck(rate.unit_price_fen, newFen) && !editing.ack) {
      setError("本次变动超过 50%，请先勾选确认知晓影响");
      return;
    }
    try {
      setSaving(true);
      setError("");
      const payload = await updateOperationRates(
        [{ subject: editing.subject, unit_price_fen: newFen }],
        editing.reason.trim(),
      );
      setRates(payload.rates);
      setHistory(payload.history);
      setEditing(null);
      setNotice(
        `已更新 ${rateLabel(editing.subject)}：${fenToYuan(rate.unit_price_fen)} → ${newYuan.toFixed(2)} 元`,
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "费率调整失败");
    } finally {
      setSaving(false);
    }
  }

  function renderRateTable(
    kind: "upstream_cost" | "external_price",
    title: string,
    ariaLabel: string,
  ) {
    const rows = rates.filter((rate) => rate.kind === kind);
    return (
      <section className="admin-panel" aria-label={ariaLabel}>
        <h2>{title}</h2>
        <table className="admin-data-table">
          <thead>
            <tr>
              <th>科目</th>
              <th>计价单位</th>
              <th>当前单价</th>
              <th>更新时间</th>
              <th>更新人</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((rate) =>
              editing?.subject === rate.subject ? (
                <tr key={rate.subject}>
                  <td>{rateLabel(rate.subject)}</td>
                  <td>{unitLabel(rate.unit)}</td>
                  <td colSpan={3}>
                    <label>
                      新单价（元）
                      <input
                        aria-label={`新单价（元）：${rateLabel(rate.subject)}`}
                        autoFocus
                        type="number"
                        min={0}
                        step="0.01"
                        value={editing.valueYuan}
                        onChange={(event) =>
                          setEditing({
                            ...editing,
                            valueYuan: event.target.value,
                          })
                        }
                      />
                    </label>
                    <label>
                      操作原因（必填）
                      <input
                        aria-label={`操作原因：${rateLabel(rate.subject)}`}
                        type="text"
                        value={editing.reason}
                        onChange={(event) =>
                          setEditing({ ...editing, reason: event.target.value })
                        }
                      />
                    </label>
                    {needsAck(
                      rate.unit_price_fen,
                      Math.round(Number(editing.valueYuan) * 100),
                    ) ? (
                      <label>
                        <input
                          aria-label={`确认知晓大幅调价：${rateLabel(rate.subject)}`}
                          checked={editing.ack}
                          type="checkbox"
                          onChange={(event) =>
                            setEditing({
                              ...editing,
                              ack: event.target.checked,
                            })
                          }
                        />
                        我已知晓本次变动超过 50%，将按新价审计留痕
                      </label>
                    ) : null}
                  </td>
                  <td>
                    <button
                      disabled={saving}
                      type="button"
                      onClick={() => void save()}
                    >
                      保存
                    </button>
                    <button
                      disabled={saving}
                      type="button"
                      onClick={cancelEdit}
                    >
                      取消
                    </button>
                  </td>
                </tr>
              ) : (
                <tr key={rate.subject}>
                  <td>{rateLabel(rate.subject)}</td>
                  <td>{unitLabel(rate.unit)}</td>
                  <td>{fenToYuan(rate.unit_price_fen)}</td>
                  <td>{rate.updated_at.slice(0, 19).replace("T", " ")}</td>
                  <td>{rate.updated_by_username ?? "—"}</td>
                  <td>
                    {readOnly ? (
                      "—"
                    ) : (
                      <button type="button" onClick={() => startEdit(rate)}>
                        调整
                      </button>
                    )}
                  </td>
                </tr>
              ),
            )}
          </tbody>
        </table>
      </section>
    );
  }

  if (loading) {
    return (
      <section className="admin-panel" aria-label="费率管理">
        <p>正在加载费率…</p>
      </section>
    );
  }

  return (
    <div className="rates-manager">
      <div className="admin-panel">
        <p className="admin-hint">
          费率变更需填写原因并二次确认；单价变动超过 50%
          触发额外告警；每个任务按提交时的费率快照核算，改价不影响在途任务。
        </p>
      </div>
      {error ? <p role="alert">{error}</p> : null}
      {notice ? <p role="status">{notice}</p> : null}
      {renderRateTable("upstream_cost", "上游成本费率", "上游成本费率")}
      {renderRateTable("external_price", "对外售价（按秒计费）", "对外售价")}
      <section className="admin-panel" aria-label="历史变更">
        <h2>历史变更（最近 {history.length} 条）</h2>
        {history.length === 0 ? (
          <p>暂无调整记录。</p>
        ) : (
          <table className="admin-data-table">
            <thead>
              <tr>
                <th>科目</th>
                <th>旧值 → 新值</th>
                <th>原因</th>
                <th>操作人</th>
              </tr>
            </thead>
            <tbody>
              {history.map((entry, index) => (
                <tr key={`${entry.subject}-${entry.created_at}-${index}`}>
                  <td>{rateLabel(entry.subject)}</td>
                  <td>
                    {entry.old_unit_price_fen === null
                      ? "—"
                      : fenToYuan(entry.old_unit_price_fen)}{" "}
                    → {fenToYuan(entry.new_unit_price_fen)}
                  </td>
                  <td>{entry.reason}</td>
                  <td>{entry.actor_username ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
