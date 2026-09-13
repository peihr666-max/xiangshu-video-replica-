import {
  type FormEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { downloadCustomersCsv } from "../api";
import {
  type AdjustmentListItem,
  type AdminRechargeOrder,
  type AdminWalletTransaction,
  type CustomerListItem,
  type CustomerSessionListItem,
  type CustomerUnitPrice,
  createCustomerAdjustment,
  type DeviceListItem,
  fetchCustomerUnitPrice,
  listAdminAdjustments,
  listAdminRechargeOrders,
  listAdminWalletTransactions,
  listCustomerSessions,
  listCustomers,
  listDevices,
  updateCustomerUnitPrice,
} from "../api.admin";
import { AccountCreditPanel } from "./AccountCreditPanel";
import { AdjustmentsPage } from "./AdjustmentsPage";
import { LegacyCreditPolicyManager } from "./LegacyCreditPolicyManager";
import { ConfirmDialog } from "./ui/ConfirmDialog";
import { PageBanner } from "./ui/PageBanner";
import { Pagination } from "./ui/Pagination";
import {
  CustomerStatusBadge,
  DeviceStatusBadge,
  OrderStatusBadge,
} from "./ui/StatusBadge";
import {
  formatDateTime,
  formatFen,
  formatYuanFromFen,
  platformLabel,
  transactionTypeLabel,
} from "./ui/vocabulary";
import "./admin-customer-detail.css";

/**
 * T33 — customer list with pagination and filtering.
 *
 * The page shows all registered customers with their activation codes,
 * usernames, and current status. Admin users can navigate through
 * pages and filter by username; auditors see the same read-only view.
 *
 * Each row links to the adjustment history for that customer (ADM-02).
 */
interface CustomersPageProps {
  embedded?: boolean;
  onOpenDevices?: (userId: string) => void;
  /** C1：从客户详情一键进入该客户的会话视图（免手输 UUID）。 */
  onOpenSessions?: (userId: string) => void;
  readOnly?: boolean;
}

export function CustomersPage({
  embedded = false,
  onOpenDevices,
  onOpenSessions,
  readOnly = false,
}: CustomersPageProps = {}) {
  const [customers, setCustomers] = useState<CustomerListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [offset, setOffset] = useState(0);
  const [pageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [usernameDraft, setUsernameDraft] = useState("");
  const [usernameFilter, setUsernameFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [createdFrom, setCreatedFrom] = useState("");
  const [createdTo, setCreatedTo] = useState("");
  const [balanceMin, setBalanceMin] = useState("");
  const [balanceMax, setBalanceMax] = useState("");
  const [detailUserId, setDetailUserId] = useState<string | null>(null);
  const [expandedUserId, setExpandedUserId] = useState<string | null>(null);

  const loadCustomers = useCallback(async () => {
    try {
      setLoading(true);
      setError("");
      const response = await listCustomers({
        limit: pageSize,
        offset,
        username_filter: usernameFilter || undefined,
        status: statusFilter === "all" ? undefined : statusFilter,
        createdFrom: createdFrom || undefined,
        createdTo: createdTo || undefined,
        balanceMin: balanceMin ? Number(balanceMin) : undefined,
        balanceMax: balanceMax ? Number(balanceMax) : undefined,
      });
      setCustomers(response.items);
      setTotal(response.total);
    } catch (err) {
      setError(
        err instanceof Error && err.message
          ? `加载失败：${err.message}`
          : "加载失败：未知错误",
      );
    } finally {
      setLoading(false);
    }
  }, [
    balanceMax,
    balanceMin,
    createdFrom,
    createdTo,
    offset,
    pageSize,
    statusFilter,
    usernameFilter,
  ]);

  useEffect(() => {
    loadCustomers();
  }, [loadCustomers]);

  const handleFilterSubmit = (e: FormEvent) => {
    e.preventDefault();
    setOffset(0);
    setExpandedUserId(null);
    setUsernameFilter(usernameDraft.trim());
  };

  if (detailUserId !== null) {
    return (
      <div className="customers-page">
        <header>
          <h1>调账历史</h1>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => setDetailUserId(null)}
          >
            ← 返回客户列表
          </button>
        </header>
        <AdjustmentsPage userId={detailUserId} />
      </div>
    );
  }

  const failedGenerations = customers.reduce(
    (sum, customer) => sum + (customer.generation_failed ?? 0),
    0,
  );
  const attentionGenerations = customers.reduce(
    (sum, customer) => sum + (customer.generation_attention ?? 0),
    0,
  );
  const inProgressGenerations = customers.reduce(
    (sum, customer) => sum + (customer.generation_in_progress ?? 0),
    0,
  );
  const visibleCustomers = customers;

  const exportList = () => {
    void downloadCustomersCsv({
      status: statusFilter === "all" ? undefined : statusFilter,
      username: usernameFilter || undefined,
      createdFrom: createdFrom || undefined,
      createdTo: createdTo || undefined,
      balanceMin: balanceMin ? Number(balanceMin) : undefined,
      balanceMax: balanceMax ? Number(balanceMax) : undefined,
    });
  };

  const focusedCustomer =
    expandedUserId === null
      ? null
      : (customers.find((customer) => customer.user_id === expandedUserId) ??
        null);
  if (focusedCustomer) {
    return (
      <CustomerDetailView
        customer={focusedCustomer}
        onChanged={() => void loadCustomers()}
        readOnly={readOnly}
        onBack={() => setExpandedUserId(null)}
        onOpenAdjustments={() => setDetailUserId(focusedCustomer.user_id)}
        onOpenDevices={onOpenDevices}
        onOpenSessions={onOpenSessions}
      />
    );
  }

  return (
    <div className="customers-page">
      {!embedded ? (
        <header className="admin-page-header">
          <h1>客户管理</h1>
          <p>
            聚焦客户状态、生成表现和消耗情况，支持在同一页快速查看运营详情。
          </p>
        </header>
      ) : null}

      <form className="admin-toolbar" onSubmit={handleFilterSubmit}>
        <label className="admin-toolbar__field">
          <span>用户名筛选</span>
          <input
            placeholder="按用户名筛选"
            type="text"
            value={usernameDraft}
            onChange={(e) => setUsernameDraft(e.target.value)}
          />
        </label>
        <label className="admin-toolbar__field">
          <span>注册起始</span>
          <input
            aria-label="注册起始"
            type="date"
            value={createdFrom}
            onChange={(event) => setCreatedFrom(event.target.value)}
          />
        </label>
        <label className="admin-toolbar__field">
          <span>注册截止</span>
          <input
            aria-label="注册截止"
            type="date"
            value={createdTo}
            onChange={(event) => setCreatedTo(event.target.value)}
          />
        </label>
        <label className="admin-toolbar__field">
          <span>最低余额（积分）</span>
          <input
            aria-label="最低余额"
            min="0"
            type="number"
            value={balanceMin}
            onChange={(event) => setBalanceMin(event.target.value)}
          />
        </label>
        <label className="admin-toolbar__field">
          <span>最高余额（积分）</span>
          <input
            aria-label="最高余额"
            min="0"
            type="number"
            value={balanceMax}
            onChange={(event) => setBalanceMax(event.target.value)}
          />
        </label>
        <label className="admin-toolbar__field admin-toolbar__field--select">
          <span>客户状态</span>
          <select
            aria-label="客户状态"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
          >
            <option value="all">全部状态</option>
            <option value="active">活跃</option>
            <option value="suspended">已暂停</option>
            <option value="revoked">已撤销</option>
          </select>
        </label>
        <button className="admin-toolbar__secondary" type="submit">
          筛选
        </button>
        <button type="button" onClick={exportList}>
          导出列表 CSV
        </button>
      </form>

      <section aria-label="需要处理" className="admin-attention-strip">
        <strong>需要处理</strong>
        <span>
          失败生成 <b>{failedGenerations}</b>
        </span>
        <span>
          待关注生成 <b>{attentionGenerations}</b>
        </span>
        <span>
          处理中 <b>{inProgressGenerations}</b>
        </span>
        <small>数据范围：当前筛选页</small>
      </section>
      <p className="admin-hint">
        计费单位：积分；单价与充值兑换比例在系统设置中配置。
      </p>

      {loading && <div className="loading">加载中...</div>}

      {error ? <PageBanner tone="error">{error}</PageBanner> : null}

      {!loading && !error && customers.length === 0 && (
        <div className="empty-state">暂无客户数据</div>
      )}

      {!loading &&
      !error &&
      customers.length > 0 &&
      visibleCustomers.length === 0 ? (
        <div className="empty-state">当前状态下暂无客户</div>
      ) : null}

      {!loading && !error && visibleCustomers.length > 0 && (
        <>
          <div className="table-scroll admin-table-card">
            <table
              aria-label="客户列表"
              className="customers-table admin-data-table"
            >
              <thead>
                <tr>
                  <th>用户名</th>
                  <th>姓名</th>
                  <th>客户 ID</th>
                  <th>激活码</th>
                  <th>注册时间</th>
                  <th>状态</th>
                  <th>设备占用</th>
                  <th>可用额度</th>
                  <th>冻结</th>
                  <th>累计消耗</th>
                  <th>生成情况</th>
                  <th>待关注</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {visibleCustomers.map((customer) => (
                  <tr key={customer.user_id}>
                    <td data-label="用户名">{customer.username}</td>
                    <td data-label="姓名">{customer.display_name || "—"}</td>
                    <td data-label="客户 ID">
                      <code>{customer.user_id}</code>
                    </td>
                    <td data-label="激活码">
                      <code>{customer.activation_code}</code>
                    </td>
                    <td data-label="注册时间">
                      {formatDateTime(customer.created_at)}
                    </td>
                    <td data-label="状态">
                      <CustomerStatusBadge status={customer.status} />
                    </td>
                    <td data-label="设备占用">
                      {customer.device_slots_used ?? 0} 台
                    </td>
                    <td data-label="可用额度">
                      <strong>{customer.available_credits ?? 0} 积分</strong>
                    </td>
                    <td data-label="冻结">
                      {customer.reserved_credits ?? 0} 积分
                    </td>
                    <td
                      aria-label={`${customer.username} 已结算消耗`}
                      data-label="累计消耗"
                    >
                      {customer.credits_spent ?? 0} 积分
                    </td>
                    <td data-label="生成情况">
                      <span>
                        {customer.generation_succeeded ?? 0} /{" "}
                        {customer.generation_total ?? 0}
                      </span>{" "}
                      · {customer.generation_failed ?? 0} 失败 ·{" "}
                      {customer.generation_in_progress ?? 0} 进行中
                    </td>
                    <td data-label="待关注">
                      {customer.generation_attention ?? 0}
                    </td>
                    <td data-label="操作">
                      <button
                        aria-controls={`customer-detail-${customer.user_id}`}
                        aria-expanded="false"
                        type="button"
                        onClick={() => setExpandedUserId(customer.user_id)}
                      >
                        展开详情
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <Pagination
            limit={pageSize}
            noun="位"
            offset={offset}
            total={total}
            onPageChange={setOffset}
          />
          {total > pageSize ? null : (
            <p className="admin-hint">共 {total} 位客户。</p>
          )}
        </>
      )}
    </div>
  );
}

type Customer360Snapshot = {
  orders: AdminRechargeOrder[];
  transactions: AdminWalletTransaction[];
  devices: DeviceListItem[];
  sessions: CustomerSessionListItem[];
  adjustments: AdjustmentListItem[];
};

function Customer360Data({ userId }: { userId: string }) {
  const [snapshot, setSnapshot] = useState<Customer360Snapshot | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setError("");
    void Promise.all([
      listAdminRechargeOrders({ userId, limit: 3, offset: 0 }),
      listAdminWalletTransactions({ userId, limit: 3, offset: 0 }),
      listDevices({ userId, limit: 3, offset: 0 }),
      listCustomerSessions(userId, { limit: 3, offset: 0 }),
      listAdminAdjustments(userId, { limit: 3, offset: 0, sort: "desc" }),
    ])
      .then(([orders, transactions, devices, sessions, adjustments]) => {
        if (!cancelled) {
          setSnapshot({
            orders: orders.items,
            transactions: transactions.items,
            devices: devices.items,
            sessions: sessions.items,
            adjustments: adjustments.items,
          });
        }
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(
            cause instanceof Error && cause.message
              ? `客户运营数据加载失败：${cause.message}`
              : "客户运营数据加载失败",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [userId]);

  if (error) {
    return <PageBanner tone="error">{error}</PageBanner>;
  }
  if (!snapshot) {
    return <p className="admin-hint">正在拼装客户运营数据…</p>;
  }

  return (
    <section aria-label="客户 360 度运营数据" className="customer-360-grid">
      <Customer360Panel title="最近充值订单">
        {snapshot.orders.length ? (
          snapshot.orders.map((order) => (
            <div className="customer-360-row" key={order.id}>
              <code>{order.order_no}</code>
              <span>{formatFen(order.amount_fen)}</span>
              <OrderStatusBadge status={order.status} />
              <small>{formatDateTime(order.paid_at ?? order.created_at)}</small>
            </div>
          ))
        ) : (
          <Customer360Empty />
        )}
      </Customer360Panel>

      <Customer360Panel title="最近额度流水">
        {snapshot.transactions.length ? (
          snapshot.transactions.map((transaction) => (
            <div className="customer-360-row" key={transaction.id}>
              <span>{transactionTypeLabel(transaction.type)}</span>
              <strong>{transaction.available_delta} 积分</strong>
              <span>
                {transaction.available_balance_after === null
                  ? "历史未记录"
                  : `余额 ${transaction.available_balance_after} 积分`}
              </span>
              <small>{formatDateTime(transaction.created_at)}</small>
            </div>
          ))
        ) : (
          <Customer360Empty />
        )}
      </Customer360Panel>

      <Customer360Panel title="绑定设备">
        {snapshot.devices.length ? (
          snapshot.devices.map((device) => (
            <div className="customer-360-row" key={device.device_id}>
              <span>
                槽位 {device.slot_no} · {device.display_name || "未命名设备"}
              </span>
              <span>{platformLabel(device.platform)}</span>
              <DeviceStatusBadge
                status={
                  device.status === "BOUND"
                    ? device.online
                      ? "ONLINE"
                      : "OFFLINE"
                    : device.status
                }
              />
              <small>
                {formatDateTime(device.last_heartbeat_at ?? device.bound_at)}
              </small>
            </div>
          ))
        ) : (
          <Customer360Empty />
        )}
      </Customer360Panel>

      <Customer360Panel title="当前会话">
        {snapshot.sessions.length ? (
          snapshot.sessions.map((session) => (
            <div className="customer-360-row" key={session.session_id}>
              <span>{session.device_name || session.device_id}</span>
              <span>{platformLabel(session.platform)}</span>
              <span>Epoch {session.session_epoch}</span>
              <small>租约至 {formatDateTime(session.lease_until)}</small>
            </div>
          ))
        ) : (
          <Customer360Empty />
        )}
      </Customer360Panel>

      <Customer360Panel title="最近调账">
        {snapshot.adjustments.length ? (
          snapshot.adjustments.map((adjustment) => (
            <div className="customer-360-row" key={adjustment.adjustment_id}>
              <span>{adjustment.admin_username || "管理员"}</span>
              <code>{adjustment.source_document_ref}</code>
              <strong>+{adjustment.credits} 积分</strong>
              <small>{formatDateTime(adjustment.created_at)}</small>
            </div>
          ))
        ) : (
          <Customer360Empty />
        )}
      </Customer360Panel>
    </section>
  );
}

function Customer360Panel({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="customer-360-panel">
      <h3>{title}</h3>
      <div>{children}</div>
    </section>
  );
}

function Customer360Empty() {
  return <p className="admin-hint">暂无记录</p>;
}

function CustomerDetailView({
  customer,
  onChanged,
  readOnly,
  onBack,
  onOpenAdjustments,
  onOpenDevices,
  onOpenSessions,
}: {
  customer: CustomerListItem;
  onChanged: () => void;
  readOnly: boolean;
  onBack: () => void;
  onOpenAdjustments: () => void;
  onOpenDevices?: (userId: string) => void;
  onOpenSessions?: (userId: string) => void;
}) {
  return (
    <div
      className="customers-page customer-focused-detail"
      id={`customer-detail-${customer.user_id}`}
    >
      <button
        className="customer-detail-back btn-secondary"
        type="button"
        onClick={onBack}
      >
        ← 返回客户列表
      </button>
      <section className="customer-detail-hero">
        <div className="customer-detail-identity">
          <div aria-hidden="true" className="customer-detail-avatar">
            {customer.display_name?.trim().slice(0, 1) ||
              customer.username.slice(0, 1)}
          </div>
          <div>
            <div className="customer-detail-title">
              <h1>{customer.username}</h1>
              <CustomerStatusBadge status={customer.status} />
            </div>
            <strong>{customer.display_name || "未设置姓名"}</strong>
            <p>
              客户 ID <code>{customer.user_id}</code>
            </p>
            <p>注册时间 {formatDateTime(customer.created_at)}</p>
          </div>
        </div>
        <div className="customer-detail-operations">
          {!readOnly ? (
            <button
              type="button"
              onClick={() =>
                document
                  .getElementById("customer-free-grant")
                  ?.scrollIntoView({ behavior: "smooth", block: "start" })
              }
            >
              后台加款
            </button>
          ) : null}
          <button
            className="btn-secondary"
            type="button"
            onClick={onOpenAdjustments}
          >
            调账历史
          </button>
          {onOpenDevices ? (
            <button
              className="btn-secondary"
              type="button"
              onClick={() => onOpenDevices(customer.user_id)}
            >
              查看设备
            </button>
          ) : null}
          {onOpenSessions ? (
            <button
              className="btn-secondary"
              type="button"
              onClick={() => onOpenSessions(customer.user_id)}
            >
              查看会话
            </button>
          ) : null}
          <small>写操作需填写原因与来源单号，全程留痕审计</small>
        </div>
      </section>

      <section aria-label="客户核心指标" className="customer-detail-kpis">
        <article>
          <span>可用额度</span>
          <strong>{customer.available_credits ?? 0}</strong>
          <small>积分</small>
        </article>
        <article>
          <span>冻结额度</span>
          <strong>{customer.reserved_credits ?? 0}</strong>
          <small>积分</small>
        </article>
        <article>
          <span>累计消耗</span>
          <strong>{customer.credits_spent ?? 0}</strong>
          <small>积分</small>
        </article>
        <article>
          <span>累计生成</span>
          <strong>{customer.generation_total ?? 0}</strong>
          <small>条</small>
        </article>
      </section>

      <section className="customer-detail-section customer-activation-summary">
        <h2>激活与账户</h2>
        <dl className="customer-detail-meta">
          <div>
            <dt>激活码</dt>
            <dd>
              <code>{customer.activation_code}</code>
            </dd>
          </div>
          <div>
            <dt>登录设备</dt>
            <dd>{customer.device_slots_used ?? 0} 台 · 数量不限</dd>
          </div>
          <div>
            <dt>生成成功</dt>
            <dd>
              {customer.generation_succeeded ?? 0}/
              {customer.generation_total ?? 0}
            </dd>
          </div>
          <div>
            <dt>异常关注</dt>
            <dd>{customer.generation_attention ?? 0} 条</dd>
          </div>
        </dl>
      </section>

      <AccountCreditPanel
        key={`account:${customer.user_id}:${customer.available_credits}`}
        onChanged={onChanged}
        userId={customer.user_id}
        readOnly={readOnly}
      />
      <Customer360Data
        key={`ledger:${customer.user_id}:${customer.available_credits}`}
        userId={customer.user_id}
      />
      <div className="customer-detail-settings-grid">
        {customer.activation_code !== "账号注册" && (
          <CustomerPriceEditor readOnly={readOnly} userId={customer.user_id} />
        )}
        {customer.activation_code !== "账号注册" && (
          <LegacyCreditPolicyManager
            onChanged={onChanged}
            userId={customer.user_id}
            readOnly={readOnly}
          />
        )}
        <FreeCreditsSection
          onChanged={onChanged}
          readOnly={readOnly}
          userId={customer.user_id}
        />
      </div>
    </div>
  );
}

function CustomerPriceEditor({
  userId,
  readOnly,
}: {
  userId: string;
  readOnly: boolean;
}) {
  const [pricing, setPricing] = useState<CustomerUnitPrice | null>(null);
  const [priceYuan, setPriceYuan] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  // null = dialog closed; number = save that price; "reset" = restore default.
  const [pendingWrite, setPendingWrite] = useState<
    { kind: "save"; unitPriceFen: number } | { kind: "reset" } | null
  >(null);
  const [dialogError, setDialogError] = useState("");

  useEffect(() => {
    let cancelled = false;
    void fetchCustomerUnitPrice(userId)
      .then((result) => {
        if (cancelled) {
          return;
        }
        setPricing(result);
        setPriceYuan(formatYuanFromFen(result.unit_price_fen));
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(
            cause instanceof Error && cause.message.trim()
              ? cause.message
              : "读取客户单价失败",
          );
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [userId]);

  function requestSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const unitPriceFen = yuanInputToFen(priceYuan);
    if (unitPriceFen === null) {
      setError("客户售价必须是大于 0、最多两位小数的金额");
      return;
    }
    setError("");
    setDialogError("");
    setPendingWrite({ kind: "save", unitPriceFen });
  }

  function requestReset() {
    setError("");
    setDialogError("");
    setPendingWrite({ kind: "reset" });
  }

  async function persistPrice(reason: string) {
    if (!pendingWrite || saving) {
      return;
    }
    const unitPriceFen =
      pendingWrite.kind === "save" ? pendingWrite.unitPriceFen : null;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const updated = await updateCustomerUnitPrice(
        userId,
        unitPriceFen,
        reason,
      );
      setPricing(updated);
      setPriceYuan(formatYuanFromFen(updated.unit_price_fen));
      setNotice(
        unitPriceFen === null ? "已恢复全局默认售价" : "客户售价已保存",
      );
      setPendingWrite(null);
    } catch (cause) {
      setDialogError(
        cause instanceof Error && cause.message.trim()
          ? cause.message
          : "保存客户售价失败",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <section aria-label="客户售价" className="customer-detail-section">
      <h3>客户售价</h3>
      <p className="admin-hint">
        历史充值兼容配置；启用系统积分计价后，以系统设置中的积分兑换比例为准。
      </p>
      {loading ? <p className="admin-hint">正在读取客户售价…</p> : null}
      {pricing ? (
        <p className="admin-hint">
          当前 {formatFen(pricing.unit_price_fen)} / 秒 · 全局默认{" "}
          {formatFen(pricing.default_unit_price_fen)} / 秒
          {pricing.custom_unit_price_fen === null
            ? "（使用默认）"
            : "（独立定价）"}
        </p>
      ) : null}
      {error ? <PageBanner tone="error">{error}</PageBanner> : null}
      {notice ? <PageBanner tone="notice">{notice}</PageBanner> : null}
      {!loading && pricing && !readOnly ? (
        <form className="admin-form" onSubmit={requestSave}>
          <label>
            售价（元/秒）
            <input
              inputMode="decimal"
              min="0.01"
              step="0.01"
              type="number"
              value={priceYuan}
              onChange={(event) => setPriceYuan(event.target.value)}
            />
          </label>
          <div className="admin-actions">
            <button disabled={saving} type="submit">
              {saving ? "正在保存" : "保存客户售价"}
            </button>
            <button
              className="btn-secondary"
              disabled={saving || pricing.custom_unit_price_fen === null}
              type="button"
              onClick={requestReset}
            >
              恢复全局默认
            </button>
          </div>
        </form>
      ) : null}
      {!loading && pricing && readOnly ? (
        <p className="admin-hint">审计员仅可查看定价，不能修改。</p>
      ) : null}

      <ConfirmDialog
        busy={saving}
        confirmLabel={
          pendingWrite?.kind === "reset" ? "确认恢复默认" : "确认保存"
        }
        description={
          pendingWrite?.kind === "reset"
            ? "将清除该客户的独立定价，恢复为全局默认售价。原因将写入审计日志。"
            : `将把该客户售价改为 ${pendingWrite ? formatFen(pendingWrite.unitPriceFen) : ""} / 秒（仅影响该客户之后的充值换算）。原因将写入审计日志。`
        }
        error={dialogError}
        level="reason"
        open={pendingWrite !== null}
        title={
          pendingWrite?.kind === "reset" ? "恢复全局默认售价" : "修改客户售价"
        }
        onClose={() => {
          setPendingWrite(null);
          setDialogError("");
        }}
        onConfirm={(reason: string) => void persistPrice(reason)}
      />
    </section>
  );
}

/**
 * 赠送积分发放（FREE_GRANT，054）：为账号发放无收款积分。
 * 走 T23 审计调账闭环——账面金额为 0、钱包照增、来源单与原因必填。
 */
function FreeCreditsSection({
  userId,
  onChanged,
  readOnly,
}: {
  userId: string;
  onChanged: () => void;
  readOnly: boolean;
}) {
  const [credits, setCredits] = useState("");
  const [sourceType, setSourceType] = useState("FREE_GRANT");
  const [sourceRef, setSourceRef] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogError, setDialogError] = useState("");
  const [notice, setNotice] = useState("");
  const retry = useRef<{ fingerprint: string; key: string } | null>(null);

  function requestGrant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const creditsNumber = Number(credits);
    if (!Number.isSafeInteger(creditsNumber) || creditsNumber <= 0) {
      setDialogError("赠送积分必须是大于 0 的整数");
      setDialogOpen(true);
      return;
    }
    if (!sourceRef.trim()) {
      setDialogError("请填写来源单号（运营审批或活动编号）");
      setDialogOpen(true);
      return;
    }
    setDialogError("");
    setDialogOpen(true);
  }

  async function submitGrant(reason: string) {
    if (submitting || readOnly) {
      return;
    }
    const creditsNumber = Number(credits);
    if (
      !Number.isSafeInteger(creditsNumber) ||
      creditsNumber <= 0 ||
      !sourceRef.trim()
    ) {
      setDialogError("请填写有效整数积分和来源单号");
      return;
    }
    const fingerprint = JSON.stringify({
      userId,
      creditsNumber,
      sourceType,
      sourceRef: sourceRef.trim(),
      reason,
    });
    if (retry.current?.fingerprint !== fingerprint)
      retry.current = { fingerprint, key: crypto.randomUUID() };
    const key = retry.current.key;
    setSubmitting(true);
    try {
      const result = await createCustomerAdjustment(
        userId,
        {
          sourceDocumentType: sourceType,
          sourceDocumentRef: sourceRef.trim(),
          credits: creditsNumber,
        },
        reason,
        key,
      );
      setNotice(
        `已发放 ${creditsNumber} 赠送积分（request id: ${result.request_id}），余额 ${result.wallet_balance_after} 积分`,
      );
      onChanged();
      setCredits("");
      setSourceRef("");
      retry.current = null;
      setDialogOpen(false);
      setDialogError("");
    } catch (cause) {
      setDialogError(
        cause instanceof Error && cause.message.trim()
          ? cause.message
          : "发放赠送积分失败",
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (readOnly) {
    return (
      <section aria-label="赠送积分" className="customer-detail-section">
        <h3>赠送积分</h3>
        <p className="admin-hint">审计员仅可查看，不能发放赠送积分。</p>
      </section>
    );
  }

  return (
    <section
      aria-label="赠送积分"
      className="customer-detail-section"
      id="customer-free-grant"
    >
      <h3>赠送积分</h3>
      <p className="admin-hint">
        发放的赠送积分直接进入该账号钱包，生成视频时与充值积分同等冻结与结算；
        账面金额记 0，来源单号与原因写入审计。
      </p>
      {notice ? <PageBanner tone="notice">{notice}</PageBanner> : null}
      <form className="admin-form" onSubmit={requestGrant}>
        <label>
          积分来源
          <select
            value={sourceType}
            onChange={(event) => {
              setSourceType(event.target.value);
              retry.current = null;
            }}
          >
            <option value="FREE_GRANT">积分赠送</option>
            <option value="CREDIT_COMPENSATION">无收款补偿</option>
          </select>
        </label>
        <label>
          发放积分
          <input
            min={1}
            placeholder="例如：10"
            step={1}
            type="number"
            value={credits}
            onChange={(event) => setCredits(event.target.value)}
          />
        </label>
        <label>
          来源单号
          <input
            placeholder="必填，例如：PROMO-2026-09-001"
            value={sourceRef}
            onChange={(event) => setSourceRef(event.target.value)}
          />
        </label>
        <button type="submit">发放赠送积分</button>
      </form>

      <ConfirmDialog
        busy={submitting}
        confirmLabel="确认发放"
        description="赠送积分会立即进入客户钱包并可立即用于生成视频。原因将写入审计日志。"
        error={dialogError}
        level="reasonAndAck"
        open={dialogOpen}
        title="发放赠送积分"
        onClose={() => {
          setDialogOpen(false);
          setDialogError("");
        }}
        onConfirm={(reason: string) => void submitGrant(reason)}
      />
    </section>
  );
}

function yuanInputToFen(value: string): number | null {
  const normalized = value.trim();
  if (!/^(?:0|[1-9]\d*)(?:\.\d{1,2})?$/.test(normalized)) {
    return null;
  }
  const [yuan, cents = ""] = normalized.split(".");
  const result = Number(yuan) * 100 + Number(cents.padEnd(2, "0"));
  return Number.isSafeInteger(result) && result > 0 ? result : null;
}
