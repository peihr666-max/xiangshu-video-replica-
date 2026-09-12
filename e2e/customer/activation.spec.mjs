import { expect, test } from "@playwright/test";
import {
  enterCustomerAccount,
  openCustomerDevices,
} from "./workspace-navigation.mjs";

test("public workbench gates operations and six-character registration returns home", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page
      .getByRole("main")
      .getByRole("button", { name: "登录 / 注册", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "用户档案", exact: true }).click();
  await expect(page.getByRole("heading", { name: "登录账号" })).toBeVisible();
  await enterCustomerAccount(page, "e2e_account_first");
});

test("registered account exposes its device and the real wallet entry", async ({
  page,
}) => {
  await enterCustomerAccount(page, "e2e_account_devices");
  const devices = await openCustomerDevices(page);
  await expect(
    devices.getByText("设备数量不限，多台设备可以同时在线，互不影响。"),
  ).toBeVisible();
  await expect(devices.getByText("当前设备", { exact: true })).toBeVisible();
  await expect(devices.getByRole("button", { name: "充值秒数" })).toBeVisible();
});
