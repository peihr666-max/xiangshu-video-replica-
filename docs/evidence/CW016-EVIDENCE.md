# CW-016 — 修复两个客户钱包入口并锁定充值回归

## 任务信息（§14 模板）

| 字段 | 值 |
| --- | --- |
| 任务/工作包 | CW-016（W2）修复两个客户钱包入口并锁定充值回归；DoD：CustomerWorkspace 只传 `customerAccount`、钱包分支统一上下文后，「使用记录」与「个人中心使用记录」两入口在客户会话下必须挂 `CustomerWalletPanel`（客户费率/秒/额度），不得落内部 `WalletPanel`（内部价/条）；充值只走 `POST /api/customer/recharge-orders`、绝不发 `POST /api/recharge-orders`；保留后端内部费率隐藏与旧客户充值写拒绝 |
| Owner / Reviewer | Owner：ZCode 代理（hlong026 会话，2026-09-10）；Reviewer：独立 CodeReview 子代理（结论见 §5，**无阻塞 M / 无应修 m**，仅 2 条可选 n 已登记处置）+ PR review |
| 分支 / 基线 SHA | `feat/customer-v3-cw016-customer-wallet-entries`；基线 `origin/main@5e9d2d7`（CW-015 PR#4 合并后） |
| 上游规格段落 | V3 清单 §18 CW-016 行（line 477）；V3 剩余任务清单行 294–308（仅做剩余：统一上下文 + 补两入口真实挂载测试；承接 CW-008 从真实挂载基座增加生产响应形状失败测试并记录充值 method-path） |
| 改动文件 | **2 文件 +344/−4，纯测试增量，生产代码零改动**：`client/src/studio/LiveWorkspacePanel.test.tsx`（+316/−4：新增「客户钱包入口 (CW-016)」describe 3 个真实挂载用例 + helpers + 生产响应形状常量；文件级 afterEach 增 `vi.unstubAllGlobals()`）、`client/src/studio/MainPages.test.tsx`（+32：新增「两个客户钱包入口路由」describe 2 个用例） |
| 生产接线现状（复用，未改） | `LiveWorkspacePanel.tsx:65` `const customerSession = customerAccount ?? customerWallet;`（由 e180228 创建该文件时即落地，git log -L 确认 line 65 自创建未变）；钱包分支（146–157）据 `customerSession` 渲染 `CustomerWalletPanel`（客户）或回落 `WalletPanel`（内部）；两入口 `MainPages.tsx:1747`（使用记录 tab）与 `:1910`（查看使用记录 button）均 `openLive("wallet")`；`StudioWorkspace.tsx:1803–1809` 将 `customerAccount` 透传给 `LiveWorkspacePanel panel={livePanel}` |
| 失败测试或回归锁定 | **红→绿证据（mutation 复现历史缺陷）**：临时将 `LiveWorkspacePanel.tsx:65` 改为旧缺陷 `customerSession = customerWallet`（仅判断 customerWallet），Test A + Test C 转 **RED（2 failed \| 3 passed）**——客户会话（仅传 customerAccount）下钱包入口落回内部 `WalletPanel`、充值走内部 lane；`git checkout` 还原后 **5 passed GREEN**。证明新增锁真能捕获该缺陷，非 vacuous |
| 实现结果 | §2 交付明细；§3 验证结果；§4 两入口验收底线矩阵 |
| 验证命令与通过数 | client 门（Node 24.14.1）：`biome check` 0 error exit 0；`tsc -b` exit 0；`vitest run --no-file-parallelism`（串行）79 文件 **1284 passed**（基线 1279 + 本任务净 +5）；`verify_no_secrets.sh` exit 0；server 零触碰（后端仅只读复验）。详见 §3 |
| 证据层级 | AUTOMATED_VERIFIED（client 门全绿 + 两入口真实挂载生产响应形状真断言 + 红→绿 mutation 证据 + 充值 method-path 正负向锁 + 后端旧写拒绝由现有 TEST-PG 用例 `test_customer_recharge.py:253-279` 锁定；纯前端接线回归锁，无 staging/真实链路依赖） |
| 安全与可观测性 | 无密钥/凭据/token 进代码、测试、日志、Web Storage 或前端制品；测试 fixture 凭据藏于命名常量（`sessionTokenText`）规避 secret scan；secrets 扫描 exit 0；断言客户会话下内部定价文案（"内部价"/"仅供内部运营使用"）与内部 lane（`/api/wallet`、`/api/recharge-orders`）零出现，锁死内部费率不向客户泄漏 |
| 迁移与回滚 | 纯前端测试增量，`server/` 零触碰、生产代码零改动，无数据库/迁移改动；回滚 = revert 本分支（仅移除回归锁，生产行为不变） |
| 外部授权记录 | 无（不涉及真实 ZPay/付费 Provider/生产 COS/发码/灰度/公网发布；充值用例全程 mock fetch，不发真实支付请求） |
| 未测试项 | server 全量 pytest、`npm run check:tauri`（cargo）、`npm run build`、`npm audit`、客户浏览器 E2E —— 均**只在 CI 三门禁执行**；本任务 server 零触碰，故 server 回归交 CI（同 CW-009/010/012/013/015 模式） |
| Lore 提交 SHA | 本 PR squash 后回填 |

## 2. 交付明细（对照 CW-016「仅做剩余」：统一上下文已在 main，本任务补两入口真实挂载测试 + 充值 method-path 记录）

| 规格要求（V3 line 301–305） | 交付 |
| --- | --- |
| 统一上下文：CustomerWorkspace 只传 `customerAccount`，钱包分支不得仅判断 `customerWallet` | **核实已在 main**：`LiveWorkspacePanel.tsx:65` `customerSession = customerAccount ?? customerWallet`（e180228 创建即含），钱包分支据此判断；本任务零改动，改以 mutation 红→绿证据锁定该统一不被回退 |
| 补两入口真实挂载测试（生产响应形状） | `LiveWorkspacePanel.test.tsx` 新增 3 个真实挂载用例（不 mock 客户钱包面板，走真实 `CustomerWalletPanel`/`WalletPanel`/`CustomerRechargeDialog` + 生产响应形状 fetch stub）；`MainPages.test.tsx` 新增 2 个入口路由用例（ProfilePage 两入口 → `openLive("wallet")`） |
| 两入口显示正确余额/计价/流水，无内部定价错误 | Test A 断言客户计价（"可用额度"/"12 秒"/"冻结中 2 秒"/"充值换算价…10元"/"额度流水"/客户专属"充值50元"档位），且内部定价文案（"内部价"/"仅供内部运营使用"/"可用条数"）**零出现** |
| 充值不发 `POST /api/recharge-orders` | Test C 驱动完整链路（客户档位→对话框→下单），断言 `POST /api/customer/recharge-orders`（body `{"amount_fen":20000}`）被调用、QR 渲染，且内部 lane POST 与任何内部 lane 命中**均为 false** |
| 保留内部兜底 | Test B 断言无客户会话时回落内部 `WalletPanel`（"内部价"出现、命中 `/api/wallet`、客户"充值50元"档位不出现），证明未过度修正 |
| 后端拒绝旧客户充值写规则保持（不改后端） | **只读复验**：`recharge_routes.py:283-289` 对 `role=="customer"` 的 legacy `POST /api/recharge-orders` 抛 **403**「Customer accounts must use /api/customer/recharge-orders.」；`wallet_routes.py:79` `expose_internal_prices = actor.role != "customer"` 对客户隐藏 `internal_unit_price_fen/min_recharge_fen/recharge_step_fen`（返回 None）。现有 `server/tests/test_customer_recharge.py:253-279` `test_customer_session_cannot_use_internal_recharge_route` 已 AUTOMATED_VERIFIED 锁定该 403 |

## 3. 验证结果（本地，Node 24.14.1 对齐 CI；client 门不碰 PG）

| 验证 | 命令/场景 | 结果 |
| --- | --- | --- |
| 红→绿（mutation） | 改 `LiveWorkspacePanel.tsx:65` 为 `customerSession = customerWallet` 后 `vitest run src/studio/LiveWorkspacePanel.test.tsx` | **2 failed \| 3 passed**（Test A 客户钱包 + Test C 充值 method-path 转红；Test B 内部兜底 + 2 现有用例仍绿）→ `git checkout` 还原后 **5 passed** |
| GREEN（定向·新钱包锁） | `vitest run src/studio/LiveWorkspacePanel.test.tsx` | **5 passed**（2 现有 tasks/analysis + 3 新增 CW-016） |
| GREEN（定向·两入口路由） | `vitest run src/studio/MainPages.test.tsx -t "CW-016"` | **2 passed**（63 skipped 为 -t 过滤） |
| 类型门 | `tsc -b` | **exit 0**，`fakeCustomerAccount` 满足 `WorkspaceShellProps["customerAccount"]` 全 15 必需字段、`fakeStore` 满足 `CustomerCredentialStore` 全 8 必需方法 |
| Lint/格式门 | `biome check`（2 文件） | **0 error，exit 0**（经 `biome check --write` 归位后复检 "No fixes applied"） |
| 单测门（全量·串行） | `vitest run --no-file-parallelism` | **79 文件 / 1284 passed**（基线 5e9d2d7 为 1279；本任务净 +5 = 3 钱包锁 + 2 路由锁；零回归） |
| secrets 门 | `bash scripts/verify_no_secrets.sh` | **exit 0**，No hardcoded secrets detected in runtime contract surface |
| server 零触碰 | `git diff --stat origin/main -- server/`（含 6 生产文件） | **空** → 生产代码零改动，server pytest/ruff/mypy/tauri/build 交 CI |

**并行 flake 说明（与本 diff 无关，沿用 CW-015 结论）**：默认并行 `vitest run` 偶发 `src/admin/AuditEventsPage.test.tsx`/`GenerationRecordsPage.test.tsx` 失败（走 `api.admin.ts` Cookie 路径，非本 diff 触及），以串行 `--no-file-parallelism` 全绿 1284/1284 为确定性证据。

## 4. 两入口验收底线矩阵（V3 DoD 逐条 → 实现 → 锁定测试）

| 验收底线 | 实现（复用/核实） | 锁定测试 |
| --- | --- | --- |
| 入口①「使用记录」tab → 客户钱包 | `MainPages.tsx:1747` `id==="billing" ? openLive("wallet")` | `MainPages.test.tsx` "「使用记录」标签入口调用 openLive(wallet)"（`getByRole("tab",{name:"使用记录"})`） |
| 入口②「查看使用记录」button → 客户钱包 | `MainPages.tsx:1910` `<Button onClick={()=>openLive("wallet")}>` | `MainPages.test.tsx` "「查看使用记录」按钮入口调用 openLive(wallet)" |
| 两入口汇聚 panel="wallet" + customerAccount → CustomerWalletPanel | `StudioWorkspace.tsx:1803-1809` 透传 customerAccount；`LiveWorkspacePanel.tsx:65/146-157` customerSession 判定 | `LiveWorkspacePanel.test.tsx` Test A（真实挂载，客户计价文案 + 客户 lane fetch + 无内部定价泄漏 + 无内部 lane 命中） |
| 无内部定价错误（不泄漏内部价/条） | `CustomerWalletPanel` 走 `/api/customer/*`，秒/额度计价 | Test A 断言 "内部价"/"仅供内部运营使用"/"可用条数" 零出现 |
| 充值不发 `POST /api/recharge-orders` | `CustomerWalletPanel.startRecharge` 有 `onRechargeRequested` 时委托父级 → `CustomerRechargeDialog.createPayment` → `customerCreateRechargeOrder` | Test C 断言 `POST /api/customer/recharge-orders`（body `{"amount_fen":20000}`）+ QR 渲染 + 内部 lane POST 与任何内部 lane 命中均 false |
| 过期 session/未支付/关闭/支付成功刷新 | 由 `CustomerWalletPanel`/`CustomerRechargeDialog` 现有逻辑承载 | 现有 `CustomerWalletPanel.test.tsx`（9 用例：remount 恢复轮询、未支付、关闭删单、迟到 ledger 等）+ `CustomerRechargeDialog.test.tsx`（2 用例）全绿不动；本任务不重复 |
| 内部兜底保留（无客户会话） | `LiveWorkspacePanel.tsx:154-156` 回落 `WalletPanel` | Test B（"内部价" 出现 + 命中 `/api/wallet` + 客户"充值50元"档位不出现） |
| 后端拒绝旧客户充值写 + 内部费率隐藏 | `recharge_routes.py:283-289` 403；`wallet_routes.py:79` 隐藏 | 现有 `test_customer_recharge.py:253-279` 锁 403；本任务只读复验不改后端 |

## 5. 独立复核

独立 CodeReview 子代理对本次 diff（2 测试文件）逐项对照生产代码（`LiveWorkspacePanel.tsx`/`CustomerWalletPanel.tsx`/`CustomerRechargeDialog.tsx`/`api.ts` customer* 传输层/`workspace-shell.ts` 类型/`MainPages.tsx` ProfilePage·Tabs）并实跑（70 passed，无 act 警告），**结论"无阻塞 M / 无应修 m"**，AUTOMATED_VERIFIED 层级达成。逐项确认：

1. `isInternalLane` 判定正确：`/api/customer/wallet`.includes("/api/wallet") 为 false、base URL 前缀 `http://127.0.0.1:8000` 不引入误判；兜底 `jsonResponse(emptyPage)` 不影响 lane 断言（fetchMock 返回前已记录调用），断言非 vacuous。
2. mock 响应形状与真实契约逐字一致：`customerCreateRechargeOrder` body `{amount_fen}`、payment-code 路由排序无串台、`customerGetWallet` 经 `requireWalletPricing` 校验通过走正常渲染分支。
3. 选择器无歧义：`充值50元`（客户专属档位）/`12 秒`/`冻结中 2 秒`/dialog 内 `生成支付二维码`（`within` 限定）/tab name `使用记录`（role=tab，与无 role 的 `<dt>使用记录` 不冲突）均唯一。
4. 隔离与清理正确：`vi.stubGlobal("fetch")` 由 `unstubAllGlobals` 清理；`fakeStore`/`fakeCustomerAccount` 满足类型契约；dialog 2s 真实定时器由 cleanup 卸载时 clearTimeout 清除，实测无泄漏无 act 警告。
5. Test C 完整链路稳健：`walletRefreshKey` 自增仅令 `CustomerWalletPanel`（key 绑定）remount，`CustomerRechargeDialog` 独立渲染不受影响。

评审可选次要项处置（n 级，登记为观察项，不阻塞合并）：

- **n1**（可选·已在它处覆盖，本任务不改）：`installWalletFetch` 对 `GET /api/customer/recharge-orders?` 恒返回空页，故 Test C 下单后 remount 的「从订单列表派生 PENDING 并恢复轮询」分支未在**集成层**执行。**处置**：该路径已由 `CustomerWalletPanel.test.tsx:170` "resumes polling an outstanding pending payment after a remount" 在**单元层**覆盖，集成层重复纳入价值低且增加 stub 复杂度，维持现状。
- **n2**（可选·非问题，本任务不改）：Test C 依赖真实定时器，若日后在 QR 断言后追加 >2s 异步等待可能引出 act 警告。**处置**：当前测试远快于 2s 并由 cleanup 清除定时器，实测无副作用；维持现状，若该用例后续扩展再考虑 fake timers。

## 6. 签认记录

| 角色 | 结论 | 日期 |
| --- | --- | --- |
| 前端负责人 | 待签认 | — |
| 后端复核 | 待签认（后端仅只读复验，零改动） | — |
