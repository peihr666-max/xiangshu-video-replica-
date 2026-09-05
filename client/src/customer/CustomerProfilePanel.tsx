import { useEffect, useState } from "react";

import type {
  CustomerActivationCodeReset,
  CustomerDeviceListResponse,
  CustomerProfile,
} from "../api";
import { CustomerWalletPanel } from "./CustomerWalletPanel";
import { DeviceManagementPage } from "./DeviceManagementPage";
import { PairingApprovalCard } from "./PairingApprovalCard";
import type { CustomerCredentialStore } from "./useCustomerSession";

type ProfileTab = "overview" | "devices" | "billing";

export function CustomerProfilePanel({
  devices,
  deviceError,
  onApprovePairing,
  onDismissPairing,
  onProfileUpdated,
  onRecharge,
  onRefreshDevices,
  onResetActivationCode,
  onSessionExpired,
  onUnbind,
  onUpdateProfile,
  profile,
  store,
  walletRefreshKey,
}: {
  devices: CustomerDeviceListResponse | null;
  deviceError: string;
  onApprovePairing: (pairingId: string) => void;
  onDismissPairing: (pairingId: string) => void;
  onProfileUpdated: (profile: CustomerProfile) => void;
  onRecharge: (amountYuan?: number) => void;
  onRefreshDevices: () => Promise<void>;
  onResetActivationCode: () => Promise<CustomerActivationCodeReset>;
  onSessionExpired: () => void;
  onUnbind: (deviceId: string) => void;
  onUpdateProfile: (displayName: string) => Promise<CustomerProfile>;
  profile: CustomerProfile | null;
  store: CustomerCredentialStore;
  walletRefreshKey: number;
}) {
  const [tab, setTab] = useState<ProfileTab>("overview");
  const [displayName, setDisplayName] = useState(profile?.display_name ?? "");
  const [profileError, setProfileError] = useState("");
  const [profileNotice, setProfileNotice] = useState("");
  const [isSavingProfile, setIsSavingProfile] = useState(false);
  const [isResettingCode, setIsResettingCode] = useState(false);
  const [replacementCode, setReplacementCode] = useState("");
  const pendingPairings = devices?.pending_pairings ?? [];

  useEffect(() => {
    setDisplayName(profile?.display_name ?? "");
  }, [profile?.display_name]);

  async function saveProfile(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextName = displayName.trim();
    if (!nextName) {
      setProfileError("请输入显示名称。");
      return;
    }
    setIsSavingProfile(true);
    setProfileError("");
    setProfileNotice("");
    try {
      const nextProfile = await onUpdateProfile(nextName);
      onProfileUpdated(nextProfile);
      setProfileNotice("个人资料已保存。");
    } catch (cause) {
      setProfileError(errorMessage(cause, "保存个人资料失败，请稍后重试。"));
    } finally {
      setIsSavingProfile(false);
    }
  }

  async function resetActivationCode() {
    if (
      isResettingCode ||
      !window.confirm(
        "确认重置激活码？旧激活码会立即失效，新激活码只显示一次；当前已绑定设备不会下线。",
      )
    ) {
      return;
    }
    setIsResettingCode(true);
    setProfileError("");
    setProfileNotice("");
    try {
      const result = await onResetActivationCode();
      setReplacementCode(result.activation_code);
      if (profile) {
        onProfileUpdated({
          ...profile,
          activation_code_masked: result.masked_code,
        });
      }
      setProfileNotice("激活码已重置，请立即复制并妥善保存。");
    } catch (cause) {
      setProfileError(errorMessage(cause, "重置激活码失败，请稍后重试。"));
    } finally {
      setIsResettingCode(false);
    }
  }

  async function copyText(value: string, successMessage: string) {
    try {
      await navigator.clipboard.writeText(value);
      setProfileError("");
      setProfileNotice(successMessage);
    } catch {
      setProfileError("复制失败，请手动选择并复制。");
    }
  }

  return (
    <section className="customer-profile" aria-label="个人中心">
      <header className="customer-profile__hero">
        <div>
          <p className="eyebrow">个人中心</p>
          <h2>{profile?.display_name ?? "客户账号"}</h2>
          <p>
            {profile?.username ?? "正在读取账号信息"}
            {profile?.joined_at
              ? ` · ${formatDate(profile.joined_at)} 加入`
              : ""}
          </p>
        </div>
        <button onClick={() => onRecharge()} type="button">
          充值秒数
        </button>
      </header>

      <nav aria-label="个人中心功能" className="customer-profile__tabs">
        {(
          [
            ["overview", "账号概览"],
            ["devices", "设备管理"],
            ["billing", "余额与记录"],
          ] as const
        ).map(([value, label]) => (
          <button
            aria-current={tab === value ? "page" : undefined}
            className={tab === value ? "is-active" : ""}
            key={value}
            onClick={() => {
              setTab(value);
              if (value === "devices") {
                void onRefreshDevices();
              }
            }}
            type="button"
          >
            {label}
            {value === "devices" && pendingPairings.length > 0 ? (
              <span>{pendingPairings.length}</span>
            ) : null}
          </button>
        ))}
      </nav>

      {tab === "overview" ? (
        <div className="customer-profile__overview">
          <section
            className="customer-profile__account"
            aria-labelledby="profile-title"
          >
            <div>
              <p className="eyebrow">个人资料</p>
              <h3 id="profile-title">账号信息</h3>
              <p>
                账号编号 <strong>{profile?.username ?? "正在读取…"}</strong>
              </p>
            </div>
            <form onSubmit={saveProfile}>
              <label>
                显示名称
                <input
                  maxLength={50}
                  onChange={(event) => setDisplayName(event.target.value)}
                  value={displayName}
                />
              </label>
              <button disabled={isSavingProfile} type="submit">
                {isSavingProfile ? "正在保存" : "保存个人资料"}
              </button>
            </form>
          </section>

          {profileError ? (
            <p className="settings-error" role="alert">
              {profileError}
            </p>
          ) : null}
          {profileNotice ? (
            <p className="wallet-notice" role="status">
              {profileNotice}
            </p>
          ) : null}

          <div className="customer-profile__metrics">
            <article>
              <span>账号状态</span>
              <strong>{activationStatus(profile?.activation_status)}</strong>
              <small>已激活，可正常使用</small>
            </article>
            <article>
              <span>已绑定设备</span>
              <strong>
                {profile?.device_slots_used ?? 0} /{" "}
                {profile?.device_slots_total ?? 2}
              </strong>
              <small>同时仅一台设备在线</small>
            </article>
            <article>
              <span>待确认设备</span>
              <strong>{pendingPairings.length}</strong>
              <small>请只批准本人设备</small>
            </article>
          </div>

          <article className="customer-profile__license">
            <div>
              <span>当前激活凭证</span>
              <strong>
                {profile?.activation_code_masked ?? "正在读取激活信息…"}
              </strong>
              <small>
                {profile?.activated_at
                  ? `${formatDate(profile.activated_at)} 激活`
                  : "完整激活码不会在个人中心再次显示"}
              </small>
            </div>
            <div className="customer-profile__license-actions">
              <button
                className="secondary-button"
                disabled={!profile?.activation_code_masked}
                onClick={() =>
                  void copyText(
                    profile?.activation_code_masked ?? "",
                    "授权编号已复制。",
                  )
                }
                type="button"
              >
                复制授权编号
              </button>
              <button
                className="secondary-button"
                disabled={
                  isResettingCode || profile?.activation_status !== "ACTIVE"
                }
                onClick={() => void resetActivationCode()}
                type="button"
              >
                {isResettingCode ? "正在重置" : "重置激活码"}
              </button>
              <button
                onClick={() => {
                  setTab("devices");
                  void onRefreshDevices();
                }}
                type="button"
              >
                管理关联设备
              </button>
            </div>
          </article>

          {replacementCode ? (
            <section className="customer-profile__replacement" role="status">
              <div>
                <strong>新激活码仅显示这一次</strong>
                <code>{replacementCode}</code>
                <small>请立即复制保存；关闭本页后将只显示脱敏编号。</small>
              </div>
              <button
                onClick={() =>
                  void copyText(replacementCode, "新激活码已复制。")
                }
                type="button"
              >
                复制新激活码
              </button>
            </section>
          ) : null}

          {pendingPairings.length > 0 ? (
            <section className="customer-profile__pending">
              <h3>需要你确认</h3>
              {pendingPairings.map((pending) => (
                <PairingApprovalCard
                  key={pending.pairing_request_id}
                  onApprove={onApprovePairing}
                  onDelete={onDismissPairing}
                  onReject={() => setTab("devices")}
                  pairing={{
                    id: pending.pairing_request_id,
                    deviceFingerprint: `${pending.display_name} · ${pending.platform}`,
                    createdAt: pending.created_at,
                  }}
                />
              ))}
            </section>
          ) : null}
        </div>
      ) : null}

      {tab === "devices" ? (
        <div className="customer-profile__devices">
          {deviceError ? (
            <p className="settings-error" role="alert">
              {deviceError}
            </p>
          ) : null}
          {pendingPairings.map((pending) => (
            <PairingApprovalCard
              key={pending.pairing_request_id}
              onApprove={onApprovePairing}
              onDelete={onDismissPairing}
              onReject={() => undefined}
              pairing={{
                id: pending.pairing_request_id,
                deviceFingerprint: `${pending.display_name} · ${pending.platform}`,
                createdAt: pending.created_at,
              }}
            />
          ))}
          {devices ? (
            <DeviceManagementPage
              devices={devices}
              isOnline
              leaseExpiresAt={null}
              onError={() => undefined}
              onRecharge={() => onRecharge()}
              onUnbind={onUnbind}
            />
          ) : (
            <p className="status-note">正在读取设备信息…</p>
          )}
        </div>
      ) : null}

      {tab === "billing" ? (
        <CustomerWalletPanel
          key={walletRefreshKey}
          onRechargeRequested={(amount) => onRecharge(amount)}
          onSessionExpired={onSessionExpired}
          store={store}
        />
      ) : null}
    </section>
  );
}

function activationStatus(status: string | null | undefined): string {
  return (
    {
      ACTIVE: "正常",
      SUSPENDED: "已暂停",
      REVOKED: "已撤销",
      EXPIRED: "已过期",
    }[status ?? ""] ?? "读取中"
  );
}

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString("zh-CN");
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message.trim()
    ? error.message
    : fallback;
}
