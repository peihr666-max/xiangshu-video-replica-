import { useEffect, useState } from "react";
import {
  type CustomerPricing,
  type CustomerSessionCredential,
  customerGetPricing,
} from "../api";

export function CustomerPricesPage({
  credential,
}: {
  credential: () => Promise<CustomerSessionCredential>;
}) {
  const [prices, setPrices] = useState<CustomerPricing | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    void retry;
    let active = true;
    setPrices(null);
    setError("");
    void credential()
      .then(customerGetPricing)
      .then((value) => {
        if (active) setPrices(value);
      })
      .catch((cause) => {
        if (active)
          setError(cause instanceof Error ? cause.message : "读取价格失败");
      });
    return () => {
      active = false;
    };
  }, [credential, retry]);
  return (
    <section className="uc-card" aria-label="接口价格">
      <div className="uc-section-heading">
        <div>
          <h2>接口价格</h2>
          <p>按实际用量扣除账号积分，所有 Token 共用账号余额。</p>
        </div>
      </div>
      {error ? (
        <div role="alert">
          <p>{error}</p>
          <button type="button" onClick={() => setRetry((v) => v + 1)}>
            重新加载价格
          </button>
        </div>
      ) : !prices ? (
        <p role="status">正在读取价格…</p>
      ) : (
        <>
          <p>
            {prices.configured
              ? `当前价格版本：V${prices.version}`
              : "当前沿用原有扣费规则，管理员尚未发布新的积分价格。"}
          </p>
          <div className="uc-table-scroll">
            <table>
              <thead>
                <tr>
                  <th>接口功能</th>
                  <th>模型 / 规格</th>
                  <th>积分单价</th>
                </tr>
              </thead>
              <tbody>
                {prices.prices.map((price) => (
                  <tr key={price.subject}>
                    <td>{price.name}</td>
                    <td>{price.specification}</td>
                    <td>
                      <strong>
                        {price.unit_credits} 积分 / {price.unit}
                      </strong>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {prices.config && (
            <p>
              消费按表中单价的{" "}
              {(prices.config.discount_basis_points ?? 10000) / 100}%
              计费，逐任务
              {prices.config.consumption_rounding === "floor" ? "向下" : "向上"}
              取整，最低 1 积分；标为 0 积分的功能不单独扣分。
            </p>
          )}
          {prices.config && (
            <p>
              <strong>1 元 = {prices.config.points_per_yuan} 积分</strong> ·{" "}
              {prices.recharge_rounding}
            </p>
          )}
          <p>
            任务按提交时的价格预扣，成功后结算，符合退款条件的失败任务退回预扣积分。价格调整不影响已受理任务和已创建充值订单。
          </p>
        </>
      )}
    </section>
  );
}
