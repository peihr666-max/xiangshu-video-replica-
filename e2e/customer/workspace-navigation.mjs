import { expect } from "@playwright/test";

export async function waitForCustomerWorkspace(page) {
  const profileEntry = page.getByRole("button", {
    name: "用户档案",
    exact: true,
  });
  await expect(profileEntry).toBeVisible({ timeout: 20_000 });
  return profileEntry;
}

export async function openCustomerCenter(page) {
  const profileEntry = await waitForCustomerWorkspace(page);
  const summary = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/customer/center-summary") &&
      response.request().method() === "GET",
  );
  await profileEntry.click();
  expect((await summary).status()).toBe(200);
  await expect(
    page.getByRole("heading", { name: "用户中心", exact: true }),
  ).toBeVisible();
  // Only the first visit creates a default credential. Wait for its lifecycle
  // request before dismissing the one-time display, without reading its value.
  await expect(page.locator(".uc-tokens tbody tr")).toHaveCount(1);
  await expect(page.getByText("自动生成", { exact: true })).toBeVisible();
  const saved = page.getByRole("button", { name: "已保存，关闭", exact: true });
  if (await saved.isVisible()) await saved.click();
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
