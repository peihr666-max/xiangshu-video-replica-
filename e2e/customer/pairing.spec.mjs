import { chromium, expect, test } from "@playwright/test";

const CODE_C = "XS04-XYZ2345-6789ABC-DEFGHJK-MNPQRST";
const DEVICE_B_NAME = "E2E Device B";

test("second-device pairing: enroll waits, primary approves, polling completes binding", async () => {
  const browser = await chromium.launch();
  const deviceA = await browser.newContext();
  const deviceB = await browser.newContext();
  const pageA = await deviceA.newPage();
  const pageB = await deviceB.newPage();

  // Device A activates a fresh code.
  await pageA.goto("/customer");
  await pageA.getByLabel("激活码").fill(CODE_C);
  await pageA.getByLabel("设备名称").fill("E2E Device A");
  await pageA.getByRole("button", { name: "激活并进入工作台" }).click();
  await expect(pageA.getByRole("button", { name: "打开个人中心" })).toBeVisible(
    {
      timeout: 20_000,
    },
  );

  // Device B enrolls on the pairing entry with its own fingerprint.
  await pageB.goto("/customer/pairing");
  await pageB.getByLabel("激活码").fill(CODE_C);
  await pageB.getByLabel("设备名称").fill(DEVICE_B_NAME);
  await pageB.getByRole("button", { name: "提交配对申请" }).click();

  // Device B parks on the waiting screen.
  await expect(
    pageB.getByRole("heading", { name: "等待主设备审批" }),
  ).toBeVisible();

  // Device A approves the pending pairing in its device view.
  await pageA.getByRole("button", { name: "打开个人中心" }).click();
  await pageA.getByRole("button", { name: "设备管理" }).click();
  await expect(pageA.getByText("新的设备绑定请求")).toBeVisible({
    timeout: 20_000,
  });
  await pageA.getByRole("button", { name: "确认绑定" }).click();
  await expect(pageA.getByText("新的设备绑定请求")).toBeHidden({
    timeout: 20_000,
  });

  // Device B automatically consumes the approved request via its waiting
  // poll, then saves the 201 device credential without another form submit.
  await expect(pageB.getByRole("heading", { name: "配对成功" })).toBeVisible({
    timeout: 20_000,
  });
  // The saved device credential must be usable. Device A is still online,
  // so device B explicitly confirms the session switch before entering.
  await pageB.getByRole("button", { name: "进入客户工作区" }).click();
  const conflict = pageB.getByRole("dialog", { name: "检测到会话冲突" });
  await expect(conflict).toBeVisible();
  await conflict.getByRole("button", { name: "切换到本设备" }).click();
  await expect(pageB.getByRole("button", { name: "打开个人中心" })).toBeVisible(
    {
      timeout: 20_000,
    },
  );
  await pageB.getByRole("button", { name: "打开个人中心" }).click();
  await pageB.getByRole("button", { name: "设备管理" }).click();
  await expect(
    pageB
      .getByRole("region", { name: "设备管理" })
      .getByText(DEVICE_B_NAME, { exact: true }),
  ).toBeVisible();

  await browser.close();
});
