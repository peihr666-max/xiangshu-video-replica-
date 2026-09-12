# CW041-EVIDENCE — CW-041 pre-GA：内部身份入口 fail-closed（2026-09-12）

> 任务：CW-041（pre-GA 范围按 owner 决策 `docs/evidence/COORD-W6-UNBLOCK-20260912.md` D2 / CW-001 §6 P1 落地）。
> 分支 `feat/customer-v3-w6-unblock`（W6 统一批次），基线 `origin/main@55220f7`。
> 本任务**零生产码改动**；交付为身份面入口 fail-closed 契约测试 + 证据。物理退出（`app/internal_accounts.py`、`app/internal_billing.py` 及 4 个 `test_internal_*.py`）归 GA 后清理批次。

## 1. 入口面分层现状（机器核验，非新造）

内部身份在客户生产的不可达性由四层既有 + 一层本批次新增的守卫构成，逐层登记如下：

| 层 | 守卫 | 既有测试（不重复，仅引用） |
| --- | --- | --- |
| HTTP 请求级 | CW-026 收敛：PG lane 全环境只认客户会话 Bearer；X-Dev-User-Id、internal Bearer 一律 401 | `test_cw026_converged_auth.py`（含 `test_customer_production_flag_still_refuses_internal_bearer`，L275） |
| HTTP 启动级 | CW-025 lifespan：客户生产拒绝 internal lane（无 PG DSN 即 RuntimeError） | `test_admin_auth.py` L1323/L1338（sqlite lane / missing DSN 两分支） |
| 请求级解析 | `identity_user_id()`：dev 头仅 `ALLOW_DEV_IDENTITY_HEADER=1` 且非生产时可达；`internal_auth_required()` 非 legacy 模式强制 Bearer | 同上 cw026 套件 |
| 数据级 | `internal_access_tokens` 表只在 internal lane DB（SQLite）；客户生产 PG 无该面 | cw026 + test_internal_access_tokens |
| **进程级（本批次新增）** | **042-a 扼流点**：`app/db.py` 三入口在客户生产抛固定 RuntimeError | `test_cw042a_sqlite_entry_failclosed.py`（CW-042-a 交付）+ 本文新增消费侧契约 |

## 2. 本批次新增：`server/tests/test_cw041_internal_identity_exit.py`（5 用例）

1. **`test_internal_accounts_cli_refuses_in_customer_production`**：`python -m app.internal_accounts` 型 CLI 调用（`--db-path` + `create-user` 全参）在客户生产抛 CW-042-a 固定 RuntimeError，且目标 .db 文件零副作用（fail-closed 先于一切文件触碰）。该 CLI 是内部身份的**管理入口**（建内部账号/发 token/撤 token），从不运行 lifespan，此前无任何生产态守卫——是本任务在入口面发现的**真实缺口**，由 042-a 扼流点闭合、本用例钉死。
2. **`test_internal_accounts_cli_still_serves_the_internal_lane`**：范围守卫——P1 切片不得打断内部 lane 自身工具；端到端 create-user → issue-token 全链在内部 lane 保持可用（真实 SQLite，逐字段断言输出 JSON）。
3. **`test_internal_accounts_has_no_route_module_importers`**：结构钉——`app/internal_accounts` 必须保持 CLI-only（实测 app/ 下零导入方）；若未来任何 app 模块导入它，即意味着内部身份面长出 HTTP 入口，须 owner 决策才能放行（fail-closed against silent re-wiring）。
4. **`test_internal_accounts_parser_requires_db_path`**：CLI 无 db-path 无法运行（防止无参误用隐式建库）。
5. （补）解析器契约：子命令必选、参数必填由 argparse 强制。

## 3. 「无合法消费者」差额核对（登记，不在本批次处置）

- CW-028 兼容允许清单已冻结：管理 `/api/control` 13 端点与管理 `/api/admin/settings` 9 端点均有客户端消费者保留；唯一复核候选 = POST paid-test（无客户端封装、服务端恒 501 存根）；`/api/wallet` 系列旧通道为 WalletPanel 受支持回退路径。**取消注册动作按 CW-028 登记留给 CW-041 物理退出批次（GA 后），本批次不动。**
- `internal_billing.reserve/finalize` 的消费者（generation.py/oral_routes.py）仅在内部分支被调用，客户生产被 lifespan + 042-a 双层隔离；模块物理删除归 042-b/清理批次。

## 4. 验证与诚实边界

- 专项 **5 passed**（真实 sqlite3 CLI 端到端；非 mock）。
- 本任务未改动任何 app/ 文件（结构钉失败即 red 的设计保证未来回归可见）。
- 诚实边界：内部身份的**完整退出**（模块/路由/测试文件物理删除与旧通道取消注册）不在 pre-GA 范围，前置 = CW-039 手册定版 + 040/041/042-a 入口关闭证据（042-b/清理批次，GA 触发后）。
