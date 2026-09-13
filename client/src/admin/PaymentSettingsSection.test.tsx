import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ControlSettings } from "../api";

import { PaymentSettingsSection } from "./PaymentSettingsSection";

vi.mock("../api.admin", () => ({
  getCustomerPaymentSettings: vi.fn(),
  updateCustomerPaymentZPay: vi.fn(),
  updateCustomerPaymentBilling: vi.fn(),
}));

import {
  getCustomerPaymentSettings,
  updateCustomerPaymentBilling,
  updateCustomerPaymentZPay,
} from "../api.admin";

const controlSettings: ControlSettings = {
  providers: {} as ControlSettings["providers"],
  runtime: {} as ControlSettings["runtime"],
  billing: {
    internal_base_unit_price_fen: 10,
    charged_unit_price_fen: 10,
    oral_unit_price_fen: 20,
    min_recharge_fen: 5000,
    recharge_step_fen: 1000,
  },
  zpay: {
    provider: "zpay" as const,
    configured: true,
    config: {
      pid: "pid-1",
      key: "已配置（掩码）",
      enabled_channels: "alipay,wxpay",
    },
  },
  deployment: {
    gateway_url: "https://pay.example.com",
    notify_url: "https://api.example.com/notify",
    return_url: "https://api.example.com/return",
  },
};

describe("PaymentSettingsSection (A-01/A-03)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getCustomerPaymentSettings).mockResolvedValue(controlSettings);
  });

  it("加载完成后渲染两个表单且提交按钮可用", async () => {
    render(<PaymentSettingsSection />);
    await waitFor(() =>
      expect(vi.mocked(getCustomerPaymentSettings)).toHaveBeenCalled(),
    );
    expect(
      screen.getByRole("button", { name: "保存 ZPay 设置" }),
    ).toBeEnabled();
    expect(screen.getByRole("button", { name: "保存内部价格" })).toBeEnabled();
  });

  it("计费配置加载完成前禁止提交内部价格（A-03：占位 0 不得写进生产）", async () => {
    vi.mocked(getCustomerPaymentSettings).mockReturnValue(
      new Promise(() => {
        /* 挂起，模拟加载中 */
      }),
    );
    render(<PaymentSettingsSection />);
    expect(screen.getByRole("button", { name: "保存内部价格" })).toBeDisabled();
  });

  it("保存 ZPay 走 reasonAndAck 确认且原因透传审计", async () => {
    vi.mocked(updateCustomerPaymentZPay).mockResolvedValue(
      controlSettings.zpay,
    );
    render(<PaymentSettingsSection />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "保存 ZPay 设置" }),
      ).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "保存 ZPay 设置" }));

    const dialog = screen.getByRole("dialog", { name: "保存 ZPay 支付设置" });
    expect(dialog).toBeInTheDocument();

    // 原因必填
    fireEvent.click(screen.getByRole("button", { name: "确认保存 ZPay 设置" }));
    expect(screen.getByText("请填写操作原因")).toBeInTheDocument();
    expect(vi.mocked(updateCustomerPaymentZPay)).not.toHaveBeenCalled();

    // 勾选"我已知晓"（reasonAndAck）
    fireEvent.click(screen.getByLabelText("我已知晓该操作的影响"));
    fireEvent.change(screen.getByPlaceholderText("请填写可审计的操作原因"), {
      target: { value: "商户换绑，工单 IT-42" },
    });
    fireEvent.click(screen.getByRole("button", { name: "确认保存 ZPay 设置" }));

    await waitFor(() =>
      expect(vi.mocked(updateCustomerPaymentZPay)).toHaveBeenCalledTimes(1),
    );
    expect(vi.mocked(updateCustomerPaymentZPay)).toHaveBeenCalledWith(
      { pid: "pid-1", key: "", enabled_channels: ["alipay", "wxpay"] },
      "商户换绑，工单 IT-42",
      expect.any(String),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "保存 ZPay 支付设置" }),
      ).not.toBeInTheDocument(),
    );
    expect(await screen.findByText("ZPay 设置已保存。")).toBeInTheDocument();
  });

  it("保存内部价格走 reason 确认且原因透传审计", async () => {
    vi.mocked(updateCustomerPaymentBilling).mockResolvedValue(
      controlSettings.billing,
    );
    render(<PaymentSettingsSection />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "保存内部价格" }),
      ).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "保存内部价格" }));

    expect(
      screen.getByRole("dialog", { name: "保存内部价格" }),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("请填写可审计的操作原因"), {
      target: { value: "季度价格复核" },
    });
    fireEvent.click(screen.getByRole("button", { name: "确认保存内部价格" }));

    await waitFor(() =>
      expect(vi.mocked(updateCustomerPaymentBilling)).toHaveBeenCalledTimes(1),
    );
    expect(vi.mocked(updateCustomerPaymentBilling)).toHaveBeenCalledWith(
      {
        internal_base_unit_price_fen: 10,
        oral_unit_price_fen: 20,
        min_recharge_fen: 5000,
        recharge_step_fen: 1000,
      },
      "季度价格复核",
      expect.any(String),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "保存内部价格" }),
      ).not.toBeInTheDocument(),
    );
    expect(await screen.findByText("内部价格已保存。")).toBeInTheDocument();
  });

  it("确认框内失败时错误留在对话框内且不关闭", async () => {
    vi.mocked(updateCustomerPaymentZPay).mockRejectedValue(
      new Error("网关校验失败"),
    );
    render(<PaymentSettingsSection />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "保存 ZPay 设置" }),
      ).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "保存 ZPay 设置" }));
    fireEvent.change(screen.getByPlaceholderText("请填写可审计的操作原因"), {
      target: { value: "测试原因" },
    });
    fireEvent.click(screen.getByLabelText("我已知晓该操作的影响"));
    fireEvent.click(screen.getByRole("button", { name: "确认保存 ZPay 设置" }));

    await waitFor(() =>
      expect(screen.getByText("网关校验失败")).toBeInTheDocument(),
    );
    // 失败后对话框仍在，可修正后重试
    expect(
      screen.getByRole("dialog", { name: "保存 ZPay 支付设置" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认保存 ZPay 设置" }));
    await waitFor(() =>
      expect(vi.mocked(updateCustomerPaymentZPay)).toHaveBeenCalledTimes(2),
    );
  });
});
