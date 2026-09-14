import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { getCustomerPricing, updateCustomerPricing } from "../api.admin";
import { CustomerPricingManager } from "./CustomerPricingManager";

vi.mock("../api.admin", () => ({
  getCustomerPricing: vi.fn(),
  updateCustomerPricing: vi.fn(),
}));

test("saves exchange and discount without implicitly publishing feature tariffs", async () => {
  const payload = {
    version: 2,
    configured: true,
    config: { video_768p: 3, video_2k: 7, oral: 11, points_per_yuan: 100 },
    prices: [],
    recharge_rounding: "向下取整",
  };
  vi.mocked(getCustomerPricing).mockResolvedValue(payload);
  vi.mocked(updateCustomerPricing).mockResolvedValue({
    ...payload,
    version: 3,
  });
  render(<CustomerPricingManager />);
  await waitFor(() =>
    expect(screen.getByLabelText("每 1 元充值获得积分")).toHaveValue(100),
  );
  fireEvent.change(screen.getByLabelText("每 1 元充值获得积分"), {
    target: { value: "5" },
  });
  expect(screen.queryByLabelText("调整原因")).not.toBeInTheDocument();
  expect(screen.getAllByRole("spinbutton")).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "保存充值换算" }));
  await waitFor(() =>
    expect(updateCustomerPricing).toHaveBeenCalledWith(
      {
        points_per_yuan: 5,
        discount_basis_points: 10000,
        consumption_rounding: "ceil",
      },
      2,
      "更新充值积分兑换比例",
      expect.any(String),
    ),
  );
});
