import { useCallback, useEffect, useState } from "react";

import {
  AdminActivationError,
  adminActivationErrorMessage,
  fetchH3ExtendedModes,
  updateH3ExtendedModes,
} from "../api.admin";
import { ConfirmDialog } from "./ui/ConfirmDialog";
import { PageBanner } from "./ui/PageBanner";
import { StatusBadge } from "./ui/StatusBadge";

/**
 * H3 扩展模式开关（CW-063 / 缺口 4b）：把此前只能进数据库改的
 * runtime_settings.h3_extended_modes_enabled 翻译成管理台上的一个开关。
 * 该列是尾帧 / 文生 T2V / 参考生 R2V 三种 H3 形态真实付费提交的总闸门，
 * 默认关闭（迁移 075），仅在供应商付费探针核对（缺口 4a）通过后才可开启。
 * 写契约与其它管理写一致：原因必填 + Idempotency-Key 幂等重放，审计行记录
 * 操作者原因，使一次真实扣费的开启始终可归因。
 */
export function H3ExtendedModesSection({
  readOnly = false,
}: {
  readOnly?: boolean;
}) {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setEnabled(await fetchH3ExtendedModes());
    } catch (cause) {
      setError(adminActivationErrorMessage(cause, "读取扩展模式开关失败"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function toggle(reason: string) {
    if (enabled === null || saving) {
      return;
    }
    setSaving(true);
    setError("");
    setNotice("");
    try {
      setEnabled(await updateH3ExtendedModes(!enabled, reason));
      setNotice(!enabled ? "H3 扩展模式已开启。" : "H3 扩展模式已关闭。");
      setConfirmOpen(false);
    } catch (cause) {
      if (cause instanceof AdminActivationError && cause.status === 401) {
        setError("会话已失效，请重新登录");
      } else {
        setError(adminActivationErrorMessage(cause, "切换扩展模式失败"));
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <section
      aria-label="H3 扩展模式开关"
      className="admin-panel h3-extended-modes-section"
    >
      <h2>H3 扩展模式</h2>
      <p className="admin-hint">
        开启后，尾帧 / 文生 T2V / 参考生 R2V
        三种扩展形态将向供应商真实付费提交；
        请仅在供应商付费探针核对通过后再开启。切换立即生效并写入审计。当前状态：
        {loading ? (
          "读取中…"
        ) : (
          <StatusBadge tone={enabled ? "good" : "neutral"}>
            {enabled === null ? "未知" : enabled ? "已开启" : "已关闭"}
          </StatusBadge>
        )}
      </p>

      {error ? <PageBanner tone="error">{error}</PageBanner> : null}
      {notice ? <PageBanner tone="notice">{notice}</PageBanner> : null}

      {readOnly ? (
        <p className="admin-hint">审计员只读，不能切换扩展模式。</p>
      ) : (
        <button
          disabled={loading || enabled === null || saving}
          type="button"
          onClick={() => setConfirmOpen(true)}
        >
          {enabled ? "关闭扩展模式" : "开启扩展模式"}
        </button>
      )}

      <ConfirmDialog
        busy={saving}
        confirmLabel={enabled ? "确认关闭" : "确认开启"}
        description={
          enabled
            ? "关闭后，扩展形态回到禁止真实付费提交。切换立即生效并写入审计。"
            : "开启后，扩展形态将向供应商真实付费提交，请确认付费探针已核对通过。切换立即生效并写入审计。"
        }
        level="reason"
        open={confirmOpen}
        title={enabled ? "关闭扩展模式" : "开启扩展模式"}
        onClose={() => setConfirmOpen(false)}
        onConfirm={(reason) => void toggle(reason)}
      />
    </section>
  );
}
