import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { adminRead } from "../api.admin";
import { AnalyticsPage } from "./AnalyticsPage";

vi.mock("../api.admin", () => ({
  adminRead: vi.fn(),
  downloadBillingCsv: vi.fn(),
}));

test.each([
  ["68.000000", "68.0 秒"],
  ["12.350000", "12.4 秒"],
  ["0.000000", "0.0 秒"],
  [null, "处理中 秒"],
])(
  "formats request usage %s without treating pending as zero",
  async (usage, expected) => {
    vi.mocked(adminRead).mockImplementation(async (url) => {
      if (url.includes("catalog")) return { services: [] } as never;
      if (url.includes("statistics"))
        return { totals: {}, periods: [], basis: "" } as never;
      return {
        items: [
          {
            id: "usage-row",
            username: "测试用户",
            service: "asr",
            unit: "second",
            state: usage === null ? "PENDING" : "SUCCEEDED",
            actual_units: usage,
            charged_credits: 0,
            revenue_fen: "0",
            nominal_revenue_fen: "0",
            cost_fen: "0",
            profit_fen: "0",
          },
        ],
        total: 1,
      } as never;
    });
    render(<AnalyticsPage />);
    const table = await screen.findByRole("table", { name: "请求明细" });
    expect(
      within(table).getByRole("cell", { name: expected }),
    ).toBeInTheDocument();
  },
);

test.each([
  ["0", "136", "¥0.00", "¥1.36"],
  ["100", "225", "¥1.00", "¥2.25"],
  [null, "75", "待核对", "¥0.75"],
])(
  "distinguishes paid revenue %s from consumed face value %s",
  async (revenue, nominal, paidDisplay, nominalDisplay) => {
    const operation = {
      id: "revenue-row",
      username: "测试用户",
      service: "asr",
      unit: "second",
      state: "SUCCEEDED",
      actual_units: "68.000000",
      budget_units: "68.267000",
      charged_credits: 136,
      reserved_credits: 138,
      revenue_fen: revenue,
      nominal_revenue_fen: nominal,
      cost_fen: "68",
      profit_fen: null,
      pricing_snapshot_json: JSON.stringify({
        enabled: true,
        unit_credits: "2",
        discount_basis_points: 10000,
        version: 1,
      }),
      attempts: [
        {
          id: "attempt",
          service: "asr",
          provider: "provider",
          unit: "second",
          usage: "68.267000",
          state: "ACTUAL",
          unit_cost_fen: "1",
          effective_cost_fen: "68",
        },
      ],
    };
    vi.mocked(adminRead).mockImplementation(async (url) => {
      if (url.includes("catalog")) return { services: [] } as never;
      if (url.includes("statistics"))
        return { totals: {}, periods: [], basis: "" } as never;
      if (url.endsWith("/revenue-row")) return operation as never;
      return { items: [operation], total: 1 } as never;
    });
    render(<AnalyticsPage readOnly />);
    const table = await screen.findByRole("table", { name: "请求明细" });
    const headers = within(table)
      .getAllByRole("columnheader")
      .map((cell) => cell.textContent);
    const cells = within(within(table).getAllByRole("row")[1]).getAllByRole(
      "cell",
    );
    expect(headers).toContain("消费折合");
    expect(headers).toContain("实付收入");
    expect(cells[headers.indexOf("消费折合")]).toHaveTextContent(
      nominalDisplay,
    );
    expect(cells[headers.indexOf("实付收入")]).toHaveTextContent(paidDisplay);
    fireEvent.click(within(table).getByRole("button", { name: "查看请求" }));
    const detail = await screen.findByRole("complementary", {
      name: "请求核算详情",
    });
    expect(detail).toHaveTextContent(
      `消费折合 ${nominalDisplay} · 实付收入 ${paidDisplay}`,
    );
    expect(detail).toHaveTextContent("预算 68.3 秒，实际 68.0 秒");
    expect(
      within(detail).getByRole("cell", { name: "68.3 秒" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "成本明细" }));
    expect(
      within(table).queryByRole("columnheader", { name: "实付收入" }),
    ).not.toBeInTheDocument();
    expect(
      within(table).queryByRole("columnheader", { name: "消费折合" }),
    ).not.toBeInTheDocument();
  },
);

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
