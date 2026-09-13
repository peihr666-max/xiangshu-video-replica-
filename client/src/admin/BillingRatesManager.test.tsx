import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { adminRead, adminWrite } from "../api.admin";
import { BillingRatesManager } from "./BillingRatesManager";

vi.mock("../api.admin", () => ({ adminRead: vi.fn(), adminWrite: vi.fn() }));
const catalog = {
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
  fireEvent.change(screen.getByLabelText("成本（分 / 秒，留空待核对）"), {
    target: { value: "0.000125" },
  });
  fireEvent.change(screen.getByLabelText("调整原因"), {
    target: { value: "录入供应商成本" },
  });
  fireEvent.click(screen.getByRole("button", { name: "确认并保存" }));
  await waitFor(() =>
    expect(adminWrite).toHaveBeenCalledWith(
      "/api/control/billing/tariff",
      {
        service: "video_768p",
        expected_version: 0,
        tariff: {
          enabled: false,
          unit_credits: null,
          unit_cost_fen: "0.000125",
          unit_rounding: "ceil",
        },
      },
      "录入供应商成本",
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
  fireEvent.change(screen.getByLabelText("调整原因"), {
    target: { value: "发布逐秒售价" },
  });
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
