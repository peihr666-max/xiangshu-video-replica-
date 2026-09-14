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
  type AdminRechargeOrder,
  type AdminWalletTransaction,
  type CustomerListItem,
  type CustomerUnitPrice,
  createCustomerAdjustment,
  fetchCustomerUnitPrice,
  listAdminRechargeOrders,
  listAdminWalletTransactions,
  listCustomers,
  updateCustomerUnitPrice,
} from "../api.admin";
import { AccountCreditPanel } from "./AccountCreditPanel";
import { ConfirmDialog } from "./ui/ConfirmDialog";
import { CopyCustomerId } from "./ui/CopyCustomerId";
import { PageBanner } from "./ui/PageBanner";
import { Pagination } from "./ui/Pagination";
import { CustomerStatusBadge, OrderStatusBadge } from "./ui/StatusBadge";
import {
  formatDateTime,
  formatFen,
  formatYuanFromFen,
  transactionTypeLabel,
} from "./ui/vocabulary";
import "./admin-customer-detail.css";

interface CustomersPageProps {
  embedded?: boolean;
  readOnly?: boolean;
}

export function CustomersPage({
  embedded = false,
  readOnly = false,
}: CustomersPageProps = {}) {
  const [customers, setCustomers] = useState<CustomerListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [offset, setOffset] = useState(0);
  const [pageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [usernameDraft, setUsernameDraft] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [createdFrom, setCreatedFrom] = useState("");
  const [createdTo, setCreatedTo] = useState("");
  const [balanceMin, setBalanceMin] = useState("");
  const [balanceMax, setBalanceMax] = useState("");
  const [expandedUserId, setExpandedUserId] = useState<string | null>(null);
  const [filters, setFilters] = useState({
    username: "",
    status: "all",
    createdFrom: "",
    createdTo: "",
    balanceMin: "",
    balanceMax: "",
  });
  const requestId = useRef(0);

  const loadCustomers = useCallback(async () => {
    const sequence = ++requestId.current;
    try {
      setLoading(true);
      setError("");
      const response = await listCustomers({
        limit: pageSize,
        offset,
        username_filter: filters.username || undefined,
        status: filters.status === "all" ? undefined : filters.status,
        createdFrom: filters.createdFrom || undefined,
        createdTo: filters.createdTo || undefined,
        balanceMin: filters.balanceMin ? Number(filters.balanceMin) : undefined,
        balanceMax: filters.balanceMax ? Number(filters.balanceMax) : undefined,
      });
      if (sequence !== requestId.current) return;
      setCustomers(response.items);
      setTotal(response.total);
    } catch (err) {
      if (sequence !== requestId.current) return;
      setError(
        err instanceof Error && err.message
          ? `加载失败：${err.message}`
          : "加载失败：未知错误",
      );
    } finally {
      if (sequence === requestId.current) setLoading(false);
    }
  }, [filters, offset, pageSize]);

  useEffect(() => {
    loadCustomers();
    return () => {
      requestId.current += 1;
    };
  }, [loadCustomers]);

  const handleFilterSubmit = (e: FormEvent) => {
    e.preventDefault();
    setOffset(0);
    setExpandedUserId(null);
    setFilters({
      username: usernameDraft.trim(),
      status: statusFilter,
      createdFrom,
      createdTo,
      balanceMin,
      balanceMax,
    });
  };

  const failedGenerations = customers.reduce(
    (sum, customer) => sum + (customer.generation_failed ?? 0),
    0,
  );
  const inProgressGenerations = customers.reduce(
    (sum, customer) => sum + (customer.generation_in_progress ?? 0),
    0,
  );

  const exportList = () => {
    void downloadCustomersCsv({
      status: filters.status === "all" ? undefined : filters.status,
      username: filters.username || undefined,
      createdFrom: filters.createdFrom || undefined,
      createdTo: filters.createdTo || undefined,
      balanceMin: filters.balanceMin ? Number(filters.balanceMin) : undefined,
      balanceMax: filters.balanceMax ? Number(filters.balanceMax) : undefined,
    }).catch((cause: unknown) =>
      setError(cause instanceof Error ? cause.message : "导出失败"),
    );
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

      <form
        className="admin-toolbar customer-list-filters"
        onSubmit={handleFilterSubmit}
      >
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
            min={createdFrom || undefined}
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
        <div className="customer-list-filters__actions">
          <button className="admin-toolbar__secondary" type="submit">
            筛选
          </button>
          <button type="button" onClick={exportList}>
            导出列表 CSV
          </button>
        </div>
      </form>

      <section aria-label="需要处理" className="admin-attention-strip">
        <strong>需要处理</strong>
        <span>
          失败生成 <b>{failedGenerations}</b>
        </span>
        <span>
          处理中 <b>{inProgressGenerations}</b>
        </span>
        <small>数据范围：当前筛选页</small>
      </section>

      {loading && <div className="loading">加载中...</div>}

      {error ? <PageBanner tone="error">{error}</PageBanner> : null}

      {!loading && !error && customers.length === 0 && (
        <div className="empty-state">暂无客户数据</div>
      )}

      {!loading && !error && customers.length > 0 && (
        <>
          <div className="table-scroll admin-table-card">
            <table
              aria-label="客户列表"
              className="customers-table admin-data-table"
            >
              <thead>
                <tr>
                  <th>用户名</th>
                  <th>客户 ID</th>
                  <th>注册时间</th>
                  <th>状态</th>
                  <th>可用额度</th>
                  <th>累计消耗</th>
                  <th>生成情况</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {customers.map((customer) => (
                  <tr key={customer.user_id}>
                    <td data-label="用户名">
                      <span
                        className="customer-cell-ellipsis"
                        title={customer.username}
                      >
                        {customer.username}
                      </span>
                    </td>
                    <td data-label="客户 ID">
                      <CopyCustomerId value={customer.user_id} />
                    </td>
                    <td data-label="注册时间">
                      <time
                        className="customer-cell-date"
                        dateTime={customer.created_at}
                      >
                        {formatDateTime(customer.created_at).split(" ")[0]}{" "}
                        <small>
                          {formatDateTime(customer.created_at).split(" ")[1]}
                        </small>
                      </time>
                    </td>
                    <td data-label="状态">
                      <CustomerStatusBadge status={customer.status} />
                    </td>
                    <td data-label="可用额度">
                      <strong>{customer.available_credits ?? 0} 积分</strong>
                    </td>
                    <td
                      aria-label={`${customer.username} 已结算消耗`}
                      data-label="累计消耗"
                    >
                      {customer.credits_spent ?? 0} 积分
                    </td>
                    <td data-label="生成情况">
                      <div className="customer-cell-generation">
                        <span>
                          成功 {customer.generation_succeeded ?? 0} /{" "}
                          {customer.generation_total ?? 0}
                        </span>{" "}
                        <small>
                          失败 {customer.generation_failed ?? 0} · 进行中{" "}
                          {customer.generation_in_progress ?? 0}
                        </small>
                      </div>
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
        </>
      )}
    </div>
  );
}

type Customer360Snapshot = {
  orders: AdminRechargeOrder[];
  transactions: AdminWalletTransaction[];
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
    ])
      .then(([orders, transactions]) => {
        if (!cancelled) {
          setSnapshot({
            orders: orders.items,
            transactions: transactions.items,
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
    return <p className="admin-hint">正在加载…</p>;
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
}: {
  customer: CustomerListItem;
  onChanged: () => void;
  readOnly: boolean;
  onBack: () => void;
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
            {customer.username.slice(0, 1)}
          </div>
          <div>
            <div className="customer-detail-title">
              <h1>{customer.username}</h1>
              <CustomerStatusBadge status={customer.status} />
            </div>
            <p>
              客户 ID <CopyCustomerId value={customer.user_id} />
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
        </div>
      </section>

      <section aria-label="客户核心指标" className="customer-detail-kpis">
        <article>
          <span>可用额度</span>
          <strong>{customer.available_credits ?? 0}</strong>
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
            ? "将清除该客户的独立定价，恢复为全局默认售价。"
            : `将把该客户售价改为 ${pendingWrite ? formatFen(pendingWrite.unitPriceFen) : ""} / 秒（仅影响该客户之后的充值换算）。`
        }
        error={dialogError}
        level="standard"
        open={pendingWrite !== null}
        title={
          pendingWrite?.kind === "reset" ? "恢复全局默认售价" : "修改客户售价"
        }
        onClose={() => {
          setPendingWrite(null);
          setDialogError("");
        }}
        onConfirm={() =>
          void persistPrice(
            pendingWrite?.kind === "reset"
              ? "恢复客户默认售价"
              : "更新客户售价",
          )
        }
      />
    </section>
  );
}

/**
 * 赠送积分发放（FREE_GRANT，054）：为账号发放无收款积分。
 * 走 T23 审计调账闭环——账面金额为 0、钱包照增、自动单号与事由留痕。
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
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogError, setDialogError] = useState("");
  const [notice, setNotice] = useState("");
  const retry = useRef<{
    fingerprint: string;
    key: string;
    sourceRef: string;
  } | null>(null);
  const saving = useRef(false);

  function requestGrant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (readOnly || saving.current) return;
    const creditsNumber = Number(credits);
    if (!Number.isSafeInteger(creditsNumber) || creditsNumber <= 0) {
      setDialogError("赠送积分必须是大于 0 的整数");
      return;
    }
    if (!reason.trim()) {
      setDialogError("请填写事由");
      return;
    }
    const fingerprint = JSON.stringify([
      userId,
      creditsNumber,
      sourceType,
      reason.trim(),
    ]);
    if (retry.current?.fingerprint !== fingerprint) {
      const key = crypto.randomUUID();
      retry.current = { fingerprint, key, sourceRef: `GRANT-${key}` };
    }
    setDialogError("");
    setDialogOpen(true);
  }

  async function submitGrant() {
    if (saving.current || readOnly || !retry.current) return;
    const creditsNumber = Number(credits);
    const { key, sourceRef } = retry.current;
    saving.current = true;
    setSubmitting(true);
    try {
      const result = await createCustomerAdjustment(
        userId,
        {
          sourceDocumentType: sourceType,
          sourceDocumentRef: sourceRef,
          credits: creditsNumber,
        },
        reason.trim(),
        key,
      );
      setNotice(
        `已发放 ${creditsNumber} 赠送积分（request id: ${result.request_id}），余额 ${result.wallet_balance_after} 积分`,
      );
      onChanged();
      setCredits("");
      setReason("");
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
      saving.current = false;
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
      {notice ? <PageBanner tone="notice">{notice}</PageBanner> : null}
      {dialogError && !dialogOpen ? (
        <PageBanner tone="error">{dialogError}</PageBanner>
      ) : null}
      <form className="admin-form" onSubmit={requestGrant}>
        <label>
          积分来源
          <select
            disabled={dialogOpen}
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
            disabled={dialogOpen}
            min={1}
            placeholder="例如：10"
            step={1}
            type="number"
            value={credits}
            onChange={(event) => setCredits(event.target.value)}
          />
        </label>
        <label>
          事由
          <input
            disabled={dialogOpen}
            placeholder="例如：新客赠送、活动奖励或售后补偿"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </label>
        <button type="submit" disabled={dialogOpen}>
          发放赠送积分
        </button>
      </form>

      <ConfirmDialog
        busy={submitting}
        confirmLabel="确认发放"
        description={
          <>
            即将发放 {credits} 积分。
            <br />
            事由：{reason.trim()}
            <br />
            来源单号：{retry.current?.sourceRef}
          </>
        }
        error={dialogError}
        level="standard"
        open={dialogOpen}
        title="发放赠送积分"
        onClose={() => {
          setDialogOpen(false);
          setDialogError("");
        }}
        onConfirm={() => void submitGrant()}
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
