# CW-025 — 把现有 PG 保护扩展到全部运行环境（全环境 PG-only 运行入口）

> 目标证据层级：`AUTOMATED_VERIFIED`。本文件登记 CW-025 的改动、逐环境启动拒绝矩阵、
> 连接与落库证据、schema readiness、全量门禁结果与范围边界。真实服务器/staging/生产切换
> 不在本任务范围（见 §7 范围边界与延后项）。

## 1. 任务信息（§14 模板）

| 字段 | 值 |
| --- | --- |
| 任务/工作包 | CW-025（W4）把现有 PG 保护扩展到全部运行环境；DoD：统一 API/Worker/开发入口/管理运行的 PG 配置，退出 DB_PATH 和 sqlite:// 在线解析、缺配置本地回退与自动建 SQLite，迁移使用单一显式 PG 入口 |
| Owner / Reviewer | Owner：Qoder 代理（hlong026 会话，2026-09-10）；Reviewer：PR #7 独立 CodeReview + connector |
| 分支 / 基线 SHA | `feat/customer-v3-cw025-pg-protection-all-env`；基线 `origin/main@9a70918`（CW-009 #108 合并后） |
| 上游规格段落 | 收敛详细任务清单 §CW-025（line 335–344）；V3 清单 §18 CW-025 行（line 486）；PG-01 运行入口合同（`docs/PostgreSQL唯一数据库实施与验收规范.md`） |
| 改动文件 | 14 文件（11 改 + 3 新）。改：`package.json`、`server/app/{bootstrap,customer_fence,db_pg,generation_worker,main}.py`、`server/tests/{test_admin_auth,test_db,test_db_pg,test_internal_access_tokens,test_postgres_migrations}.py`（+304/−315）；新：`scripts/dev-with-pg.sh`（30 行）、`server/tests/test_bootstrap_all_env_pg_gate.py`（308 行）、`server/tests/test_desktop_artifact_no_pg_dsn.py`（188 行） |
| 失败测试或回归锁定 | 新增 `test_bootstrap_all_env_pg_gate.py`（51 用例：50 passed + 1 skip）构建逐环境启动拒绝矩阵；新增 `test_desktop_artifact_no_pg_dsn.py`（8 用例）锁定桌面制品不注入 PG DSN；反转/更新 `test_db_pg.py`（resolve 全环境 fail-closed）、`test_db.py`（删除 SQLite bootstrap 用例）、`test_admin_auth.py`（lifespan fail-closed 消息） |
| 实现结果 | §2 交付明细；§3 拒绝矩阵；§4 连接/落库/readiness；§5 验证结果；§6 根因修复专章 |
| 验证命令与通过数 | `npm run check`（等价 CI Linux 质量门，含服务端全量 pytest 一次）：secret 扫描 exit 0；biome 199 文件 0 error；**client vitest 79 文件 1267 passed**；e2e biome 15 文件；Tauri `cargo fmt --check` + `cargo check --locked` 通过（2 项既有 dead_code 警告，非阻断）；`ruff check server` All checks passed；`ruff format --check server` 293 files already formatted；`mypy server/app` Success 104 files；**服务端全量 pytest 2210 passed / 1 skipped / 0 failed（1009.52s，16:49）**。详见 §5 |
| 证据层级 | **AUTOMATED_VERIFIED**（PG-01 运行入口全环境 fail-closed 经逐环境拒绝矩阵 + 正向对照 + 全量门禁零回归验证；无 staging/真实链路依赖。真实服务器/生产切换不在本任务范围） |
| 安全与可观测性 | 无真实 API key/激活码明文/设备或 session token 进入代码、日志、测试夹具或 PR；`test_check_pg_ready_redacts_dsn_credentials` 保证 readiness 日志脱敏 DSN 凭据；secret 扫描通过；bootstrap 记录 `PostgreSQL runtime ready (pool_max, server_now)` readiness 日志 |
| 迁移与回滚 | **零迁移文件改动**（未触碰冻结的 025–030 区间，未新增 revision）；纯运行入口解析层 + 测试增量。回滚 = revert 本分支，运行入口恢复原 SQLite/PG 双解析 |
| 外部授权记录 | 无（不涉及真实 ZPay / 付费 Provider / 生产 COS 变更 / 对外发码 / 灰度扩大 / 公网发布） |
| 未测试项 | `cargo test`、`npm audit`、客户浏览器 E2E、`npm run build` —— 均**只在 CI 三门禁执行**，本地 `npm run check` 不含（见 §8） |
| Lore 提交 SHA | 本 PR squash 后回填 |

## 2. 交付明细（对照 CW-025 DoD）

| DoD 要求（收敛清单 §CW-025 line 340/342） | 实现 |
| --- | --- |
| 退出 `sqlite://` 在线解析 | `db_pg.resolve_database_config()`：`sqlite://`/`sqlite:///` URL → `RuntimeError`（不再返回 `DatabaseMode.SQLITE`） |
| 退出 `DB_PATH` 在线解析（含与 PG 混配） | `resolve_database_config()`：**先**检查 `VIDEO_REPLICA_DB_PATH`，非空即 `RuntimeError`——即使同时设置了合法 PG DSN（`db_path_with_pg` 混配场景）也拒绝 |
| 退出缺配置本地回退 | `resolve_database_config()`：缺 DSN 且缺 DB_PATH → `RuntimeError`（删除原 `MissingDatabaseConfigError` 内部 lane 容忍分支）；不支持 scheme → `ValueError` |
| 退出自动建 SQLite | `bootstrap._run_runtime_bootstrap()`：删除 `bootstrap_runtime(db_path)` SQLite 分支；`config.mode` 非 POSTGRESQL 时防御性 `RuntimeError`；拒绝矩阵断言无 `.db/.db-wal/.db-shm` 副作用 |
| 统一 API 入口 PG 配置 | `main._lifespan()`：customer lane（`DATABASE_URL=postgresql://`）走 `resolve_database_config()` + `validate_customer_production()` 全环境 fail-closed；删除吞 `MissingDatabaseConfigError` 的 try/except |
| 统一 Worker 入口 PG 配置 | `generation_worker.main()`：删除 SQLite `SystemExit("VIDEO_REPLICA_DB_PATH is required")` 入口与 `run_sqlite_worker_round`/`run_forever` 调用；SQLite 在线路径改为防御性 `RuntimeError`（unreachable after CW-025） |
| 迁移使用单一显式 PG 入口 | `test_bootstrap_pg_branch_does_not_call_alembic_upgrade`：bootstrap PG 分支不自动跑 alembic upgrade（迁移由 `deploy/postgres/migrate.sh` 单一显式入口执行）；`test_concurrent_api_worker_startup_does_not_race_schema_migration`：API/Worker 并发启动不竞争 schema |
| 开发仅放宽外部替身/环境配置，不放宽数据库类型 | 新增 `scripts/dev-with-pg.sh`：幂等拉起 pg-fixture 并注入开发 PG DSN（`postgresql://…@localhost:5433/customer_v3_test`）；`package.json` dev:server/dev:worker 经该 wrapper 启动——开发环境仍强制 PG，不放行 SQLite |
| 桌面制品不获得 PG DSN | 新增 `test_desktop_artifact_no_pg_dsn.py`（8 用例，见 §3.3） |

## 3. 逐环境启动拒绝矩阵（必交证据①）

### 3.1 bootstrap 入口拒绝矩阵（`test_bootstrap_rejects_non_pg_config_all_environments`）

5 环境 × 4 场景 = **20 用例全绿**；每例断言抛 `(RuntimeError, SystemExit)` **且** `tmp_path` 下无 `.db`/`.db-wal`/`.db-shm` 生成：

| 场景 \ 环境 | dev | test | ci | staging | production |
| --- | :-: | :-: | :-: | :-: | :-: |
| `missing_dsn`（缺 DSN 且缺 DB_PATH） | ✅ | ✅ | ✅ | ✅ | ✅ |
| `sqlite_url`（`sqlite:///…`） | ✅ | ✅ | ✅ | ✅ | ✅ |
| `db_path_only`（仅 DB_PATH） | ✅ | ✅ | ✅ | ✅ | ✅ |
| `db_path_with_pg`（DB_PATH + PG DSN 混配） | ✅ | ✅ | ✅ | ✅ | ✅ |

### 3.2 Worker 入口拒绝矩阵（`test_worker_main_rejects_non_pg_config_all_environments`）

同 5 环境 × 4 场景 = **20 用例全绿**（`sys.argv=["generation_worker","--once"]`），断言抛错且无 SQLite 文件副作用。

### 3.3 正向对照与桌面制品隔离

| 测试 | 覆盖 | 结果 |
| --- | --- | --- |
| `test_bootstrap_accepts_valid_pg_all_environments` | dev/test/ci/staging 有效 PG DSN → bootstrap 成功连接并 readiness（production 因 TLS 要求 skip，由 `test_db_pg.py` 纯配置测试覆盖） | 4 passed + 1 skip |
| `test_api_lifespan_rejects_unsupported_scheme_all_environments` | dev/test/ci/staging `mysql://` → `ValueError: unsupported database URL scheme` | 4 passed |
| `test_desktop_artifact_no_pg_dsn.py`（8 用例） | 客户 Tauri 配置存在/无 `DATABASE_URL` env/无后端 resources/不引用 start_backend；内部 Tauri 配置与客户分离；`package.json` 客户构建脚本不注入 PG DSN；`require_customer_api_base.mjs` 不注入 PG DSN；客户制品 env 隔离汇总 | 8 passed |

### 3.4 纯配置层拒绝矩阵（`test_db_pg.py`，34 函数 / 69 参数化用例）

`test_resolve_rejects_db_path_all_environments`、`test_resolve_missing_dsn_raises_runtime_error_all_environments`、`test_resolve_rejects_unsupported_scheme`、`test_production_rejects_sqlite`、`test_production_rejects_leftover_db_path`、`test_production_rejects_postgres_without_enforced_tls`、`test_non_production_rejects_sqlite_url`、`test_all_environment_startup_rejection_matrix`（PG 不可达/只读端点：`test_check_pg_ready_rejects_a_read_only_endpoint`）。

## 4. 连接与落库证据 + schema readiness（必交证据②④）

| 证据 | 来源 | 说明 |
| --- | --- | --- |
| 有效 PG 连接 + readiness | `test_bootstrap_accepts_valid_pg_all_environments` → `check_pg_ready()` | 真实连 pg-fixture PG16（端口 5433），返回 `pool_size`/`server_now`，bootstrap 记录 `PostgreSQL runtime ready (pool_max=%d, server_now=%s)` |
| 首装空库落库 | `test_postgres_migrations.py::test_empty_customer_bootstrap_runs_on_a_fresh_migrated_database` | 真实迁移后空 PG 库上 `provision_empty_customer` 原子写入首 admin + wallet(0,0) + 加密 COS（密文不含明文 secret）+ runtime_settings + audit_logs，逐行 SELECT 核对 |
| schema readiness 不竞争 | `test_concurrent_api_worker_startup_does_not_race_schema_migration` | API 与 Worker 并发启动不各自触发 schema migration |
| DSN 凭据脱敏 | `test_check_pg_ready_redacts_dsn_credentials` | readiness 日志/异常不泄漏 DSN 用户名口令 |

PG 配置/角色清单（必交证据③）：测试基座用 pg-fixture 单库 `customer_v3_test`（role `testuser`，端口 5433，来自 `scripts/pg-fixture.sh`）；各 PG 测试文件另有独立库（如 `t36_empty_customer_bootstrap_test`、`a1_internal_token_lane_test`）。生产 PG 角色/DSN 清单属部署侧交付（CW-032 可重建后端交付包），本任务不登记真实生产凭据。

## 5. 验证结果（本地，对齐 CI Linux 质量门）

`npm run check` 一次承载全量门禁（含服务端全量 pytest，每任务唯一一次全量）：

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| secret 扫描 | `bash scripts/verify_no_secrets.sh` | **exit 0**，No hardcoded secrets detected |
| 前端 lint/类型/单测 | `biome check . && tsc -b && vitest run` | biome 199 文件 0 error；**vitest 79 文件 1267 passed** |
| e2e lint | `biome check e2e` | 15 文件 0 error |
| Tauri | `cargo fmt --check && cargo check --locked` | 通过（2 项既有 `dead_code` 警告：`CREDENTIALS_FILE`/`DPAPI_ENTROPY`，非本任务引入、非阻断） |
| 服务端 lint | `ruff check server` | **All checks passed!** |
| 服务端格式 | `ruff format --check server` | **293 files already formatted** |
| 服务端类型 | `mypy server/app` | **Success: no issues found in 104 source files** |
| **服务端全量 pytest** | `pytest --rootdir server server/tests` | **2210 passed, 1 skipped, 0 failed（1009.52s / 16:49）** |

前置：`scripts/pg-fixture.sh start`（Docker PG16 `customer-v3-pg-test`，端口 5433）已启动；CW-007 硬门生效（fixture 未启动时 PG 套件失败而非 skip）。1 skipped = `test_bootstrap_accepts_valid_pg_all_environments[production]`（TLS 要求由 `test_db_pg.py` 纯配置测试覆盖）。

## 6. 根因修复专章：全量 pytest 连接池单例泄漏（本任务收尾发现并修复）

**现象**：全量 `npm run check` 中 `test_postgres_migrations.py::test_empty_customer_bootstrap_runs_on_a_fresh_migrated_database` 失败，日志显示 PG 连接尝试指向不存在的库 `a1_internal_token_lane_test`（专项单跑该文件时全绿）。

**根因**：`db_pg.get_pg_pool()` 是**进程级懒加载单例** `_pool`，仅在 `_pool is None or _pool.closed` 时读 `resolve_database_config()` 解析 DSN 并缓存。`test_internal_access_tokens.py` 的 `a1_dsn` fixture（`scope="module"`）创建独立库 `a1_internal_token_lane_test`、经 probe app 触发 `get_pg_pool()` 初始化单例指向该库；teardown **只 `DROP DATABASE` 却未重置单例**，泄漏一个指向已删库的陈旧 pool。pytest 默认字母序下 `test_internal_access_tokens`(i) 先于 `test_postgres_migrations`(p)，后者经 `provision_empty_customer → pg_transaction → get_pg_pool()` 复用到陈旧单例 → 连接已删库报错。

**为何是 A1 独有**：全仓 8+ 个设置独立 DSN 的 PG fixture（`test_admin_audit_routes`/`test_customer_devices`/`test_customer_queue_fairness`/`test_worker_crash_recovery`/`test_customer_chain_e2e`/`test_customer_activation`/`test_customer_security`/`test_customer_sessions`）均在 setup+teardown **成对** `close_pg_pool()`；A1 的 `a1_dsn` 是唯一违反此约定者。

**修复（源头 + 消费端双保险）**：
1. **源头（约定对齐）**：`test_internal_access_tokens.py` 模块级 import `close_pg_pool`，在 `a1_dsn` fixture 的 `try` 前（setup）与 `finally` 首行（teardown，先于 `DROP DATABASE`）各调用一次——与其余 8 个 PG fixture 完全一致。
2. **消费端（防御）**：`test_postgres_migrations.py::test_empty_customer_bootstrap…` 开头 `close_pg_pool()`，确保本用例重新解析自身 t36 DSN（对齐 `test_customer_devices.py` 独立测试约定）。

**验证**：`test_internal_access_tokens.py + test_postgres_migrations.py` 合跑 31 passed（污染顺序复现且修复）；全量 `npm run check` 中 A1[57%] 全绿、test_postgres_migrations[70%] 24 用例全绿、最终 2210 passed / 0 failed。

## 7. 范围边界与延后项（诚实登记）

CW-025 完工标准（收敛清单 line 343）明确：**"PG-01 运行入口验收通过；SQL/类型与事务契约由 CW-054/055 补齐，历史工具由 CW-060 隔离；最终 SQLite 在线实现移除须等 CW-043 覆盖完成。"** 交付顺序（line 779）亦为 "CW-025 **入口** → CW-054/055/056/057 → CW-058/059 与 CW-060 历史工具隔离 → CW-043 → CW-042 退出 SQLite → CW-044/045 硬门"。据此，本任务范围是**单一在线解析入口的全环境 fail-closed**，以下明确延后、本任务**不声称已完成**：

| 延后项 | 归属任务 | 本任务现状 |
| --- | --- | --- |
| 内部 P0 遗留 lane 的请求级 `DB_PATH`/SQLite 通道（`customer_fence.BusinessDb.write` / `get_business_read_conn` 的 internal lane 分支） | CW-042/CW-043（退出 SQLite + 覆盖）；内部身份/固定桌面身份 → CW-026 | **保留**。内部 P0 是已收口独立线，不属客户版 V3 运行环境（dev/test/CI/staging/production）；`resolve_database_config()` 入口已对其 fail-closed，请求级通道待 CW-042/043 移除 |
| Worker SQLite 业务实现（`run_sqlite_worker_round`/`run_forever`/`--db-path`） | CW-030（收敛各类 Worker 的 PG 调度与恢复差额） | **保留函数体**，仅移除 `main()` 在线入口调用（改为 unreachable 防御性 RuntimeError） |
| 历史 SQLite 工具（backup/sqlite_to_postgres/gate1_*） | CW-060（历史工具隔离白名单） | 不经 `resolve_database_config()` 在线通道，本任务未触碰 |
| SQL/类型/事务契约差额 | CW-054/CW-055 | 不在本任务范围 |
| 真实服务器/staging/生产切换、PG HA、双 API/四 Worker 部署 | CW-032/CW-051 等 + 人工授权 | 不提升 `STAGING_VERIFIED` |

**内部 lane 保留的必要性**：若 CW-025 强行使请求级 `customer_fence` internal lane 也 fail-closed，将击穿整套内部 P0 测试（数百用例用 DB_PATH+SQLite），属越界回归；完工标准明确 SQLite 在线实现最终移除须等 CW-043，故本任务在**入口层**（`resolve_database_config`/bootstrap/worker main/lifespan customer lane）fail-closed，请求级 internal lane 通道按分解延后。

## 8. 未测试项（交 CI 三门禁）

`cargo test`（Rust 单测）、`npm audit`（依赖审计）、客户浏览器 E2E、`npm run build`（前端/Tauri 构建）四项**只在 CI 三门禁执行**，本地 `npm run check` 不含。本任务 Rust 侧零触碰（Tauri 仅 `cargo check` 通过），构建/依赖回归以 CI 结果为准。

## 9. 签认记录

| 角色 | 结论 | 日期 |
| --- | --- | --- |
| 后端负责人 | 待签认 | — |
| 独立安全/代码复核 | PR #7 CodeReview + connector | — |
| 集成负责人 | 待签认 | — |
