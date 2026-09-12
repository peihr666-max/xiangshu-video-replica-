import { expect, test } from "@playwright/test";
import {
  enterCustomerAccount,
  openCustomerDevices,
} from "./workspace-navigation.mjs";

test("three devices remain online and logout affects only the current device", async ({
  browser,
}, testInfo) => {
  const contexts = await Promise.all(
    Array.from({ length: 3 }, () =>
      browser.newContext({ baseURL: testInfo.project.use.baseURL }),
    ),
  );
  try {
    const pages = await Promise.all(
      contexts.map((context) => context.newPage()),
    );
    for (const [index, page] of pages.entries()) {
      await enterCustomerAccount(page, "e2e_parallel_account", index === 0);
      await expect(
        page.getByRole("dialog", { name: "检测到会话冲突" }),
      ).toHaveCount(0);
    }
    for (const page of pages) {
      const devices = await openCustomerDevices(page);
      await expect(devices.locator(".device-slot-card")).toHaveCount(3);
    }
    await pages[1]
      .getByRole("button", { name: "退出登录", exact: true })
      .click();
    for (const page of [pages[0], pages[2]]) {
      await page.getByRole("button", { name: "账号概览", exact: true }).click();
      await page.getByRole("button", { name: "设备管理", exact: true }).click();
      await expect(
        page.getByRole("region", { name: "设备管理" }),
      ).toBeVisible();
      await expect(page.getByText("会话已失效", { exact: true })).toHaveCount(
        0,
      );
    }
  } finally {
    await Promise.all(contexts.map((context) => context.close()));
  }
});
