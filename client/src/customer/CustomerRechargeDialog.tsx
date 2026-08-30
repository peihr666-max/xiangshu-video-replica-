import { type FormEvent, useCallback, useEffect, useState } from "react";

import {
  type CreatedRechargeOrder,
  CustomerApiError,
  type CustomerPaymentCode,
  customerCreateRechargeOrder,
  customerCreateRechargePaymentCode,
  customerGetRechargeOrder,
  customerGetWallet,
  type WalletSnapshot,
} from "../api";
import type { CustomerCredentialStore } from "./useCustomerSession";

const RECHARGE_PRESETS_YUAN = [100, 200, 500, 1000] as const;
const ORDER_POLL_INTERVAL_MS = 2_000;

export function CustomerRechargeDialog({
  isOpen,
  onClose,
  onPaid,
  onSessionExpired,
  store,
  suggestedAmountYuan,
}: {
  isOpen: boolean;
  onClose: () => void;
  onPaid: () => void;
  onSessionExpired: () => void;
  store: CustomerCredentialStore;
  suggestedAmountYuan?: number;
}) {
  const [wallet, setWallet] = useState<WalletSnapshot | null>(null);
  const [amountYuan, setAmountYuan] = useState("");
  const [order, setOrder] = useState<CreatedRechargeOrder | null>(null);
  const [paymentCode, setPaymentCode] = useState<CustomerPaymentCode | null>(
    null,
  );
  const [paymentState, setPaymentState] = useState<
    "choosing" | "creating" | "waiting" | "paid"
  >("choosing");
  const [isQrLoaded, setIsQrLoaded] = useState(false);
  const [error, setError] = useState("");

  const loadCredential = useCallback(async () => {
    const token = await store.loadSessionToken();
    if (token === null) {
      onSessionExpired();
      return null;
    }
    return { kind: "session" as const, token };
  }, [store, onSessionExpired]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    setAmountYuan(suggestedAmountYuan ? String(suggestedAmountYuan) : "");
    setOrder(null);
    setPaymentCode(null);
    setPaymentState("choosing");
    setIsQrLoaded(false);
    setError("");
    let active = true;
    void loadCredential()
      .then(async (credential) => {
        if (credential === null) {
          return;
        }
        const nextWallet = await customerGetWallet(credential);
        if (active) {
          setWallet(nextWallet);
        }
      })
      .catch((cause) => {
        if (active) {
          setError(visibleError(cause, "充值信息暂不可用，请稍后重试。"));
        }
      });
    return () => {
      active = false;
    };
  }, [isOpen, suggestedAmountYuan, loadCredential]);

  useEffect(() => {
    if (!isOpen || paymentState !== "waiting" || order === null) {
      return;
    }
    let active = true;
    let timer: number | undefined;

    async function pollOrder() {
      const credential = await loadCredential();
      if (!active || credential === null) {
        return;
      }
      try {
        const latest = await customerGetRechargeOrder(
          credential,
          order?.order_no ?? "",
        );
        if (!active) {
          return;
        }
        if (latest.status === "PAID") {
          setPaymentState("paid");
          onPaid();
          return;
        }
        if (latest.status === "FAILED" || latest.status === "CLOSED") {
          setError("该充值订单已结束，请重新创建订单。");
          setPaymentState("choosing");
          return;
        }
        timer = window.setTimeout(pollOrder, ORDER_POLL_INTERVAL_MS);
      } catch (cause) {
        if (active) {
          setError(
            visibleError(cause, "暂时无法确认支付结果，系统会继续查询。"),
          );
          timer = window.setTimeout(pollOrder, ORDER_POLL_INTERVAL_MS);
        }
      }
    }

    void pollOrder();
    return () => {
      active = false;
      if (timer !== undefined) {
        window.clearTimeout(timer);
      }
    };
  }, [isOpen, paymentState, order, loadCredential, onPaid]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [isOpen, onClose]);

  async function createPayment(nextAmountYuan: number) {
    if (!wallet || paymentState === "creating") {
      return;
    }
    const amountFen = nextAmountYuan * 100;
    if (
      !Number.isInteger(nextAmountYuan) ||
      amountFen < wallet.min_recharge_fen ||
      amountFen % wallet.recharge_step_fen !== 0
    ) {
      setError(
        `充值金额须为${formatFen(wallet.min_recharge_fen)}起，并按${formatFen(wallet.recharge_step_fen)}递增。`,
      );
      return;
    }
    const credential = await loadCredential();
    if (credential === null) {
      return;
    }
    setPaymentState("creating");
    setError("");
    setIsQrLoaded(false);
    try {
      const created = await customerCreateRechargeOrder(credential, amountFen, {
        idempotencyKey: crypto.randomUUID(),
      });
      setOrder(created);
      const code = await customerCreateRechargePaymentCode(
        credential,
        created.order_no,
      );
      setPaymentCode(code);
      setPaymentState("waiting");
    } catch (cause) {
      setError(visibleError(cause, "支付二维码暂时无法生成，请稍后重试。"));
      setPaymentState("choosing");
    }
  }

  async function retryPaymentCode() {
    if (order === null) {
      return;
    }
    const credential = await loadCredential();
    if (credential === null) {
      return;
    }
    setPaymentState("creating");
    setError("");
    try {
      const code = await customerCreateRechargePaymentCode(
        credential,
        order.order_no,
      );
      setPaymentCode(code);
      setIsQrLoaded(false);
      setPaymentState("waiting");
    } catch (cause) {
      setError(visibleError(cause, "支付二维码暂时无法生成，请稍后重试。"));
      setPaymentState("choosing");
    }
  }

  function submitCustom(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void createPayment(Number(amountYuan));
  }

  if (!isOpen) {
    return null;
  }

  return (
    <div className="recharge-dialog">
      <section
        aria-labelledby="recharge-dialog-title"
        aria-modal="true"
        className="recharge-dialog__panel"
        role="dialog"
      >
        <header className="recharge-dialog__header">
          <div>
            <p className="eyebrow">余额充值</p>
            <h2 id="recharge-dialog-title">扫码充值</h2>
          </div>
          <button
            aria-label="关闭充值窗口"
            className="secondary-button"
            onClick={onClose}
            type="button"
          >
            关闭
          </button>
        </header>

        {paymentState === "paid" ? (
          <div className="recharge-dialog__success" role="status">
            <strong>充值成功</strong>
            <p>条数已经到账，可以继续创建视频。</p>
            <button onClick={onClose} type="button">
              完成
            </button>
          </div>
        ) : paymentCode && order ? (
          <div className="recharge-dialog__payment">
            <div className="recharge-dialog__qr">
              {!isQrLoaded ? <span>二维码加载中…</span> : null}
              <img
                alt="充值支付二维码"
                onError={() => {
                  setIsQrLoaded(false);
                  setError("二维码图片加载失败，请点击重新获取。");
                }}
                onLoad={() => setIsQrLoaded(true)}
                src={paymentCode.qr_image_url}
              />
            </div>
            <div className="recharge-dialog__summary">
              <span>支付金额</span>
              <strong>{formatFen(order.amount_fen)}</strong>
              <p>到账 {order.credits} 条 · 支付完成后自动到账</p>
              <span className="recharge-dialog__waiting" role="status">
                正在等待支付结果
              </span>
              <button
                className="secondary-button"
                onClick={() =>
                  window.open(
                    paymentCode.payment_url,
                    "_blank",
                    "noopener,noreferrer",
                  )
                }
                type="button"
              >
                无法扫码？打开支付页面
              </button>
            </div>
          </div>
        ) : (
          <div className="recharge-dialog__chooser">
            <p>
              {wallet
                ? `当前可用 ${wallet.available_credits} 条，单条价格 ${formatFen(wallet.internal_unit_price_fen)}。`
                : "正在读取充值信息…"}
            </p>
            <div className="recharge-dialog__presets">
              {RECHARGE_PRESETS_YUAN.map((amount) => (
                <button
                  disabled={!wallet || paymentState === "creating"}
                  key={amount}
                  onClick={() => void createPayment(amount)}
                  type="button"
                >
                  <strong>{amount} 元</strong>
                  <span>
                    {wallet
                      ? `${Math.floor((amount * 100) / wallet.internal_unit_price_fen)} 条`
                      : "—"}
                  </span>
                </button>
              ))}
            </div>
            <form onSubmit={submitCustom}>
              <label>
                自定义金额（元）
                <input
                  inputMode="numeric"
                  onChange={(event) => setAmountYuan(event.target.value)}
                  type="number"
                  value={amountYuan}
                />
              </label>
              <button
                disabled={!wallet || paymentState === "creating"}
                type="submit"
              >
                {paymentState === "creating"
                  ? "正在生成二维码…"
                  : "生成支付二维码"}
              </button>
            </form>
            {order && !paymentCode ? (
              <button
                className="secondary-button"
                onClick={() => void retryPaymentCode()}
                type="button"
              >
                重新获取上一订单二维码
              </button>
            ) : null}
          </div>
        )}

        {error ? (
          <p className="settings-error" role="alert">
            {error}
          </p>
        ) : null}
        <footer>请以本窗口显示的金额为准；如已扣款，请勿重复支付。</footer>
      </section>
    </div>
  );
}

function formatFen(amountFen: number): string {
  const yuan = amountFen / 100;
  return `${Number.isInteger(yuan) ? yuan : yuan.toFixed(2)}元`;
}

function visibleError(cause: unknown, fallback: string): string {
  if (cause instanceof CustomerApiError && cause.status === 401) {
    return "登录已失效，请重新进入工作台。";
  }
  return cause instanceof Error && cause.message.trim()
    ? cause.message
    : fallback;
}
