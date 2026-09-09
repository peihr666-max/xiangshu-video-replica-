# CW-012 — 迁出旧入口中的共享类型和客户映射（解耦 WorkspaceShell 类型依赖）

## 任务信息（§14 模板）

| 字段 | 值 |
| --- | --- |
| 任务/工作包 | CW-012（W2）迁出旧入口中的共享类型和客户映射；DoD：解除客户工作台对旧入口的类型依赖 |
| Owner / Reviewer | Owner：ZCode 代理（hlong026 会话，2026-09-09）；Reviewer：独立 CodeReview 子代理（结论见 §5，7/7 通过）+ PR review |
| 分支 / 基线 SHA | `feat/customer-v3-cw012-decouple-workspace-type-deps`；基线 `origin/main@b45de8f`（#105 合并后，tree d4e52dc） |
| 上游规格段落 | V3 清单 §18 CW-012 行；代码开发清单 §15.1（本任务新增叶子模块冻结登记） |
| 改动文件 | 9 文件 +152/−57：新增 `client/src/workspace-shell.ts`（纯类型叶子，导出 `WorkspaceShellProps`）、`client/src/customer/customerToCurrentUser.ts`（纯函数叶子）、`client/src/customer/customerToCurrentUser.test.ts`（3 用例）；改 `client/src/App.tsx`（+2/−35）、`RootApp.tsx`（−14）、`studio/StudioWorkspace.tsx`（+2/−3）、`studio/LiveWorkspacePanel.tsx`（+4/−4）、`customer/CustomerWorkspace.tsx`（+1/−1）、`docs/客户版代码开发清单-V3.md`（+11，§15.1 冻结） |
| 失败测试或回归锁定 | 新增 `customerToCurrentUser.test.ts` 3 用例锁定映射回退链；`App.test.tsx` 37 用例（含 `ComponentProps<typeof WorkspaceShell>` mock）保持绿即本项回归锁 |
| 实现结果 | §2 交付明细；§3 验证结果；§4 无环校验 |
| 验证命令与通过数 | client 门（Node 24.14.1）：`biome check .` 199 文件 0 error exit 0；`tsc -b --force` exit 0；`vitest run` 79 文件 **1267 passed**（基线 1264 + 新增 3）；`verify_no_secrets.sh` exit 0。详见 §3 |
| 证据层级 | AUTOMATED_VERIFIED（client 门全绿 + 无环校验 + 类型/映射等价经独立复核；纯类型/映射重构，无运行时行为变更，无 staging/真实链路依赖） |
| 安全与可观测性 | 无密钥/凭据/token 进入代码或测试；secrets 扫描通过；无新增日志/可观测面 |
| 迁移与回滚 | 纯前端类型/映射重构，server/ 零触碰，无数据库/迁移改动；回滚 = revert 本分支，运行时行为不变 |
| 外部授权记录 | 无（不涉及真实 ZPay/付费 Provider/生产 COS/发码/灰度/公网发布） |
| 未测试项 | server 全量 pytest、`npm run check:tauri`（cargo）、`npm run build`、`npm audit`、客户浏览器 E2E —— 均**只在 CI 三门禁执行**；本任务 server 零触碰，故 server 回归交 CI（同 CW-009 模式，且规避 dev server 占用共享 `customer_v3_test` PG fixture 的并发互踩红线） |
| Lore 提交 SHA | 本 PR squash 后回填 |

## 2. 交付明细（对照 CW-012 DoD：迁出旧入口中的共享类型和客户映射）

| 现状问题 | 实现 |
| --- | --- |
| `App.tsx` 导出 `WorkspaceShell` 组件，其 props 为内联匿名类型；`studio/StudioWorkspace.tsx`、`studio/LiveWorkspacePanel.tsx` 经 `ComponentProps<typeof WorkspaceShell>` 从 `../App` 反向派生该类型，而 App.tsx 又运行时 import 这两个 studio 组件 → 构成 `App ↔ studio` 的 import type 环 | 新建纯类型叶子 `workspace-shell.ts`，导出 `WorkspaceShellProps`（从 App.tsx 内联 props **逐字段抽出**）；`WorkspaceShell` 组件本体仍留 App.tsx，仅以 `WorkspaceShellProps` 注解其 props；studio 两文件改从 `../workspace-shell` import，删除 `../App` 依赖与 `ComponentProps` |
| `customer/CustomerWorkspace.tsx` 需从旧入口 `../RootApp` import `customerToCurrentUser` → 构成"客户域 → 旧入口"反向依赖 | 新建纯函数叶子 `customer/customerToCurrentUser.ts`，从 RootApp.tsx **逐字节迁出**该映射；RootApp.tsx 删除该导出及其专用类型 import（`CurrentUser`/`CustomerProfile`/`CustomerWorkspaceUser`）；CustomerWorkspace 改从同目录 `./customerToCurrentUser` import |
| 新增应用模块需先冻结路径 | 代码开发清单 §15.1 登记 2 新叶子的确切路径、导出符号、消费者、入口/打包边界与责任（先冻结后编码） |

等价性保证：`WorkspaceShellProps` 为原内联 props 的逐字段抽取（字段名/可选性 `?`/类型/注释一致），故 `ComponentProps<typeof WorkspaceShell>`（旧）与 `WorkspaceShellProps`（新）解析出相同类型；`LiveWorkspacePanel` 的 `WorkspaceShellProps["customerAccount"]`/`["customerWallet"]` 因字段可选而保留 `| undefined`。`customerToCurrentUser` 函数体逐字节一致（三条 `??` 回退链、`role: "customer"`、`id: user.userId`）。

## 3. 验证结果（本地，Node 24.14.1 对齐 CI；client 门不碰 PG）

| 验证 | 命令/场景 | 结果 |
| --- | --- | --- |
| 类型门 | `tsc -b --force`（强制重建，全项目引用） | **exit 0**，无类型错误 |
| Lint/格式门 | `biome check .` | **199 文件，0 error，exit 0**（3 处 import 排序经 `biome check --write` 权威归位后复检通过） |
| 单测门（全量） | `vitest run` | **79 文件 / 1267 passed**（基线 b45de8f 为 client 1264；本任务 +3 = 新增 `customerToCurrentUser.test.ts`，零回归） |
| 单测门（定向） | `vitest run customerToCurrentUser.test.ts App.test.tsx` | 新测试 **3 passed**（红→绿）；`App.test.tsx` **37 passed**（基线不变） |
| secrets 门 | `bash scripts/verify_no_secrets.sh` | **exit 0**，No hardcoded secrets |
| server 零触碰 | `git diff --cached --name-only \| grep '^server/'` | **空** → server pytest/ruff/mypy/tauri/build 交 CI |

RED→GREEN：先建 `customerToCurrentUser.test.ts`（import 尚不存在的模块 → 红），再建 `customerToCurrentUser.ts` 使消费者可从新路径 import → 绿；3 条用例覆盖 profile 存在/profile 缺省回退/username 为 null 回退默认三分支。

环境说明：本机默认 Node **v20.20.2** 无法跑 vitest——`vite.config.ts` 的 `test.execArgv: ["--no-experimental-webstorage"]` 是 Node 22+ flag（Node 20 报 `bad option` 致 worker fork 秒崩，"Worker exited unexpectedly / no tests"）。改用 nvm **Node v24.14.1**（对齐 CI Node 24）后全绿。此为本地 Node 版本与配置假设不匹配，与 CW-012 改动无关。

## 4. 无环校验（CW-012 核心目标）

| 校验 | 命令 | 结果 |
| --- | --- | --- |
| studio 不再依赖旧入口 | `grep -rn 'from "\.\./App"' client/src/studio/` | **空**（环已断） |
| 新叶子不回指消费者 | `workspace-shell.ts` 仅 import `./api` + `./customer/useCustomerSession`；`customerToCurrentUser.ts` 仅 import `../api` + `./useCustomerSession` | 均为纯叶子，单向 |
| workspace-shell 被单向依赖 | App.tsx、StudioWorkspace.tsx、LiveWorkspacePanel.tsx 各 import 一次 | 叶子不回指，无环 |

结论：原 `App → studio → App` 的 import type 环，重构后变为 `App → studio`（运行时单向）+ 双方 `→ workspace-shell`（纯类型叶子），环彻底打断。

## 5. 独立复核

独立 CodeReview 子代理对暂存 diff（9 文件）做类型等价/映射等价/消费者完整性/无环/无残留未使用 import/运行时零行为变更/测试充分性七项复核，**全部通过，无 P0/P1/P2**，结论"可进入提交流程"。要点：

- 类型等价：`WorkspaceShellProps` 与原内联 props 逐字段/逐可选性/逐注释一致；索引访问保留 `| undefined`。
- 映射等价：`customerToCurrentUser` 函数体逐字节一致。
- 消费者完整性：生产代码 `ComponentProps<typeof WorkspaceShell>` 仅余 `App.test.tsx:18`（合理保留——测试值导入组件后派生 mock 类型，不构成环，解析等价）；`customerToCurrentUser from ../RootApp` 全清除。
- 无残留未使用 import：App.tsx / RootApp.tsx 删除的类型在各自文件内确无其他使用点。
- 运行时零行为变更：纯类型文件 + 纯函数平移 + import 路径替换。

## 6. 签认记录

| 角色 | 结论 | 日期 |
| --- | --- | --- |
| 前端负责人 | 待签认 | — |
| 集成负责人 | 待签认 | — |
