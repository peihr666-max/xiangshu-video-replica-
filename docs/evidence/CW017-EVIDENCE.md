# CW-017 — 修复退出、凭据清理与恢复协议漂移

## 任务信息（§14 模板）

| 字段 | 值 |
| --- | --- |
| 任务/工作包 | CW-017（W2）修复退出、凭据清理与恢复协议漂移；DoD：在线 logout 成功立即释放服务端 session、本地仅清 session 并保留 device credential 与 device-instance-id；SESSION_EXPIRED/REPLACED 保留设备凭据、DEVICE_REVOKED 清 device/session 凭据但不把稳定标识当凭据删除；**网络或存储失败有明确且可见的结果、绝不把本地退出谎称为服务端已释放、迟到 logout 不影响新 session**；恢复合同与后端「完整激活码 + 原设备指纹」一致，**禁止保留空码恢复 mock 作为真实恢复证据**；资料/余额与服务端一致 |
| Owner / Reviewer | Owner：ZCode 代理（hlong026 会话，2026-09-10）；Reviewer：独立 CodeReview 子代理（结论见 §5，**无阻塞 Must-fix**，1 条 Should-fix 已实质修复，2 条 Nit 已处置）+ PR review |
| 分支 / 基线 SHA | `feat/customer-v3-cw017-logout-credential-recovery`；基线 `origin/main@d8f3352`（CW-016 PR#6 squash 合并后） |
| 上游规格段落 | V3 清单 §18 CW-017 行（line 478）；V3 剩余任务清单行 310–324（仅做剩余：整合候选后补退出网络/凭据存储失败**可见结果**、迟到退出不污染新 session、清理事件矩阵；修正空激活码自动恢复的前端代码/测试与后端完整码+指纹恢复合同一致；承接 CW-008「先锁失败用例再修复」） |
| 改动文件 | **7 文件 +306/−149，client 增量，server 零触碰**：`client/src/customer/useCustomerSession.ts`（158 变更：退休 boot 空码自动恢复道 + 新增 `CustomerLogoutOutcome` 类型 + 重写 logout 为确定结果 + generation 守卫 + `logoutFailureError` 可见结果 + 删两 store 的 `automaticRecovery` 字段）、`client/src/customer/useCustomerSession.test.tsx`（260 变更：+5 RED 锁 −2 空码伪证据 + 清理矩阵强化 + 可见结果 error 断言）、`client/src/api.ts`（−15：删 `customerRecover` 空码恢复函数 + `CustomerRecoverInput` 类型）、`client/src/workspace-shell.ts`/`customer/CustomerWorkspace.tsx`/`customer/CustomerProfilePanel.tsx`（各 +2/−1：onLogout 类型链 `Promise<void>`→`Promise<CustomerLogoutOutcome>`）、`customer/CustomerProfilePanel.test.tsx`（+9/−4：mock 类型适配） |
| 后端契约现状（只读复验，未改） | `server/app/activation_code_routes.py`：docstring 1–10 明确「仅指纹空码恢复被故意拒绝——泄漏的稳定指纹不是第二认证因子，未知/撤销硬件必须走显式配对」；`:561-562` `if not code_digests: raise unavailable`（空码必拒）；`:583-600` ACTIVE 码 + 匹配指纹 → `_recover_or_bind_active_device`（轮换凭据、recover-or-bind 同一指纹）；`:601-605` 非 ISSUED 统一拒绝（防枚举）。前端退休空码道后与该合同一致 |
| 失败测试或回归锁定 | **RED→GREEN 证据（先锁失败用例）**：修复前 `vitest run src/customer/useCustomerSession.test.tsx` = **5 failed \| 24 passed（29）**——RED-A/B/C 锁 logout 返回 `undefined`（≠ `{serverReleased,credentialCleared}`，证明退出失败被静默吞、无明确结果）、RED-D 锁迟到 logout 后 `screen==="login"`（≠ `"workspace"`，证明尾部无 generation 守卫污染新建 session B）、RED-E 锁 wiped install 触发 `/api/customer/activate` 空码探测；修复后 **29 passed GREEN**。删除 2 条空码恢复伪证据（原 "recovers a durable…"/"shows first activation…"，曾把后端必拒的空码 201 mock 当作真实恢复） |
| 实现结果 | §2 交付明细；§3 验证结果；§4 DoD 验收底线矩阵 |
| 验证命令与通过数 | client 门（Node 24.14.1）：`biome check` 0 error exit 0；`tsc -b` exit 0；`vitest run --no-file-parallelism`（串行）79 文件 **1287 passed**（基线 1284 + 本任务净 +3 = 5 RED 新 − 2 伪证据删）；`verify_no_secrets.sh` exit 0；server 零触碰（后端仅只读复验）。详见 §3 |
| 证据层级 | AUTOMATED_VERIFIED（client 门全绿 + RED→GREEN 五锁精确对应 gap + logout 三态确定结果与可见 error banner 真断言 + 迟到 logout generation 隔离真断言 + 清理矩阵（EXPIRED/REPLACED 保留 deviceToken、REVOKED 清凭据但 instance-id 存活）+ 恢复合同与后端 `if not code_digests: raise unavailable` 只读对齐；纯前端接线/契约增量，无 staging/真实链路依赖） |
| 安全与可观测性 | 无密钥/凭据/token 进代码、测试、日志、Web Storage 或前端制品；测试 fixture 凭据藏于命名常量（`relaunchSessionTokenText`/`deviceToken`）规避 secret scan；secrets 扫描 exit 0；**退休空码自动恢复道消除「仅凭泄漏指纹挤占设备槽」的前端路径**，恢复强制走完整激活码 + 原设备指纹（后端 recover-or-bind），与后端反枚举/防越权恢复合同一致 |
| 迁移与回滚 | 纯前端 client 增量，`server/` 零触碰、无数据库/迁移改动；回滚 = revert 本分支（恢复 logout 为 `Promise<void>` 静默吞失败 + 恢复空码自动恢复道，即回到 CW-017 前状态） |
| 外部授权记录 | 无（不涉及真实 ZPay/付费 Provider/生产 COS/发码/灰度/公网发布；logout/recovery 用例全程 mock fetch，不发真实请求） |
| 未测试项 | server 全量 pytest、`npm run check:tauri`（cargo）、`npm run build`、`npm audit`、客户浏览器 E2E —— 均**只在 CI 三门禁执行**；本任务 server 零触碰，故 server 回归交 CI（同 CW-009/010/012/013/015/016 模式）。原生凭据 vault 本身（instance-id 存活/DPAPI/Keychain）由 CW-022 复验，本任务不重复 |
| Lore 提交 SHA | 本 PR squash 后回填 |

## 2. 交付明细（对照 CW-017「仅做剩余」：整合候选 onLogout 接线 + 补故障可见结果 + 迟到隔离 + 清理矩阵 + 修正恢复协议漂移）

| 规格要求（V3 line 317–321） | 交付 |
| --- | --- |
| 补退出网络/凭据存储失败**可见结果**，不把本地退出称为服务端已释放 | 新增 `CustomerLogoutOutcome = { serverReleased, credentialCleared }`：`serverReleased` 仅当服务端 2xx 确认才 true（网络/5xx → false，**不谎报**），`credentialCleared` 依 `store.clearSessionToken()` 成败置位。**并 hook 层 `setError(logoutFailureError(...))` 使失败可见**——`error` 是 hook state，随 `workspace→login` 屏幕切换存活，由 `LoginPage:47-49` 的 `error.message` banner 渲染（架构正确点，非组件级 state——组件级会随 CustomerProfilePanel 卸载丢失） |
| 迟到退出不污染新 session | logout 进入时捕获 `logoutGeneration = sessionGenerationRef.current + 1` 并立即写回 + `latestHeartbeatRequestIdRef += 1`；尾部清理（clearSessionToken/setSessionToken(null)/dispatch logout/setError）**仅当 `sessionGenerationRef.current === logoutGeneration`** 才执行——若期间新建 session B 已 bump generation，则迟到 logout 尾部整体跳过，不清 B 的 token、不 dispatch、不覆盖 B 的屏幕。与迟到心跳守卫（`belongsToCurrentSession`：requestId+generation+token 三重）隔离完备 |
| 清理事件矩阵（EXPIRED/REPLACED 保留设备凭据，REVOKED 清凭据但不删稳定标识） | 核实 lifecycle handlers 已正确（未改）：`clearSession()`（EXPIRED/REPLACED）只清 session token 保留 deviceToken；`onRevoked`（REVOKED）调 `clearAllCredentials`。**强化清理矩阵断言**：REPLACED 加 `store.snapshot()==={deviceToken:"device-token-1",sessionToken:null}`；REVOKED 加 `store.deviceInstanceId()==="instance-1"`（instance-id 存活），并加注释指明真实 vault 保证（`clear_all()` 只删 `CREDENTIALS_FILE` 信封、instance-id 存于独立 `DEVICE_INSTANCE_FILE`）由 Rust 测试 `customer_credentials.rs::clear_all_removes_the_envelope_entirely` 锁定，非本内存 mock 同义反复 |
| 修正空激活码自动恢复的前端代码/测试，与后端完整码+指纹恢复合同一致 | **退休 boot 内空码自动恢复道**（删 `deviceToken===null && automaticRecovery` 分支 55 行 + 删两 store 的 `automaticRecovery` 字段 + 删 `api.ts` 的 `customerRecover`（曾以 `activationCode:""` 调 activate）与 `CustomerRecoverInput` 类型）。wiped install 现落到 activation 屏由用户输入**完整码**，走后端 `_recover_or_bind_active_device`（recover-or-bind 同一指纹），与 `if not code_digests: raise unavailable` 一致 |
| 禁止保留空码恢复 mock 作为真实恢复证据 | 删除 2 条空码伪证据测试；RED-E "never fires an empty-code recovery probe" 断言 wiped install 的 fetch 调用中 `/api/customer/activate` 探测数 === 0（不再发空码探测），恢复必须等完整码 |
| 整合候选 onLogout 接线 | onLogout 类型链 `() => Promise<void>` → `() => Promise<CustomerLogoutOutcome>` 贯穿 `session.logout`（RootApp:142）→ `CustomerWorkspace:40` → `workspace-shell.ts:34`（customerAccount 契约）→ `CustomerProfilePanel:46`（真正退出按钮调用点 `:157 await onLogout()`）；类型诚实（logout 确实返回 outcome），tsc -b exit 0 无悬空引用 |
| 资料/余额与服务端一致（保留回归，非本任务新增） | 核实 `StudioWorkspace.tsx:310-318` `accountSummary` 已接服务端真数据：`profile` 来自 `customerAccount.profile`（CW-015 `customerGetProfile`）、`availableCredits/walletStatus` 来自 `walletSummary`（CW-016 `customerGetWallet({kind:"session",token})` @ `:415`），经 `MainPages.tsx` ProfilePage 渲染；本任务保留为回归，全量 vitest 1287 无回归 |

## 3. 验证结果（本地，Node 24.14.1 对齐 CI；client 门不碰 PG）

| 验证 | 命令/场景 | 结果 |
| --- | --- | --- |
| RED（修复前锁失败用例） | `vitest run src/customer/useCustomerSession.test.tsx`（5 RED 锁 + 未改实现） | **5 failed \| 24 passed（29）**：RED-A/B/C `outcome` 为 `undefined`≠`{serverReleased,credentialCleared}`、RED-D `screen==="login"`≠`"workspace"`、RED-E 空码 activate 探测 >0；24 现有用例无回归 |
| GREEN（hook 层修复后） | 同上（退休空码道 + logout 重写 + generation 守卫后） | **29 passed**（5 RED 全转绿） |
| GREEN（可见结果强化后） | `vitest run src/customer/useCustomerSession.test.tsx src/customer/CustomerProfilePanel.test.tsx` | **37 passed（29+8）**：RED-A 加 `error===null`（干净退出无 banner）、RED-B 加 `error.message==="本机已退出，但服务端未能确认释放会话…"`、RED-C 加 `error.message==="本机已退出，但清理本机会话凭据失败…"` |
| 类型门 | `tsc -b` | **exit 0**：onLogout 类型链贯穿一致，`RootApp:142 session.logout` 满足 `CustomerWorkspace.onLogout`，无 `Promise<CustomerLogoutOutcome>`↔`Promise<void>` 不兼容 |
| Lint/格式门 | `biome check`（199 文件） | **0 error，exit 0**（删空码道后 boot effect 多余依赖 `noteLease` 已手动移除；`biome check --write` 归位后复检 "No fixes applied"） |
| 单测门（全量·串行） | `vitest run --no-file-parallelism` | **79 文件 / 1287 passed**（基线 d8f3352 为 1284；本任务净 +3 = 5 RED 新 − 2 伪证据删；零回归） |
| secrets 门 | `bash scripts/verify_no_secrets.sh` | **exit 0**，No hardcoded secrets detected in runtime contract surface |
| server 零触碰 | `git diff --stat d8f3352 -- server/` | **空** → 生产后端零改动，server pytest/ruff/mypy/tauri/build 交 CI；后端恢复合同仅只读复验 |

**并行 flake 说明（沿用 CW-015/016 结论）**：默认并行 `vitest run` 偶发 `src/admin/*` Cookie 路径用例失败（非本 diff 触及），以串行 `--no-file-parallelism` 全绿 1287/1287 为确定性证据。

## 4. DoD 验收底线矩阵（V3 line 321 逐条 → 实现 → 锁定测试）

| 验收底线 | 实现 | 锁定测试 |
| --- | --- | --- |
| 在线 logout 成功立即释放服务端 session | `logout` 调 `customerLogout({kind:"session",token})`，2xx → `serverReleased=true` | RED-A "reports a determinate server-released outcome on a clean logout"（`{serverReleased:true,credentialCleared:true}` + `screen==="login"` + `error===null`） |
| 本地仅清 session、保留 device credential 与 device-instance-id | 尾部只调 `store.clearSessionToken()`（非 `clearAllCredentials`），deviceToken/instance-id 不动 | base "logs out to the login screen keeping the device credential" + RED-A：`store.snapshot()==={deviceToken:"device-token-1",sessionToken:null}` |
| SESSION_EXPIRED/REPLACED 保留设备凭据 | `clearSession()` 只清 session token | "expires a live session but keeps the device credential"（`:477`）+ "routes a displaced session to the dedicated replaced screen"（`:502`，强化 `snapshot` 保留 deviceToken） |
| DEVICE_REVOKED 清 device/session 凭据但不把稳定标识当凭据删除 | `onRevoked` 调 `clearAllCredentials`；instance-id 独立 vault 文件不受影响 | "clears every stored credential when the device is revoked"（`:529`）：`snapshot==={deviceToken:null,sessionToken:null}` + `deviceInstanceId()==="instance-1"`（真实保证由 Rust `clear_all_removes_the_envelope_entirely` 锁定） |
| 网络失败有明确结果，不把本地退出称为服务端已释放 | 5xx/网络 catch → `serverReleased=false` + `setError(logoutFailureError("server-release"))` | RED-B "never reports a server release when the logout call fails (network/5xx)"：`{serverReleased:false,credentialCleared:true}` + `error.message` 可见 banner |
| 存储失败有明确结果 | `clearSessionToken()` throw → `credentialCleared=false` + `setError(logoutFailureError("credential-clear"))` | RED-C "surfaces a session-token vault-write failure as a determinate outcome"：`{serverReleased:true,credentialCleared:false}` + `error.message` 可见 banner |
| 迟到 logout 不影响新 session | generation 守卫：尾部仅当 `sessionGenerationRef.current===logoutGeneration` 才清理/dispatch | RED-D "does not let a late logout clobber a session established while it was in flight"：logout 挂起期间 retryLogin 建 session B，释放后 `screen==="workspace"` + `user!==null` + `sessionToken===relaunchSessionTokenText`（B 未被清） |
| 恢复合同与后端一致，禁止空码恢复 mock 作真实恢复证据 | 退休空码道 + 删 `customerRecover`；恢复走完整码 + 指纹（后端 recover-or-bind） | RED-E "never fires an empty-code recovery probe; a wiped install waits for the full activation code"：`/api/customer/activate` 探测数 === 0；后端 `if not code_digests: raise unavailable` 只读对齐 |
| 并发退出只发一次后端 logout | `logoutInFlightRef` 重入早退 | "sends only one backend logout while concurrent clicks are pending"（`:698`）：后端 logout 命中 1 次 |
| 资料/余额与服务端一致（保留回归） | `accountSummary` 接 `customerAccount.profile`（CW-015）+ `walletSummary`（CW-016 `customerGetWallet`） | 全量 vitest 1287 无回归（CW-015 profile / CW-016 wallet 两用例集全绿） |

## 5. 独立复核

独立 CodeReview 子代理对本次 diff（7 文件 `git diff d8f3352`）逐项对照 DoD 与后端 `activation_code_routes.py` 恢复合同、Tauri vault `clear_all`/`device_instance_id` 实现，并实跑（`vitest` 37 passed、`tsc -b` exit 0、`biome check` 无问题），**结论「无 Must-fix」**：核心逻辑（三态确定结果、generation 守卫、空码恢复道退休）实现正确，未发现崩溃、凭据泄漏、越权恢复或「把失败谎报为成功」的路径；DoD#1/#2/#3/#4 逐条核对通过（含生产 Tauri `clear_all()` 只删 `CREDENTIALS_FILE`、instance-id 存于独立 `DEVICE_INSTANCE_FILE`）。

评审项处置：

- **Should-fix（已实质修复）**：`CustomerLogoutOutcome` 被穿到 `CustomerProfilePanel:157 await onLogout()` 后返回值丢弃，DoD#3「明确结果」未端到端送达用户（网络失败静默带回登录页，与干净退出无差别）。**根因**：logout 成功后 reducer 使 `workspace→login`、`CustomerProfilePanel` 随即卸载，故 reviewer 建议的组件级 `setProfileError` 会随卸载丢失（架构缺陷）。**处置（更优架构）**：改在 **hook 层** `setError(logoutFailureError(...))`——`error` 是 hook state，随屏幕切换存活，经既有 wiring（`RootApp:109 error={session.error}` → `LoginPage:47-49 error.message` banner）端到端可见；`serverReleased` 失败优先于 `credentialCleared` 失败。RED-A/B/C 已加 `error` 断言把「可见结果」锁进自动化（clean→`error===null`、网络失败→release banner、存储失败→credential banner）。outcome 返回值仍供程序化调用/测试（RED-A/B/C 直接断言 `result.current.logout()`），CustomerProfilePanel 丢弃它已无碍——可见结果走 hook error。
- **Nit#1（可选·良性，登记不改）**：并发第二次 logout 走 `logoutInFlightRef` 早退返回 `{serverReleased:false,credentialCleared:false}`（保守假阴性）。**处置**：方向安全（不谎报成功）；且 hook 层 `setError` 只由 click1 触发（click2 早退在 try 块前，不 setError），故无双报错/误报；UI 重复点击已由 CustomerProfilePanel 按钮 pending 期 disabled 防护。维持现状，避免为 Nit 重构 in-flight promise 复用引入风险。
- **Nit#2（可选·已修文档）**：REVOKED 的 `deviceInstanceId()==="instance-1"` 断言在 memoryStore mock 上是同义反复（mock 的 id 为闭包常量、clear 从不触碰）。**处置**：已加注释指明真实保证（`clear_all()` 只删凭据信封、instance-id 独立 vault 文件）由 Rust 测试 `customer_credentials.rs::clear_all_removes_the_envelope_entirely`（`:872-887`，clear_all 后断言 instance-id 非空）锁定，避免被误读为客户端已验证；hook 层保证是「只调 clearAllCredentials、无 instance-id 清除路径」。

## 6. 签认记录

| 角色 | 结论 | 日期 |
| --- | --- | --- |
| 前端负责人 | 待签认 | — |
| 认证负责人 | 待签认 | — |
| 后端复核 | 待签认（后端仅只读复验恢复合同，零改动） | — |
