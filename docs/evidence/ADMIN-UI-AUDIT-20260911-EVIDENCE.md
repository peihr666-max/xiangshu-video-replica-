# ADMIN-UI-AUDIT-20260911 证据

> 维护任务（非 CW 编号）：管理端页面综合排查 + 登录界面改造。
> 基线 `origin/main@a093f61`；worktree `.worktrees/ADMIN-UI-AUDIT-20260911`；分支 `chore/admin-ui-audit-20260911`。
> 服务端零改动（control_auth.py / admin_auth_routes.py / control_routes.py 仅只读走查）。

## 1. 交付物

| 类型 | 文件 |
| --- | --- |
| 综合分析（PM + 后端视角，前后端联动） | `docs/管理端页面综合排查分析-2026-09-11.md` |
| P0 修复：管理端入口补基础样式表 | `client/src/admin-main.tsx`（`import "./styles.css"` + 契约注释） |
| P0 防回归契约 | `client/src/entryContract.test.ts`（"管理端入口必须引入共享基础样式表 styles.css"） |
| 登录门重构 | `client/src/AdminApp.tsx`（认证三 phase）、`client/src/admin/admin-login.css`（新增） |
| 登录交互测试 | `client/src/AdminApp.test.tsx`（新增 4 用例） |
| 视觉对照 | `docs/evidence/admin-ui-audit-20260911/login-before-a093f61.png` / `login-after-fixed.png` |

## 2. P0：管理端产线包缺基础样式表（先红后绿）

**根因**：`styles.css`（`.admin-shell` 壳层布局、`.admin-panel`/`.admin-form`、全局 input/button、`--admin-*` 设计令牌定义）此前只被客户壳 `App.tsx` 导入；CW-019 拆分双入口后，管理端入口链（admin.html → admin-main.tsx → AdminApp → admin/*.css）不含它。

**产物取证**（基线 a093f61 实测重建 `dist-admin`，同一构建命令 `vite build --config vite.admin.config.ts`）：

| 断言 | 修复前 | 修复后 |
| --- | --- | --- |
| 管理包 CSS 体积 | 16.57 kB（gzip 3.75） | 146.11 kB（gzip 27.27） |
| `.admin-shell{` 基础定义 | 0 次 | 2 次 |
| `--admin-bg` / `--admin-text:` 令牌定义 | 0 次 / 0 次 | 2 次 / 1 次 |
| `.admin-login__*` 登录门样式 | —（新增） | 25 处命中 |

**视觉证据**：`login-before-a093f61.png`（main 现状：白底裸控件、完全无布局）→ `login-after-fixed.png`（品牌区 + 表单卡 + 聚焦环 + 密码可见性切换 + 金色主按钮）。截图环境：vite dev + headless Chrome 1440×900；before 图中的 "API base URL is required" 为本地无 `VITE_API_BASE_URL` 的预期提示，与回归无关。

**RED→GREEN 说明**：AdminApp 4 个新用例首跑即 RED（断言失败详情见 vitest 输出：上下文变化错误呈现英文原文、无"正在登录…"态、无显示/隐藏密码按钮）。`entryContract` 新用例首跑因本任务正则未转义 `/` 导致整文件 PARSE_ERROR（测试自身语法错误，非有效 RED）；修正正则后按构造验证：`git show HEAD:client/src/admin-main.tsx` 不含 `import "./styles.css"`，断言必然失败，随后实现转绿。

## 3. 登录门改造（P1）

- **防重复提交**：`authPending` 状态机（login/exchange/recover 三态），提交中禁用按钮 + "正在登录…"。对齐后端 `admin_auth_routes._spend_admin_password_budget` 的 IP+账号双维度计数——双击不再白烧限流预算。
- **错误全量中文化**：`adminActivationErrorMessage` 的 `overrides` 参数补 `RATE_LIMITED`→"登录尝试过于频繁，请稍后再试。"、`ADMIN_SESSION_CONTEXT_CHANGED`→"检测到登录环境变化（网络或浏览器），请重新登录。"。仅作用于 AdminApp，不改 `api.admin.ts` 全局映射。
- **密码可见性切换**：`aria-pressed` + `aria-label`（显示密码/隐藏密码），输入框 type 随动。
- **聚焦管理**：biome 禁 `autoFocus`，改 ref + effect，按 authPhase 聚焦各表单首字段。
- **布局**：左品牌价值区（logo、标题、职责说明、三条安全语义点）+ 右表单卡；≤900px 折叠单列并隐藏要点列表。全部复用 `--admin-*` 令牌，无第三套视觉。
- **可访问性**：label `htmlFor`/`id` 显式关联；错误保留 `role="alert"`（PageBanner）；`autocomplete` 语义保留（username/current-password/new-password/off）。
- 所有既有测试选择器（`管理员账号`/`管理员密码`/`登录后台`/`首次设置或找回密码` 等）零改动兼容。

## 4. 验证记录（本机 macOS，Node 24）

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| RED | `npx vitest run src/entryContract.test.ts src/AdminApp.test.tsx`（实现前） | 4 failed / 19 passed（entryContract 文件级 PARSE_ERROR，见 §2 说明） |
| GREEN（专项） | 同上（实现后） | **31 passed**（2 文件） |
| 客户端全量门 | `npm run check --workspace client`（biome + tsc -b + vitest run） | **80 文件 1301 passed**（基线 1296 + 新增 5，零回归） |
| 管理包重建 | `npx vite build --config vite.admin.config.ts` | §2 表格修复后列 |
| 客户包排除红线 | `npx vite build` + `node scripts/verify_customer_bundle.mjs` | ✅ 禁止命中 0；阳性对照 6/6 自证有效 |
| 秘密扫描 | 随 CI Secret scan；本机未单独跑 | 以 PR CI 为准 |

## 5. 边界与未测试项

- 服务端零改动：不触发 pytest 义务；`cargo test`/`npm audit`/浏览器 E2E/Windows NSIS 按 path-filter 由 CI 判定，未记为已验证。
- 视觉验证为 macOS headless Chrome 单分辨率（1440×900）；≤900px 折叠布局由 CSS 媒体查询承载，未逐档截图。
- P2 遗留（不在本任务范围）：会话上下文绑定对办公网络友好性的取舍（安全决策待用户拍板）、客户项目列表分页（独立任务）、恢复凭据输入的格式提示打磨。
- 证据等级：`CODE_PRESENT` + 本机 `AUTOMATED_VERIFIED`（客户端段）；最终三门禁以 PR CI 为准。
