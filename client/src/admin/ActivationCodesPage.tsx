import {
  type FormEvent,
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  type ActivationCodeDevice,
  type ActivationCodeListItem,
  AdminActivationError,
  adminActivationErrorMessage,
  createIdempotencyKey,
  listActivationCodes,
  revealActivationCode,
  revokeActivationCode,
  revokeDeviceCredential,
  unbindDevice,
} from "../api.admin";

type PendingAction =
  | { kind: "code"; codeId: string }
  | {
      kind: "device";
      action: "unbind" | "revoke";
      codeId: string;
      deviceId: string;
      deviceName: string;
    };

const STATUS_LABELS: Record<string, string> = {
  GENERATED: "待启用",
  ISSUED: "可使用",
  ACTIVE: "使用中",
  SUSPENDED: "已暂停",
  REVOKED: "已撤销",
  EXPIRED: "已过期",
};

const DEVICE_STATUS_LABELS: Record<string, string> = {
  BOUND: "已绑定",
  UNBOUND: "已解绑",
  REVOKED: "已退出",
};

const PLATFORM_LABELS: Record<string, string> = {
  windows: "Windows",
  macos: "macOS",
  ios: "iOS",
  android: "Android",
  linux: "Linux",
};

export function ActivationCodesPage({
  readOnly = false,
  refreshToken = 0,
  onSessionExpired,
}: {
  readOnly?: boolean;
  refreshToken?: number;
  onSessionExpired?: () => void;
}) {
  const [items, setItems] = useState<ActivationCodeListItem[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [search, setSearch] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [expandedCodeId, setExpandedCodeId] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [actionReason, setActionReason] = useState("");
  const [actionConfirmed, setActionConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [copyingCodeId, setCopyingCodeId] = useState<string | null>(null);
  const [actionKey, setActionKey] = useState<string | null>(null);

  const handleFailure = useCallback(
    (cause: unknown, fallback: string) => {
      if (cause instanceof AdminActivationError && cause.status === 401) {
        setError("会话已失效，请重新登录");
        onSessionExpired?.();
        return;
      }
      setError(adminActivationErrorMessage(cause, fallback));
    },
    [onSessionExpired],
  );

  useEffect(() => {
    void refreshToken;
    let cancelled = false;
    void (async () => {
      setError("");
      try {
        const page = await listActivationCodes({
          status: filterStatus || undefined,
        });
        if (!cancelled) {
          setItems(page.items);
        }
      } catch (cause) {
        if (!cancelled) {
          handleFailure(cause, "读取激活码与设备失败");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [filterStatus, handleFailure, refreshToken]);

  const visibleItems = useMemo(() => {
    const keyword = search.trim().toLocaleLowerCase();
    if (!keyword) {
      return items;
    }
    return items.filter((item) => {
      const deviceText = item.devices
        .map((device) => `${device.display_name ?? ""} ${device.platform}`)
        .join(" ");
      return `${item.masked_code} ${item.bound_username ?? ""} ${deviceText}`
        .toLocaleLowerCase()
        .includes(keyword);
    });
  }, [items, search]);

  async function copyActivationCode(codeId: string) {
    setError("");
    setNotice("");
    setCopyingCodeId(codeId);
    try {
      const result = await revealActivationCode(
        codeId,
        "后台复制激活码",
        createIdempotencyKey(),
      );
      await navigator.clipboard.writeText(result.activation_code);
      setNotice(`激活码已复制（request id: ${result.request_id}）`);
    } catch (cause) {
      handleFailure(cause, "复制激活码失败");
    } finally {
      setCopyingCodeId(null);
    }
  }

  function openAction(action: PendingAction) {
    setPending(action);
    setActionReason("");
    setActionConfirmed(false);
    setActionKey(null);
    setError("");
    setNotice("");
  }

  async function submitAction(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!pending || busy) {
      return;
    }
    if (!actionReason.trim()) {
      setError("请填写操作原因");
      return;
    }
    if (!actionConfirmed) {
      setError("请先勾选确认操作");
      return;
    }

    setBusy(true);
    const reason = actionReason.trim();
    try {
      if (pending.kind === "code") {
        const key = actionKey ?? createIdempotencyKey();
        setActionKey(key);
        const result = await revokeActivationCode(pending.codeId, reason, key);
        setItems((current) =>
          current.map((item) =>
            item.code_id === result.code_id
              ? { ...item, status: result.status }
              : item,
          ),
        );
        setNotice(`激活码已撤销（request id: ${result.request_id}）`);
      } else {
        const result =
          pending.action === "unbind"
            ? await unbindDevice(pending.deviceId, reason)
            : await revokeDeviceCredential(pending.deviceId, reason);
        setItems((current) =>
          updateDeviceStatus(
            current,
            pending.codeId,
            pending.deviceId,
            result.status,
          ),
        );
        setNotice(
          `${pending.action === "unbind" ? "设备已解绑" : "设备已强制退出"}（request id: ${result.request_id}）`,
        );
      }
      setPending(null);
      setActionReason("");
      setActionConfirmed(false);
      setActionKey(null);
    } catch (cause) {
      handleFailure(
        cause,
        pending.kind === "code" ? "撤销激活码失败" : "设备操作失败",
      );
      if (cause instanceof AdminActivationError && cause.status !== undefined) {
        setActionKey(null);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      className="admin-panel activation-device-page"
      aria-label="激活码与设备"
    >
      <header className="admin-page-header">
        <div>
          <h2>激活码与设备</h2>
          <p>
            在同一处查看激活码的使用账号、关联设备，并执行复制、撤销或设备解绑。
          </p>
        </div>
      </header>

      {readOnly ? (
        <p className="wallet-notice" role="status">
          当前为只读模式，写操作不可用。
        </p>
      ) : null}
      {error ? (
        <p className="settings-error" role="alert">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="wallet-notice" role="status">
          {notice}
        </p>
      ) : null}

      <div className="admin-filters activation-device-filters">
        <label>
          搜索
          <input
            placeholder="激活码、账号或设备名称"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <label>
          状态
          <select
            value={filterStatus}
            onChange={(event) => setFilterStatus(event.target.value)}
          >
            <option value="">全部</option>
            <option value="GENERATED">待启用</option>
            <option value="ISSUED">可使用</option>
            <option value="ACTIVE">使用中</option>
            <option value="SUSPENDED">已暂停</option>
            <option value="REVOKED">已撤销</option>
          </select>
        </label>
      </div>

      <div className="table-scroll admin-table-card">
        <table className="internal-table admin-data-table">
          <thead>
            <tr>
              <th>激活码</th>
              <th>状态</th>
              <th>绑定账号</th>
              <th>关联设备</th>
              <th>最近活跃</th>
              {readOnly ? null : <th>操作</th>}
            </tr>
          </thead>
          <tbody>
            {visibleItems.map((item) => {
              const expanded = expandedCodeId === item.code_id;
              return (
                <Fragment key={item.code_id}>
                  <tr>
                    <td>
                      <code>{item.masked_code}</code>
                      {readOnly ? null : (
                        <button
                          type="button"
                          disabled={copyingCodeId !== null}
                          onClick={() => void copyActivationCode(item.code_id)}
                        >
                          {copyingCodeId === item.code_id ? "复制中…" : "复制"}
                        </button>
                      )}
                    </td>
                    <td>{statusLabel(item.status)}</td>
                    <td>{item.bound_username ?? "未绑定"}</td>
                    <td>
                      <button
                        className="activation-device-toggle"
                        type="button"
                        aria-expanded={expanded}
                        onClick={() =>
                          setExpandedCodeId(expanded ? null : item.code_id)
                        }
                      >
                        {item.devices.length} 台设备
                      </button>
                    </td>
                    <td>{formatDate(latestActivity(item.devices))}</td>
                    {readOnly ? null : (
                      <td>
                        {item.status === "REVOKED" ? (
                          "无需操作"
                        ) : (
                          <button
                            className="admin-action--danger"
                            type="button"
                            onClick={() =>
                              openAction({ kind: "code", codeId: item.code_id })
                            }
                          >
                            撤销激活码
                          </button>
                        )}
                      </td>
                    )}
                  </tr>
                  {expanded ? (
                    <tr className="admin-detail-row activation-device-detail-row">
                      <td colSpan={readOnly ? 5 : 6}>
                        <DeviceList
                          codeId={item.code_id}
                          devices={item.devices}
                          readOnly={readOnly}
                          onAction={openAction}
                        />
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      {visibleItems.length === 0 ? (
        <p className="activation-device-empty">没有符合条件的激活码。</p>
      ) : null}
      <p className="admin-hint">仅显示最近 50 条，可按状态或关键词缩小范围。</p>

      {pending ? (
        <form
          className="admin-form activation-device-action"
          onSubmit={submitAction}
        >
          <h2>{actionTitle(pending)}</h2>
          <p className="admin-hint">{actionWarning(pending)}</p>
          <label>
            操作原因
            <input
              placeholder="请填写可审计的操作原因"
              value={actionReason}
              onChange={(event) => setActionReason(event.target.value)}
            />
          </label>
          <label>
            <input
              checked={actionConfirmed}
              type="checkbox"
              onChange={(event) => setActionConfirmed(event.target.checked)}
            />
            我已确认操作
          </label>
          <div className="admin-actions">
            <button disabled={busy} type="submit">
              确认执行
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => setPending(null)}
            >
              取消
            </button>
          </div>
        </form>
      ) : null}
    </section>
  );
}

function DeviceList({
  codeId,
  devices,
  readOnly,
  onAction,
}: {
  codeId: string;
  devices: ActivationCodeDevice[];
  readOnly: boolean;
  onAction: (action: PendingAction) => void;
}) {
  if (devices.length === 0) {
    return <p className="activation-device-empty">该激活码尚未关联设备。</p>;
  }
  return (
    <table className="activation-device-subtable">
      <thead>
        <tr>
          <th>设备</th>
          <th>平台</th>
          <th>状态</th>
          <th>绑定时间</th>
          <th>最近活跃</th>
          {readOnly ? null : <th>设备操作</th>}
        </tr>
      </thead>
      <tbody>
        {devices.map((device) => {
          const active = device.status === "BOUND";
          const deviceName = device.display_name || `设备 #${device.slot_no}`;
          return (
            <tr key={device.device_id}>
              <td>{deviceName}</td>
              <td>{PLATFORM_LABELS[device.platform] ?? device.platform}</td>
              <td>{DEVICE_STATUS_LABELS[device.status] ?? device.status}</td>
              <td>{formatDate(device.bound_at)}</td>
              <td>{formatDate(device.last_active_at)}</td>
              {readOnly ? null : (
                <td>
                  {active ? (
                    <div className="admin-actions admin-actions--table">
                      <button
                        type="button"
                        onClick={() =>
                          onAction({
                            kind: "device",
                            action: "unbind",
                            codeId,
                            deviceId: device.device_id,
                            deviceName,
                          })
                        }
                      >
                        解绑设备
                      </button>
                      <button
                        className="admin-action--danger"
                        type="button"
                        onClick={() =>
                          onAction({
                            kind: "device",
                            action: "revoke",
                            codeId,
                            deviceId: device.device_id,
                            deviceName,
                          })
                        }
                      >
                        强制退出
                      </button>
                    </div>
                  ) : (
                    "无需操作"
                  )}
                </td>
              )}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function updateDeviceStatus(
  items: ActivationCodeListItem[],
  codeId: string,
  deviceId: string,
  status: string,
): ActivationCodeListItem[] {
  return items.map((item) =>
    item.code_id === codeId
      ? {
          ...item,
          devices: item.devices.map((device) =>
            device.device_id === deviceId ? { ...device, status } : device,
          ),
        }
      : item,
  );
}

function latestActivity(devices: ActivationCodeDevice[]): string | null {
  return devices.reduce<string | null>((latest, device) => {
    if (!device.last_active_at) {
      return latest;
    }
    return !latest || device.last_active_at > latest
      ? device.last_active_at
      : latest;
  }, null);
}

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString("zh-CN") : "—";
}

function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

function actionTitle(action: PendingAction): string {
  if (action.kind === "code") {
    return `撤销激活码 ${action.codeId}`;
  }
  return `${action.action === "unbind" ? "解绑" : "强制退出"} ${action.deviceName}`;
}

function actionWarning(action: PendingAction): string {
  if (action.kind === "code") {
    return "撤销后该激活码不可恢复，已绑定设备也不能再用它重新登录。";
  }
  return action.action === "unbind"
    ? "设备将解除当前绑定，但不会撤销激活码。"
    : "当前设备凭据将立即失效，激活码本身保持原状态。";
}
