import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { customerGetPricing } from "../api";
import { CustomerPricesPage } from "./CustomerPricesPage";

vi.mock("../api", () => ({ customerGetPricing: vi.fn() }));

test("loads server prices and retries failures without showing a fake price", async () => {
  vi.mocked(customerGetPricing)
    .mockRejectedValueOnce(new Error("暂不可用"))
    .mockResolvedValueOnce({
      version: 3,
      configured: true,
      config: { video_768p: 7, video_2k: 9, oral: 15, points_per_yuan: 100 },
      recharge_rounding: "向下取整",
      prices: [
        {
          subject: "video_768p",
          name: "视频生成",
          specification: "768P",
          unit: "秒",
          unit_credits: 7,
          configurable: true,
        },
      ],
    });
  render(
    <CustomerPricesPage
      credential={async () => ({ kind: "session", token: "test-session" })}
    />,
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("暂不可用");
  expect(screen.queryByText("7 积分 / 秒")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "重新加载价格" }));
  await waitFor(() =>
    expect(screen.getByText("7 积分 / 秒")).toBeInTheDocument(),
  );
  expect(screen.getByText("1 元 = 100 积分")).toBeInTheDocument();
});
