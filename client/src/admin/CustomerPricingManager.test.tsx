import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { getCustomerPricing, updateCustomerPricing } from "../api.admin";
import { CustomerPricingManager } from "./CustomerPricingManager";

vi.mock("../api.admin", () => ({
  getCustomerPricing: vi.fn(),
  updateCustomerPricing: vi.fn(),
}));

test("saves configured credit prices with version and reason", async () => {
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
    expect(screen.getByLabelText("768P 视频（积分/秒）")).toHaveValue(3),
  );
  fireEvent.change(screen.getByLabelText("768P 视频（积分/秒）"), {
    target: { value: "5" },
  });
  fireEvent.change(screen.getByLabelText("调整原因"), {
    target: { value: "更新客户价格" },
  });
  fireEvent.click(screen.getByLabelText("确认对后续新任务和新充值订单生效"));
  fireEvent.click(screen.getByRole("button", { name: "保存积分价格" }));
  await waitFor(() =>
    expect(updateCustomerPricing).toHaveBeenCalledWith(
      {
        ...payload.config,
        video_768p: 5,
        discount_basis_points: 10000,
        consumption_rounding: "ceil",
      },
      2,
      "更新客户价格",
      expect.any(String),
    ),
  );
});
