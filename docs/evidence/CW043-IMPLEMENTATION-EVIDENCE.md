# CW-043 Segment 4+ 实施证据（正式实施 · CODE_AND_TEST_INCREMENT）

- 任务：CW-043（V6·复核类）——独立核销全业务 PG 测试覆盖
- 分支：`feat/customer-v3-cw043-audit-implementation`（基线 `origin/main@a093f61`；worktree `.worktrees/CW-043-audit-implementation`）
- 授权：继承盘点 claim `next_steps` 第 10 步——CW-061 合入 main 后另启会话启动正式实施（scope=CODE_AND_TEST_INCREMENT）
- 环境：`vs-pg-cw043 @ 5438`（postgres:16.15-alpine，devuser/devpass/customer_v3_test）· venv Python 3.12.14 · fcntl shim
- 证据日期：2026-09-11 · 维护人：CW-043 Owner（claim 见 `.git/codex-task-claims/CW-043/claim.json`）
- 权威计划源：`docs/evidence/CW043-AUDIT-PLAN.md`（§3 抽样 / §4 债务核销 / §1 DoD）

> 本文件累积 Segment 4+ 全部实施证据。§A 现状基线 → §B 抽样复核 → §C R1–R5 补漏 → §D 机制退役登记 → §E 签字。

---

## §A. 全量现状基线（clean main@a093f61 · Windows · real PG 5438）

**命令**：`pytest tests/ -q --tb=line -rf`（runner `.dev-env/run-cw043-pytest.ps1`，TEST_POSTGRESQL_URL=5438）
**结果**：`25 failed, 2574 passed, 2 skipped, 1 warning in 1652.22s (0:27:32)`
**worktree 状态**：`git diff a093f61 HEAD` 为空 → **CW-043 零代码改动**，故 25 个失败全部为 main@a093f61 既有基线，非本次引入。

前置健康基线（先于全量，已 GREEN）：
- `test_cw059_billing_pg_matrix.py` → 12 passed（账务域 W1/W2 覆盖源）
- 4 域 PG 矩阵（billing/task/rbac/content）→ 53 passed in 30.22s

### §A.1 失败分组 A —— 22 例 `test_cw033_pitr_drill_validation.py`（Windows 平台产物，非债务）

- 症状：全部 `FileNotFoundError: [WinError 2]` @ `subprocess.py:1538`
- 根因：测试 `test_cw033_pitr_drill_validation.py:57-58` 硬编码
  `subprocess.run(["/usr/bin/env", "bash", str(DRILL_SCRIPT), *args], ...)`；Windows 无 `/usr/bin/env` 可执行文件 → 直接 FileNotFoundError。
- 性质：**POSIX/Linux-CI 专用测试**（PITR restore-drill 的 fail-fast CLI 校验，需 bash + `.sh`）。已登记于 CI `shard-3.txt:12`，CI Linux 上为 GREEN；本地 Windows 永远无法运行。
- 与 CW-043 关系：**非 SQLite→PG 语义债务**，属 CW-033 文件（CW-043 边界禁改）。本地基线按平台例外 deselect 处理，A2「本地全量 GREEN」对此组记为「Linux-CI-only 平台例外」。

### §A.2 失败分组 B —— 3 例 `test_storage_cross_instance.py`（CW-026↔CW-031 潜伏跨任务回归）⚠️

失败用例（隔离复跑 `3 failed, 24 passed in 2.95s` 稳定复现，非全量单进程污染）：
- `test_local_object_endpoints_fail_closed_without_cos`（:609，`assert 401 == 503`）
- `test_local_object_endpoints_keep_404_when_cos_is_configured`（:633，`assert 401 == 404`）
- `test_local_object_put_is_not_fenced_on_the_desktop_lane`（:653，`assert 401 == 404`）

**根因链（已代码级定位）**：
1. `server/app/auth.py:86-110 authenticate_request()`：`if conn.is_postgres:` 分支——CW-026 收敛后，**PG lane 在所有环境（含 dev/test/CI）只认活客户会话 Bearer**；`authorization is None` → `raise 401 SESSION_TOKEN_REQUIRED`。`X-Dev-User-Id`（dev lane）在 PG 上不可达（legacy internal/desktop lane 为 SQLite-only，随 CW-021/040/041 退出）。
2. 3 个失败用例走 `media_client` fixture（`test_storage_cross_instance.py:290-298`，仅挂 `media_router`）+ `headers={"X-Dev-User-Id": ADMIN_USER_ID}`（无 Bearer）→ 在 real PG（`fence_dsn`=PG）上命中 `conn.is_postgres` 门禁 → 401，未达其期望的存储 fail-closed 逻辑（503/404）。
3. 同文件已有 `customer_lane` fixture（:301-320，激活→设备→业务登录→Bearer），其文档串明写「dev 身份被 401 挡在存储之前」——即作者已知 PG lane 需 Bearer，但这 3 个用例仍用旧 dev-lane 模式。

**时间线（git 佐证）**：
- `test_storage_cross_instance.py` 仅 1 次提交：`f5e24c9` **CW-031（PR #17）**
- `auth.py` 的 `conn.is_postgres` 收敛门禁进入：`eea767e` **CW-026（PR #20）**
- PR #17 < PR #20 → **CW-031 先合、CW-026 后合打断了它**。当时该文件是「CI 缺口」（`CW043-PG-COVERAGE-MATRIX.md` N21 = ❌），CI 从未跑到；**CW-061（PR #36）补入 shard-3 后，CW-043 审计首次暴露此潜伏回归**。

**平台无关性**：门禁是 PG-lane 逻辑（`conn.is_postgres`），与操作系统无关 → **CI Linux shard-3 同样会红**。推论：main@a093f61 的 shard-3 很可能为 RED，或 CW-061 补片后未真正验证过 shard-3。

### §A.3 边界处置决定（Owner 决策：留在 CW-043 泳道 · 记录并路由）

- 两组失败均在 CW-043 claim `forbidden` 边界内的他任务文件（CW-033 / CW-031），且 `minimal_fix_allowed` 白名单（character_asset_review / db_portable / internal_billing / payments）不含它们。
- **决定**：CW-043 **不越界修改**；将分组 B 作为「CW-026↔CW-031 潜伏回归」审计发现**记录并路由**给 CW-031 owner / 项目 lead。
- **建议修复（交 CW-031，非 CW-043 执行）**：把 3 个 `test_local_object_endpoints_*` 从 `media_client`+`X-Dev-User-Id` 迁到同文件现成的 `customer_lane`+Bearer fixture（激活→设备→登录建立会话），即可 PG-lane GREEN。
- **对 CW-043 DoD 的影响**：
  - A2「本地全量 pytest GREEN on real PG」：分组 A 记 Linux-CI-only 平台例外；分组 B 记「既有域外例外（CW-031 待修）」。CW-043 自身域内（抽样 20 + R1–R5 + 账务/任务/权限/内容 PG 矩阵）须全 GREEN。
  - A3「CI quality-linux pass」：分组 B 会使 shard-3 RED，属 CW-043 域外前置阻塞，须由 CW-031 修复后 CW-043 方可宣告 A3 全绿；CW-043 签字时携带此例外说明。

---

## §B. 抽样复核（§3.2）——完成 ✅ 全绿，无 RED

**方法**：将 §3.2 示例 12 例逐一映射到既有 PG 矩阵断言，在 real PG 5438 上运行取逐用例 GREEN 证据。
**运行**：`pytest tests/test_cw059_billing_pg_matrix.py tests/test_cw059_task_worker_pg_matrix.py tests/test_cw030_worker_pg_matrix.py tests/test_cw059_rbac_pg_matrix.py tests/test_cw058_content_asset_pg_matrix.py -v --tb=short`
**结果**：`82 passed, 1 warning in 55.37s`，rc=0（证据 `.dev-env/cw043_sampling.out.txt`）。

| # | 抽样不变量 | PG 矩阵断言（real PG GREEN） | 核销 |
| --- | --- | --- | --- |
| W1 | 钱包负余额拒绝 | `billing::test_pg_wallets_reject_negative_available_and_reserved`（docstring「Maps test_internal_billing.py::test_wallets_reject_negative_balances」） | ✅ |
| W2 | 商户订单号并发唯一 | `billing::test_pg_concurrent_duplicate_merchant_order_no_commits_exactly_once`（双连接 race） | ✅ |
| W3 | reserve/release 循环 + 超支回滚 | `billing::test_pg_wallet_transactions_reject_duplicate_reserve_round`（RESERVE arm）+ `..._terminal_round`（SETTLE/RELEASE arm）+ W1 nonnegative CHECK | ✅ |
| W4 | 支付回调验签 + 幂等键唯一 | `billing::test_pg_recharge_orders_reject_duplicate_merchant_order_no` + `..._provider_trade_no` + `test_pg_wallet_transactions_reject_duplicate_idempotency_key`（验签本身=app crypto，非 DB 不变量） | ✅ |
| T1 | 生成任务状态机 + lease | `task_worker::test_pg_first_frame_tasks_status_enum_boundary` 等 + CW-030 lease/claim 组 | ✅ |
| T2 | 并发抢单 FOR UPDATE SKIP LOCKED | `cw030::test_character_generation_skip_locked_double_claim` + `test_independent_double_claim_is_exclusive` | ✅ |
| T3 | source_frame worker 消费原子落库 | `cw030::test_source_frame_double_claim_is_exclusive` + `test_independent_worker_settles_exactly_once_on_pg` | ✅ |
| T4 | ASR 超时 SUBMISSION_UNCERTAIN | `task_worker::test_pg_source_frame_tasks_reject_uncertain_status` + `cw030::test_independent_expired_lease_marks_uncertain_and_releases_slot` | ✅ |
| P1 | 项目删除 ON DELETE RESTRICT | `rbac::test_pg_project_delete_blocked_by_active_generation_task[PENDING/SUBMITTING/QUEUED]` + `..._allowed_once_generation_task_terminal` | ✅ |
| P2 | delete_project 缓存失效 + 隔离级 | 计划名 `delete_project_with_stale_cache` **在 rbac_routes.py 不存在**（§3.2 为「示例」近似名）；真实 `delete_project` 生产路由已由 rbac 矩阵在 real PG 双向驱动；character 缓存恢复不变量由 test_storage_cross_instance.py 的 24-passed 部分钉住（rbac_routes.py:143 注释） | ✅（附注） |
| C1 | ctid 序 + append-only 审计 | `content::test_character_review_history_latest_decision_wins_on_pg`（rowid→ctid 修复已验证） | ✅ |
| C2 | viral_store (platform,video_id) 部分唯一去重 | `content::test_viral_store_upsert_dedup_and_statistics_coalesce_on_pg`（docstring「旧断言（test_viral_store.py 去重/统计组）」，用 `upsert_viral_videos(bus,…)` 于 real PG） | ✅ |

**结论**：抽样 12/12 例在真实 PG 全绿，**未发现 RED → 无需触发 §3.3 minimal-fix**。账务/任务/权限/内容四域的 SQLite 保留不变量已由 CW-058/059/030 翻译为 PG 断言，**核销确认**。SQLite 保留源（如 test_viral_store.py:44 `BusinessConnection.sqlite`、test_internal_billing.py）继续跑内部桌面通道，其 PG 等价事实已由上述矩阵证明；SQLite 专有机制（EXPLAIN QUERY PLAN / trace 计数）按 §4.2 退役登记（见 §D）。

## §C. 补漏（§4.3 + 矩阵 §5.1.3）——完成 ✅ 12 新 PG 用例全绿

### §C.0 核销定义（矩阵 §7 line 247 权威）
采「**不变量在真实 PG 上有断言级证据即可，旧 SQLite 文件随 CW-042 退休**」（非逐文件迁移），与 CW-058 §1 / CW-059 §1 交付同形。据此，两套同名 R1–R5 校准如下。

### §C.1 矩阵 §5.1.3「TEST-SQLITE-CONN 剩余 R1–R5」（5 个测试文件）→ 全为 E2 例外/可退休，登记为主

| ID | 文件 | 事实核验 | 处置 |
| --- | --- | --- | --- |
| R1 | `test_db.py` | db.py = SQLite 兼容层本体（CW-053 §3 E2）；PG 等价=alembic head + `BusinessConnection.postgres`，已由 pg_test_kit `upgrade_test_database_to_head` + 全部 PG 矩阵证明 | 登记退休（随 CW-042），无需新测试 |
| R2 | `test_db_portable.py` | `translate_to_sqlite`/`_is_begin_immediate`/`_is_sqlite_pragma` = SQLite 翻译助手（E2）；PG 侧契约已由 CW-054 `test_cw054_pg_portable_contract.py` 覆盖 | 登记退休（E2/CW-042） |
| R3 | `test_db_pg.py` | 混合：PG 半边已覆盖，SQLite 半边同 R2 | 登记退休（SQLite 半边） |
| R4 | `test_internal_access_tokens.py` | internal lane = CW-053 §3 E2 例外；收敛客户会话已由 CW-026 `test_cw026_converged_auth.py` 覆盖 | 登记退休（internal lane/CW-042） |
| R5 | `test_viral_refresh.py` | **已验证**：`_run_sqlite_viral_refresh_step`（generation_worker.py:432）仅在 SQLite worker 循环内调用（:506 docstring「SQLite connections stay short-lived」/:513）；PG lane 走独立 `run_pg_worker_once`（:1072），其 viral-refresh 通道已由 cw058 #21 `test_viral_refresh_pg_lane_enqueues_and_worker_consumes_on_pg` 覆盖 | 登记退休（SQLite 半边，随 CW-042） |

> R6/R7（test_migration_dialect_contract.py / test_sqlite_to_postgres.py）= ✅ CW-053 §3 E1/E4 永久例外，无缺口。

### §C.2 审计 §4.3 / 矩阵 §5.1.1 #8·#19·#20「CW-058 移交的 app 全矩阵」→ 2 个真新测试缺口

| ID | app 模块（已核验存在） | 覆盖现状 | 处置 |
| --- | --- | --- | --- |
| analytics | `studio_routes.py::studio_analytics(conn)`（L204，PG-capable，SQL 用 `::timestamptz` cast + 北京日界分桶 + cost_credits 相关子查询 NULL 安全 + `NOT EXISTS(customer_batch_visibility)` 隐藏反连接 + 属主范围 + batch_id 去重 + oral/generation 分离） | #8 部分：`studio_task_stats` 同 SQL 家族已由 cw058 `test_studio_task_stats_scope_and_hidden_batch_on_real_pg`(:694) 覆盖；**analytics 特有的批次去重/成本 NULL 安全/口播分离/窗口分桶未覆盖** | **新建 `test_cw043_analytics_pg_matrix.py`（6–8 用例）** |
| viral_import | `viral_import.py`（676 行，存在） | #20：`test_viral_import.py` 全程 `BusinessConnection.sqlite`（L35/91/202/254/298/347）→ **import 幂等/属主/租约/worker 消费/重试不变量在 PG 上零覆盖** | **新建 `test_cw043_viral_import_pg.py`（4+ 用例：lease SKIP LOCKED 双连接互斥 + attempt 递增 + 失败回滚 + 幂等重放）** |
| viral_statistics | `viral_statistics.py`（138 行） | #19：持久化面（native_json RMW 原子递增/统计 COALESCE）已由 C2 `test_viral_store_upsert_dedup_and_statistics_coalesce_on_pg` 覆盖；仅 trace 语句计数为 SQLite 专有 | 无需新测试（trace 计数按 §4.2 退役登记） |
| media_upload / 素材管线（§4.3 R4/R5） | `media_routes.py` / `materials` | **已由 cw058 content 矩阵覆盖**：`test_media_upload_persists_asset_analysis_and_project_status_on_pg`(:763) + `test_media_upload_dedup_reuses_owned_hash_never_foreign_on_pg`(:798) + `test_media_completion_rolls_back_atomically_when_enqueue_fails_on_pg`(:855) + `test_materials_pagination_hide_rename_and_audit_on_pg`(:917)，均在本文件 §B 的 82-passed 内 | 无需新测试（引用既有证据） |

**净新测试工作量**：analytics（6–8）+ viral_import（4+）≈ **10–12 个新 PG 用例**（远小于 §6 粗估 30，因 R1–R5 测试文件走退休登记、media/materials/viral_statistics 已覆盖）。

### §C.3 12 个新 PG 用例 GREEN 结果（§4.3 R1/R3 补漏落地）——完成 ✅

**运行**：`pytest tests/test_cw043_analytics_pg_matrix.py tests/test_cw043_viral_import_pg.py -v --tb=short`（runner `.dev-env/run-cw043-pytest.ps1`，TEST_POSTGRESQL_URL=5438，venv Python 3.12.14）
**结果**：`12 passed in 9.11s`，rc=0（证据 `.dev-env/cw043_t11_verify.out.txt`，采集于 2026-09-11）。两专属库（`cw043_analytics_test` / `cw043_viral_import_test`）同跑无池污染。

**analytics 域**（`test_cw043_analytics_pg_matrix.py`，6 用例，专属库 `cw043_analytics_test`）：

| # | 新 PG 用例 | 移植的旧 SQLite 不变量（`test_studio_analytics.py`） | real PG |
| --- | --- | --- | --- |
| A1 | `test_daily_series_covers_full_window_by_beijing_day_on_real_pg` | daily 序列覆盖整北京日界窗口 + 跨午夜完成时刻归对日（t3 北京 09-05 23:59 / t2·oral 09-06 00:01）+ range/today/total 计数 + 去重批次数；`updated_at::timestamptz >= %s::timestamptz` 在 PG 原样执行真 cast | ✅ PASSED |
| A2 | `test_analytics_uses_one_clock_read_across_beijing_midnight_on_real_pg` | 全程单次 now 读（generated_at 与窗口同源），跨北京午夜不漂移（MidnightClock monkeypatch 与后端无关） | ✅ PASSED |
| A3 | `test_kind_breakdown_counts_only_visible_completed_tasks_on_real_pg` | kind_breakdown 仅计可见完成项 + 普通生成 batch_id 去重 + employee/customer/other-employee 三视角属主范围 + 隐藏批反连接 | ✅ PASSED |
| A4 | `test_recent_works_sorted_scoped_and_capped_on_real_pg` | recent_works completed_at 倒序 + task_id 稳定序 + 按秒计费 cost_credits NULL 安全（t1 RESERVE=8 / 口播·无计费=null）+ 无项目独立批 title 回退 display_name + 属主范围 | ✅ PASSED |
| A5 | `test_recent_works_cap_at_twenty_on_real_pg` | 22 成片全计 range 计数但 recent_works 截断到看板容量 20 + 首项为最新 t-21 | ✅ PASSED |
| A6 | `test_days_window_is_clamped_on_real_pg` | days 钳制 [1,90] + daily 序列长度随钳制 + 30 天窗口外 t9 在 90 天窗口内计入 | ✅ PASSED |

**viral_import 域**（`test_cw043_viral_import_pg.py`，6 用例，专属库 `cw043_viral_import_test`）：

| # | 新 PG 用例 | 移植/新增的持久队列租约不变量（旧 `test_viral_import.py` 全 SQLite + 路由级） | real PG |
| --- | --- | --- | --- |
| V1 | `test_acquire_viral_import_lease_is_exclusive_on_real_pg` | 一个 PENDING 任务只被一个 worker 认领（`FOR UPDATE SKIP LOCKED` + status 状态机；worker-a attempt 0→1/RUNNING，worker-b 得 None） | ✅ PASSED |
| V2 | `test_expired_viral_import_lease_is_reclaimed_and_attempt_increments_on_real_pg` | 过期租约回收（locked_until TEXT 词法比较）+ attempt 1→2 + locked_by 换手 + started_at 保留 | ✅ PASSED |
| V3 | `test_fail_viral_import_task_releases_lease_and_marks_retryable_on_real_pg` | 普通异常 → FAILED + retryable=1 + error_code VIRAL_IMPORT_FAILED + 锁释放 NULL | ✅ PASSED |
| V4 | `test_terminal_viral_import_error_marks_non_retryable_on_real_pg` | 终态 ViralImportError(retryable=False) → retryable=0 + error_code 取业务码 VIRAL_IMPORT_PROJECT_CHANGED | ✅ PASSED |
| V5 | `test_stale_viral_import_lease_failure_is_a_noop_on_real_pg` | 栅栏令牌（locked_by + attempt）：陈旧 worker-a 迟到失败 WHERE 不匹配 → 0 行更新 no-op，保持 worker-b RUNNING/attempt=2 | ✅ PASSED |
| V6 | `test_viral_import_idempotency_key_is_unique_per_owner_on_real_pg` | `uq_viral_import_tasks_owner_idempotency`：同属主重复幂等键触发 IntegrityError（enqueue ON CONFLICT DO NOTHING 重放去重所依赖），不同属主可复用 | ✅ PASSED |

**净新工作量核对**：§C.2 估算 10–12，实际交付 **12**（analytics 6 + viral_import 6），落在估算区间上界。§4.3 R1（analytics 6–8）→ 交付 6；R3（viral_import 4+）→ 交付 6（超配，含栅栏令牌 no-op + 幂等键属主唯一）。R2（viral_statistics）/R4（media_upload）/R5（素材管线）经 §C.2 校准为已覆盖，无新测试（trace 计数退役见 §D）。

**PG-lane 关键事实（本组用例验证成立）**：
- analytics：核心表 `updated_at` 是 `sa.Text()`（迁移 065/067/070），psycopg 逐字回读 → SQLite 断言 1:1 移植；`SET TIME ZONE 'UTC'` 使 `::timestamptz` cast 与 SQLite `datetime()` 语义对齐（A1/A2/A6 窗口过滤全绿印证）。
- viral_import：`locked_until`/`updated_at`/`created_at` 皆 TEXT（迁移 078），acquire 用 TEXT 词法比较且 now_text 由 Python `datetime.now(UTC).strftime` 生成 → 全程与会话 TimeZone 无关；固定过去文本 `'2020-01-01 00:00:00'` 制造确定性过期（V2/V5 印证）。
- oral 链 FK 简化：`oral_avatars.source_asset_id` / `oral_tasks.result_asset_id` 是无 FK 的纯 Text（迁移 065），裸串即可播种（A1/A3/A4 口播计入印证）。

## §D. 44 项部分核销「机制退役」登记（§4.2）——完成 ✅

依矩阵 §7 line 247 权威核销定义「**不变量在真实 PG 上有断言级证据即可，旧 SQLite 文件随 CW-042 退休**」（CW-058 §1/CW-059 §1 交付同形），对审计计划 §4.2 的 44 项部分核销（§8 line 257：SQLITE-HELPER 8 + TYPE-DEBT 30 + 混合 3 + CW-058 移交 3 全矩阵）与 §4.3 R1–R5 补漏落地后残留的 SQLite 专有断言，按类别登记「Mechanism Retired — No PG Equivalent Needed」。

### §D.1 SQLite 专有断言机制退役（按类别，覆盖 44 项部分核销的退役面）

| 机制类别 | SQLite 专有断言（原文示例） | 为何不适用 PG | PG 等价事实（核销依据） | 登记出处 |
| --- | --- | --- | --- | --- |
| EXPLAIN QUERY PLAN 查询计划内省 | `test_living_video_pipeline.py::test_db_query_plan_optimized`「EXPLAIN QUERY PLAN 无 TEMP B-TREE」；`test_viral_store.py`（矩阵 #17）同款断言 | 只适用于 SQLite 查询规划器内省；PG 用完全不同的 planner（无 TEMP B-TREE 概念） | alembic 迁移含正确索引定义（`upgrade_test_database_to_head` 于全部 PG 矩阵证明）+ 持久化面不变量已由 `test_viral_store_upsert_dedup_and_statistics_coalesce_on_pg` 钉住 | 审计 §4.2 / 矩阵 #17 |
| sqlite_master / schema 内省 | `test_characters.py::test_characters_migration_creates_library_tables`（矩阵 #14）「建 9 张人物域表」 | SQLite 内省表；PG 用 information_schema/pg_catalog，结构由 alembic 权威管理 | alembic head 含全部域表（`upgrade_test_database_to_head` 建库到 head 即证） | 矩阵 #14 |
| trace 语句计数 | `test_viral_statistics.py`（矩阵 #19 / 审计 §4.3 R2）「sqlite3 trace 回调计 SQL 语句条数」 | sqlite3 `set_trace_callback` 专有；PG 无等价钩子，且「语句条数」非业务不变量 | 持久化面主不变量（native_json RMW 原子递增 + statistics COALESCE）已由 `test_viral_store_upsert_dedup_and_statistics_coalesce_on_pg`（§B C2）覆盖 | 审计 §4.3 R2 / 矩阵 #19 |

**登记结论**：以上三类 SQLite 专有机制断言随 SQLite 在线通道（`db.py`）**退休（CW-042）**，不迁移到 PG；其对应的**业务主不变量**（数据一致性/属主隔离/约束拒绝/索引存在性）已由既有 PG 矩阵在真实 PG 上断言级证明，故 44 项部分核销的核销结论不受影响（审计 §4.2 point 3）。

### §D.2 §5.1.3 R1–R5 TEST-SQLITE-CONN 文件退役登记（§C.1 落地）

| ID | 文件 | CW-053 §3 例外 | 退役条件 | PG 等价核销 |
| --- | --- | --- | --- | --- |
| R1 | `test_db.py` | E2（SQLite 兼容层本体） | 随 CW-042 裁剪 | alembic head + `BusinessConnection.postgres`（pg_test_kit `upgrade_test_database_to_head` + 全部 PG 矩阵） |
| R2 | `test_db_portable.py` | E2（`translate_to_sqlite`/`_is_begin_immediate`/`_is_sqlite_pragma` 翻译助手） | 随 CW-042 | PG 侧契约已由 CW-054 `test_cw054_pg_portable_contract.py` 覆盖 |
| R3 | `test_db_pg.py` | E2（SQLite 半边） | SQLite 半边随 CW-042 | PG 半边已覆盖 |
| R4 | `test_internal_access_tokens.py` | E2（internal lane） | 随 CW-042 | 收敛客户会话已由 CW-026 `test_cw026_converged_auth.py` 覆盖 |
| R5 | `test_viral_refresh.py` | E2（SQLite worker 路径 `_run_sqlite_viral_refresh_step`） | SQLite 半边随 CW-042（PG lane 走独立 `run_pg_worker_once`） | PG worker 通道已由 cw058 #21 `test_viral_refresh_pg_lane_enqueues_and_worker_consumes_on_pg` 覆盖 |

> R6/R7（`test_migration_dialect_contract.py` / `test_sqlite_to_postgres.py`）= ✅ CW-053 §3 E1/E4 永久例外，无缺口，不在退役范围。

### §D.3 路由级 dev-header 用例退役登记（CW-026 收敛的直接后果）

| 旧用例 | 退役理由 | PG 等价核销 |
| --- | --- | --- |
| `test_studio_analytics.py::test_analytics_route_scopes_by_caller` | 经 `X-Dev-User-Id` dev lane；CW-026（PR #20）收敛后 PG lane 只认活客户会话 Bearer，X-Dev-User-Id 在 PG 上不可达（`auth.py:101` `conn.is_postgres` → 401） | analytics 属主范围不变量已由本 Segment 新增函数级用例 A3/A4（employee/customer/other-employee 三视角）在真实 PG 覆盖 |
| `test_viral_import.py` 全部路由级 X-Dev-User-Id 用例 | 同上：TestClient + dev-header 在 PG lane 不可达 | 爆款导入持久队列租约不变量已由本 Segment 新增 V1–V6 在真实 PG 覆盖（脱离路由/媒体管线，直测 acquire/fail 队列机制） |

**§D 汇总**：44 项部分核销的 SQLite 专有机制（EXPLAIN QUERY PLAN / sqlite_master / trace 计数）+ §5.1.3 R1–R5 五文件 SQLite 半边 + 两组路由级 dev-header 用例，全部登记「Mechanism Retired — No PG Equivalent Needed」，随 SQLite 在线通道退休（CW-042）；对应业务主不变量均已在真实 PG 上有断言级证据。**待办**：账本 §18 备注 + §2.2 回填（见 §E / t7）。

## §E. 独立复核签字（A4）——A1/A2/A3 本机就绪，A4 待独立复核者签署（不自评自合）

本节按 claim.json `implementation_status.dod` 的 A1–A4 四级标准逐项对照。**本会话为 CW-043 Segment 4+ 实现者，遵 CW-059 先例「不自评自合」：A1/A2/A3 为本机可自动核验门（已就绪），A4 独立复核签字留待非本会话的独立复核者。**

### §E.1 DoD A1–A4 对照表

| 门 | 定义（claim.json dod） | 本机证据 | 判定 |
| --- | --- | --- | --- |
| A1 | 代码检查：app 无 sqlite3.Row/Error；PG 测试用 BusinessConnection.postgres | `git status --short -- server/app server/migrations` = NONE（Segment 4+ 零 app、零迁移改动）；2 新测试 `BusinessConnection.postgres` 命中 analytics×1 + viral_import×2；`sqlite3.(Row\|Error)` 命中 = 0；app 无 sqlite3.Row/Error 继承盘点矩阵结论（本 Segment 未触碰 app） | ✅ 满足 |
| A2 | 本地全量 pytest GREEN on real PG | `pytest tests/ -q --tb=line -rf` @ vs-pg-cw043:5438 = **2586 passed / 25 failed / 2 skipped in 1730.83s (28:50)**；2586 = 基线 2574 + 本 Segment 12 新 PG 用例全绿；CW-043 范围（12 新用例 + §B 4 域抽样 82 passed）零 RED | ✅ CW-043 范围内 GREEN（25F 域外，见 §E.4） |
| A3 | CI quality-linux pass | 本机无 gh、GitHub Actions 不可实跑；CI 守门步骤 `build-test-shards.py --check-coverage` 本机 **rc=0（118 文件全覆盖）**；shard 清单 canonical 重生处置见 §E.2 | ⏳ 本机守门就绪，最终以 push 后 CI quality-linux 裁决 |
| A4 | 独立复核签字 | 本会话=实现者，不自评自合；待独立复核者按 §E.3 核验包签署 | ⏳ 待独立复核 |

### §E.2 A3 CI shard 清单处置（canonical 重生 + LPT 敏感性路由）

**背景**：Segment 4+ 新增 2 个测试文件（`test_cw043_analytics_pg_matrix.py` / `test_cw043_viral_import_pg.py`）。CI Linux 门用 committed 分片清单（白名单语义，CW-061），清单未含新文件则 CI 静默漏跑 → `--check-coverage` 守门 rc=1（118 发现 / 2 未覆盖）。此为 CW-043 自身必须修的 CI 缺口（属本任务「证据可信度」核心范围，非域外）。

**处置=canonical 重生**：`python3 scripts/ci/build-test-shards.py --shards 4` 重生四份清单，26/30/27/33（116）→ **30/30/28/30（118）**，`git diff --numstat` = **32 插入 / 30 删除**（shard-0 10/6、shard-1 9/9、shard-2 6/5、shard-3 7/10；30 个既有文件跨片重排）。重生后 `--check-coverage` **rc=0（118 全覆盖）**。

**实证（判定重生为确定性正确输出，非陈旧修正）**：
- committed 清单 == `LPT(116 文件)` = **True**（committed 本身即 canonical）；按秒数均衡 loads = [253.0, 253.0, 253.1, 253.0]（文件数 26/30/27/33 不均，但成本均衡）。
- `test-durations.json` profile 仅覆盖 88 文件，其中 **17 个 profiled 文件 cost < 1.0s**；新文件无 profile 条目 → 用 `DEFAULT_ESTIMATE_SECONDS = 1.0`。
- LPT 按 `(-cost, path)` 排序装箱：cost=1.0 的 2 新文件插入到 17 个 sub-1.0 文件**之前**的排序中段，改变其后所有文件的放置轨迹 → 即使 2 个廉价新文件也引发 30 文件重排。重生输出对 118 文件集是**唯一确定性 canonical 结果**。

**决策依据（保留 canonical 重生，非最小手工追加 +2 行）**：①`build-test-shards.py` docstring 契约「Regenerating with the same inputs yields byte-identical manifests」要求 committed 清单 == `--shards 4` 输出，最小手改会破坏该确定性不变量、令后续维护者重生时看到意外 diff；②与 CW-061 账本先例一致（§18 line 546「①分片清单陈旧已再生（116 文件全覆盖）」——CW-061 自身在测试文件增加时即全量再生）；③`scripts/ci/test-shards/**` 不在 claim.json forbidden 列表，且更新清单使新测试进 CI 正是 CW-043「证据可信度」核心职责；④重排只改变测试落在哪个分片（118 文件各跑恰好一次），不改任何测试语义、不触碰他任务实现文件。

**路由观察（→ CW-061 / CW-044 owner，不在本任务执行）**：`test-durations.json` profile 陈旧（仅 88/118 文件有实测成本，30 文件用 1.0s 默认）是本次 30 文件重排的根因放大器。建议周期性用 `build-test-shards.py --from-log <全量 pytest --durations=0 log> --shards 4` 刷新 profile，使新增中间成本文件的插入不再引发大规模重排。此为 CI 基建维护项，超出 CW-043 边界，记录并路由。

### §E.3 待独立复核包（A4 复核者入口）

| 项 | 内容 |
| --- | --- |
| Worktree | `.worktrees/CW-043-audit-implementation` |
| 分支 | `feat/customer-v3-cw043-audit-implementation`（base `a093f61` = CW-061 PR #36 合并后 main 头；upstream 已 unset） |
| 改动面 | 2 新测试（analytics 6 例 / viral_import 6 例）+ `pg_test_kit.py`（allowlist +2 库）+ 4 shard 清单（canonical 重生 118）+ 证据 `CW043-IMPLEMENTATION-EVIDENCE.md` §A–§E；**零 server/app/**、零 server/migrations/** |
| PG 资源 | vs-pg-cw043 @ 5438（与 cw059=5437/cw058=5440/cw031=5436/cw056=5435/dev=5434/backend=5432/CI=5433 全隔离）；专属库 `cw043_analytics_test` / `cw043_viral_import_test`（已登记 RECORDED_TEST_DATABASES） |
| 复跑入口 | `.dev-env/run-cw043-pytest.ps1`（venv python + fcntl shim + TEST_POSTGRESQL_URL@5438）；12 新用例 `pytest tests/test_cw043_analytics_pg_matrix.py tests/test_cw043_viral_import_pg.py -v`（预期 12 passed）；全量 `pytest tests/ -q --tb=line -rf`（预期 2586 passed / 25 域外 failed / 2 skipped） |
| 复核动作 | 独立跑 12 新用例 + §B 4 域抽样 + 全量确认 GREEN；核验 §C 补漏映射 + §D 44 项机制退役登记；核对 §E.2 shard 重生为 canonical；确认 25F 域外分类与路由无误；签署 A4 |

## §F. A4 独立复核签署（2026-09-12，非实现会话）

- **复核者**：ZCode session on behalf of honor.pei（实现会话为 Qoder session，满足 A4 独立性要求）；owner 指令授权（W6 统一批次，分支 `feat/customer-v3-w6-unblock`，基线 55220f7）。
- **独立容器复跑**：vs-pg-cw043a@5444（全新 postgres:16-alpine，非实现时的 5438）。①12 新用例 + §B 五矩阵文件 82 用例 = **94 passed in 134.96s**——与实现者声称逐数一致，无 RED。
- **§C 补漏映射核验**：R1–R5 退休登记与 §C.2 两真缺口（analytics/viral_import）校准逻辑复核通过；机械抽查三条声称逐一属实——R5 双通道（`_run_sqlite_viral_refresh_step` @generation_worker.py:432、调用点 :513、PG 侧 `run_pg_worker_once` @:1072）、`test_viral_import.py` 12 处 `BusinessConnection.sqlite` + `viral_import.py` 676 行、`pg_test_kit.upgrade_test_database_to_head` @:218。
- **§D 机制退役登记核验**：EXPLAIN QUERY PLAN / sqlite_master / trace 计数三类登记齐备，「业务主不变量已在真实 PG 断言级证明」的核销口径与矩阵 §7 line 247 一致。
- **§E.2 shard 重生 canonical 核验**：`build-test-shards.py --check-coverage` rc=0（本批次分支 132 文件口径）。
- **全量复跑**（本批次分支，TEST_POSTGRESQL_URL@5444）：**42 failed / 2827 passed / 1 skipped in 1:30:43**。分类（git stash 归因法逐组实证）：
  - 22× `test_cw033_pitr_drill_validation` = §A.1 已登记的 Windows 平台例外（`/usr/bin/env` 硬编码），Linux-CI-only；
  - 17× `test_viral_routes` = **main 侧滚动日期窗口时间炸弹**（更正：初判「本机环境类」不成立——Linux 容器 solo 复跑同样失败）。fixture 固定日期滚出有效窗口，与改动面零交集；owner 已于本批次 CI 窗口内经 FIX-TESTBASE（#78，8ae7305，20:57）修复，rebase 后 35/35 全绿复证。初判时点该修复未落 main，如实记录判更过程；
  - 3× `test_analysis/test_character_identity_api/test_first_frames` 的 customer_production 拒绝类单测 = **本批次 042-a 守卫引起的回归**（stash 归因实证：干净基线过、挂守卫即红）——由本批次修复（三测试重排为「先建连接、后升生产旗标」，断言不变），3 passed 验证；详见 CW042A-EVIDENCE.md §5。
- **签署结论**：§C/§D/§E 核验包与实现者声称一致，12/12 真实 PG 全绿无 RED，核销确认成立；**A4 签署通过**。附带发现（viral 17F）确认为滚动日期窗口时间炸弹（非 CW-043 交付物缺陷），owner 已修复并复证；rebase 至 37a2633 后本批次门禁全绿（ruff/mypy/coverage/secrets/migration-guard + 专项 63P），不影响核销结论。

### §E.4 诚实边界

1. **A2 的 25 failed 均为 main@a093f61 既有域外债务，非 CW-043 引入**：`git diff a093f61 HEAD` 为空 + 工作树零 app 改动即证。分组：**22×** `test_cw033_pitr_drill_validation.py`（Windows 平台缺陷：硬编码 `/usr/bin/env bash`、WinError 2；Linux-CI-only 落 shard-3，CI 上转绿；非 PG 债务）+ **3×** `test_storage_cross_instance.py`（CW-026 PR#20 收敛 PG lane 强制 Bearer → 打断 CW-031 PR#17 的 media_client+X-Dev-User-Id 测试；潜伏回归被 CW-061 分片纳入 + CW-043 审计暴露；平台无关 → CI shard-3 亦红）。处置=Option A（Owner 裁决，见 §A.3）：留在 CW-043 泳道、记录并路由给 CW-031 owner，不越界修改他任务测试。建议修法（供 CW-031，非 CW-043）：3 测试从 media_client+X-Dev-User-Id 迁到该文件既有 customer_lane+Bearer fixture。
2. **A3 CI quality-linux 最终以 push 后 GitHub Actions 裁决**：本机无 gh，仅能核验守门步骤 `--check-coverage`（rc=0）；四片 pytest + 静态门的完整 CI 结果留待 push 后。
3. **A4 不自评自合**：本会话为实现者，A4 独立复核签字留待非本会话复核者（遵 CW-059「尚未 commit/push/PR，待独立复核」先例）。
4. **核销定义边界**：CW-043 采矩阵 §7 line 247 权威定义「不变量在真实 PG 上有断言级证据即可，旧 SQLite 文件随 CW-042 退休」，非逐文件迁移；44 项部分核销 + §5.1.3 R1–R5 + 路由级 dev-header 用例的机制退役登记见 §D，对应业务主不变量均已在真实 PG 断言级证明。
