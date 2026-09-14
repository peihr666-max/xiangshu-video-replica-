import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { adminRead, adminWrite } from "../api.admin";
import { BillingRatesManager } from "./BillingRatesManager";

vi.mock("../api.admin", () => ({ adminRead: vi.fn(), adminWrite: vi.fn() }));
const catalog = {
  pricing: { version: 3, points_per_yuan: 100 },
  services: [
    {
      service: "video_768p",
      name: "视频生成 · 768P",
      unit: "second",
      provider: "metaso",
      module: "video",
      customer_charge_allowed: true,
      configured: false,
      tariff: {
        enabled: false,
        unit_credits: null,
        unit_cost_fen: null,
        unit_rounding: "ceil",
        version: 0,
      },
    },
  ],
};
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(adminRead).mockResolvedValue(catalog);
  vi.mocked(adminWrite).mockResolvedValue(catalog);
});

test("cost-only configuration leaves the customer tariff absent and disabled", async () => {
  render(<BillingRatesManager />);
  fireEvent.click(
    await screen.findByRole("button", { name: "配置 视频生成 · 768P" }),
  );
  const row = screen
    .getByRole("textbox", { name: "成本（积分 / 秒，留空待核对）" })
    .closest("tr");
  expect(row).not.toBeNull();
  expect(
    within(row as HTMLTableRowElement).getByText("视频生成 · 768P"),
  ).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("成本（积分 / 秒，留空待核对）"), {
    target: { value: "0.000125" },
  });
  expect(screen.queryByLabelText("调整原因")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "确认并保存" }));
  await waitFor(() =>
    expect(adminWrite).toHaveBeenCalledWith(
      "/api/control/billing/tariff",
      {
        service: "video_768p",
        expected_version: 0,
        expected_pricing_version: 3,
        tariff: {
          enabled: false,
          unit_credits: null,
          unit_cost_fen: "0.000125",
          unit_rounding: "ceil",
        },
      },
      "配置视频生成 · 768P成本与售价",
      expect.any(String),
      expect.any(String),
      "PUT",
    ),
  );
});

test("enabling a tariff requires an explicit price and preserves the key after an uncertain write", async () => {
  vi.mocked(adminWrite).mockRejectedValueOnce(new Error("请求结果未知"));
  render(<BillingRatesManager />);
  fireEvent.click(
    await screen.findByRole("button", { name: "配置 视频生成 · 768P" }),
  );
  fireEvent.click(screen.getByLabelText("启用用户扣分"));
  expect(screen.queryByLabelText("调整原因")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "确认并保存" }));
  expect(adminWrite).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("售价（积分 / 秒）"), {
    target: { value: "0.25" },
  });
  fireEvent.click(screen.getByRole("button", { name: "确认并保存" }));
  await screen.findByText("请求结果未知");
  fireEvent.click(screen.getByRole("button", { name: "确认并保存" }));
  await waitFor(() => expect(adminWrite).toHaveBeenCalledTimes(2));
  expect(vi.mocked(adminWrite).mock.calls[1]).toEqual(
    vi.mocked(adminWrite).mock.calls[0],
  );
});

test("auditors can read tariff rows but cannot open the write form", async () => {
  render(<BillingRatesManager readOnly />);
  expect(
    await screen.findByRole("button", { name: "配置 视频生成 · 768P" }),
  ).toBeDisabled();
  expect(
    screen.queryByRole("checkbox", { name: "启用用户扣分" }),
  ).not.toBeInTheDocument();
});

test("cost credits use the current exchange ratio while sale credits stay unchanged", async () => {
  vi.mocked(adminRead).mockResolvedValue({
    ...catalog,
    pricing: { version: 9, points_per_yuan: 200 },
  });
  render(<BillingRatesManager />);
  fireEvent.click(
    await screen.findByRole("button", { name: "配置 视频生成 · 768P" }),
  );
  fireEvent.change(screen.getByLabelText("成本（积分 / 秒，留空待核对）"), {
    target: { value: "25" },
  });
  fireEvent.change(screen.getByLabelText("售价（积分 / 秒）"), {
    target: { value: "40" },
  });
  fireEvent.click(screen.getByRole("button", { name: "确认并保存" }));
  await waitFor(() =>
    expect(adminWrite).toHaveBeenCalledWith(
      "/api/control/billing/tariff",
      expect.objectContaining({
        expected_pricing_version: 9,
        tariff: expect.objectContaining({
          unit_credits: "40",
          unit_cost_fen: "12.5",
        }),
      }),
      expect.any(String),
      expect.any(String),
      expect.any(String),
      "PUT",
    ),
  );
});

test("keeps infrastructure and internal quality services out of the configuration table", async () => {
  vi.mocked(adminRead).mockResolvedValue({
    pricing: catalog.pricing,
    services: [
      ...catalog.services,
      ...["cos", "zpay", "quality_inspection", "analysis_repair"].map(
        (service) => ({
          ...catalog.services[0],
          service,
          name: service,
          customer_charge_allowed: false,
        }),
      ),
    ],
  });
  render(<BillingRatesManager />);
  await screen.findByRole("button", { name: "配置 视频生成 · 768P" });
  for (const name of ["cos", "zpay", "quality_inspection", "analysis_repair"])
    expect(screen.queryByText(name)).not.toBeInTheDocument();
});

test("saving unchanged credit displays preserves the original sub-cent cost", async () => {
  vi.mocked(adminRead).mockResolvedValue({
    pricing: { version: 8, points_per_yuan: 3 },
    services: [
      {
        ...catalog.services[0],
        tariff: {
          ...catalog.services[0].tariff,
          unit_credits: "1",
          unit_cost_fen: "0.000001",
          enabled: true,
        },
      },
    ],
  });
  render(<BillingRatesManager />);
  await screen.findByText("0.00000003");
  fireEvent.click(screen.getByRole("button", { name: "配置 视频生成 · 768P" }));
  expect(screen.getByLabelText("售价（积分 / 秒）")).toHaveValue("1");
  fireEvent.click(screen.getByRole("button", { name: "确认并保存" }));
  await waitFor(() =>
    expect(adminWrite).toHaveBeenCalledWith(
      "/api/control/billing/tariff",
      expect.objectContaining({
        expected_pricing_version: 8,
        tariff: expect.objectContaining({
          unit_credits: "1",
          unit_cost_fen: "0.000001",
        }),
      }),
      expect.any(String),
      expect.any(String),
      expect.any(String),
      "PUT",
    ),
  );
});
