# CW-057 证据文件 — 统一剩余维护与种子 CLI 的 PG 入口

任务：CW-057（W4 · 代码与测试增量 · 统一剩余维护与种子CLI的PG入口）
分支：`feat/customer-v3-cw057-maintenance-seed-cli-pg`（独立 worktree `E:/众墅之家爆款短视频创作/.worktrees/CW-057-maintenance-seed-cli-pg`，从 `origin/main@e829ad1` 创建）
基线：origin/main = `e829ad1a6d859a51ae804a7cd31cc5513b393cb9`（CW-055 #13 squash 合入后的 main 顶端）
前置核验：CW-025（de737aa / PR #7，`docs/evidence/CW025-EVIDENCE.md` 在 main）、CW-054（91014f6 / PR #14）、CW-053（e817d93 + W0 #107 26e596c，`docs/evidence/CW053-DB-SEMANTIC-INVENTORY.md` 在 main）——三者均已合入最新 origin/main。
上游规格：V3 收敛清单「CW-057 统一剩余维护与种子CLI的PG入口」；PG-01（全环境唯一数据库）与 PG-08（工具与备份）责任行；排班清单 §3/§4/§5；审计 `audit/backend.json` CW-057 条目（status=partial，remaining 三条）。

---

## 1. 交付差额（对审计 remaining 三条逐一收口）

| 审计 remaining | 本 PR 处置 |
| --- | --- |
| gate1_bootstrap、gate1_e2e、app.backup 与 internal backup systemd 仍是 SQLite 当前入口 | gate1_bootstrap/gate1_e2e → **current→PG**（代码转换，见 §2/§3）；app.backup + `video-replica-backup.{service,timer}` → **historical-internal-p0**（模块横幅注册 + 隔离横幅守卫 + 客户链零引用守卫；物理退出归 CW-040/CW-042，客户正式包排除归 CW-032），见 §4 |
| 盘点全部 HTTP 外命令，逐个标 current→PG / historical→CW-060 / retire；未知项不得遗漏 | 命令×分类矩阵见 §5，并以 `server/tests/test_cw057_cli_pg_entry.py` 的注册表断言固化为**机器可核验**：server/scripts 全部模块、deploy/systemd 全部 unit、deploy/postgres 全部 shell 工具、scripts 离线工具逐一登记，任一新增未登记文件都会使测试失败 |
| 当前命令必须拒绝缺/错 DSN 与 SQLite 参数；只读不写、写命令审计/幂等、备份目标与日志脱敏 | 新增统一入口 `app.db_pg.resolve_cli_pg_dsn`；逐命令拒绝矩阵 + 有效 PG 成功 + 只读零变化测试见 §6；脱敏见 §7 |

**剔除范围（不重复开发）**：`sqlite_to_postgres.py`、`reconcile_customer_billing.py` 属 CW-060 隔离制品，本 PR 零触碰（并有反向守卫断言其未接入统一入口）；实际恢复演练归 CW-048；PG migrate/PITR 工具已存在（复用、注册，不重写）。

## 2. 统一 PG 入口：`app.db_pg.resolve_cli_pg_dsn`（新增，附加式）

- `--database-url` 参数优先；为空时**逐字沿用 CW-025 的 `resolve_database_config()` fail-closed 契约**（缺 DSN / `sqlite://` / `VIDEO_REPLICA_DB_PATH` 残留 → 异常，消息与运行时 lane 一致）。
- 显式 DSN 场景同样拒绝：`sqlite://` URL（PG-01：SQLite 参数不得到达连接层）、`VIDEO_REPLICA_DB_PATH` 环境残留（与运行时 lane 的「歧义配置即错误」同构）、非 PG scheme。
- 抛 `CliDatabaseConfigError`（继承 RuntimeError）；**在连接尝试之前**拒绝，因此失败路径不创建任何数据库文件（守卫测试在空目录运行断言 `iterdir()==[]`）。
- 消费者：4 个维护 timer CLI（purge×3、reconcile_dangling）、`gate1_bootstrap`、`gate1_e2e`。`check_ops_alerts` 沿用其既有 `resolve_database_config()+validate_customer_production()` 直连（同一契约，输出为 JSON 事件故不改）；`issue_admin_exchange_credential` 无数据库访问；`pitr_recovery_facts` 走 PGSERVICEFILE（密码不经 argv，注册为入口例外）。

## 3. gate1_bootstrap / gate1_e2e：种子与桌面 Gate-1 harness 转 PG

- **gate1_bootstrap**：`--db-path` + `initialize_database`（SQLite 建库）路径整体退役；新契约 = 只接受 PG DSN → 要求目标已迁移到 head（`to_regclass('public.users')` 缺失即报「先跑 deploy/postgres/migrate.sh / alembic upgrade head」）→ 单事务种子（`pg_advisory_xact_lock` 串行化 + pristine 检查：已含用户行的库拒绝再种子，取代旧「文件已存在即拒绝」语义）→ 种子内容与旧版逐字段同义（admin 用户、10 信用钱包、PAID 充值单、CHARGE 流水、runtime_settings 6/2/local）。PG 约束差异修正：`recharge_orders` 按迁移 026 的约束模型写 `provider='admin_adjustment' + pricing_scope='INTERNAL' + status='PAID'`（无第三方交易号、不受 zpay 金额梯度约束），替代 SQLite 时代的 `channel='gate1_fixture'` 字面量。
- **gate1_e2e**（`npm run test:gate1` 的底层 harness）：新增 `--database-url`（默认 env）；顺序为 DSN 解析 → 进程内 `alembic upgrade head`（与 `pg_test_kit.upgrade_test_database_to_head` 同法；生产迁移入口仍是 migrate.sh，harness 只迁移自己的 Gate-1 库）→ PG 种子 → 以 `VIDEO_REPLICA_DATABASE_URL`（并**显式弹出** `VIDEO_REPLICA_DB_PATH`）拉起 API/Worker/Playwright，桌面 auth 模式不变。运行元数据 runtime 字段同步改为 PostgreSQL。API/Worker 的 PG lane 在本基线已可用（lifespan 走 customer lane 的 `resolve_database_config`；generation_worker 全部 `pg_transaction`+`BusinessConnection.postgres`）。
- 语义漂移声明：Gate-1 harness 的**数据库**从桌面 SQLite lane 切到 PG lane（auth 仍是 desktop 身份）。这与 2026-09-08「开发均使用 PostgreSQL」决议一致，也与 CW-021（删除桌面本地后端，届时本 harness 随之退役）同向；桌面 SQLite 运行时本体（`bootstrap_runtime`、internal lane）零触碰，归 CW-030/CW-040。

## 4. app.backup 与 internal backup systemd：注册为 historical-internal-p0

- `server/app/backup.py` 仅新增模块 docstring 分类横幅（零代码改动）：internal P0 SQLite lane 专用；客户 PG 备份路径是 `deploy/postgres/pitr-*.sh`（pg_basebackup + WAL，已有），SQLite backup timer 不进客户正式部署（排除动作在 CW-032 打包面），整条 internal lane 随 CW-040/CW-042 退出；`sqlite_to_postgres`（CW-060 制品）对 `SqliteSnapshot`/`create_readonly_snapshot` 的复用保持原样。
- 新守卫：`video-replica-backup.service` 必须保留 "Internal P0 SQLite only" 隔离横幅；`deploy/customer-git-rollout.sh`、`deploy/customer.env.example`、maintenance/pitr 两个客户 unit 零 `app.backup`/`video-replica-backup` 引用；customer.env.example 中该 timer 只允许出现在注释行（现有「旧的 video-replica-backup.timer 只适用于内部 SQLite P0」说明保留，正是 PG-08 要求的注册形态）。

## 5. 命令×分类×数据库×角色×写入/审计/幂等矩阵

**current-pg（在线通道，全部经统一入口或既有 PG-only 解析器）**

| 命令 | 数据库 | 角色 | 写入/审计/幂等 |
| --- | --- | --- | --- |
| `python -m scripts.purge_idempotency_envelopes` | PG 业务库 | maintenance timer | 写（窗口清除）；按恢复窗重跑=0；仅计数输出 |
| `python -m scripts.purge_expired_export_ciphertexts` | PG 业务库 | maintenance timer | 写；按保留窗重跑=0；仅计数输出 |
| `python -m scripts.purge_stale_rate_limit_counters` | PG 业务库 | maintenance timer | 写；追加式失败审计表不动；仅计数输出 |
| `python -m scripts.reconcile_dangling_billing_reservations` | PG 业务库 | 对账 timer | 写（SETTLE/RELEASE 补账）；ledger 键幂等；仅计数输出 |
| `python -m scripts.check_ops_alerts` | PG（ops 状态） | ops 告警 timer | 探测读 + advisory-lock 状态写；错误只输出异常类型（脱敏） |
| `python -m scripts.pitr_recovery_facts` | PG（PGSERVICEFILE，无 argv 密码） | 备份核验 | capture 写 manifest 文件；verify 只读 |
| `python -m app.gate1_bootstrap` | PG 业务库（pristine 迁移库） | 种子 | 单事务 + advisory lock + pristine 拒绝重种；摘要 DSN 脱敏 |
| `python -m app.gate1_e2e` | PG 业务库（harness 自迁移） | dev E2E harness | 拉起 API/Worker/Playwright 于 PG lane |
| `python -m app.bootstrap provision-empty-customer` | PG 业务库 | 管理开通 | 一次性 SERIALIZABLE + advisory lock + pristine 检查（既有） |
| `deploy/postgres/migrate.sh`、`pitr-backup.sh`、`pitr-fetch-wal.sh`、`pitr-preflight.sh`、`pitr-restore-drill.sh` | PG | 迁移/备份 | PG 原生工具链（复用，CW-056 拥有 migrate.sh 语义） |

**current-offline（无数据库）**

| 命令 | 角色 |
| --- | --- |
| `python -m scripts.issue_admin_exchange_credential` | 管理凭据签发（HMAC，打印一次，零 DB） |
| `scripts/p0_acceptance_evidence.py`、`scripts/customer_release_preflight.py`、`scripts/verify_no_secrets.sh`、`scripts/require_customer_api_base.mjs`、`scripts/verify_customer_bundle.mjs` | 验收/发布/扫描离线工具 |
| `scripts/pg-fixture.sh`、`scripts/dev-with-pg.sh` | TEST-PG 资源与开发 lane（PG） |

**historical（登记保留，不在客户在线通道）**

| 命令/单元 | 分类 | 去向 |
| --- | --- | --- |
| `python -m app.backup` + `video-replica-backup.{service,timer}` | historical-internal-p0 | 客户正式包排除=CW-032；internal lane 退出=CW-040；代码裁剪=CW-042 |
| `python -m scripts.sqlite_to_postgres`、`python -m scripts.reconcile_customer_billing` | historical-cw060 | 仅 CW-060 隔离 operator 制品可达（本 PR 零触碰） |
| `video-replica-api{,@}.service`、`video-replica-worker{,@}.service` | runtime | 运行时入口（PG lane 由 CW-025 lifespan 契约承载；internal lane 退出归 CW-030/CW-040） |

未知项=0：`server/scripts/*.py`（除 `__init__.py`）、`deploy/systemd/video-replica-*`、`deploy/postgres/*.sh` 全目录扫描断言逐一命中注册表（`test_every_server_scripts_module_is_classified`、`test_every_deployed_unit_is_classified`）。

## 6. 验证记录（本机，Windows / Python 3.12.14 / vs-pg-dev 容器 5434）

测试资源：`vs-pg-dev`（postgres:16.15-alpine，host 5434，devuser）——沿用 CW-054/055 的实例约定；本任务专用库名 `cw057_gate1_seed_test`（已按 CW-054 先例追加进 `pg_test_kit.RECORDED_TEST_DATABASES` 白名单，纯增量）；fcntl Windows shim（`.dev-env/pyshim`）经 PYTHONPATH 仓外注入，仓内零改动；未与主 worktree（CW-056@5435）或 CW-031（@5436）并发跑任何测试。

- **新增专项**（`tests/test_cw057_cli_pg_entry.py` 37 用例 + `tests/test_gate1_bootstrap.py` 重写 8 用例 + `tests/test_gate1_e2e.py` 更新）：
  - 注册表完备性：scripts 模块、systemd unit、postgres shell 工具、离线工具全目录扫描逐一命中矩阵；
  - 统一入口语义：current CLI 源码必须经 `resolve_cli_pg_dsn`/`resolve_database_config` 且不得 `import sqlite3`；CW-060 两文件必须**未**接入（边界反向钉住）；
  - 拒绝矩阵（无 PG 可达环境运行）：4 个 timer CLI × {缺 DSN、空 DSN、sqlite:///、错误 scheme、显式 PG DSN+DB_PATH 残留} → 全部 exit 1 且 `iterdir()==[]`（零文件创建）；gate1_bootstrap 同矩阵 6 例；`gate1_e2e` CLI 对 sqlite DSN 在任何 harness 动作前 exit≠0 且零产物；
  - 有效 PG 成功：4 个 timer CLI `--dry-run` 于真实迁移库 exit 0（只读模式业务表变化=0 的读侧证明）；purge CLI 实写模式连续两次 exit 0（第二次无可清=幂等不退化）；
  - gate1 种子契约：迁移库种子→用户/钱包/充值单/CHARGE/runtime 逐断言、摘要 DSN 脱敏（无凭据、等于 `redact_postgres_dsn`）；二次种子 RuntimeError("not pristine") 且零部分写入；未迁移库 → "run migrate.sh first"；客户部署链零 SQLite backup 引用；internal unit 隔离横幅保留。
- **回归复验**（零回归）：`test_db_pg.py + test_db_portable.py + test_bootstrap_all_env_pg_gate.py + test_customer_idempotency.py + test_ops_alerts.py + test_customer_pitr.py` → **234 passed, 1 skipped**；`test_customer_security.py + test_activation_code_service.py + test_wallet_billing_service.py + test_customer_fencing.py` → **139 passed**（覆盖 4 个被改 CLI 的全部既有行为契约与其余 CW-055 fencing 面）。
- **静态门（本机）**：`uv run mypy app` → 104 source files 无问题；`uv run ruff check .` → All checks passed；`uv run ruff format --check .` → 297 files already formatted；`bash scripts/verify_no_secrets.sh` → No hardcoded secrets detected；`npm run check --workspace client`（biome+tsc+vitest）→ 80 files / 1296 tests 全过；`npm run check:e2e` → 15 files 无修正；`check:tauri` 本机无 cargo 不可执行（CW-054 先例：零 Rust 改动，由 CI 三门禁承载）。
- **全量 pytest（顺序，本机唯一一次）**：PG fixture（scripts/pg-fixture.sh，单容器 5433）+ `PYTHONUTF8=1` → **28 failed, 2319 passed, 2 skipped, 38 errors in 3533.95s**。非绿逐类归因（与 CW-055/056 证据登记的 Windows 环境基线逐类一致，**零新增**）：28 failed = 22 × `test_cw033_pitr_drill_validation.py`（子进程调 `.sh` → `FileNotFoundError [WinError 2]`）+ 6 × `test_simple_character.py`（本机无 ffmpeg，`SIMPLE_CHARACTER_IMAGE_VALIDATION_UNAVAILABLE`）；38 errors 全为 `test_oral_domain.py` 的 `MediaToolUnavailable`（ffmpeg 缺失，与基线 38 逐数一致）。本任务三个测试文件（cw057/gate1_bootstrap/gate1_e2e）零 FAILED/ERROR。附注：同日曾先试 4 分片并行（`CI_SHARD_BASE_PORT=25433`），因宿主机同时存活 4 个其它任务常驻 PG 容器（5434-5437）导致分片容器中途不可达（726 errors 全为 fixture connection timeout），已改顺序全量取得上述干净信号；分片中 30 failed 与顺序全量 28 failed + 2 个容器中断连逐一对齐，**未采用并行结果作证据**。全量绿的最终判定权归 CI Linux 门。

## 7. 日志与输出脱敏

- gate1 种子摘要：`database` 字段经 `app.db_pg.redact_postgres_dsn`（既有单一脱敏器），密码不落 stdout/日志/证据（有专项断言）。
- 统一入口的错误消息为**固定文案**，从不回显 DSN 内容（沿用 check_ops_alerts 的脱敏原则）。
- 4 个 timer CLI 输出保持仅计数；`check_ops_alerts` 保持 JSON 事件式错误。

## 8. 文件清单（全部在认领边界内）

- 改：`server/app/db_pg.py`（+`CliDatabaseConfigError`/`resolve_cli_pg_dsn`，纯附加，零既有行为改动）
- 改：`server/scripts/purge_idempotency_envelopes.py`、`purge_expired_export_ciphertexts.py`、`purge_stale_rate_limit_counters.py`、`reconcile_dangling_billing_reservations.py`（DSN 解析块替换为统一入口；退出码 1 与既有测试契约不变）
- 改：`server/app/gate1_bootstrap.py`（SQLite→PG 重写）、`server/app/gate1_e2e.py`（PG harness 化）
- 改：`server/app/backup.py`（仅 docstring 横幅）、`server/tests/pg_test_kit.py`（+1 白名单库名，纯增量）
- 增：`server/tests/test_cw057_cli_pg_entry.py`
- 改：`server/tests/test_gate1_bootstrap.py`（SQLite 版→PG 版，旧用例的 PG 替代一一对应，无删测）、`server/tests/test_gate1_e2e.py`（环境构造与 manifest 用例随实现更新）
- 文档：`docs/evidence/CW057-EVIDENCE.md`（本文件）、`docs/客户版任务清单-V3.md`（§18 CW-057 行）、`docs/客户版代码开发清单-V3.md`（CW-057 增量映射节）、`docs/CUSTOMER-TASK-EVIDENCE-V3.md`（CW-057 登记）
- 零触碰：`server/scripts/sqlite_to_postgres.py`、`reconcile_customer_billing.py`（CW-060）；`server/migrations/**`、`deploy/postgres/migrate.sh`、`test_postgres_migrations.py`（CW-056）；`server/app/db_portable.py`（CW-054 面，零改动）；`server/app/storage.py`/`media_routes.py`（CW-031）；`server/app/customer_fence.py`/`auth.py`（CW-026 在制域）

## 9. 诚实边界（未测试/未宣称）

- **Gate-1 Playwright 全链路（`npm run test:gate1`）本机未执行**：需要 ffmpeg + npm dev server + 浏览器栈，属人工门；本 PR 交付的是 harness 的 PG 化与可复验组件（DSN 解析、迁移调用、种子、子进程环境），E2E 实跑留桌面验收窗（且 CW-021 后该 harness 退役）。API/Worker 于 PG lane 的就绪性由 234+139 的既有套件间接覆盖。
- 全量 pytest 的最终判定权归 CI（本机 Windows 的 ffmpeg/`.sh` 子进程类环境性失败按 CW-054/055 先例不在本机追绿）。
- `app.backup` 仅注册未退役：物理隔离/删除是 CW-060/CW-040/CW-042 的明确职责，本任务不越界提前删除（PG-08 的「退出正式部署」以客户链零引用守卫守住可达性下限）。
- 证据等级 `AUTOMATED_VERIFIED`（本地自动化）；不宣称 STAGING_VERIFIED 及以上。

## 10. 与 CW-060 的错开声明

CW-060 截至 `origin/main@e829ad1` 尚未启动（无同编号分支、无 claim、无 PR）。本任务不改其两个登记文件，不引入 backup/scripts 面的语义耦合；其未来隔离工作（移动 `backup.py`/`db.py` 的 SQLite 面）将以本文件的注册横幅与矩阵为输入，反向冲突风险低。
