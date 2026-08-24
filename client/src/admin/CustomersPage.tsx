import { type FormEvent, useCallback, useEffect, useState } from "react";

import {
  type CustomerListItem,
  AdminCustomerError,
  listCustomers,
} from "../api.admin";

/**
 * T33 — customer list with pagination and filtering.
 *
 * The page shows all registered customers with their activation codes,
 * email addresses, and current status. Admin users can navigate through
 * pages and filter by email; auditors see the same read-only view.
 *
 * Write controls (adjustments) are disabled when readOnly=true (auditor role).
 */
export function CustomersPage({
  readOnly = false,
}: {
  readOnly?: boolean;
}) {
  const [customers, setCustomers] = useState<CustomerListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [emailFilter, setEmailFilter] = useState("");

  const loadCustomers = useCallback(async () => {
    try {
      setLoading(true);
      setError("");
      const response = await listCustomers({
        page,
        page_size: pageSize,
        email_filter: emailFilter || undefined,
      });
      setCustomers(response.customers);
      setTotal(response.total);
    } catch (err) {
      if (err instanceof AdminCustomerError) {
        setError(`加载失败：${err.message}`);
      } else {
        setError("加载失败：未知错误");
      }
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, emailFilter]);

  useEffect(() => {
    loadCustomers();
  }, [loadCustomers]);

  const handleFilterSubmit = (e: FormEvent) => {
    e.preventDefault();
    setPage(1); // Reset to first page when filtering
    loadCustomers();
  };

  const handleNextPage = () => {
    if (page < Math.ceil(total / pageSize)) {
      setPage(page + 1);
    }
  };

  const handlePrevPage = () => {
    if (page > 1) {
      setPage(page - 1);
    }
  };

  const totalPages = Math.ceil(total / pageSize);

  const statusLabels: Record<string, string> = {
    active: "活跃",
    suspended: "已暂停",
    revoked: "已作废",
  };

  return (
    <div className="customers-page">
      <header>
        <h1>客户管理</h1>
        {!readOnly && (
          <button type="button" className="btn-primary">
            新建调账
          </button>
        )}
      </header>

      <form onSubmit={handleFilterSubmit} className="filter-form">
        <input
          type="text"
          placeholder="按邮箱筛选"
          value={emailFilter}
          onChange={(e) => setEmailFilter(e.target.value)}
        />
        <button type="submit">筛选</button>
      </form>

      {loading && <div className="loading">加载中...</div>}

      {error && <div className="error">{error}</div>}

      {!loading && !error && customers.length === 0 && (
        <div className="empty-state">暂无客户数据</div>
      )}

      {!loading && !error && customers.length > 0 && (
        <>
          <table className="customers-table">
            <thead>
              <tr>
                <th>邮箱</th>
                <th>激活码</th>
                <th>注册时间</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              {customers.map((customer) => (
                <tr key={customer.user_id}>
                  <td>{customer.email}</td>
                  <td>
                    <code>{customer.activation_code}</code>
                  </td>
                  <td>{new Date(customer.created_at).toLocaleString("zh-CN")}</td>
                  <td>
                    <span className={`status-badge status-${customer.status}`}>
                      {statusLabels[customer.status] || customer.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="pagination">
            <button
              type="button"
              onClick={handlePrevPage}
              disabled={page === 1}
            >
              上一页
            </button>
            <span>
              第 {page} 页 / 共 {totalPages} 页（共 {total} 位客户）
            </span>
            <button
              type="button"
              onClick={handleNextPage}
              disabled={page === totalPages}
            >
              下一页
            </button>
          </div>
        </>
      )}
    </div>
  );
}
