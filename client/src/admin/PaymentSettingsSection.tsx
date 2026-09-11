import { type FormEvent, useEffect, useState } from "react";

import {
  type BillingSettings,
  type ControlSettings,
  getControlSettings,
  updateControlBillingSettings,
  updateControlZPaySettings,
} from "../api";
import { ConfirmDialog } from "./ui/ConfirmDialog";
import { PageBanner } from "./ui/PageBanner";
import { formatFen } from "./ui/vocabulary";

type PendingConfirm = "zpay" | "billing" | null;

/**
 * 支付与价格设置（从 AdminApp 内联表单抽出）。密钥只展示掩码，
 * 新密钥留空表示保留旧值；网关与回调地址来自部署环境，不可提交。
 *
 * A-01/A-03（前端分析报告 2026-09-12）：两条写路径都接入全站统一的
 * 确认对话框契约——ZPay 触及生产收款配置与商户密钥，取 reasonAndAck；
 * 内部价格影响所有计费取 reason。确认原因透传到审计，不再由前端硬编码。
 * 计费配置加载完成（billing !== null）之前禁止提交，避免把占位 0 写入生产。
 */
export function PaymentSettingsSection({
  readOnly = false,
}: {
  readOnly?: boolean;
}) {
  const [settings, setSettings] = useState<ControlSettings | null>(null);
  const [zpayPid, setZpayPid] = useState("");
  const [zpayKey, setZpayKey] = useState("");
  const [channels, setChannels] = useState<Array<"alipay" | "wxpay">>([
    "alipay",
    "wxpay",
  ]);
  const [billing, setBilling] = useState<BillingSettings | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [pendingConfirm, setPendingConfirm] = useState<PendingConfirm>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [confirmError, setConfirmError] = useState("");

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      setError("");
      try {
        const nextSettings = await getControlSettings();
        if (cancelled) {
          return;
        }
        setSettings(nextSettings);
        setBilling(nextSettings.billing);
        setZpayPid(nextSettings.zpay.config.pid ?? "");
        setZpayKey("");
        setChannels(parseChannels(nextSettings.zpay.config.enabled_channels));
      } catch (cause) {
        if (!cancelled) {
          setError(
            cause instanceof Error && cause.message
              ? `加载失败：${cause.message}`
              : "加载失败：读取支付与价格失败。",
          );
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function saveZPay(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // 再入守卫：确认框打开期间底层表单键盘仍可达（共享 ConfirmDialog 无焦点
    // 陷阱），防止 pendingConfirm 被翻转导致串台。
    if (pendingConfirm !== null || confirmBusy) {
      return;
    }
    setNotice("");
    setError("");
    setPendingConfirm("zpay");
  }

  async function saveBilling(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pendingConfirm !== null || confirmBusy) {
      return;
    }
    if (!billing) {
      return;
    }
    setNotice("");
    setError("");
    setPendingConfirm("billing");
  }

  async function runConfirmedSave(reason: string) {
    if (pendingConfirm === null || confirmBusy) {
      return;
    }
    setConfirmBusy(true);
    setConfirmError("");
    try {
      if (pendingConfirm === "zpay") {
        await updateControlZPaySettings(
          {
            pid: zpayPid,
            key: zpayKey,
            enabled_channels: channels,
          },
          reason,
        );
        setNotice("ZPay 设置已保存。");
      } else if (pendingConfirm === "billing" && billing) {
        const nextBilling = await updateControlBillingSettings(
          {
            internal_base_unit_price_fen: billing.internal_base_unit_price_fen,
            oral_unit_price_fen: billing.oral_unit_price_fen,
            min_recharge_fen: billing.min_recharge_fen,
            recharge_step_fen: billing.recharge_step_fen,
          },
          reason,
        );
        setBilling(nextBilling);
        setNotice("内部价格已保存。");
      } else {
        // 结构性兜底：正常流程不可达（saveBilling 已挡 !billing），
        // 但宁可显式报错也不静默关框。
        setConfirmError("内部状态异常，请关闭对话框后重试。");
        return;
      }
      setPendingConfirm(null);
    } catch (cause) {
      setConfirmError(
        cause instanceof Error && cause.message ? cause.message : "保存失败。",
      );
    } finally {
      setConfirmBusy(false);
    }
  }

  return (
    <section
      aria-label="支付与价格"
      className="admin-panel admin-payment-settings"
    >
      {error ? <PageBanner tone="error">{error}</PageBanner> : null}
      {notice ? <PageBanner tone="notice">{notice}</PageBanner> : null}

      <form className="admin-form" onSubmit={saveZPay}>
        <h2>ZPay</h2>
        <label>
          ZPay 商户 PID
          <input
            disabled={readOnly}
            value={zpayPid}
            onChange={(event) => setZpayPid(event.target.value)}
          />
        </label>
        <div className="admin-readonly-field">
          已保存密钥
          <span className="readonly-value">
            {settings?.zpay.config.key || "未配置"}
          </span>
        </div>
        <label>
          新商户密钥
          <input
            autoComplete="new-password"
            disabled={readOnly}
            placeholder="留空则保留当前密钥"
            type="password"
            value={zpayKey}
            onChange={(event) => setZpayKey(event.target.value)}
          />
        </label>
        <fieldset className="admin-checks">
          <legend>支付渠道</legend>
          <label>
            <input
              checked={channels.includes("alipay")}
              disabled={readOnly}
              type="checkbox"
              onChange={() => toggleChannel("alipay")}
            />
            支付宝
          </label>
          <label>
            <input
              checked={channels.includes("wxpay")}
              disabled={readOnly}
              type="checkbox"
              onChange={() => toggleChannel("wxpay")}
            />
            微信
          </label>
        </fieldset>
        <p className="admin-hint">支付接口地址由系统自动配置，无需填写。</p>
        <button disabled={readOnly || !settings} type="submit">
          保存 ZPay 设置
        </button>
      </form>

      <form className="admin-form" onSubmit={saveBilling}>
        <h2>内部价格</h2>
        <p className="admin-hint">
          当前内部单价{" "}
          {billing ? formatFen(billing.internal_base_unit_price_fen) : "—"} /
          秒；最低充值与步长只约束 ZPay 在线充值。
        </p>
        <label>
          内部单价（分/秒）
          <input
            disabled={readOnly || !billing}
            inputMode="numeric"
            type="number"
            value={billing?.internal_base_unit_price_fen ?? 0}
            onChange={(event) =>
              updateBilling("internal_base_unit_price_fen", event.target.value)
            }
          />
        </label>
        <label>
          最低充值（分）
          <input
            disabled={readOnly || !billing}
            inputMode="numeric"
            type="number"
            value={billing?.min_recharge_fen ?? 0}
            onChange={(event) =>
              updateBilling("min_recharge_fen", event.target.value)
            }
          />
        </label>
        <label>
          递增步长（分）
          <input
            disabled={readOnly || !billing}
            inputMode="numeric"
            type="number"
            value={billing?.recharge_step_fen ?? 0}
            onChange={(event) =>
              updateBilling("recharge_step_fen", event.target.value)
            }
          />
        </label>
        {/* A-03：配置未加载完成前禁止提交——此时输入框是占位 0，提交会把 0 写进生产价格。 */}
        <button disabled={readOnly || !billing} type="submit">
          保存内部价格
        </button>
      </form>

      <ConfirmDialog
        busy={confirmBusy}
        confirmLabel={
          pendingConfirm === "zpay" ? "确认保存 ZPay 设置" : "确认保存内部价格"
        }
        description={
          pendingConfirm === "zpay"
            ? "该操作更新生产收款配置（商户 PID / 商户密钥 / 支付渠道），保存后立即生效。"
            : "该操作更新全局计费配置，影响后续所有生成扣费与充值门槛。"
        }
        error={confirmError}
        level={pendingConfirm === "zpay" ? "reasonAndAck" : "reason"}
        open={pendingConfirm !== null}
        title={
          pendingConfirm === "zpay" ? "保存 ZPay 支付设置" : "保存内部价格"
        }
        onClose={() => {
          if (!confirmBusy) {
            setPendingConfirm(null);
            setConfirmError("");
          }
        }}
        onConfirm={(reason) => void runConfirmedSave(reason)}
      />
    </section>
  );

  function toggleChannel(channel: "alipay" | "wxpay") {
    setChannels((current) =>
      current.includes(channel)
        ? current.filter((item) => item !== channel)
        : [...current, channel],
    );
  }

  function updateBilling(field: keyof BillingSettings, value: string) {
    setBilling((current) =>
      current ? { ...current, [field]: Number(value) } : current,
    );
  }
}

function parseChannels(value: unknown): Array<"alipay" | "wxpay"> {
  if (typeof value !== "string") {
    return ["alipay"];
  }
  const next = value
    .split(",")
    .filter(
      (item): item is "alipay" | "wxpay" =>
        item === "alipay" || item === "wxpay",
    );
  return next.length ? next : ["alipay"];
}
