import { useEffect, useState } from "react";
import { DevicePairingPage } from "./DevicePairingPage";
import type { CustomerCredentialStore } from "./useCustomerSession";

/**
 * T30 / FE-03 — the second-device pairing entry at /customer/pairing.
 *
 * Wires the M4-shipped DevicePairingPage into the customer lane:
 * - a 202 enroll (another device is already bound) parks the user on a
 *   waiting screen with the pairing expiry; the next enroll attempt is
 *   idempotent server-side, so "我已审批,重新配对" is the polling-free
 *   re-check that eventually lands on 201;
 * - a 201 enroll (primary device approved meanwhile) stores the device
 *   credential — the same shape the vault holds after activation, but
 *   without a session token — then hands back to /customer, where the
 *   state machine's boot path logs the new device in automatically.
 */
export function CustomerPairingFlow({
  store,
  onPaired,
}: {
  store: CustomerCredentialStore;
  onPaired: () => void;
}) {
  const [stage, setStage] = useState<"form" | "pending" | "consumed">("form");
  const [pendingExpiry, setPendingExpiry] = useState("");
  const [error, setError] = useState("");
  const [deviceFingerprint, setDeviceFingerprint] = useState("");
  const [draft, setDraft] = useState({ activationCode: "", deviceName: "" });

  useEffect(() => {
    let active = true;
    void store
      .deviceInstanceId()
      .then((value) => {
        if (active) {
          setDeviceFingerprint(value);
        }
      })
      .catch(() => {
        if (active) {
          setError("无法读取本机机器标识，请重启应用后重试。");
        }
      });
    return () => {
      active = false;
    };
  }, [store]);

  async function handleEnrollSuccess(
    result: {
      status: "pending" | "consumed";
      data: unknown;
    },
    input: { activationCode: string; deviceName: string },
  ) {
    setDraft(input);
    setError("");
    if (result.status === "pending") {
      const pending = result.data as { expires_at: string };
      setPendingExpiry(pending.expires_at);
      setStage("pending");
      return;
    }
    const consumed = result.data as { device_token: string };
    try {
      // The consumed branch carries only the device credential; the session
      // token arrives on the first login, so the vault is primed without one.
      await store.saveActivation(consumed.device_token, "");
      setStage("consumed");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存设备凭据失败");
      setStage("form");
    }
  }

  if (stage === "pending") {
    return (
      <main
        className="device-pairing-page"
        aria-labelledby="pairing-waiting-title"
      >
        <header>
          <h1 id="pairing-waiting-title">等待主设备审批</h1>
          <p className="page-subtitle">
            配对请求已提交，请在已登录的主设备个人中心确认；也可以联系管理员审批。
          </p>
        </header>
        <section className="pairing-pending" aria-live="polite">
          {pendingExpiry ? (
            <p className="request-time">
              本请求将在 {new Date(pendingExpiry).toLocaleString()} 过期。
            </p>
          ) : null}
          <p className="pending-status">等待主设备确认</p>
          <div className="form-actions">
            <button
              type="button"
              className="btn-secondary"
              onClick={() => setStage("form")}
            >
              返回修改
            </button>
            <button
              type="button"
              className="btn-primary"
              onClick={() => setStage("form")}
            >
              返回重新提交
            </button>
          </div>
        </section>
      </main>
    );
  }

  if (stage === "consumed") {
    return (
      <main
        className="device-pairing-page"
        aria-labelledby="pairing-success-title"
      >
        <header>
          <h1 id="pairing-success-title">配对成功</h1>
          <p className="page-subtitle">本设备已加入您的客户账号。</p>
        </header>
        <section className="pairing-pending" aria-live="polite">
          <button type="button" className="btn-primary" onClick={onPaired}>
            进入客户工作区
          </button>
        </section>
      </main>
    );
  }

  return (
    <>
      {error ? (
        <p className="settings-error" role="alert">
          {error}
        </p>
      ) : null}
      <DevicePairingPage
        deviceFingerprint={deviceFingerprint}
        devicePlatform={store.devicePlatform()}
        initialActivationCode={draft.activationCode}
        initialDeviceName={draft.deviceName}
        onSuccess={(result, input) => void handleEnrollSuccess(result, input)}
        onError={(cause) => setError(cause.message)}
        onCancel={onPaired}
      />
    </>
  );
}
