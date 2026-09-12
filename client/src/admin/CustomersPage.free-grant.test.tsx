import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { clearAdminCsrfToken, setAdminCsrfToken } from "../api";
import { CustomersPage } from "./CustomersPage";

afterEach(() => {
  clearAdminCsrfToken();
  vi.unstubAllGlobals();
});

it.each(["timeout", "server-error", "network"])(
  "replays the same free-grant intent after %s and refreshes customer data",
  async (failure) => {
    const posts: { key: string; body: string }[] = [];
    const ledger = new Set<string>();
    const reads: string[] = [];
    let balance = 50;
    const json = (body: unknown, status = 200) =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = new URL(String(input)).pathname;
        if (path.endsWith("/adjustments") && init?.method === "POST") {
          const key = new Headers(init.headers).get("Idempotency-Key") ?? "";
          const body = String(init.body);
          posts.push({ key, body });
          // Idempotent server model; this UI test does not claim real PG validation.
          if (!ledger.has(key)) {
            ledger.add(key);
            balance += Number(JSON.parse(body).credits);
          }
          if (posts.length === 1) {
            if (failure === "timeout") {
              return await new Promise<Response>((_resolve, reject) => {
                init.signal?.addEventListener(
                  "abort",
                  () =>
                    reject(
                      new DOMException(
                        "Response lost after commit",
                        "AbortError",
                      ),
                    ),
                  { once: true },
                );
              });
            }
            if (failure === "server-error")
              return json({ detail: "gateway error" }, 503);
            throw new TypeError("network response lost");
          }
          return json({
            adjustment_id: "adj",
            order_id: "order",
            credits: "10",
            amount_fen: "0",
            wallet_balance_after: balance,
            request_id: "request-grant",
            source_document_type: "FREE_GRANT",
            source_document_ref: "source",
            pricing_scope: "CUSTOMER_STANDARD",
          });
        }
        reads.push(path);
        if (path === "/api/control/customers")
          return json({
            items: [
              {
                user_id: "customer",
                username: "customer",
                created_at: "2026-09-12T00:00:00Z",
                activation_code: "MASKED",
                status: "active",
                available_credits: balance,
                reserved_credits: 0,
              },
            ],
            total: 1,
            limit: 20,
            offset: 0,
          });
        if (path.endsWith("/unit-price"))
          return json({
            user_id: "customer",
            unit_price_fen: 10,
            custom_unit_price_fen: null,
            default_unit_price_fen: 10,
            min_recharge_fen: 100,
            recharge_step_fen: 100,
            updated_at: null,
            request_id: "price",
          });
        return json({ items: [], total: 0, limit: 3, offset: 0 });
      }),
    );
    setAdminCsrfToken("fixture-csrf");
    render(<CustomersPage />);
    fireEvent.click(await screen.findByRole("button", { name: "展开详情" }));
    fireEvent.change(await screen.findByLabelText("发放秒数"), {
      target: { value: "10" },
    });
    fireEvent.change(screen.getByLabelText("来源单号"), {
      target: { value: "source" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发放免费秒数" }));
    fireEvent.change(screen.getByLabelText("操作原因"), {
      target: { value: "approved grant" },
    });
    fireEvent.click(screen.getByLabelText("我已知晓该操作的影响"));
    fireEvent.click(screen.getByRole("button", { name: "确认发放" }));
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument(), {
      timeout: 8000,
    });
    expect(balance).toBe(60);
    expect(screen.getByLabelText("发放秒数")).toBeDisabled();
    expect(screen.getByLabelText("来源单号")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    fireEvent.click(screen.getByRole("button", { name: "发放免费秒数" }));
    fireEvent.click(screen.getByRole("button", { name: "确认发放" }));
    expect(await screen.findByText(/已发放 10 秒免费时长/)).toHaveTextContent(
      "余额 60 秒",
    );
    expect(posts).toHaveLength(2);
    expect(posts[0]).toEqual(posts[1]);
    expect(ledger.size).toBe(1);
    await waitFor(() =>
      expect(
        within(screen.getByRole("region", { name: "客户核心指标" })).getByText(
          "60",
        ),
      ).toBeInTheDocument(),
    );
    expect(
      reads.filter((path) => path === "/api/control/customers"),
    ).toHaveLength(2);
    expect(reads.filter((path) => path.endsWith("/adjustments"))).toHaveLength(
      2,
    );
    expect(screen.getByLabelText("发放秒数")).toBeEnabled();
  },
  15000,
);
