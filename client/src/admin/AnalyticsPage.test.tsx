import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { adminRead } from "../api.admin";
import { AnalyticsPage } from "./AnalyticsPage";

vi.mock("../api.admin", () => ({
  adminRead: vi.fn(),
  downloadBillingCsv: vi.fn(),
}));

test("switches profit and cost columns while retaining filters and loaded data", async () => {
  const totals = {
    operation_count: 2,
    charged_credits: 5,
    known_revenue_fen: 200,
    known_cost_fen: 50,
    profit_fen: null,
    legacy_cost_count: 2,
    legacy_settlement_count: 1,
    platform_cost_fen: 10,
    unknown_cost_count: 0,
    unknown_revenue_count: 0,
    pending_count: 0,
    refunded_credits: 0,
    seconds: "3",
    images: "0",
    calls: "0",
  };
  vi.mocked(adminRead).mockImplementation(async (url) => {
    if (url.includes("catalog")) return { services: [] } as never;
    if (url.includes("statistics"))
      return {
        totals,
        periods: [{ ...totals, period: "2026-09-13" }],
        basis: "",
      } as never;
    return { items: [], total: 0 } as never;
  });
  render(<AnalyticsPage />);
  const profit = await screen.findByRole("table", { name: "周期汇总" });
  expect(
    screen.getByText(/2 条历史成本、1 条历史结算待核对/),
  ).toBeInTheDocument();
  expect(within(profit).getByText("待核对")).toBeInTheDocument();
  expect(
    within(profit).getByRole("columnheader", { name: "利润" }),
  ).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("用户 ID"), {
    target: { value: "test-customer" },
  });
  const calls = vi.mocked(adminRead).mock.calls.length;
  fireEvent.click(screen.getByRole("tab", { name: "成本明细" }));
  const cost = screen.getByRole("table", { name: "周期汇总" });
  expect(
    within(cost).queryByRole("columnheader", { name: "利润" }),
  ).not.toBeInTheDocument();
  expect(
    within(cost).getByRole("columnheader", { name: "平台承担成本" }),
  ).toBeInTheDocument();
  expect(screen.getByLabelText("用户 ID")).toHaveValue("test-customer");
  expect(adminRead).toHaveBeenCalledTimes(calls);
});
