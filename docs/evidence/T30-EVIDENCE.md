# T30 — Second-Device Pairing, Conflict, Explicit Switch and Displacement Notices (FE-03)

## Task Information

| Field | Value |
| --- | --- |
| **Task ID** | T30 / FE-03 |
| **Owner** | Frontend (Agent) |
| **Reviewer** | chatgpt-codex-connector PR pass (3 P1 + 1 P2 + 1 P1 file-map — all five addressed, see the review section below) |
| **Branch / Base SHA** | `feat/customer-v3-t30-second-device-pairing-ui` / base `main` (PR #58) |
| **Date** | 2026-08-25 |
| **Evidence Level** | `AUTOMATED_VERIFIED` (vitest/jsdom client lane) |

## Exit-Gate Verification

Task exit gate (task list §6 T30): *普通冲突不进入工作台；二次确认后切换；旧端提示准确* — work package §12 FE-03: *普通登录 409；确认后切换；旧端状态准确* — both delivered as automated tests:

```bash
$ cd client && npm run check
# biome check . && tsc -b && vitest run
Checked 66 files — no errors
30 test files, 382 tests passed
```

- 普通登录 409 → `OTHER_DEVICE_ONLINE` 进入 `binding-conflict` 屏幕（`CustomerApp.test.tsx`：conflict dialog 渲染且 `switchSession` **未被**自动调用 —— 无静默接管）；
- 二次确认后切换 → `switchSession` 调 `customerSwitch`（typed adapter），服务端确认后才保存新 session token 并转 workspace（`CustomerApp.test.tsx`「explicit switch」用例；`SessionConflictDialog.test.tsx`「no silent takeover」用例）；
- 取消切换 → `cancelSessionSwitch` 回 login 屏（`CustomerApp.test.tsx`「switch is cancelled」用例）；
- 旧端状态准确 → `session-replaced` 提示（`SessionDisplacedNotice`）与 `session-expired` / `device-revoked` 提示屏均挂载于最小客户入口；reducer 终态收到同事件即离开终态（expired/replaced → login，revoked → activation），`restartAfter*` 不再死循环（P2-4 修复，`customerScreenReducer` 回归用例）。

## Review Disposition — PR #58 Codex pass (5 comments, all addressed)

Reviewed commit `c00c6fe`；处置提交 `8d55c17`（CI 修复）+ 本证据对应提交（功能修复）：

| 级别 | 评论 | 处置 |
| --- | --- | --- |
| P1 | Mount the customer flow in the shipped application | 新增 `CustomerApp.tsx` + `store.ts`，RootApp 路由 `/customer/` → 客户入口；激活/登录/工作台/配对/冲突/切换/被踢全部可达（最小挂载：浏览器内存凭据存储过渡实现，T29 Tauri 桥合并后替换；正式激活/登录页由 T29/FE-02 迭代，全链路 E2E 验收在 T34） |
| P1 | Route enrollment through the typed customer adapter | `DevicePairingPage` 改调 `customerEnrollDevice`：激活码输入补齐、幂等键由 transport 携带、202 `PENDING`/201 `CONSUMED` 按 adapter 判别（不再本地 `data.status === "pending"` 误判大写）；测试改 mock adapter 验证入参与双响应 |
| P1 | Expose and execute the confirmed session switch | `useCustomerSession` 新增 `switchSession`（调 `customerSwitch`，成功后保存新 token 并转 workspace）与 `cancelSessionSwitch`（回 login）；reducer 增加 `conflict-detected` / `conflict-cancelled` 事件，`login-succeeded` 接受 `binding-conflict` → workspace |
| P2 | Transition restart actions out of terminal states | reducer 终态转移：`session-expired`/`session-replaced` 状态收到同事件 → login；`device-revoked` 收到同事件 → activation；新增 `restartAfterReplaced` action |
| P1 | Keep new components within the frozen customer file map | 映射文档（`docs/客户版代码开发清单-V3.md` §4.1）登记 `CustomerApp.tsx`、`PairingApprovalCard.tsx`、`SessionDisplacedNotice.tsx`、`store.ts`（含 §10.x checklist 行），AGENTS.md 账本流程内更新 |

## Implementation Highlights

- `useCustomerSession.ts`：`switchSession` / `cancelSessionSwitch` / `restartAfterReplaced` 三个新 action；boot 与 retryLogin 的 `OTHER_DEVICE_ONLINE` 分支补 `conflict-detected` 事件；reducer 终态恢复转移（不再死循环）。
- `DevicePairingPage.tsx`：走 `customerEnrollDevice` typed adapter；激活码必填；删除裸 `fetch` 与 `any`。
- `CustomerApp.tsx`：最小客户入口装配（`/customer/` 路由），注入式 `store`（测试可注入隔离内存 store）；配对 202/201 结果提示。
- `store.ts`：浏览器凭据存储过渡实现（内存，不落 Web Storage —— 红线内安全；T29 桥接替换）。
- CI 修复（提交 `8d55c17`）：`cancelled` 未声明、重复导出、useReducer init、JSX namespace（React 19）、`global.fetch` → `vi.stubGlobal`、CRLF → LF。

## Files Changed

```
client/src/customer/CustomerApp.tsx            (new)
client/src/customer/CustomerApp.test.tsx       (new)
client/src/customer/store.ts                   (new)
client/src/customer/useCustomerSession.ts      (switch/cancel/restart actions, reducer transitions)
client/src/customer/DevicePairingPage.tsx      (typed adapter + activation code field)
client/src/customer/DevicePairingPage.test.tsx (adapter-mocked cases)
client/src/RootApp.tsx                         (/customer/ route)
client/src/RootApp.test.tsx                    (customer route cases)
docs/客户版代码开发清单-V3.md                  (§4.1 map registration)
```

## Regression

- `npm run check`：biome 66 files 零错误；tsc 零错误；vitest 30 files / 382 tests 全过。
- Windows Tauri NSIS build（`npm run build` = `tsc -b && vite build`）本地通过。
- 未触碰服务端与 Tauri 代码；server 全量 pytest 未在本 PR 改动面内（无服务端文件变更）。
