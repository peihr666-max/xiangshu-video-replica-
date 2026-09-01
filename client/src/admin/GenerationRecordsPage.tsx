import { useCallback, useEffect, useRef, useState } from "react";

import {
  type AdminGenerationRecord,
  getAdminGenerationRecords,
} from "../api.admin";

const PAGE_SIZE = 50;

const recordTypeLabels: Record<AdminGenerationRecord["record_type"], string> = {
  VIDEO: "视频生成",
  FIRST_FRAME_IMAGE: "人物置换首帧",
  CHARACTER_SHEET_IMAGE: "人物五视图",
  CHARACTER_VIEW_IMAGE: "人物单视图",
  SOURCE_FRAME_AI_SCORE: "源画面 AI 评分",
  SOURCE_FRAME_PROCESS: "源画面处理",
};

export function GenerationRecordsPage() {
  const [items, setItems] = useState<AdminGenerationRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const requestIdRef = useRef(0);

  const loadRecords = useCallback(async () => {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    try {
      setLoading(true);
      setError("");
      setItems([]);
      const response = await getAdminGenerationRecords(PAGE_SIZE, offset);
      if (requestId !== requestIdRef.current) {
        return;
      }
      setItems(response.items);
      setTotal(response.total);
    } catch (cause) {
      if (requestId !== requestIdRef.current) {
        return;
      }
      setError(
        cause instanceof Error && cause.message
          ? `加载失败：${cause.message}`
          : "加载失败：未知错误",
      );
    } finally {
      if (requestId === requestIdRef.current) {
        setLoading(false);
      }
    }
  }, [offset]);

  useEffect(() => {
    void loadRecords();
  }, [loadRecords]);

  return (
    <section className="admin-panel" aria-label="生成记录">
      <div className="admin-actions">
        <button type="button" onClick={() => void loadRecords()}>
          {loading ? "刷新中…" : "刷新记录"}
        </button>
        <span>共 {total} 条</span>
      </div>

      <p className="admin-hint">
        记录视频、图片和 AI
        评分调用。上游未返回精确成本时会明确标注，不以零成本代替。
      </p>

      {error ? (
        <p className="settings-error" role="alert">
          {error}
        </p>
      ) : null}

      {!loading && items.length === 0 ? (
        <p className="wallet-notice">暂无生成记录。</p>
      ) : (
        <div className="table-scroll">
          <table className="internal-table" aria-label="用户生成记录列表">
            <thead>
              <tr>
                <th>时间</th>
                <th>用户</th>
                <th>项目</th>
                <th>生成类型</th>
                <th>服务 / 模型</th>
                <th>状态</th>
                <th>扣减额度</th>
                <th>上游成本</th>
                <th>结果 / 错误</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={`${item.record_type}-${item.record_id}`}>
                  <td>{formatTime(item.created_at)}</td>
                  <td>{item.username}</td>
                  <td>{item.project_name ?? "—"}</td>
                  <td>{recordTypeLabels[item.record_type]}</td>
                  <td>{formatProvider(item)}</td>
                  <td>{item.status}</td>
                  <td>{item.charged_credits}</td>
                  <td>{formatProviderCost(item)}</td>
                  <td>{formatResult(item)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {total > PAGE_SIZE ? (
        <nav className="pagination" aria-label="生成记录分页">
          <button
            disabled={offset === 0 || loading}
            type="button"
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          >
            上一页
          </button>
          <span>
            第 {Math.floor(offset / PAGE_SIZE) + 1} /{" "}
            {Math.ceil(total / PAGE_SIZE)} 页
          </span>
          <button
            disabled={offset + PAGE_SIZE >= total || loading}
            type="button"
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            下一页
          </button>
        </nav>
      ) : null}
    </section>
  );
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}

function formatProvider(item: AdminGenerationRecord): string {
  return [item.provider, item.model].filter(Boolean).join(" / ") || "本地处理";
}

function formatProviderCost(item: AdminGenerationRecord): string {
  if (item.provider_cost_status === "NOT_APPLICABLE") {
    return "无付费调用";
  }
  if (
    item.provider_cost_status === "UNAVAILABLE" ||
    item.provider_cost === null
  ) {
    return "上游未回传";
  }
  if (item.provider_cost_status === "ESTIMATED") {
    return `估算 ${item.provider_cost}`;
  }
  return String(item.provider_cost);
}

function formatResult(item: AdminGenerationRecord): string {
  if (item.record_data_status === "CORRUPTED") {
    return "记录数据损坏";
  }
  return item.error_code ?? item.result_reference ?? "—";
}
