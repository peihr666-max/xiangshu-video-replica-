# CW-028 证据 — 迁出共享设置工具并核销旧路由消费者

> 状态：`AUTOMATED_VERIFIED`（本机 Windows 原生 + Docker Linux 容器（python:3.12-slim + PG 16.15 vs-pg-cw028，独立网络 vs-cw028-net，不占宿主端口）执行）。
> 分支 `feat/customer-v3-cw028-shared-settings-migration`，基线 `origin/main@8ab85c7`（CW-057 #19；前置 CW-026 #20、CW-027 #23、CW-003 均已入 main）。
> 按规格「剔除重复开发」：最终取消旧路由注册归 CW-041，源文件删除归 CW-042，本任务零取消注册、零路由删除。

## 1. 任务与范围

- 任务/工作包：CW-028 / W4 代码与测试增量（后端负责人）。
- 上游规格：V3 收敛清单 §CW-028；任务账本 §18；排班清单 §2.2/§3—§7；AGENTS.md 标准工作流。
- 查重（2026-09-11 fetch 后）：无 cw028 本地/远程分支、无 PR/Draft（开放 PR 仅 #25=CW-023）、认领登记无 CW-028 行；同仓原子认领目录 + 独立 worktree 新建成功。
- 差额定位：`control_routes.py:41` 直接 `from app.settings_routes import` 六个共享工具（ProviderTester / ProviderTestResult / get_provider_tester / merge_provider_config / remove_cos_lifecycle_rules / require_supported_provider）——管理控制面反向依赖 admin 设置路由模块；两条管理通道（/api/control 与 /api/admin/settings）共用这些工具却无一中性宿主。
- 仅做剩余：共享工具迁往中性现有模块 `app/settings.py`（settings.py 本就承载 ProviderName/SettingsRepository/is_secret_field/normalize_provider，且无路由依赖）；control_routes 改从 app.settings 导入；settings_routes 改为从中性模块导入自身消费的符号；补客户与管理员合同回归；产出逐端点消费者清单与兼容允许清单（§3，冻结供 CW-041 执行）。

## 2. 共享函数消费者清单（迁移前实测，grep 全仓）

| 符号 | settings_routes 内部消费 | control_routes 消费 | 测试消费 | 迁移后宿主 |
| --- | --- | --- | --- | --- |
| `ProviderTestResult` | connection-test/paid-test 响应模型 + 三个测试器实现 | `test_control_provider_connection` 响应模型 | test_settings / 新合同测试 | app/settings.py |
| `ProviderTester`（Protocol） | 测试器类型注解 | Depends 注解 | 新合同测试 | app/settings.py |
| `NoopProviderTester` | get_provider_tester 组合末端 | （经 get_provider_tester 间接） | test_settings / 新合同测试 | app/settings.py |
| `HiflyProviderTester` | get_provider_tester fallback 层 | 同上 | test_settings / 新合同测试 | app/settings.py（hifly 惰性导入） |
| `StorageProviderTester` | get_provider_tester 首层 | 同上 | test_settings / 新合同测试 | app/settings.py |
| `get_provider_tester` | 3 个端点 Depends | connection-test Depends | test_settings / 新合同测试 | app/settings.py |
| `merge_provider_config` | update_provider_settings | control provider 设置写入业务函数 | 新合同测试 | app/settings.py |
| `remove_cos_lifecycle_rules` | update_provider_settings（cos 保存后清 180 天规则） | 同一业务点 | 新合同测试 | app/settings.py |
| `require_supported_provider` | 4 个端点 | 2 个端点 | 新合同测试 | app/settings.py |

- 唯一外部路由消费者就是 control_routes（grep `from app.settings_routes import` 全仓仅 main.py 的 router 注册与本文件）；wallet_routes / recharge_routes 均不导入 settings_routes（仅用 app.settings 的 DEFAULT_BILLING_SETTINGS / SettingsRepository）。
- **循环导入破环**：`app/hifly.py:25` 顶层 `from app.settings import SettingsRepository`，故 HiflyProviderTester 的默认客户端工厂与三个 Hifly 异常类改为**调用期惰性导入**（`_default_hifly_client` + connection_test 函数内导入）；storage 无反向依赖（仅 stdlib+cryptography），`from app.storage import ...` 保持顶层。可观察行为不变（同一默认工厂、同一异常→HTTP 映射）。
- 单一实现由合同测试钉死：`test_settings_routes_reexports_neutral_implementation` 断言 settings_routes 再导出与 app.settings **同一对象**（`is`）；`test_settings_routes_no_longer_reexports_unused_tester_classes` 断言路由模块不再保留第二层实现入口；`test_control_routes_no_longer_import_shared_tools_from_settings_routes` 断言 control_routes 源码零 `settings_routes` 引用。

## 3. 逐端点消费者清单与兼容允许清单（冻结，CW-041 依此执行）

认证角色来源：/api/control*=ControlUser（control_auth）；/api/admin/settings*=SettingsAdmin（require_role admin）；/api/wallet*、/api/recharge-orders*=AuthenticatedUser（内部身份）；/api/recharge/customer/*=客户会话 fencing。客户端消费者按 client/src 实测（api 封装→页面挂载）。

### 3.1 /api/control（control_routes.py；管理构建制品 dist-admin 专用，客户构建依赖图不可达=CW-019 断言）

| 端点 | 实际调用者（client/src） | 替代路径 | 分类 |
| --- | --- | --- | --- |
| GET /accounts | api.ts `getControlAccounts`（页面级无调用，仅测试引用） | /api/control/customers | **保留兼容待复核**（API 封装在册；未知消费者不得标可删） |
| GET /recharge-orders | api.admin.ts `listAdminRechargeOrders` → OrdersPage、CustomersPage | /recharge-orders.csv | 保留（在用） |
| GET /wallet-transactions | api.admin.ts `listAdminWalletTransactions` → AccountsPage、CustomersPage | /wallet-transactions.csv | 保留（在用） |
| GET /generation-records | api.admin.ts → GenerationRecordsPage、OverviewPage、OrdersPage | — | 保留（在用） |
| GET /billing-reconciliation | api.ts `getControlReconciliation` → OrdersPage | — | 保留（在用） |
| GET /settings | api.ts `getControlSettings` → SystemSettingsPage `controlBackend.load` | /api/admin/settings | 保留（在用） |
| PUT /settings/providers/{provider} | api.ts `updateControlProviderSettings` → controlBackend.saveProvider | /api/admin/settings/providers/{provider} | 保留（在用） |
| POST /settings/providers/{provider}/connection-test | api.ts `testControlProviderConnection` → controlBackend.testProvider | /api/admin/settings/.../connection-test | 保留（在用） |
| PATCH /settings/runtime | api.ts `updateControlRuntimeSettings` → controlBackend.saveRuntime | /api/admin/settings/runtime | 保留（在用） |
| PATCH /settings/zpay | api.ts `updateControlZPaySettings` → PaymentSettingsSection | — | 保留（在用） |
| PATCH /settings/billing | api.ts `updateControlBillingSettings` → controlBackend.saveBilling | /api/admin/settings/billing | 保留（在用） |
| GET /recharge-orders.csv | api.ts `downloadControlRechargeOrdersCsv` → OrdersPage | — | 保留（在用） |
| GET /wallet-transactions.csv | api.ts `downloadControlWalletTransactionsCsv` → OrdersPage:154 | — | 保留（在用） |

### 3.2 /api/admin/settings（settings_routes.py；工作台 SettingsPanel 默认后端，App.tsx settings 页 + StudioWorkspace 挂载）

| 端点 | 实际调用者 | 替代路径 | 分类 |
| --- | --- | --- | --- |
| GET ""（快照） | api.ts `getSettings` → SettingsPanel | /api/control/settings | 保留（在用） |
| PUT /providers/{provider} | api.ts `updateProviderSettings` → SettingsPanel | /api/control/settings/providers/{provider} | 保留（在用） |
| POST /providers/{provider}/secrets/{field}/reveal | api.ts `revealProviderSecret` → SettingsPanel 密钥查看 | — | 保留（在用） |
| PATCH /runtime | api.ts `updateRuntimeSettings` → SettingsPanel | /api/control/settings/runtime | 保留（在用） |
| PATCH /billing | api.ts `updateBillingSettings` → SettingsPanel | /api/control/settings/billing | 保留（在用） |
| POST /providers/{provider}/connection-test | api.ts `testProviderConnection` → SettingsPanel testProvider | /api/control 同名 | 保留（在用） |
| POST /providers/{provider}/paid-test | **无客户端封装、无 UI 调用**（仅 OpenAPI 生成面 generated/api.ts）；服务端恒 501（NoopProviderTester 存根） | — | **CW-041 复核候选**：无已知调用者；取消注册前须网关/日志复核真实流量 |
| POST /diagnostic-test | api.ts `runSettingsDiagnostic` → SettingsPanel 诊断 | — | 保留（在用） |
| GET /diagnostic-reports/{id}/download | api.ts `downloadDiagnosticReport` → SettingsPanel | — | 保留（在用） |

### 3.3 /api/wallet 与旧充值通道（wallet_routes.py；recharge_routes.py 前缀 /api 下三个旧端点）

| 端点 | 实际调用者 | 替代路径 | 分类 |
| --- | --- | --- | --- |
| GET /api/wallet | api.ts `getWallet` → WalletPanel（App.tsx:423 / LiveWorkspacePanel:155 无客户会话时的**受支持回退**）+ StudioWorkspace:379 | /api/recharge/customer/wallet | 保留兼容；CW-041 取消注册前须先收敛客户端回退挂载 |
| GET /api/wallet/transactions | api.ts `listWalletTransactions` → WalletPanel | /api/recharge/customer/wallet/transactions | 同上 |
| POST /api/recharge-orders | api.ts `createRechargeOrder` → WalletPanel | /api/recharge/customer/recharge-orders | 同上 |
| GET /api/recharge-orders | api.ts `listRechargeOrders` → WalletPanel | /api/recharge/customer/recharge-orders | 同上 |
| GET /api/recharge-orders/{order_no} | api.ts `getRechargeOrder` → WalletPanel | /api/recharge/customer/recharge-orders/{order_no} | 同上 |

### 3.4 /api/recharge/customer/*（recharge_routes.py 客户通道）——客户主通道

POST/GET/DELETE /customer/recharge-orders*、payment-code、profile、wallet、wallet/transactions 共 8 端点：CustomerWalletPanel / CustomerRechargeDialog / CustomerProfilePanel 在用（CW-016 已把客户钱包入口钉在客户 lane）。分类：**保留**。

### 3.5 保留验收底线复核（规格逐条）

- 「通用 /api/projects 等客户路由不因缺 customer 前缀被删」：本任务零取消注册、零路由删除，红线由「剔除范围」声明 + CI 既有授权矩阵测试（test_cw027）守护。
- 「仍被受支持客户调用的端点可用或明确要求升级」：§3.3 回退路径保持可用（WalletPanel 仍挂载于两处）。
- 「内部专用路由没有遗漏消费者」：§3.1/§3.2 逐端点登记；两个无页面调用者端点（/accounts、paid-test）按「未知消费者不得标可删」分别登记为**待复核**与 **CW-041 复核候选**，未标可删。

## 4. 验证命令与通过数

| 验证 | 环境 | 结果 |
| --- | --- | --- |
| RED：新增 `tests/test_cw028_shared_settings_contract.py` | 本机 Windows | 收集期 ImportError（cannot import name 'HiflyProviderTester' from 'app.settings'），失败原因即迁移目标 |
| GREEN：同文件 34 用例（合同行为 + 单一实现身份 + control 零反向依赖） | 本机 Windows | 34 passed / 0 fail / 0 skip |
| `pytest tests/test_settings.py`（管理设置 9 端点回归，含 4 处 monkeypatch 目标改指 app.settings） | 本机 Windows（SQLite 历史通道，规格允许的既有测试基线） | 86 passed |
| `pytest tests/test_internal_admin.py`（/api/control/settings PUT+connection-test 回归） | 本机 Windows | 22 passed |
| `pytest tests/test_admin_auth.py tests/test_cw027_admin_permission_matrix.py tests/test_cw028_shared_settings_contract.py` | Docker Linux（python:3.12-slim + PG16.15 vs-pg-cw028，TEST_POSTGRESQL_URL 指向容器） | **131 passed / 0 fail / 0 skip**（pg_test_kit fcntl 为 POSIX-only，Windows 原生无法收集，与 CI Linux 门同环境跑绿） |
| `ruff check app tests` / `ruff format` | 本机 | All checks passed / 已格式化 |
| `mypy app`（strict） | 本机 | Success: no issues found in 104 source files |
| main 全量门（check:sharded + 三门禁） | CI | PR 承载，结果以 PR CI 为准 |

## 5. Section 14 Ledger Record

```text
任务/工作包：CW-028 / W4 代码与测试增量（迁出共享设置工具并核销旧路由消费者）
Owner / Reviewer：ZCode 全链路代理（用户 2026-09-11 指令「开始28和30的开发」授权开发与提交）/ 待 PR 独立评审 + CI 三门禁
分支 / 基线 SHA：feat/customer-v3-cw028-shared-settings-migration / origin/main@8ab85c7（CW-057 合并提交）
上游规格段落：V3 收敛清单 CW-028 行；任务账本 §18；排班清单 §2.2 批次5、§3—§7；AGENTS.md 标准工作流
改动文件：server/app/settings.py（共享工具中性实现宿主）；server/app/settings_routes.py（改为导入中性实现，删重复定义）；server/app/control_routes.py（改自 app.settings 导入）；server/tests/test_settings.py（4 处 monkeypatch 目标 + 测试器类改自 app.settings 导入）；server/tests/test_cw028_shared_settings_contract.py（新增 34 用例）；docs/evidence/CW028-EVIDENCE.md；docs/CUSTOMER-TASK-EVIDENCE-V3.md；docs/客户版任务清单-V3.md §18+头部；docs/客户版代码开发清单-V3.md（新测试文件登记）
失败测试或回归锁定：合同测试先红（ImportError）后绿；单一实现以 `is` 身份断言钉死；control_routes 源码零 settings_routes 引用以源码扫描断言钉死；mask 掩码保留/空值清除/掩码回传不覆盖凭据等合同逐项相等断言
实现结果：九个共享符号仅存 app/settings.py 一份中性实现；hifly 反向依赖以调用期惰性导入破环（可观察行为不变）；settings_routes 仅再导出自身消费的六符号，测试器实现类不再从路由模块暴露；control/admin 两条设置通道合同回归全绿
验证命令与通过数：见 §4（新增 34 passed；settings 86 + internal_admin 22 + Linux PG 容器 131 零回归；ruff/format/mypy 全绿）
证据层级：AUTOMATED_VERIFIED（真实 PG16 容器执行 PG 门禁套件；不涉及真实 Provider/COS 凭据链，真实链路归 CW-050）
安全与可观测性：无真实 secret 入代码/日志/夹具（测试用 Fernet 运行时生成键、假 COS 配置）；迁移未改变认证依赖与审计写入路径；掩码合同测试钉住「掩码回传不覆盖真实凭据」安全底线
迁移与回滚：无 DB 迁移；回滚 = revert 本分支提交（导入关系回到 settings_routes，行为等价）
外部授权记录：用户指令授权本任务开发；PR squash 合并由用户执行（本任务不自行合并）；未触碰真实 ZPay/付费 Provider/生产 COS
未测试项：cargo test / npm audit / 客户浏览器 E2E / npm run build（仅 CI 三门禁）；真实网关流量统计（CW-041 复核 paid-test 与 /accounts 时取得）；STAGING 及以上层级
Lore 提交 SHA：见 claim.json 与 PR 登记
```
