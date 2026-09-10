# CW-013 — 收敛客户根入口与路由恢复（删除内部 App 兜底）

## 任务信息（§14 模板）

| 字段 | 值 |
| --- | --- |
| 任务/工作包 | CW-013（W2）统一客户入口与路由恢复；DoD：客户矩阵全部走同一状态机、内部兜底删除（非仅隐藏内部登录文案）、补刷新/后退/深链接/历史 hash 与配对返回矩阵、交接独立管理入口 |
| Owner / Reviewer | Owner：ZCode 代理（hlong026 会话，2026-09-10）；Reviewer：独立 CodeReview 子代理（结论见 §5，通过/无阻塞 M，m1/m2/m3+n1/n2 逐条实质修复）+ PR review |
| 分支 / 基线 SHA | `feat/customer-v3-cw013-unify-customer-entry-routing`；基线 `pei666/main@f1ba4ec`（CW-010 PR#1 合并后） |
| 上游规格段落 | V3 清单 §18 CW-013 行；V3 剩余任务清单行 247–261（收敛正式客户入口 + 承接 CW-008 回归锁） |
| 改动文件 | 2 文件 +174/−31：`client/src/RootApp.tsx`（生产改动，路由三段式收敛 + 删 `import { App }` 与 `<App/>` 兜底 + docstring）、`client/src/RootApp.test.tsx`（收敛矩阵：删旧"根→内部 App"用例，新增 6 块 = 8 case + 评审加固 m1 的 it.each×2） |
| 失败测试或回归锁定 | RED：改前 `8 failed \| 13 passed`（8 个新收敛用例因根→内部 App 失败）；GREEN：改后 `RootApp.test.tsx 23 passed`。CW-008 回归基线（既有 12 客户路由用例）全绿不动 |
| 实现结果 | §2 交付明细；§3 验证结果；§4 路由状态矩阵 |
| 验证命令与通过数 | client 门（Node 24.14.1）：`biome check .` 0 error exit 0；`tsc -b` exit 0；`vitest run` 79 文件 **1278 passed**（基线 1276 + 评审 m1 新增 2）；`verify_no_secrets.sh` exit 0。详见 §3 |
| 证据层级 | AUTOMATED_VERIFIED（client 门全绿 + 路由状态矩阵逐路径推演等价 + 身份隔离真断言经独立复核；纯前端路由收敛，无 staging/真实链路依赖） |
| 安全与可观测性 | 无密钥/凭据/token 进入代码或测试；secrets 扫描通过；身份隔离红线固化为客户入口结构上不可达内部访问令牌壳与 `/api/auth/me` 探针 |
| 迁移与回滚 | 纯前端路由收敛，server/ 零触碰，无数据库/迁移改动；回滚 = revert 本分支，恢复内部 App 兜底 |
| 外部授权记录 | 无（不涉及真实 ZPay/付费 Provider/生产 COS/发码/灰度/公网发布） |
| 未测试项 | server 全量 pytest、`npm run check:tauri`（cargo）、`npm run build`、`npm audit`、客户浏览器 E2E —— 均**只在 CI 三门禁执行**；本任务 server 零触碰，故 server 回归交 CI（同 CW-009/010/012 模式） |
| Lore 提交 SHA | 本 PR squash 后回填 |

## 2. 交付明细（对照 CW-013 DoD：收敛客户根入口 + 内部兜底删除）

| 现状问题 | 实现 |
| --- | --- |
| 普通浏览器根路径 `/` 与任意未匹配路由仍落到内部 `<App/>` 兜底（内部访问令牌壳 + `/api/auth/me` 探针），客户矩阵存在"内部 App"与"客户状态机"两个入口 | RootApp 路由由四分支「① `/review/v1.4`(DEV) ② `isTauriRuntime()\|\|/customer*` → CustomerShell ③ `/admin*` → AdminApp ④ else → 内部 `<App/>`」收敛为三分支「① `/review/v1.4`(DEV) → ReviewWorkspace ② `!isTauriRuntime() && /admin*` → AdminApp ③ else → `<CustomerShell>`」 |
| 内部访问令牌壳曾是浏览器根入口的合法落点（仅靠文案区分内部/客户，不满足"结构性不可达"） | 删除 `import { App } from "./App"` 与 `<App/>` 渲染兜底 → 客户入口子树结构上无法反向拉起内部 App；`App.tsx` 本体保留（CW-041 才退役内部入口，本任务不删文件，仅解除 RootApp 引用） |
| 刷新/后退/深链接/历史 hash 与配对返回缺可执行回归 | 新增收敛矩阵 6 块（§4）；RootApp 默认参数 `path = window.location.pathname` 每次全新挂载真读 `window.location`，刷新/深链接天然生效；历史 `/#characters`（pathname 仍为 `/`）不再重入内部 App |
| `/admin` 需交接为独立管理入口且桌面客户构建不得有 admin 通道 | `/admin*` 仅在 `!isTauriRuntime()` 时进 AdminApp；Tauri 运行时任意路径（含 `/admin`）恒落客户状态机（改前靠 `isTauriRuntime()` 首条短路，改后靠 `!isTauriRuntime()` 守卫，行为等价，见 §4） |

## 3. 验证结果（本地，Node 24.14.1 对齐 CI；client 门不碰 PG）

| 验证 | 命令/场景 | 结果 |
| --- | --- | --- |
| RED（改前） | `vitest run src/RootApp.test.tsx`（未改 RootApp.tsx） | **8 failed \| 13 passed**（8 收敛用例因根→内部 App 失败；既有客户用例全绿） |
| GREEN（改后定向） | `vitest run src/RootApp.test.tsx` | **23 passed**（21 收敛矩阵 + 2 评审 m1 新增 Tauri×admin） |
| 类型门 | `tsc -b`（`npm run check` 承载） | **exit 0**，无类型错误 |
| Lint/格式门 | `biome check .` | **0 error，exit 0**（新增用例经 `biome check --write` 权威归位后复检通过） |
| 单测门（全量） | `vitest run` | **79 文件 / 1278 passed**（基线 f1ba4ec 为 client 1276；本任务净 +2 = 删 1 旧根兜底用例 + 加 10 收敛 case + 评审 m1 加 2，零回归） |
| secrets 门 | `bash scripts/verify_no_secrets.sh` | **exit 0**，No hardcoded secrets |
| server 零触碰 | `git diff --name-only \| grep '^server/'` | **空** → server pytest/ruff/mypy/tauri/build 交 CI |

环境说明：本机默认 Node v20 无法跑 vitest（`--no-experimental-webstorage` 为 Node 22+ flag），改用 nvm Node v24.14.1（对齐 CI Node 24）后全绿；与 CW-013 改动无关。

## 4. 路由状态矩阵（CW-013 核心：改前/改后逐路径等价，除显式目标）

| 路径 | 运行时 | 改前落点 | 改后落点 | 是否 CW-013 目标变更 |
| --- | --- | --- | --- | --- |
| `/review/v1.4` | 任意（DEV） | ReviewWorkspace | ReviewWorkspace | 否（等价） |
| `/review/v1.4` | 任意（prod，ReviewWorkspace=null） | 内部 `<App/>` | CustomerShell | 是（归"未匹配路由"收敛） |
| `/admin`、`/admin/*` | 浏览器 | AdminApp | AdminApp | 否（等价） |
| `/admin`、`/admin/*` | Tauri | CustomerShell（`isTauriRuntime()` 短路） | CustomerShell（`!isTauriRuntime()` 守卫失败落默认） | 否（等价，守卫形态变化） |
| `/customer`、`/customer/pairing` | 浏览器 & Tauri | CustomerShell（`startInPairing` 同式） | CustomerShell（`startInPairing` 同式） | 否（等价） |
| `/`（根） | 浏览器 | **内部 `<App/>`** | **CustomerShell** | **是（CW-013 核心目标）** |
| `/`、任意路径 | Tauri | CustomerShell | CustomerShell | 否（等价） |
| 任意未匹配路径（`/internal`、`/login`、`/some/unknown/route`） | 浏览器 | **内部 `<App/>`** | **CustomerShell** | **是（不绕过认证收敛）** |

收敛矩阵 6 块（`RootApp.test.tsx`）：① 根收敛到客户状态机 + 内部兜底删除（断言激活标题 / 无内部令牌 label / 无运营管理后台 / 无 `/api/auth/me`）；② 未认证零私有业务调用（收窄白名单：仅 activate/enroll/login 为 pre-auth，wallet/profile/devices GET 激活前被调即失败）；③ 历史 `/#characters` 不重入内部 App；④ `it.each(["/","/customer","/customer/pairing"])` 全新挂载真读 `window.location`（刷新/深链接）+ 无 `/api/auth/me`；⑤ 后退到根（unmount+remount 模拟硬导航）仍客户；⑥ `it.each` 未匹配路由不绕过认证。评审 m1 追加 `it.each(["/admin","/admin/funds"])` Tauri 下仍客户（固化"桌面无 admin 通道"红线）。

## 5. 独立复核

独立 CodeReview 子代理对本次 diff（2 文件）做行为等价性/身份隔离红线/内部兜底真删除/测试质量/注释准确性五项复核，**结论"通过"，无阻塞 M**，并已核查确认 10 项无问题（逐路径行为等价矩阵、内部兜底 import+JSX 双删除且全仓无反向引用、身份隔离双证据链真断言、历史 hash pathname 语义、深链接真读 window.location、afterEach 三件套清理、isTauriRuntime 同步纯读安全、startInPairing 表达式前后一致、docstring 技术准确、AdminApp 内部 pushState 不跨 pathname）。

评审次要项逐条实质修复（本 PR 内，非流程噪音跳过）：

- **m1**（应修）：`/admin` 在 Tauri 下未被显式测试 → 新增 `it.each(["/admin","/admin/funds"])` Tauri 用例，断言仍进客户激活屏且无"运营管理后台"，把"桌面无 admin 通道"红线固化为可执行断言。**已修，GREEN 验证（+2 用例）**。
- **m2**（应修）：Test 4（刷新/深链接 it.each）遗漏 `/api/auth/me` 断言，与其他身份隔离用例强度不对称 → 捕获 fetchMock 并追加探针断言。**已修**。
- **m3**（应修）：Test 2"非客户域"过滤 `!url.includes("/api/customer/")` 偏宽，会掩盖"激活前预取 wallet/profile/devices"回归 → 收窄为 pre-auth 白名单（activate/enroll/login），使登录后私有接口在激活前被调即失败。**已修**。
- **n1**（可选）：docstring 首句"every browser path"与 `/admin`、`/review/v1.4` 例外有张力 → 改为"every non-admin browser path"并前置列出两个例外。**已修**。
- **n2**（可选）：Test 5 用 unmount+remount 模拟后退缺注释说明 → 补注释"RootApp 不订阅 popstate；跨路径后退是硬导航/整页重载"。**已修**。

修复后重跑：`RootApp.test.tsx 23 passed` + client 全量 `79 文件 / 1278 passed` + biome/tsc/secrets 全绿。

## 6. 签认记录

| 角色 | 结论 | 日期 |
| --- | --- | --- |
| 前端负责人 | 待签认 | — |
| 集成负责人 | 待签认 | — |
