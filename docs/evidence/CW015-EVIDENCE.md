# CW-015 — 统一客户 API 地址、凭据和错误恢复（移除内部身份与 loopback 回退）

## 任务信息（§14 模板）

| 字段 | 值 |
| --- | --- |
| 任务/工作包 | CW-015（W2）统一客户 API 地址、凭据和错误恢复；DoD：移除 `workspaceAccessToken` 内部 token 优先、正式客户 loopback fallback 与开发身份路径，接入唯一地址来源；客户构建缺地址/断网/会话过期·被替换/429 均有确定提示与重试；旧组件卸载不清理新 session；直传·下载 COS 或 Provider 时不携客户 Bearer；敏感凭据不进 Web Storage/日志/前端制品 |
| Owner / Reviewer | Owner：ZCode 代理（hlong026 会话，2026-09-10）；Reviewer：独立 CodeReview 子代理（结论见 §5，**无阻塞 M / 无重大 m**，可选 n1 已实质补齐）+ PR review |
| 分支 / 基线 SHA | `feat/customer-v3-cw015-single-customer-api-base`；基线 `pei666/main@7c58718`（CW-013 PR#2 合并后） |
| 上游规格段落 | V3 清单 §18 CW-015 行；V3 剩余任务清单行 278–292（移除内部 token 优先 + loopback fallback + 开发身份，接入唯一地址来源；承接 CW-008/011 回归锁） |
| 改动文件 | 5 文件 +81/−60：`client/src/api.ts`（9 hunks 生产改动，+31/−31）、`client/src/api.test.ts`（缺地址 throw + 4 处 X-Dev-User-Id 负向锁 + 上传客户 token 优先 + n1 集成 fail-closed）、`client/src/test/setup.ts`（全局 `VITE_API_BASE_URL` env stub +7/−1）、`client/src/App.test.tsx`（上传文案 ripple +1/−1）、`.env.example`（`VITE_DEV_USER_ID`→`VITE_API_BASE_URL` 文档块 +5/−2） |
| 失败测试或回归锁定 | RED：改前 `api.test.ts 7 failed \| 90 passed`（缺地址 throw、4 处 X-Dev-User-Id 不发、上传客户 token 优先未满足）；GREEN：改后 client 全量 **79 文件 / 1279 passed**（基线 1278 + n1 新增 1），串行 `--no-file-parallelism` 确定性全绿。CW-008 回归基线（既有客户 API/origin/上传/会话生命周期用例）全绿不动 |
| 实现结果 | §2 交付明细；§3 验证结果；§4 (A)/(B) 决策与验收底线矩阵 |
| 验证命令与通过数 | client 门（Node 24.14.1）：`biome check .` 0 error exit 0；`tsc -b` exit 0；`vitest run`（串行）79 文件 **1279 passed**；`verify_no_secrets.sh` exit 0；server 零触碰。详见 §3 |
| 证据层级 | AUTOMATED_VERIFIED（client 门全绿 + 缺地址 fail-closed 单元与集成双路径真断言 + 身份唯一性由 CW-013 结构性不可达链保证 + 上传 Bearer origin 边界真断言；纯前端地址/凭据收敛，无 staging/真实链路依赖） |
| 安全与可观测性 | 无密钥/凭据/token 进入代码、测试、日志、Web Storage 或前端制品；secrets 扫描通过；开发身份（`X-Dev-User-Id`/`VITE_DEV_USER_ID`）生产路径彻底移除，仅存负向断言测试锁死"不再发送"；缺唯一地址来源 fail-closed（抛错），不再静默回退 loopback origin |
| 迁移与回滚 | 纯前端地址/凭据收敛，`server/` 零触碰，无数据库/迁移改动；构建期守卫 `scripts/require_customer_api_base.mjs`（CW-011 已接入）未改，与本任务运行时 fail-closed 互补；回滚 = revert 本分支，恢复 loopback 默认与内部 token 优先 |
| 外部授权记录 | 无（不涉及真实 ZPay/付费 Provider/生产 COS/发码/灰度/公网发布） |
| 未测试项 | server 全量 pytest、`npm run check:tauri`（cargo）、`npm run build`、`npm audit`、客户浏览器 E2E —— 均**只在 CI 三门禁执行**；本任务 server 零触碰，故 server 回归交 CI（同 CW-009/010/012/013 模式） |
| Lore 提交 SHA | 本 PR squash 后回填 |

## 2. 交付明细（对照 CW-015 DoD：三移除 + 唯一地址来源接入）

| 现状问题（改前） | 实现（改后） |
| --- | --- |
| `workspaceAccessToken()` = `internalAccessToken ?? customerSessionToken`，**内部 token 优先**：错误恢复可能回退到内部身份 | 翻转为 `customerSessionToken ?? internalAccessToken`（方案 A，见 §4）：客户会话 token 优先，内部 token 降为兜底；客户构建里内部 App 壳不可达（CW-013）→ `internalAccessToken` 恒 null → 错误恢复永不回退内部身份 |
| `resolveApiBaseUrl` 缺配置时静默回退 `DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"`（loopback），部署到正式客户会指向 localhost | 删除 `DEFAULT_API_BASE_URL`；缺地址改为 `throw new Error("API base URL is required (VITE_API_BASE_URL)")`（fail-closed）；唯一地址来源 = `VITE_API_BASE_URL`，构建期由 `require_customer_api_base.mjs` 校验为非 loopback HTTPS 源，运行时 fail-closed 与之互补 |
| 开发身份路径：`getDevelopmentUserId()` 读 `import.meta.env.VITE_DEV_USER_ID`（DEV 下返回 employee_1），`requestApi`/`uploadStorageObject` 在无 Bearer 时挂 `X-Dev-User-Id` 合成身份 | 删除 `getDevelopmentUserId()` 函数 + `requestApi`/`uploadStorageObject` 两处 `X-Dev-User-Id` 分支；正式客户请求永不携合成开发身份，认证只走 workspace Bearer |
| 上传 URL 判定 `isLocalApiUploadUrl`（按 loopback 字面匹配）→ 决定是否携 Bearer | 重命名 `isApiUploadUrl`，改为 `new URL(url).origin === new URL(apiBaseUrl()).origin` 按唯一地址来源的 origin 比对：只有 API origin 上传携客户 Bearer，COS/Provider 直传（不同 origin）不携；`apiBaseUrl()` 抛错时 catch 返回 false（fail-safe：宁可不带也不误带） |
| 上传失败文案"无法连接本地服务"（假设地址必为 localhost） | 改为"无法连接服务"（地址不再必然 loopback，语义更准）；App.test.tsx 同步 ripple |

**核实无需改动（复用现有，避免范围渗漏）**：
- `client/src/api.admin.ts`：Cookie 认证（`credentials:"include"`），复用同一 `resolveApiBaseUrl`（import 自 api.ts），继承 fail-closed。
- `client/src/customer/useCustomerSession.ts`：grep `internal`/`loopback`/`dev` = 0 命中。
- `scripts/require_customer_api_base.mjs`：构建期守卫已存在（CW-011 接入），已被 `server/tests/test_customer_ha_smoke.py` 覆盖；本任务只做运行时 fail-closed 与之互补。
- `internalAccessToken` 的彻底退役属 CW-041，不在本任务范围（方案 A 保留其为内部壳兜底）。

## 3. 验证结果（本地，Node 24.14.1 对齐 CI；client 门不碰 PG）

| 验证 | 命令/场景 | 结果 |
| --- | --- | --- |
| RED（改前） | `vitest run src/api.test.ts`（未改 api.ts） | **7 failed \| 90 passed**（缺地址 throw、4 处 X-Dev-User-Id 不发、上传客户 token 优先未满足） |
| GREEN（定向） | `vitest run src/api.test.ts`（改后 + n1） | **98 passed**（含 n1 集成 fail-closed 用例） |
| 类型门 | `tsc -b`（`npm run check` 承载） | **exit 0**，无类型错误；`getDevelopmentUserId`/`DEFAULT_API_BASE_URL`/`isLocalApiUploadUrl` 全部调用点已同步删除/重命名（tsconfig 无 `noUnusedLocals`，已人工核零残留） |
| Lint/格式门 | `biome check .` | **0 error，exit 0**（新增用例经 `biome check --write` 权威归位后复检 "No fixes applied"） |
| 单测门（全量·串行） | `vitest run --no-file-parallelism` | **79 文件 / 1279 passed**（基线 7c58718 为 1278；本任务净 +1 = n1 集成用例；零回归） |
| secrets 门 | `bash scripts/verify_no_secrets.sh` | **exit 0**，No hardcoded secrets detected in runtime contract surface |
| server 零触碰 | `git diff --name-only \| grep '^server/'` | **空** → server pytest/ruff/mypy/tauri/build 交 CI |
| 开发身份残留 | `grep -rn 'getDevelopmentUserId\|DEFAULT_API_BASE_URL\|isLocalApiUploadUrl' client/src`（排除 generated） | **生产代码 0 命中**；`X-Dev-User-Id`/`VITE_DEV_USER_ID` 仅存于负向断言测试（stub env 后断言 header `.toBe(false)`）与 1 条注释，及 `outputs/` 冻结审计快照（历史产物，非活代码） |

**并行 flake 说明（与本 diff 无关）**：默认并行 `vitest run` 偶发 `src/admin/AuditEventsPage.test.tsx` / `src/admin/GenerationRecordsPage.test.tsx` 各 1 例失败（不同跑次失败子集不同：2→1），隔离重跑 15/15 通过、串行全量 1279/1279 通过。二者走 `api.admin.ts` Cookie 路径，不在本 diff 触及范围，属 jsdom 并行 worker CPU 争用下既有异步渲染 flake（CodeReview 子代理独立跑亦复现并判定为既有 flake）。以串行 `--no-file-parallelism` 全绿为确定性证据。

环境说明：本机默认 Node v20 无法跑 vitest（`--no-experimental-webstorage` 为 Node 22+ flag），改用 nvm Node v24.14.1（对齐 CI Node 24）后全绿；与 CW-015 改动无关。

## 4. (A)/(B) 设计决策与保留验收底线矩阵

### 4.1 关键决策：`workspaceAccessToken` 采用方案 (A)

| 方案 | 形态 | 取舍 |
| --- | --- | --- |
| **(A) 采用** | `customerSessionToken ?? internalAccessToken`（翻转优先级，客户 token 优先，内部保留兜底） | ①字面精确匹配 V3"移除内部 token **优先**"——移除的是 `??` 优先序而非删 token；②身份唯一性由 CW-013 结构性保证（客户构建内部壳不可达→`setInternalAccessToken` 永不调用→`internalAccessToken` 恒 null→`?? internalAccessToken` 等于 `?? null`）；③保留现有测试（`App.test.tsx:465` 断言 `Bearer internal-user-token` 在内部壳车道仍绿）；④避免 (B) 的 `internalAccessToken` 只写死状态与 CW-041 范围渗漏 |
| (B) 未采用（旧 WIP 参考） | `customerSessionToken`（只留客户，内部彻底摘除） | 属过度移除：把 CW-041 的活提前干；且旧 WIP 未同步更新 `App.test.tsx:465`，该分支跑起来会 RED——这是不盲抄 WIP、改选 (A) 的直接动因之一 |

### 4.2 保留验收底线矩阵（V3 DoD 逐条 → 实现 → 锁定测试）

| 验收底线 | 实现 | 锁定测试 |
| --- | --- | --- |
| 缺服务地址有确定提示 + fail-closed | `resolveApiBaseUrl` 缺地址 `throw`；`apiBaseUrl()` 在 fetch 前抛错 | `api.test.ts` "throws an error when no API base URL is configured"（直接单元）+ n1 "fails closed at runtime when VITE_API_BASE_URL is missing"（经 `getHealth()→requestJson()→apiBaseUrl()` 集成路径，断言 rejects `API base URL is required`） |
| 网络断开有确定提示与重试 | 上传 onerror 文案"无法连接服务"（保留全角标点） | `App.test.tsx:2044` 断言 `/上传参考视频失败（无法连接服务，请确认服务已启动）/` |
| 会话过期/被替换有确定提示 | `emitWorkspaceSessionEnded` + `CUSTOMER_SESSION_EXPIRED/REPLACED/REVOKED_EVENT`（未改动，继承） | 既有会话生命周期用例全绿 |
| 429 有确定提示与重试 | `requestApi` 错误分类（未改动，继承） | 既有错误恢复用例全绿 |
| 旧组件卸载不清理新 session | `customerOwnerAtStart = internalAccessToken === null ? customerSessionOwner : null` owner 守卫**保留不动**（客户构建 internalAccessToken 恒 null→等于 customerSessionOwner，语义无操作） | 既有迟到响应隔离用例全绿 |
| 直传/下载 COS 或 Provider 不携客户 Bearer | `isApiUploadUrl` 按 `apiBaseUrl()` origin 比对，仅 API origin 携 Bearer | `api.test.ts` 上传用例：COS/Provider（不同 origin）断言不带 Authorization；API origin 断言带 `Bearer customer-session-token-1`（客户 token 优先） |
| 敏感凭据不进 Web Storage/日志/前端制品 | dev 身份移除；无 token 落 Storage；secrets 门 | `verify_no_secrets.sh` exit 0 + X-Dev-User-Id 负向断言测试 |

## 5. 独立复核

独立 CodeReview 子代理对本次 diff（5 文件）做 fail-closed 无绕过 / (A) 客户 token 优先 / dev 身份彻底移除 / `isApiUploadUrl` origin 边界 fail-safe / 凭据零泄漏 / 测试真断言六项复核，**结论"无阻塞项（无 M / 无 m）"**，AUTOMATED_VERIFIED 层级达成。逐项确认：

1. `resolveApiBaseUrl` fail-closed 三条分支无 loopback 绕过（显式配置直返、production+https 返回页面自身 https origin 非 loopback、tauri/非生产 http 落 throw）；抛错消息子串与 `.toThrow("API base URL is required")` 一致。
2. (A) 客户 token 优先正确落地；会话结束清空 `customerSessionToken` 后 `workspaceAccessToken()` 返回 null → 无 Authorization → 正确走 401，不渗漏内部身份；未做反悔建议。
3. `getDevelopmentUserId` 已删，全仓 `client/` grep 0 残留调用点；两处 `X-Dev-User-Id` 分支均移除；tsc 无未用符号告警。
4. `isApiUploadUrl` origin 比对正确，COS/Provider 不携 Bearer；`apiBaseUrl()` 抛错 catch 返回 false 为 fail-safe 正确方向。
5. `.env.example` 无 `VITE_DEV_USER_ID` 残留；无敏感值进 Storage/日志/制品。
6. 测试为真断言（`.toThrow`/`.has(...).toBe(false)`/`Bearer customer-session-token-1`）；`setup.ts` 全局 stub 是维持既有硬编码 URL 测试所必需，且缺地址用例直接调 `resolveApiBaseUrl(undefined,...)` 绕过 stub 真实验证抛错，未被掩盖。

评审可选次要项逐条处置（本 PR 内实质修复，非流程噪音跳过）：

- **n1**（可选·已补）：fail-closed 此前仅由 `resolveApiBaseUrl(undefined,...)` 直接单测覆盖，缺"运行时 env 缺失 → 真实 API 调用抛错"的集成路径 → 新增 `api.test.ts` 集成用例：`vi.stubEnv("VITE_API_BASE_URL","")` 后断言 `getHealth()` rejects `API base URL is required`（经 `getHealth()→requestJson()→apiBaseUrl()` 真实调用链，且 `requestJson` 只有 `try/finally` 无 catch，抛错原样冒泡、在 fetch 发出前触发）。**已修，GREEN 验证（api.test.ts 98 passed，全量 +1 → 1279）**。

修复后重跑：`api.test.ts 98 passed` + client 全量串行 `79 文件 / 1279 passed` + biome/tsc/secrets 全绿。

## 6. 签认记录

| 角色 | 结论 | 日期 |
| --- | --- | --- |
| 前端负责人 | 待签认 | — |
| 集成负责人 | 待签认 | — |
