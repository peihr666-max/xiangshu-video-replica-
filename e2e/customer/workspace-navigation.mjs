import { expect } from "@playwright/test";

export async function waitForCustomerWorkspace(page) {
  const profileEntry = page.getByRole("button", {
    name: "用户档案",
    exact: true,
  });
  await expect(profileEntry).toBeVisible({ timeout: 20_000 });
  return profileEntry;
}

export async function openCustomerDevices(page) {
  const profileEntry = await waitForCustomerWorkspace(page);
  await profileEntry.click();
  // V1.4 navigation is two-level:
  //  1) the 设备管理 tab (role=tab) on the 用户档案 page calls openLive("profile"),
  //     mounting CustomerProfilePanel which defaults to the 账号概览 tab;
  //  2) the 设备管理 nav button (role=button) inside that panel switches to the
  //     devices tab, which renders DeviceManagementPage (a region labelled by
  //     its 设备管理 heading).
  await page.getByRole("tab", { name: "设备管理", exact: true }).click();
  await page.getByRole("button", { name: "设备管理", exact: true }).click();
  const devices = page.getByRole("region", { name: "设备管理" });
  await expect(devices).toBeVisible({ timeout: 20_000 });
  return devices;
}

export async function openCustomerWallet(page) {
  const profileEntry = await waitForCustomerWorkspace(page);
  await profileEntry.click();
  // V1.4: the 使用记录 tab opens the wallet page (余额与充值) directly.
  await page.getByRole("tab", { name: "使用记录", exact: true }).click();
}

/** A throwaway account exercises the actual public password entry. */
export async function enterCustomerAccount(page, username, register = true) {
  await page.goto(register ? "/register" : "/login");
  await page.getByLabel("用户名", { exact: true }).fill(username);
  await page.getByLabel("密码", { exact: true }).fill("test-6");
  if (register)
    await page.getByLabel("确认密码", { exact: true }).fill("test-6");
  await page
    .getByRole("button", {
      name: register ? "注册并登录" : "登录",
      exact: true,
    })
    .click();
  await waitForCustomerWorkspace(page);
  await expect(page).toHaveURL(/#studio\/workbench$/);
}
