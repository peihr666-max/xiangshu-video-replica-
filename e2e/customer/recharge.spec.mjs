import { expect, test } from "@playwright/test";
import {
  enterCustomerAccount,
  openCustomerCenter,
} from "./workspace-navigation.mjs";

test("customer wallet creates a recharge order under the customer session", async ({
  page,
}) => {
  // The provider QR exchange is an external chain and must not reach real
  // ZPay during local integration.  Keep the owned order creation real, then
  // supply only the display-only QR response at the browser boundary.
  await page.route(
    "**/api/customer/recharge-orders/*/payment-code",
    async (route) => {
      const orderNo = new URL(route.request().url()).pathname.split("/").at(-2);
      await route.fulfill({
        contentType: "application/json",
        json: {
          order_no: orderNo,
          amount_fen: 10_000,
          credits: 10,
          qr_image_url:
            "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'/%3E",
          payment_url: "https://payment.invalid/e2e",
        },
        status: 200,
      });
    },
  );

  await enterCustomerAccount(page, "e2e_recharge_account");

  await openCustomerCenter(page);
  const balance = page.locator(".uc-balance strong");
  const creditsBefore = await balance.textContent();
  await page.getByRole("button", { name: "充值积分", exact: true }).click();
  const rechargeDialog = page.getByRole("dialog", { name: "扫码充值" });
  await expect(rechargeDialog).toBeVisible();
  await rechargeDialog.getByRole("button", { name: /^100 元/ }).click();
  await expect(
    rechargeDialog.getByRole("img", { name: "充值支付二维码" }),
  ).toBeVisible();
  await rechargeDialog.getByRole("button", { name: "关闭充值窗口" }).click();
  await page.getByRole("tab", { name: "充值记录", exact: true }).click();
  await expect(page.getByText("待支付", { exact: true })).toBeVisible();
  expect(await balance.textContent()).toBe(creditsBefore);
  page.once("dialog", (dialog) => dialog.accept());
  await page
    .getByRole("button", { name: "关闭待支付订单", exact: true })
    .click();
  await expect(page.getByText("已关闭", { exact: true })).toBeVisible();
  expect(await balance.textContent()).toBe(creditsBefore);
});
