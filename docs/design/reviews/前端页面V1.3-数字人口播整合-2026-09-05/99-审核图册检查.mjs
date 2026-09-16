import { readFile, readdir, stat } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const root = path.dirname(fileURLToPath(import.meta.url));
const manifestPath = path.join(root, "99-页面清单.json");
const albumPath = path.join(root, "00-打开审核.html");
const errors = [];

function check(condition, message) {
  if (!condition) errors.push(message);
}

function pngSize(buffer) {
  const signature = "89504e470d0a1a0a";
  if (buffer.length < 24 || buffer.subarray(0, 8).toString("hex") !== signature) return null;
  return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) };
}

const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
const pages = manifest.pages ?? [];
const expectedCount = manifest.plannedPages;
check(Number.isInteger(expectedCount) && expectedCount > 0, "plannedPages 必须是正整数");
check(pages.length === expectedCount, `页面清单应有 ${expectedCount} 项，当前为 ${pages.length} 项`);
check(new Set(pages.map((page) => page.id)).size === pages.length, "页面 id 存在重复");
check(new Set(pages.map((page) => page.file)).size === pages.length, "图片文件名存在重复");

let album = "";
try {
  album = await readFile(albumPath, "utf8");
} catch {
  errors.push("缺少 00-打开审核.html");
}

const reviewChains = {
  "copy-to-oral": ["08", "20E", "20C", "20D", "12"],
  "person-to-replace": ["10", "15B", "04A", "04", "03"],
};
for (const [chain, ids] of Object.entries(reviewChains)) {
  check(album.includes(`data-chain="${chain}"`), `图册缺少业务链审核入口：${chain}`);
  for (const id of ids) check(pages.some((page) => page.id === id), `业务链 ${chain} 引用了清单外页面：${id}`);
}

for (const page of pages) {
  check(typeof page.id === "string" && page.id.length > 0, "发现空页面 id");
  check(typeof page.name === "string" && page.name.length > 0, `${page.id || "未知页面"} 缺少名称`);
  check(typeof page.nav === "string" && page.nav.length > 0, `${page.id || "未知页面"} 缺少模块 nav`);
  check(album.includes(`data-id="${page.id}"`), `图册未引用页面 id：${page.id}`);
  check(album.includes(page.file), `图册未引用图片：${page.file}`);

  const imagePath = path.join(root, page.file);
  try {
    const image = await readFile(imagePath);
    const size = pngSize(image);
    check(Boolean(size), `${page.file} 不是有效 PNG`);
    if (size) check(size.width >= 1200 && size.height >= 700, `${page.file} 尺寸过小：${size.width}×${size.height}`);
  } catch {
    errors.push(`缺少图片：${page.file}`);
  }
}

const secretPatterns = [
  /(?:api[_-]?key|secret|token|password)\s*[:=]\s*["'][^"']{8,}["']/i,
  /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/,
  /sk-[A-Za-z0-9_-]{20,}/,
  /AKIA[0-9A-Z]{16}/,
];
const textFiles = (await readdir(root)).filter((name) => /\.(?:html|md|json|mjs|css|js)$/i.test(name));
for (const name of textFiles) {
  const filePath = path.join(root, name);
  if (!(await stat(filePath)).isFile()) continue;
  const text = await readFile(filePath, "utf8");
  for (const pattern of secretPatterns) check(!pattern.test(text), `${name} 疑似包含密钥或凭证`);
}

if (errors.length) {
  console.error(`审核图册检查失败（${errors.length} 项）：`);
  for (const error of errors) console.error(`- ${error}`);
  process.exit(1);
}

console.log(`审核图册检查通过：${pages.length} 个页面、图片文件与 HTML 引用完整，未发现疑似密钥。`);
