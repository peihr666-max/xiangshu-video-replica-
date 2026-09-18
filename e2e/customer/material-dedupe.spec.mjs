import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { enterCustomerAccount } from "./workspace-navigation.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..", "..");
// Same venv layout rule as setup-backend.mjs (Windows uses Scripts/python.exe).
const python =
  process.platform === "win32"
    ? path.join(repoRoot, "server", ".venv", "Scripts", "python.exe")
    : path.join(repoRoot, "server", ".venv", "bin", "python");

const TEST_PG_URL =
  process.env.TEST_POSTGRESQL_URL ??
  "postgresql://testuser:testpass@localhost:5433/customer_v3_test";
const E2E_DSN = `${TEST_PG_URL.slice(0, TEST_PG_URL.lastIndexOf("/"))}/customer_e2e`;

/** 参考生视频（r2v_enabled）由 runtime_settings.h3_extended_modes_enabled 派生。
 *  只在本用例内打开，避免改动共享 seed 影响其他 e2e。 */
function enableExtendedModes() {
  execFileSync(
    python,
    [
      "-c",
      `
import psycopg
with psycopg.connect("${E2E_DSN}", autocommit=True) as conn:
    conn.execute(
        "UPDATE runtime_settings SET h3_extended_modes_enabled = TRUE WHERE id = 1"
    )
`,
    ],
    { encoding: "utf8" },
  );
}

/** 1x1 PNG：同一份字节上传两次，第二次必须命中 sha256 去重。
 *  走图片分支可绕开视频/音频的时长探测，直接落在 uploadVideoMaterial 上。 */
const PNG_BYTES = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==",
  "base64",
);

const FILE_NAME = "e2e-dedupe-1x1.png";

function materialCalls(requests) {
  return {
    intents: requests.filter(
      (r) => r.method === "POST" && r.url.endsWith("/upload-intent"),
    ),
    content: requests.filter(
      (r) => r.method === "PUT" && r.url.endsWith("/content"),
    ),
    completes: requests.filter(
      (r) => r.method === "POST" && r.url.endsWith("/complete"),
    ),
  };
}

test("参考生视频页重复上传同一内容不再失败，且第二次不传输字节", async ({
  page,
}) => {
  // 必须在工作区首次挂载前打开：能力探测只在挂载时发起一次，
  // 而后续的 #studio/<page> 跳转是同文档导航，不会重新探测。
  enableExtendedModes();
  await enterCustomerAccount(page, `e2e_dedupe_${Date.now().toString(36)}`);

  const requests = [];
  page.on("request", (request) => {
    const url = request.url();
    if (url.includes("/api/studio/materials/")) {
      requests.push({ method: request.method(), url });
    }
  });

  await page.goto("/#studio/reference");
  const input = page.getByLabel("上传参考素材", { exact: true });
  await expect(input).toBeAttached();
  await expect(input).toBeEnabled();

  // 第一次：全新内容，走真实的三步上传。
  await input.setInputFiles({
    name: FILE_NAME,
    mimeType: "image/png",
    buffer: PNG_BYTES,
  });
  await expect(page.locator(".studio-toast")).toContainText(
    `参考素材「${FILE_NAME}」已上传到素材库。`,
    { timeout: 30_000 },
  );

  const first = materialCalls(requests);
  expect(first.intents).toHaveLength(1);
  expect(first.content).toHaveLength(1);
  expect(first.completes).toHaveLength(1);

  // 等首次提示消失，让第二次的断言不依赖残留文本。
  await expect(page.locator(".studio-toast")).toBeHidden({ timeout: 20_000 });

  // 第二次：字节完全相同，应当复用已登记素材而不是重新传输。
  await input.setInputFiles({
    name: FILE_NAME,
    mimeType: "image/png",
    buffer: PNG_BYTES,
  });
  await expect(page.locator(".studio-toast")).toContainText(
    `参考素材「${FILE_NAME}」已上传到素材库。`,
    { timeout: 30_000 },
  );
  await expect(page.locator(".studio-toast")).not.toContainText("素材上传失败");

  // 去重契约：第二次只查登记表，不再 PUT 字节、也不再 /complete。
  const all = materialCalls(requests);
  expect(all.intents).toHaveLength(2);
  expect(all.content).toHaveLength(1);
  expect(all.completes).toHaveLength(1);
});
