# CW-059 证据：补齐账务与全部任务测试的真实PG覆盖

- 任务：CW-059（W6·代码与测试增量）——账务/支付/钱包 + 全部任务域（生成/口播/图片/首帧/源帧/拆解/改写/ASR）测试迁真实 PG 多连接
- 分支：`feat/customer-v3-cw059-billing-task-pg-tests`（基线 origin/main@`38ae06c`，worktree `.worktrees/CW-059-billing-task-pg-tests`）
- 证据等级目标：AUTOMATED_VERIFIED（本任务交付矩阵范围）；账务/任务域**全量**映射闭合按完工标准交 CW-043 汇总，财务/任务域 PG 覆盖交**独立复核**（本会话为实现者，不自评自合）
- 证据日期：2026-09-11 · 维护人：CW-059 Owner（claim 见 `.git/codex-task-claims/CW-059/claim.json`，owner=task-7bf）

## 1. 交付范围与方式

按 CW-058 / CW-029 交付同形：沿用既有行为测试的持久化断言，把它们整体重放在真实
PostgreSQL 多连接上（新增 `test_cw059_billing_pg_matrix.py` + `test_cw059_task_worker_pg_matrix.py`），
而不是改写旧 SQLite 文件的 fixture。原因与边界：

1. 前置 CW-054/055 已把业务 SQL 收敛为「PG 规范式 + translate_to_sqlite 降级」，服务层
   不含 SQLite 专有 SQL；CW-029/CW-030 已建账务/Worker 平行 PG 矩阵但**未迁移旧 SQLite
   套件本身**（`test_cw029_billing_pg_matrix.py` docstring 明列 `test_payments.py` 仍跑
   legacy SQLite lane 为「CW-029 closes 的 gap」）。因此 CW-059 的实质是**旧断言组 → 同一
   不变量在 PG 多连接通道复现 + 补 DoD 特定场景**（PG-06 账务/任务半边）。
2. 旧 SQLite 测试文件本任务**一个不删**（§3 给出逐文件映射与替代/退休编号）；它们继续覆盖
   内部桌面通道（CW-042 移除在线 SQLite 实现时统一退休），不构成本组 TEST-PG 类的替代证据。
3. 本任务不重建状态机/账务逻辑、不新增 ORM/多后端抽象（剔除重复开发：不从零重写状态机/
   账务测试、不以 H3 一组替代全部任务）；`server/app/*` 仅在 RED 暴露真实 PG-lane 缺陷时
   做最小修复（如 CW-058 的 `rowid`→`ctid`），SQLite 专有入口的移除归 CW-042，不在本任务。

## 2. 测试资源与合同（PG-05）

| 项 | 值 |
| --- | --- |
| PG server_version | PostgreSQL 16.15（docker `postgres:16.15-alpine`，容器 `vs-pg-cw059`） |
| 隔离 | 宿主端口 **5437**（与在用 5432 backend-dev / 5433 CI 收敛线 / 5434 vs-pg-dev / 5435 cw056 / 5436 cw031 / 5440 cw058 全隔离）；专属库 `cw059_billing_test` + `cw059_task_test` |
| 凭据 | `devuser/devpass`（复刻 vs-pg-cw058 容器配置；LOCAL DEV ONLY，非生产密钥） |
| DSN 注入 | `TEST_POSTGRESQL_URL=postgresql://devuser:devpass@localhost:5437/customer_v3_test`；建库经 `pg_test_kit.create_test_database`（allowlist 已登记 `cw059_billing_test`/`cw059_task_test`） |
| schema | `upgrade_test_database_to_head`（alembic head=`081_oral_unit_price`） |
| 缺库行为 | `require_pg_or_explicit_skip()` 硬失败，无 `VIDEO_REPLICA_TEST_ALLOW_PG_SKIP`；本组目标 0 skip |
| 用例隔离 | 每用例 `session_replication_role=replica` 下 TRUNCATE（与 CW-058/`pg_test_kit.seed_customer_scenario` 同款） |
| 业务通道 | 全部经生产 PG 通道：`DATABASE_URL_ENV` 分支 / `pg_transaction` / `BusinessConnection.postgres` / `run_pg_worker_once`；零 `sqlite3.connect`、零 `DB_PATH`、零 `BusinessConnection.sqlite` |
| Windows 运行 | venv Python 3.12.14（`xiangshu-video-replica-\server\.venv`）+ CWD=worktree/server（app 解析到 worktree 代码，非主仓）+ `PYTHONPATH=.dev-env/pyshim`（fcntl shim）；runner 见 `.dev-env/run-cw059-pytest.ps1` |

**与其它在制任务的资源合同：**

1. 命名边界：CW-059 只新增/引用 `test_cw059_*` 测试文件；不触碰 `test_cw058_*`（内容/资产，已合并 #33）、`test_cw031_*`（云端资产，在制）。
2. 端口/库隔离：CW-059 用 5437 + `cw059_*_test`；不复用他任务在用容器/库（§2.2 L57「与 031 分开任务/资产用例及 PG 资源」）。
3. 库名 allowlist：`cw059_billing_test`/`cw059_task_test` 已登记 `pg_test_kit.RECORDED_TEST_DATABASES` 并以 `_test` 结尾。

## 3. 旧断言 → PG 用例映射（逐文件全量登记）

「替代」= 本矩阵用例复现其持久化不变量；「保留」= 旧文件继续覆盖内部桌面通道，在 CW-042
移除在线 SQLite 时随通道退休（登记于 CW-043 全量核销）；「机制退休」= 断言依赖 SQLite 引擎
内省或 SQLite 迁移链（TEST-HISTORY），在 PG 上由等价结果断言替代或归历史工具；「引用」=
不变量已由既有 PG 矩阵覆盖，本任务登记指向不重做。

> 断言级替代编号已随 Segment 1（账务 §3.1.1，12 用例）/ Segment 2（任务 §3.2.1，14 用例）/
> Segment 3（权限 §3.3.1，7 用例）逐条回填；文件级定域与处置为 Segment 0 交付，边界悬案已用测试函数名证据裁决。

### 3.1 账务/支付/钱包域（Segment 1 → `test_cw059_billing_pg_matrix.py`，库 `cw059_billing_test`）

| # | 旧测试文件（SQLite 通道） | 行 | 关键持久化断言 | 处置 |
| --- | --- | --- | --- | --- |
| B1 | test_payments.py | 772 | ZPay 回调验签/订单状态机/跨用户订单隔离/重复回调幂等/查询客户端 | 替代+保留（CW-029 建平行矩阵但未迁本文件，本组补映射） |
| B2 | test_recharge_orders.py | 404 | 充值订单创建/支付确认/到账入账/幂等/属主 | 替代+保留 |
| B3 | test_internal_billing.py | 272 | reserve/settle/release + billing_round 幂等 + available/reserved/ledger 差额 | 替代+保留 |
| B4 | test_wallet_routes.py | 142 | 钱包路由/余额/交易历史属主隔离 | 替代+保留 |

**DoD 特定场景（Segment 1 在真实 PG 多连接证明）**：账务差额=0（逐例 available+reserved+ledger 对账）·重复付费=0·重复入账=0·历史价格快照不可被现价改写·支付回调验签·跨用户订单隔离。

> 分工说明：上述「支付回调验签 / 跨用户订单隔离 / 历史价格快照 / 乱序幂等」由 **CW-029**
> `test_cw029_billing_pg_matrix.py` 在 PG 证明（本任务**引用**不重做）；「钱包 RESERVE/SETTLE/RELEASE
> 逻辑 / 按秒 / dangling-sweep / SAVEPOINT / 钱包行锁 overspend」由 **CW-010**
> `test_wallet_billing_service.py` 证明（引用）。Segment 1 本组 12 用例填补的是二者留下的
> **裸 DB 约束强制 + 全局唯一键的真实多连接并发**缺口（旧 `test_internal_billing.py` 仅 SQLite
> `IntegrityError` 单连接断言）。

#### 3.1.1 断言级映射（Segment 1 交付：`test_cw059_billing_pg_matrix.py`，12 用例全 GREEN）

| # | CW-059 PG 用例 | 旧 SQLite 断言（文件::函数·arm） | PG 机制（真实 5437 证明） | 处置 |
| --- | --- | --- | --- | --- |
| S1-01 | test_pg_wallets_reject_negative_available_and_reserved | test_internal_billing.py::test_wallets_reject_negative_balances | CheckViolation 23514 · ck_wallets_available_nonnegative / ck_wallets_reserved_nonnegative · 拒绝后余额仍 (100,0) | 替代 |
| S1-02 | test_pg_recharge_orders_reject_duplicate_merchant_order_no | test_internal_billing.py::test_recharge_orders_reject_duplicate_merchant_and_provider_numbers（merchant arm） | UniqueViolation 23505 · merchant_order_no 列 UNIQUE · count=1 | 替代 |
| S1-03 | test_pg_recharge_orders_reject_duplicate_provider_trade_no | 同上（provider_trade_no arm） | UniqueViolation · uq_recharge_orders_provider_trade_no（部分 WHERE NOT NULL）· count=1 | 替代 |
| S1-04 | test_pg_recharge_orders_reject_blank_provider_trade_no | 同上（空串 arm，order_5） | CheckViolation · ck_recharge_orders_provider_trade_no（**026 重塑 022 的 _not_blank** 为 provider/status/trade-no 耦合）| 替代（RED→GREEN，见 §4） |
| S1-05 | test_pg_wallet_transactions_reject_duplicate_idempotency_key | test_internal_billing.py::test_wallet_transactions_reject_duplicate_charge_reserve_and_terminal（idempotency arm） | UniqueViolation · idempotency_key 列 UNIQUE（跨 order 复用）· count=1 | 替代 |
| S1-06 | test_pg_wallet_transactions_reject_duplicate_charge_per_order | 同上（CHARGE arm） | UniqueViolation · uq_wallet_transactions_charge_order（部分 WHERE type='CHARGE'）· count=1 | 替代 |
| S1-07 | test_pg_wallet_transactions_reject_duplicate_reserve_round | 同上（RESERVE arm） | UniqueViolation · uq_wallet_transactions_reserve_round（部分 WHERE type='RESERVE'）· count=1 | 替代 |
| S1-08 | test_pg_wallet_transactions_reject_duplicate_terminal_round | 同上（terminal SETTLE/RELEASE arm） | UniqueViolation · uq_wallet_transactions_terminal_round（部分 WHERE type IN('SETTLE','RELEASE')）· count=1 | 替代+引用（prior art test_postgres_migrations.py::test_pg_wallet_terminal_round_row_level） |
| S1-09 | test_pg_wallet_transactions_reject_malformed_ledger_shape | 旧 SQLite 无等价（057 按秒形状 CHECK） | CheckViolation · ck_wallet_transactions_shape（RESERVE 需 available_delta=-reserved_delta AND reserved_delta>=1；(-1,+2) 被拒）· count=0 | 新增证明 |
| S1-10 | test_pg_ledger_sequence_is_immutable_on_update | test_internal_admin.py::test_wallet_ledger_sequence_migration_is_reversible（UPDATE-immutable arm，sqlite3.IntegrityError match="immutable"） | RaiseException P0001 · 063 BEFORE UPDATE 触发器 "ledger_sequence is immutable" · 拒绝后 ledger_sequence 未变 | 替代+引用（CW-056 已证 INSERT "database assigned"） |
| S1-11 | test_pg_concurrent_duplicate_merchant_order_no_commits_exactly_once | 旧单连接无法证（DoD「真实 PG 多连接」新证） | 双独立连接 barrier race 同 merchant_order_no · sorted(outcomes)==["duplicate","inserted"] · count=1 | 新增证明（多连接） |
| S1-12 | test_pg_concurrent_duplicate_charge_per_order_commits_exactly_once | 旧单连接无法证（DoD「真实 PG 多连接」新证） | 双连接 race 同 order_1 CHARGE 不同 idempotency_key · 063 wallets FOR UPDATE 行锁 + 部分唯一索引共同序列化 · sorted==["duplicate","inserted"] · count=1 | 新增证明（多连接） |

**去重裁定（DoD「剔除重复开发」）**：S1-01..10 逐一映射旧 SQLite 约束断言到真实 PG；S1-11/12 是旧单连接
测试**无法证明**的多连接并发唯一性（DoD 明列「约束 / 真实 PG 多连接」）。支付回调矩阵 / 钱包逻辑 /
属主隔离分别引用 CW-029 / CW-010 / CW-026，本组**不重做**。

### 3.2 任务/生成域（Segment 2 → `test_cw059_task_worker_pg_matrix.py`，库 `cw059_task_test`）

| # | 旧测试文件（SQLite 通道） | 行 | 关键持久化断言 | 处置 |
| --- | --- | --- | --- | --- |
| T1 | test_generation.py | 6887 | 生成批次/任务状态机/取消/lease/公平排队 | 替代+保留（CW-030 建平行矩阵但未迁本文件） |
| T2 | test_first_frames.py | 2058 | 首帧任务持久化/lease/worker 消费 | 替代+保留（CW-058 §7.2 移交 CW-059） |
| T3 | test_character_image_generation.py | 1235 | 图片生成 7 视图/lease-fencing/stale worker 不可 finalize/cost actual/retry-expired lease 恢复 | 替代+保留（图片**生成任务/Worker** 域，非 CW-058 人物内容/资产） |
| T4 | test_script_rewrite.py | 1071 | 文案改写任务/lease/结果持久化 | 替代+保留 |
| T5 | test_source_frames.py | 778 | 源帧拆解任务持久化/worker | 替代+保留（CW-058 §7.2 移交 CW-059） |
| T6 | test_script_from_audio.py | 601 | ASR 任务/lease/Provider 超时/UNCERTAIN 语义 | 替代+保留（CW-058 §7.2 移交 CW-059） |
| T7 | test_e2e_fake_provider.py | 407 | 生成端到端（fake provider，依赖 test_generation helpers） | 替代+保留 |

**DoD 特定场景（Segment 2 在真实 PG 证明）**：混合任务队列（逐类策略）·未知收费·迟到 lease/epoch 写拒绝（fenced）·FOR UPDATE SKIP LOCKED（双抢互斥）·advisory lock·约束（FK/UNIQUE/check）·不确定提交恢复（SUBMISSION_UNCERTAIN→exactly-once）·Provider 请求次数证据（无重复提交）。

#### 3.2.1 断言级映射（Segment 2 交付：`test_cw059_task_worker_pg_matrix.py`，14 用例全 GREEN）

| # | CW-059 PG 用例 | 旧断言 / DoD 类别（文件::函数·arm） | PG 机制（真实 5437 证明） | 处置 |
| --- | --- | --- | --- | --- |
| S2-01 | test_pg_generation_tasks_reject_negative_attempt | DoD「约束（check）」·旧 flow 仅播种合法 attempt | CheckViolation 23514 · `generation_tasks_attempt_check`（attempt>=0）· 账务域 S1-01 的任务域镜像 | 新增证明 |
| S2-02 | test_pg_generation_batches_reject_duplicate_idempotency_key | test_postgres_migrations.py 仅断名 `uq_generation_batches_user_project_key` 存在 | UniqueViolation 23505 · 同约束**强制**拒绝第二个 (created_by_user_id,project_id,idempotency_key) · count=1 | 替代（名→强制） |
| S2-03 | test_pg_generation_tasks_reject_orphan_batch_foreign_key | DoD「约束（FK）」·旧仅 migrations 断名 | ForeignKeyViolation 23503 · `generation_tasks_batch_id_fkey` 拒绝孤儿 batch | 新增证明 |
| S2-04 | test_pg_generation_batch_delete_cascades_to_tasks | DoD「约束（FK）」级联 | `generation_tasks_batch_id_fkey … ON DELETE CASCADE` · 删 batch_1 → 2 个 task 同删 · count=0 | 新增证明 |
| S2-05 | test_pg_character_generation_tasks_reject_uncertain_status | CW-002 登记限制（人物图无 SUBMISSION_UNCERTAIN）·CW-030 行为级登记（attempt 耗尽 fail-closed） | CheckViolation · `ck_character_generation_tasks_status` 仅 PENDING/RUNNING/SUCCEEDED/FAILED · UNCERTAIN 在 schema 层不可表示 | 新增证明（DB 级 CW-002 限制） |
| S2-06 | test_pg_source_frame_tasks_reject_uncertain_status | CW-030::test_source_frame_expired_fails_closed_to_manual_recovery（L839，行为级） | CheckViolation · `ck_source_frame_tasks_status` 排除 SUBMISSION_UNCERTAIN（源帧 fail-closed 到人工恢复，从不自动 uncertain） | 新增证明（DB 级） |
| S2-07 | test_pg_first_frame_tasks_status_enum_boundary | 与 S2-05/06 对比·旧无逐类 enum 边界断言 | `ck_first_frame_tasks_status` **接受** SUBMISSION_UNCERTAIN（图片任务隔离过期在途提交）但拒绝 BOGUS_STATUS · 精确钉住逐类 enum 边界 | 新增证明 |
| S2-08 | test_pg_operation_cost_records_accept_unknown_reject_bad_status_and_unit | DoD「未知收费」·flow 级已由 test_operation_costs.py::test_missing_provider_usage_is_recorded_as_unknown（L262，app 写 UNKNOWN cost_status）覆盖 | `ck_operation_cost_status` **接受 UNKNOWN** + 拒绝 BOGUS·`ck_operation_cost_unit` 拒绝 bogus_unit（裸 DB 负边界，flow 从不写非法值）· count(UNKNOWN)=1 | 新增证明（约束负边界）+引用（flow） |
| S2-09 | test_pg_operation_cost_records_reject_negative_and_enforce_source_subject_unique | DoD「约束」·app 幂等 flow 已由 test_operation_costs.py::test_generic_operation_cost_is_idempotent_and_uses_rate_snapshot（L339，record_id 级）覆盖 | CheckViolation `ck_operation_cost_value_non_negative`（cost_fen=-5）+ UniqueViolation `uq_operation_cost_source_subject`（source_type,source_id,subject 裸 DB UNIQUE backstop，flow 未断）· exactly-one 成本冻结 | 新增证明（约束级）+引用（flow） |
| S2-10 | test_pg_script_rewrite_tasks_enforce_ip_profile_shape | DoD「约束（check）」·旧 test_script_rewrite.py 无裸 DB 形状断言 | CheckViolation `ck_script_rewrite_tasks_ip_profile_shape`（(identity_id,snapshot,hash) 全 NULL 或全含 64 位 hash；半填拒绝）· 逐 shape 用独立 project（proj_1/2/3/4）隔离 S2-11 部分索引 · count=2 | 新增证明（RED→GREEN，见 §4） |
| S2-11 | test_pg_script_rewrite_tasks_reject_second_active_per_project | DoD「约束」·RED 揭示的隐藏部分唯一索引（pg_constraint 探针盲区） | UniqueViolation `uq_script_rewrite_tasks_active_project`（UNIQUE(project_id) WHERE status IN('PENDING','RUNNING')）· 第二个 active 拒绝 · retire 到 SUCCEEDED 释放槽位后可再插 · count(proj_1)=2 | 新增证明（RED 升华为主动证明） |
| S2-12 | test_pg_generation_task_operations_enforce_idempotency_unique | DoD「约束（UNIQUE）」·旧无裸 DB 幂等断言 | UniqueViolation `uq_generation_task_operations_idempotency`（actor_user_id,task_id,action,idempotency_key）· 一 actor 一 action 一 task 一 key exactly-once（result_status='ACCEPTED' 避开 pending 部分索引）· count=1 | 新增证明 |
| S2-13 | test_pg_concurrent_duplicate_batch_idempotency_commits_exactly_once | test_generation.py::test_task_paid_regeneration_concurrency_creates_only_one_replacement（L1361，HTTP 层 [200,409]）·旧单连接无法证裸 DB | 双独立连接 barrier race 同 idempotency_key · `uq_generation_batches_user_project_key` 跨会话序列化 · sorted(outcomes)==["duplicate","inserted"] · count=1 | 新增证明（多连接） |
| S2-14 | test_pg_concurrent_operation_cost_freeze_commits_exactly_once | 旧单连接无法证（DoD「真实 PG 多连接」+「约束」新证） | 双连接 race 同 (generation_task,task_race,output_seconds) · `uq_operation_cost_source_subject` 决出胜者 · provider 收费永不双记 · sorted==["duplicate","inserted"] · count=1 | 新增证明（多连接） |

**去重裁定（DoD「剔除重复开发」）**：任务域已被既有 PG 套件证明的部分，本组**引用不重做**——
① 逐类 Worker claim/lease/expiry/recovery/SUBMISSION_UNCERTAIN 行为/混合队列/两设备（顺序 double-claim）
= **CW-030** `test_cw030_worker_pg_matrix.py`；② 两阶段 claim 持久化 / 过期 lease 接管 / 并发 expiry sweeper /
exactly-once 对账计费 / 拒绝猜测未知 provider id（SUBMISSION_REQUIRES_MANUAL_CONFIRMATION=未知收费）/
dangling-RESERVE / worker 循环 drain / **真·多连接 FIFO double-claim race 由 FOR UPDATE SKIP LOCKED 收口** =
**crash-recovery** `test_worker_crash_recovery.py::test_fifo_double_claim_race_skips_locked_head`（T26）；
③ 4 线程 drain 负载 + EXPLAIN 计划/索引断言 = `test_queue_load_10k.py`；④ 任务表 upgrade head 后**存在** +
约束**名存在** + 部分索引 WHERE 子句 = `test_postgres_migrations.py`；⑤ **未知收费 / 成本快照 / 幂等 / replay**
的 app 函数级 flow = `test_operation_costs.py`（库 operation_costs_test@5433）；⑥ **advisory lock**（DoD）=
`test_sqlite_to_postgres.py` / `test_customer_ha_smoke.py` / `test_ops_alerts.py` / `test_cw057_cli_pg_entry.py`。
本组 S2-01..14 填补的 genuine gap 是上述 flow 套件**从不裸断**的任务表 DB 约束强制（CHECK/UNIQUE/FK，含
CW-002 无-UNCERTAIN 限制的 DB 级证明 + `operation_cost_records` 约束负边界）+ 全局唯一键的真实多连接并发 exactly-once。

### 3.3 权限域（Segment 3，部分归 CW-059）

| # | 旧测试文件 | 行 | 归属裁决（测试函数名证据） | 处置 |
| --- | --- | --- | --- | --- |
| P1 | test_rbac.py | 1024 | **归 CW-059 部分**：`test_cross_user_wallet_is_owner_scoped_and_not_leakable`（钱包属主隔离）·`test_project_delete_blocked_while_generation_tasks_are_active`（任务活动阻断）·`test_not_found_remap_preserves_deferred_postgres_denial_audit`（PG 拒绝审计）；**已由 CW-058 覆盖部分**：资产/下载/项目 IDOR（`test_project_owner_can_read_asset` 等，CW058-EVIDENCE §6 owner/IDOR #1/#10/#13） | 部分替代（钱包/任务/PG 审计不变量）+引用 CW-058（资产 IDOR）+保留 |

#### 3.3.1 断言级映射（Segment 3 交付：`test_cw059_rbac_pg_matrix.py`，7 用例全 GREEN）

**形态差异（与前两段纯 psycopg 裸 DB 约束不同）**：本段直调**生产路由函数** `delete_project` 本身于真实 PG
`BusinessConnection.postgres(raw)`（`with psycopg.connect(dsn) as raw:` 复现生产单事务 commit/rollback 语义，
Annotated 依赖 `Database`/`AuthenticatedUser` 传显式值绕过 FastAPI DI），从不复制其 SQL、从不 mock 数据库——
因为 L415 的不变量是「路由 `has_active_tasks` 谓词 + FK 级联 + PG-only `customer_authorization_evidence` 事务
语义」三者耦合，裸 DB 无法表达。

| # | CW-059 PG 用例 | 旧 SQLite 断言（文件::函数·arm） | PG 机制（真实 5437 证明） | 处置 |
| --- | --- | --- | --- | --- |
| S3-01 | test_pg_project_delete_blocked_by_active_generation_task[PENDING] | test_rbac.py::test_project_delete_blocked_while_generation_tasks_are_active（L415，SQLite 仅 RUNNING arm） | route-function 真 PG：`has_active_tasks` UNION 命中 PENDING → HTTPException 409 `PROJECT_DELETE_HAS_ACTIVE_TASKS` · project/task 存活（count=1）· 409 事务回滚 `require_project_access` 写的 authorization-evidence 候选（delta 0，从不落持久行） | 替代（单 RUNNING→全 in-flight 状态集） |
| S3-02 | 同上[SUBMITTING] | 同上 | 同 S3-01，状态 SUBMITTING | 替代 |
| S3-03 | 同上[QUEUED] | 同上 | 同 S3-01，状态 QUEUED | 替代 |
| S3-04 | 同上[RUNNING] | 同上（SQLite 唯一覆盖的 arm） | 同 S3-01，状态 RUNNING（与旧 SQLite 断言直接等价） | 替代 |
| S3-05 | 同上[ARCHIVING] | 同上 | 同 S3-01，状态 ARCHIVING | 替代 |
| S3-06 | test_pg_project_delete_allowed_once_generation_task_terminal[SUCCEEDED] | test_rbac.py 反向边界（SQLite 无——旧仅证阻断，未证终态放行） | route-function 真 PG：terminal SUCCEEDED → 204 · FK 级联删 projects→generation_batches→generation_tasks（三表 count=0）· audit_logs `project.delete`=1（每测试重置，证本次事务提交）· PG-only `customer_authorization_evidence`（resource_type='project'）提交=1（ON CONFLICT 去重后恒定） | 新增证明（反向边界 + PG-only 证据提交语义） |
| S3-07 | 同上[FAILED] | 同上 | 同 S3-06，终态 FAILED | 新增证明 |

**去重裁定（DoD「剔除重复开发」——§3.3 pinned 三函数，仅 L415 是 genuine gap）**：

1. **L1004 `test_cross_user_wallet_is_owner_scoped_and_not_leakable`（钱包属主隔离）→ 引用 CW-026 不重做**：
   `test_cw026_converged_auth.py::test_customer_session_reads_resolve_to_session_owner_only`（L465，库
   cw026_converged_auth_test@5433）已在收敛客户会话 PG 通道证明每个会话只读到自己的 `/api/wallet`
   （mine==theirs）+ 被顶替令牌 401 `SESSION_REPLACED` fencing（**严格更强**：含令牌取代栅栏）。
2. **L977 `test_not_found_remap_preserves_deferred_postgres_denial_audit`（PG 拒绝审计）→ 纯内存单测 + 引用 CW-010 不重做**：
   该函数是 `permissions.remap_security_denial` 的**纯内存单测**（无数据库、后端无关，无可迁移物）；其守护的
   *延迟 PG 拒绝审计写入*已由 **CW-010**（`test_oral_domain.py` / `test_independent_creation.py`：`pg_transaction`
   捕获 `AuditedSecurityDenial` → `persist_security_denial` → 持久 `audit_logs` 拒绝行）在真实 PG 证明。
3. **资产/下载/项目 IDOR → 引用 CW-058 不重做**：`test_project_owner_can_read_asset` 等已由 CW058-EVIDENCE §6
   owner/IDOR #1/#10/#13 覆盖。
4. **仅 L415（项目删除活动任务阻断）是 genuine gap**：`PROJECT_DELETE_HAS_ACTIVE_TASKS` 全套件**仅** test_rbac.py
   L429 一处（SQLite lane），PG 上从未被断言——S3-01..07 在 route-function 级真 PG 双向证明填补之。

### 3.4 TEST-HISTORY 退休 / 主体非 CW-059 核心

| # | 旧测试文件 | 行 | 归属裁决 | 处置 |
| --- | --- | --- | --- | --- |
| X1 | test_script_from_audio_migration.py | 40 | `command.upgrade(config,"076_...")` + 回滚 schema 的 alembic 迁移往返（SQLite 链专有）= TEST-HISTORY，归 CW-060 历史工具 | 机制退休（DoD：TEST-IMPORT/TEST-HISTORY 不冒充当前业务） |
| X2 | test_internal_admin.py | ~1150 | 内部**控制面**（admin）：wallet ledger sequence/价格规则不可改写等账务不变量**已由 CW-010 wallet_billing + CW-029 覆盖**；控制面设置/nginx/proxy/CSV 归 CW-027/028/040/042/043（internal lane SQLite 见 CW055-EVIDENCE §延后项） | 引用 CW-010/CW-029 + 保留（非 CW-059 核心，不重做） |

### 3.5 已 PG 化被复用（登记指向，不重做）

- CW-010：`test_wallet_billing_service.py`（钱包多连接 + ledger_sequence 因果序）·`test_oral_domain.py`（口播）·`test_independent_creation.py`（独立创作，pg_test_kit helper 首选样板）·`test_worker_crash_recovery.py`（T26，含真并发 FIFO SKIP LOCKED race）·`test_customer_queue_fairness.py`
- 任务/成本域已 PG（Segment 2 引用不重做）：`test_operation_costs.py`（未知收费/成本快照/幂等/replay，app 函数级，库 operation_costs_test@5433）·`test_queue_load_10k.py`（4 线程 drain + EXPLAIN 计划/索引）·`test_postgres_migrations.py`（表/约束名存在 + 部分索引 WHERE 子句）
- CW-029：`test_cw029_billing_pg_matrix.py`（账务差额/重复/乱序/未知提交/取消/隐藏/回调验签/跨用户）
- CW-030：`test_cw030_worker_pg_matrix.py`（逐类 Worker claim/lease/recovery，`run_pg_worker_once`）
- CW-015：`test_customer_security.py`（限流/安全，已 PG）·CW-027：`test_cw027_admin_permission_matrix.py`（管理权限矩阵，已 PG）

**重复开发剔除**：不重写 CW-029 账务矩阵 / CW-030 Worker 矩阵 / CW-010 恢复基线；不触碰 CW-058 内容/资产 30 文件；不移植 SQLite 迁移往返（TEST-HISTORY，归 CW-060）；oral_worker.py 已 PG-portable（无 sqlite 专用路径，无需改）；viral refresh worker 已由 CW-058 `test_viral_refresh_pg_lane_enqueues_and_worker_consumes_on_pg` 覆盖（避让）。

## 4. 缺陷先红后绿

**app 层缺陷：无。**账务/任务服务层经 CW-054/055 已 PG 规范式（不含 SQLite 专有 SQL）；Segment 1
矩阵为纯 psycopg DDL/约束证明，**不 import app 模块、未改一行 `server/app/*`**，RED 未暴露 PG-lane 业务缺陷。

**测试侧 RED→GREEN 四处（真实 PG 纠正源码阅读/约束探针/事务语义假设，本身即证据）**：

| 位置 | RED | 根因 | 修复 | GREEN |
| --- | --- | --- | --- | --- |
| `test_cw059_billing_pg_matrix.py::test_pg_recharge_orders_reject_blank_provider_trade_no`（S1-04） | 断言 `constraint_name == "ck_recharge_orders_provider_trade_no_not_blank"`——名取自源码阅读 `022_internal_billing.py` | 迁移 `026_customer_security_and_billing.py`（L72-99 `_PROVIDER_TRADE_NO`）将 022 的 not-blank CHECK **重塑**为更严的 provider/status/trade-no 耦合 `ck_recharge_orders_provider_trade_no`（PENDING zpay 订单必须 provider_trade_no IS NULL，故 `''` 违反）；022 旧名在 head 已不存在 | 断言改为 live PG 报的权威名 `ck_recharge_orders_provider_trade_no` + docstring 说明 026 重塑（纯测试侧，无 app 改动） | CheckViolation 正确触发·constraint_name 匹配·12/12 passed |
| `test_cw059_task_worker_pg_matrix.py::test_pg_script_rewrite_tasks_enforce_ip_profile_shape`（S2-10） | 4 个 ip-profile shape 探针全插 `proj_1`：第二个 PENDING/RUNNING 行撞 `UniqueViolation: uq_script_rewrite_tasks_active_project`（DETAIL: Key (project_id)=(proj_1) already exists），ip-profile CHECK 被部分唯一索引遮蔽——约束探针（pg_constraint contype u/c/f）**看不到** `CREATE UNIQUE INDEX … WHERE` 部分索引 | 隐藏部分唯一索引 `uq_script_rewrite_tasks_active_project`（UNIQUE(project_id) WHERE status IN('PENDING','RUNNING')）住在 pg_indexes 非 pg_constraint；首稿探针只查 pg_constraint 故漏判（与 S1-04 的 022→026 名漂移同类：源码/探针假设 ≠ live PG） | ①补 `cw059_seg2_idxprobe.py` 读 pg_indexes 拿全部唯一索引含 WHERE 谓词 ②S2-10 每 shape 用独立 project（proj_1/2/3/4）隔离 ③RED 升华为新用例 S2-11 主动证明该部分索引（含 terminal SUCCEEDED 释放槽位边界）（纯测试侧，无 app 改动） | UniqueViolation 不再误触·S2-10 ip-profile CHECK 正确断言·S2-11 部分索引边界证明·14/14 passed |

| `test_cw059_rbac_pg_matrix.py`（S3 权限矩阵，reset + 证据断言） | 第 7 用例（terminal FAILED）reset 阶段 `DELETE FROM customer_authorization_evidence` 抛 `psycopg.errors.RaiseException: customer_authorization_evidence is append-only`（CONTEXT: PL/pgSQL `customer_authorization_evidence_refuse_rewrite()` line 3 at RAISE）·1 failed/6 passed（日志 `.dev-env/cw059_seg3_run1.log`） | 该表 **append-only**：行级触发器 `customer_authorization_evidence_refuse_rewrite` 对任何 DELETE/UPDATE RAISE。前 6 用例过是因 block 分支 409 回滚（表空，行级触发器 0 行不触发）；第 6 个 allow(SUCCEEDED) 提交 1 行后，第 7 个 allow(FAILED) 的 reset DELETE 撞守卫 | ①从 `_CLEANUP_ORDER` 移除该表（只存 digest、无 FK 到 users/projects，留在库里不阻塞其余表 reset）②证据断言改 **delta 式**（调用前后行计数差）——纯测试侧，无 app 改动 | append-only 触发器不再误撞·进 RED2 |
| `test_cw059_rbac_pg_matrix.py::test_pg_project_delete_allowed_once_generation_task_terminal[FAILED]`（S3-07） | delta 式断言 `assert _count(...)==evidence_before+1` → `AssertionError: assert 1==(1+1)`·1 failed/6 passed（日志 `.dev-env/cw059_seg3_run2.log`） | `_record_authorization_evidence` 用 `ON CONFLICT (resource_type, actor_digest, owner_digest) DO NOTHING`（permissions.py L451）：两个 allow 用例都是 user_1→user_1 项目，同一 (resource_type,actor,owner) 三元组被去重为一行，故第 2 个 allow 的 delta=0（append-only 表跨用例累积、无法 reset） | allow 断言改回**存在性**（`COUNT WHERE resource_type='project' == 1`，去重后恒为 1）+ 移除 allow 用例的 `evidence_before`；`audit_logs project.delete == 1`（每测试重置）独立证明本次事务提交；block 用例保留 `delta==0` 证明 409 回滚——纯测试侧，无 app 改动 | ON CONFLICT 去重语义被正确断言·**7/7 passed**（日志 `.dev-env/cw059_seg3_run3.log`） |

> 价值：源码阅读（022）给出过时约束名、约束探针（pg_constraint）漏掉部分唯一索引、源码假设「authorization-evidence 可 reset 且逐次 +1」撞上 **append-only 触发器 + ON CONFLICT 去重**的真实事务语义——**live PostgreSQL at head 给出真相**（真名 + pg_indexes 里的隐藏 WHERE 索引 + 触发器/去重的持久化行为）。这正是本矩阵“从 PG 读真相而非从源码/探针假设”的 RED→GREEN 证据链（S1-04 名漂移 / S2-10·11 部分索引盲区 / S3 append-only + 去重，同类）。

## 5. 运行记录（自动核销）

运行环境：Windows PC-202609071434，venv Python 3.12.14，psycopg 3.3.4；`PYTHONPATH=.dev-env/pyshim`（fcntl shim）；CWD=worktree/server（app 解析到 worktree）；PG 容器 `vs-pg-cw059`（postgres:16.15-alpine，`0.0.0.0:5437->5432`，与在用 5432–5440 全隔离）。

| 轮次 | 树 | 命令 | 结果 |
| --- | --- | --- | --- |
| Segment 0 harness 自检 | 38ae06c + allowlist 编辑 | `pytest tests/test_pg_test_kit.py -q`（@5437） | **9 passed / 0 failed / 0 skipped** in 17.29s，rc=0（日志 `.dev-env/cw059_seg0_kitcheck.log`）；确认 venv+worktree+pyshim+5437+`cw059_*` allowlist 全链路可用 |
| Segment 1 账务矩阵 RED | 38ae06c + allowlist + `test_cw059_billing_pg_matrix.py`（初稿，S1-04 断言 022 旧名） | `pytest tests/test_cw059_billing_pg_matrix.py -v`（@5437，内联 venv+pyshim） | **11 passed / 1 failed** in ~8s，rc=1（日志 `.dev-env/cw059_seg1_run1.log`）；FAILED=S1-04 blank_provider_trade_no 约束名断言（022 名被 026 取代） |
| Segment 1 账务矩阵 GREEN | 38ae06c + S1-04 断言改 live PG 权威名 | 同上 | **12 passed / 0 failed / 0 skipped** in 8.27s，rc=0（日志 `.dev-env/cw059_seg1_run2.log`） |
| Segment 2 任务矩阵 RED | 38ae06c + allowlist + `test_cw059_task_worker_pg_matrix.py`（初稿 596 行 13 测试，S2-10 四探针全 proj_1） | `pytest tests/test_cw059_task_worker_pg_matrix.py -v`（@5437，内联 venv+pyshim） | **12 passed / 1 failed** in 3.07s，rc=1（日志 `.dev-env/cw059_seg2_run1.log`）；FAILED=S2-10 撞 `uq_script_rewrite_tasks_active_project` 部分唯一索引（pg_constraint 探针盲区） |
| Segment 2 任务矩阵 GREEN | 38ae06c + idxprobe 补部分索引 + S2-10 独立 project 隔离 + 新增 S2-11（14 测试） | 同上 | **14 passed / 0 failed / 0 skipped** in 3.29s，rc=0（日志 `.dev-env/cw059_seg2_run2.log`） |
| Segment 3 权限矩阵 RED1 | 38ae06c + allowlist(`cw059_rbac_test`) + `test_cw059_rbac_pg_matrix.py`（初稿 255 行，customer_authorization_evidence 在 _CLEANUP_ORDER + 存在性证据断言） | `pytest tests/test_cw059_rbac_pg_matrix.py -v`（@5437，内联 venv+pyshim） | **6 passed / 1 failed** in 3.33s，rc=1（日志 `.dev-env/cw059_seg3_run1.log`）；FAILED=第 7 用例 reset `DELETE FROM customer_authorization_evidence` 撞 append-only 触发器 `customer_authorization_evidence_refuse_rewrite` |
| Segment 3 权限矩阵 RED2 | + 移除该表出 _CLEANUP_ORDER + 证据断言改 delta 式 | 同上 | **6 passed / 1 failed** in 3.45s，rc=1（日志 `.dev-env/cw059_seg3_run2.log`）；FAILED=第 2 个 allow 用例 delta 断言 `assert 1==(1+1)`（ON CONFLICT (resource_type,actor_digest,owner_digest) DO NOTHING 去重） |
| Segment 3 权限矩阵 GREEN | + allow 断言改存在性（resource_type='project' == 1）+ 移除 allow 的 evidence_before（block 保留 delta==0） | 同上 | **7 passed / 0 failed / 0 skipped** in 2.87s，rc=0（日志 `.dev-env/cw059_seg3_run3.log`） |
| 三门禁·静态 | 38ae06c + 3 CW-059 矩阵 + pg_test_kit allowlist | `ruff check server` + `ruff format --check server` + `mypy --config-file server/pyproject.toml server/app`（venv ruff 0.16.2 / mypy 2.3.0 = uv.lock 锁定版） | ruff check **All checks passed**·ruff format --check **311 files already formatted**·mypy **Success: no issues found in 104 source files**·rc=0×3（日志 `cw059_seg3_gate_ruff_check.log`/`_ruff_format.log`）。首跑捕获 2 E501 + 3 文件需重排，`ruff format` 自动修复 + 1 处手动拆长 SQL 串（隐式拼接等值），format 后 33 PG 复跑仍 **33 passed**（`cw059_seg3_gate_pg_all_postfmt.log`） |
| 三门禁·PG 专项全量 | 38ae06c + 3 CW-059 矩阵 | `pytest test_cw059_billing_pg_matrix.py test_cw059_task_worker_pg_matrix.py test_cw059_rbac_pg_matrix.py`（@5437，三库共存） | **33 passed**（billing 12 + task 14 + rbac 7）in 16.21s·rc=0（日志 `cw059_seg3_gate_pg_all.log`）——三库（cw059_billing/task/rbac_test）共享 5437 互不干扰、无跨文件污染 |
| 三门禁·Rust/构建 | — | CI `changes` 过滤：本 diff 纯 `server/**`+`docs/**` → desktop=false·frontend=false | **CI 自身 SKIP** Rust 测试/NSIS/web build/admin build/E2E/npm audit（均 `if: desktop=='true'` 或 `frontend=='true'`）；server-only 改动实际门禁 = `check:static`（ruff+mypy）+ sharded pytest，均已 GREEN。零 client/·零 src-tauri/ 改动 |
| 缺库硬门（0 skip） | 3 CW-059 矩阵 | `TEST_POSTGRESQL_URL=...@localhost:5499/...`（不可达端口）+ `VIDEO_REPLICA_TEST_ALLOW_PG_SKIP≠1` | **33 errors / 0 skipped** in 18.56s·rc=1（日志 `cw059_seg3_gate_missingdb.log`）；`require_pg_or_explicit_skip` → `pytest.fail(pytrace=False)`“fixture is not reachable”，`-rs` 无 SKIPPED 段——缺 PG 全部硬失败，从不静默 skip 冒充证据（DoD「缺 PG skip=0」） |
| SQLite 通道回归（零回归） | 38ae06c + 全部改动 | `pytest test_internal_billing.py test_recharge_orders.py test_wallet_routes.py test_rbac.py test_script_rewrite.py`（旧账务/钱包/权限/任务 SQLite lane） | **115 passed / 0 failed** in 100.38s·rc=0（日志 `cw059_seg3_gate_sqlite_regression.log`，1 warning=既有 StarletteDeprecation 无关）——旧 SQLite 套件零回归。佐证：唯一共享代码改动 pg_test_kit.py 向 `RECORDED_TEST_DATABASES` frozenset **纯追加** 3 条，无测试断言其精确内容（grep 证实），成员检查只增不减=可证明零影响 |

## 6. 验收底线对照（V3 §18 CW-059 行）

逐条对照 DoD 保留验收底线 → 本组交付证据（Segment 1/2/3 矩阵 + 三门禁 + 既有 PG 套件引用）：

| # | DoD 验收底线 | 证据（用例 / 门禁 / 引用） | 状态 |
| --- | --- | --- | --- |
| A1 | TEST-PG 100% 真实 PG（零 SQLite 替代 / 零 mock） | 33 用例全经生产 PG 通道 @5437（裸 psycopg / `BusinessConnection.postgres` / 真 `delete_project` 路由）；§2 合同「零 sqlite3.connect·零 DB_PATH·零 BusinessConnection.sqlite」 | ✅ |
| A2 | 缺 PG skip=0（不静默跳过冒充证据） | 缺库硬门：不可达端口 → **33 errors / 0 skipped**（`require_pg_or_explicit_skip`→`pytest.fail`，§5） | ✅ |
| A3 | 账务差额=0 / 重复入账=0 / 重复付费=0 | Segment 1 S1-01..12：wallets CHECK 非负·recharge_orders/wallet_transactions UNIQUE·ledger 形状 CHECK·ledger_sequence 不可改写·多连接 exactly-once（S1-11/12）；余额对账引用 CW-029 | ✅ |
| A4 | 约束（FK / UNIQUE / check）实际强制 | Segment 1（账务约束）+ Segment 2 S2-01..12（任务域 CHECK/UNIQUE/FK/级联/部分唯一索引/enum 边界，名→强制） | ✅ |
| A5 | 真实 PG 多连接并发 exactly-once | S1-11/12（merchant_order_no / CHARGE per order）·S2-13/14（batch idempotency / operation_cost freeze）双独立连接 barrier race，sorted==["duplicate","inserted"]·count=1 | ✅ |
| A6 | 旧 lease/epoch 迟到回写拒绝（fenced） | **引用** CW-030 `test_cw030_worker_pg_matrix.py`（逐类 claim/lease/expiry/fencing）+ crash-recovery（过期 lease 接管）——本组不重做（§3.2 去重裁定①②） | ✅ 引用 |
| A7 | FOR UPDATE SKIP LOCKED（双抢互斥） | **引用** crash-recovery `test_worker_crash_recovery.py::test_fifo_double_claim_race_skips_locked_head`（T26，真·多连接 FIFO race）——本组不重做（§3.2 去重裁定②） | ✅ 引用 |
| A8 | advisory lock | **引用** `test_sqlite_to_postgres.py`/`test_customer_ha_smoke.py`/`test_ops_alerts.py`/`test_cw057_cli_pg_entry.py`（§3.2 去重裁定⑥） | ✅ 引用 |
| A9 | 不确定提交恢复（SUBMISSION_UNCERTAIN→exactly-once） | **引用** CW-030（行为级 recovery）+ 本组 S2-05/06/07 在 **DB enum 层**钉住逐类边界（人物图/源帧拒绝 UNCERTAIN=fail-closed，首帧接受=隔离过期在途） | ✅ 引用+DB 级新增 |
| A10 | 未知收费 / 成本快照 / 幂等 / replay | **引用** `test_operation_costs.py`（app flow 级）+ 本组 S2-08/09 补 `operation_cost_records` **约束负边界**（UNKNOWN 接受 / 非法 status·unit·负值拒绝 / source_subject UNIQUE） | ✅ 引用+约束级新增 |
| A11 | 权限域不变量（钱包属主 / PG 拒绝审计 / 项目删除阻断） | 钱包属主→**引用** CW-026（更强，含 SESSION_REPLACED fencing）；PG 拒绝审计→纯内存单测+**引用** CW-010；项目删除活动任务阻断→**本组 S3-01..07 genuine gap**（route-function 真 PG 双向 + PG-only authorization-evidence 事务语义） | ✅ 引用+新增 |
| A12 | 所有旧测试有映射 | §3.1（账务 B1-B4→S1）/§3.2（任务 T1-T7→S2）/§3.3（权限 P1→S3）/§3.4（TEST-HISTORY 退休 X1-X2）/§3.5（已 PG 化引用）逐文件 + 断言级全量登记 | ✅ |
| A13 | 三门禁 + SQLite 通道回归 | 静态（ruff check/format + mypy 104 files）·PG 专项全量 33 passed·Rust/构建 CI 对 server-only 自身 SKIP·旧 SQLite 套件 115 passed 零回归（§5） | ✅ |

**结论**：CW-059 DoD 全部验收底线在 Segment 1/2/3 交付矩阵 + 三门禁 + 既有 PG 套件引用下**逐条闭合**；本会话为实现者，最终证据等级 AUTOMATED_VERIFIED 交**独立复核**核定（不自评自合，§5 不自行 merge）。

## 7. 剩余范围（诚实登记，不关闭本组全量核销）

1. **旧 SQLite 文件仍在内部桌面通道运行**：§3.1/§3.2/§3.3 登记的 12 个旧文件（账务 4 + 任务 7 + 权限 1，约 1.5 万行）本任务**一个不删**，处置为「替代+保留」——它们继续覆盖内部桌面 SQLite lane，在 **CW-042** 移除在线 SQLite 实现时随通道统一退休（登记于 **CW-043** 全量核销）。本组 TEST-PG 矩阵**不构成**对这些文件逐行 1:1 迁移，而是重放其「验收底线场景类别」的持久化不变量于真实 PG + 补 DoD 特定场景 + 引用既有 PG 覆盖。
2. **逐文件全量迁移的剩余块**：若后续要求把旧 SQLite 套件的**每一条**断言都在 PG 逐行复现（而非验收底线类别 + genuine gap + 引用），该增量（类比 analytics/import 全矩阵）按 **CW-043 全量核销补漏清单**处理，不在本 CW-059 矩阵范围。
3. **去重裁定的引用依赖**：§3.2/§3.3 的 6 类引用（CW-010/026/029/030/crash-recovery/operation_costs/queue-load/migrations/advisory-lock 套件）以那些套件**持续 GREEN** 为前提；若它们后续被改动，本组引用需同步复核（已在 §3.5 登记指向）。
4. **本行不作为 CW-059 全任务关闭依据**：账本 §18 CW-059 状态以**最终合并评审 + 独立复核**为准。本会话（task-7bf）为实现者，交付 33 用例 PG 矩阵 + 证据闭合 + 三门禁 + SQLite 回归，**不自评、不自合**（§5 约束）；lifecycle 推进至 REVIEW 待独立复核接手。
