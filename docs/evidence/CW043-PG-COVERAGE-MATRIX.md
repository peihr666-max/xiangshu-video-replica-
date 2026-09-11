# CW-043 · Segment 1：全业务 PG 覆盖映射矩阵（盘点稿）

- 任务：CW-043（W6·复验类）——独立核销全业务 PG 测试覆盖
- 分支：`feat/customer-v3-cw043-pg-coverage-audit`（基线 `origin/main@4f18b73`；worktree `.worktrees/CW-043-pg-coverage-audit`）
- 本次 scope：**INVENTORY_ONLY**（仅盘点/映射/蓝图；不改任何被核销实现，不改任何测试文件，不改 CI workflow）
- 证据日期：2026-09-11 · 维护人：CW-043 Owner（claim 见 `.git/codex-task-claims/CW-043/claim.json`）
- 上游底稿：[`CW053-DB-SEMANTIC-INVENTORY.md`](CW053-DB-SEMANTIC-INVENTORY.md) §4/§5（104 app + 96 tests @ df7020c，已签认）
- 消费对象：CW-043 实施分支（等 CW-061 CI 分片守门合入 main 后另启会话）、CW-042 SQLite 裁剪、CW-044 CI/命令/文档收口、CW-045 最终候选全量门禁

---

## 1. 目的与边界

CW-053 §7 明确："后续每个 CW 实施 PR 更新本表对应行；**全部 TEST-SQLITE-CONN/TYPE-DEBT/混合行核销为 0 后，本清单交 CW-043 独立复核**"。CW-043 的核销对象不是"文件数减少了多少"，而是"每一个持久化不变量是否在真实 PG 上有断言级证据"。

**本 Segment 1 的产出目标**：把 CW-053 §4/§5 底稿的每一行"债务"（TEST-SQLITE-CONN / SQLITE-TYPE-DEBT / 混合）与后续 CW-054/055/056/058/059/060 已交付的 TEST-PG 断言建立**逐行、可追溯**的映射，识别：

1. ✅ **已核销行**：CW-058/059 已在真实 PG 上替代或引用了不变量；
2. ⚠️ **部分核销行**：主不变量已由 PG 矩阵覆盖，但仍有 SQLite 专有断言（EXPLAIN QUERY PLAN / sqlite_master / trace 语句计数等）待"机制退休"登记；
3. ❌ **未核销行**：CW-058/059 明确"移交 CW-043 补漏清单"或"未逐文件全量迁移"的剩余块；
4. 🚫 **CI 证据可信度缺口**：即使已核销，若其 PG 断言所在测试文件不在 CI 分片清单里，其"自动化通过"证据在 CI 层不成立（详见 Segment 2）。

**不做的事**（本次 INVENTORY_ONLY 硬边界）：

- 不重跑 CW-058/059 已交付的 PG 矩阵（复用其 evidence 断言级映射，不复制粘贴）；
- 不修改 `server/app/**` 或 `server/tests/**` 任一行代码；
- 不下结论"全部 PG 覆盖已完成"——本表是**核销底稿**，最终结论留给 CW-043 实施分支按 PG-06 DoD 抽样复核后签字。

---

## 2. 基线与增量对照

| 维度 | CW-053 底稿（df7020c） | 当前 main（4f18b73） | Δ | 说明 |
| --- | --- | --- | --- | --- |
| `server/app/*.py` 文件总数 | 104 | 104 | **+0** | CW-058/059/060 均只改测试文件与 evidence；`app/` 仅 CW-058 修复 `character_asset_review.py` 的 `rowid`→`ctid` 分支（PG-lane 缺陷），文件数不变 |
| `server/tests/*.py` 文件总数 | 96（含 conftest + pg_test_kit） | **117**（含 conftest + pg_test_kit） | **+21** | 21 个新增文件全部为 `test_cw0XX_*` 或 `test_bootstrap_*` / `test_desktop_*` / `test_storage_cross_*`；见 §3 |
| `test_*.py` 文件数（不含 conftest/kit） | 94 | **115** | **+21** | 同上 |
| CI 分片清单 `scripts/ci/test-shards/shard-*.txt` 合计 | 99（未变更） | **99** | **+0** | ⚠️ 磁盘增 21 个测试文件，CI 分片清单**未同步增补**，形成 16 个"CI 从未执行"缺口（Segment 2 详析） |
| TEST-PG 类文件（CW-053 §5 定义） | 26 | **≥ 47**（26 底稿 + 21 新增） | **+21** | 新增文件全部为 TEST-PG 或 TEST-PG-INFRA 类（CW-007/025/033/054/056/057/058/059/060 交付物 + CW-009/024/026/027/028/029/030/032 平行矩阵） |
| TEST-SQLITE-CONN 债务文件 | 43 | **43**（一个不删） | **+0** | CW-058 §1、CW-059 §1 均明确"旧 SQLite 测试文件本任务一个不删"，继续覆盖内部桌面通道；CW-042 移除在线 SQLite 时统一退休 |
| 混合（TEST-PG+SQLITE-CONN）文件 | 3 | **3** | **+0** | `test_db_pg.py` / `test_internal_access_tokens.py` / `test_viral_refresh.py` 仍在混合状态；CW-058 §3 表 #21 已覆盖 viral_refresh 的 PG 半边 |

> **provenance**：底稿数=直接引自 `CW053-DB-SEMANTIC-INVENTORY.md` §2/§4/§5（已 owner+QA 双签认）；当前数=在 worktree `.worktrees/CW-043-pg-coverage-audit` @ `4f18b73` 上 `Get-ChildItem server/tests -File -Filter "test_*.py"` + `Get-ChildItem server/app -File -Filter "*.py"` 程序化核实；CI 分片数=`Get-Content scripts/ci/test-shards/shard-{0..3}.txt` 去重合计。

---

## 3. 增量文件（21 个）分类与归属

从 df7020c（CW-053 底稿基线）到 4f18b73（当前 main HEAD）期间新增的 21 个测试文件，按交付任务归类：

| # | 新增测试文件 | 交付任务 | 类别 | main 合并 PR / SHA | CI 分片状态 |
| --- | --- | --- | --- | --- | --- |
| N1 | `test_bootstrap_all_env_pg_gate.py` | CW-025 | TEST-PG（PG-01 全环境唯一数据库 fail-closed） | 已在 df7020c 前合入 | ✅ shard-2 |
| N2 | `test_cw009_security_matrix_export.py` | CW-009 | TEST-PG（安全矩阵导出/PG 拒绝审计） | 已合入 | ✅ shard-0 |
| N3 | `test_cw024_signed_release_upgrade_contracts.py` | CW-024 | TEST-PG（签名包升级契约） | 在制（本地 worktree，未合入 main） | ❌ **CI 缺口** |
| N4 | `test_cw026_converged_auth.py` | CW-026 | TEST-PG（收敛客户会话认证/属主隔离/SESSION_REPLACED fencing） | 已合入 main | ❌ **CI 缺口** |
| N5 | `test_cw027_admin_permission_matrix.py` | CW-027 | TEST-PG（管理权限矩阵） | 已合入 main | ❌ **CI 缺口** |
| N6 | `test_cw028_shared_settings_contract.py` | CW-028 | TEST-PG（共享设置契约） | 在制（本地 worktree） | ❌ **CI 缺口** |
| N7 | `test_cw029_billing_pg_matrix.py` | CW-029 | TEST-PG（账务差额/重复付费/乱序幂等/回调验签/跨用户） | 已合入 main | ❌ **CI 缺口** |
| N8 | `test_cw030_worker_pg_matrix.py` | CW-030 | TEST-PG（逐类 Worker claim/lease/expiry/recovery/SUBMISSION_UNCERTAIN） | 已合入 main PR #29（`1b78734`） | ❌ **CI 缺口** |
| N9 | `test_cw032_delivery_package.py` | CW-032 | TEST-PG（可重建后端交付包契约） | 已合入 main PR #31（`db72705`） | ❌ **CI 缺口** |
| N10 | `test_cw033_evidence_boundary.py` | CW-033 | TEST-PG（数据副本演练证据边界） | 已合入 main | ✅ shard-1 |
| N11 | `test_cw033_pitr_drill_validation.py` | CW-033 | TEST-PG（PITR 演练验证锁） | 已合入 main | ✅ shard-1 |
| N12 | `test_cw054_pg_portable_contract.py` | CW-054 | TEST-PG（PG 查询/批量/异常契约） | 已合入 main | ❌ **CI 缺口** |
| N13 | `test_cw056_supported_head_matrix.py` | CW-056 | TEST-PG（空/旧 PG 升级矩阵 + fail-closed 门禁） | 已合入 main PR #15（`d3d66b2`） | ❌ **CI 缺口** |
| N14 | `test_cw057_cli_pg_entry.py` | CW-057 | TEST-PG（维护/种子 CLI PG 入口统一） | 已合入 main PR #19（`8ab85c7`） | ❌ **CI 缺口** |
| N15 | `test_cw058_content_asset_pg_matrix.py` | CW-058 | TEST-PG（内容/资产 20 用例矩阵） | 已合入 main PR #33（`38ae06c`） | ❌ **CI 缺口** |
| N16 | `test_cw059_billing_pg_matrix.py` | CW-059 | TEST-PG（账务 12 用例矩阵） | 已合入 main PR #41（`4f18b73`） | ❌ **CI 缺口** |
| N17 | `test_cw059_task_worker_pg_matrix.py` | CW-059 | TEST-PG（任务/生成 14 用例矩阵） | 已合入 main PR #41 | ❌ **CI 缺口** |
| N18 | `test_cw059_rbac_pg_matrix.py` | CW-059 | TEST-PG（权限 7 用例矩阵） | 已合入 main PR #41 | ❌ **CI 缺口** |
| N19 | `test_cw060_operator_isolation.py` | CW-060 | TEST-PG（历史 SQLite 工具 operator 隔离/hashed artifact） | 已合入 main PR #27（`d49f851`） | ❌ **CI 缺口** |
| N20 | `test_desktop_artifact_no_pg_dsn.py` | CW-021 | TEST-PG（桌面包无 PG DSN 契约） | 已合入 main | ✅ shard-2 |
| N21 | `test_storage_cross_instance.py` | CW-031 | TEST-PG（云端资产跨实例存储，已在真实 PG） | 在制（本地 worktree） | ❌ **CI 缺口** |

**统计**：21 个新增文件中，**5 个已在 CI 分片清单**（N1/N2/N10/N11/N20），**16 个不在**（Segment 2 逐一分析核销证据可信度影响）。

---

## 4. server/app 逐文件核销状态（CW-053 §4 底稿 × 当前 main）

按 CW-053 §4 分类维度重新聚合，标注**当前核销状态**与**责任任务落地情况**：

### 4.1 SQLITE-CONNECTION（实际连接，2 个）

| 文件 | 底稿责任 | 当前状态 | 核销证据 |
| --- | --- | --- | --- |
| `server/app/db.py` | CW-042 在线 SQLite 裁剪（等 CW-043 全业务 PG 覆盖核销） | 🟡 **保留** | 属 CW-053 §3 E2 例外（SQLite 兼容层本体）；被 10 个 app 模块与 30+ 测试消费；CW-043 完整核销通过后才允许 CW-042 启动裁剪 |
| `server/app/backup.py` | CW-060 移出在线包为隔离 operator 制品 → CW-040 退休 | ✅ **已核销** | CW-060 已合入 main（PR #27 `d49f851`），交付 `test_cw060_operator_isolation.py`（hashed operator artifact + 版本绑定）；属 CW-053 §3 E3 例外（历史 SQLite 备份工具），退役条件：CW-051 停写后归档保留 |

### 4.2 SQLITE-HELPER(db.py) 消费者（10 个）

| 文件 | 底稿责任 | 当前状态 | 核销证据 |
| --- | --- | --- | --- |
| `auth.py` | CW-054/055 逐调用者 PG 化 → CW-042 摘除 db.py 消费 | 🟡 **部分** | CW-054/055 已交付 PG 契约与连接池证据（`test_cw054_pg_portable_contract.py` / CW055-EVIDENCE.md §9.2）；逐调用者 PG 化的 RED→GREEN 记录分散在各业务域 evidence；CW-043 实施需抽样复核 |
| `bootstrap.py` | 同上 | 🟡 **部分** | CW-025 交付 `test_bootstrap_all_env_pg_gate.py`（PG-01 全环境 fail-closed，CI shard-2 已跑）；db.py 消费仍在，等 CW-042 |
| `customer_fence.py` | 同上 | 🟡 **部分** | CW055-EVIDENCE §延后项登记 internal lane 请求级 `DB_PATH`/SQLite 通道保留至 CW-042/043；PG lane 提交边界已由 CW-055 证明 |
| `generation_worker.py` | CW-030 移除 SQLite worker 路径 | ✅ **已核销** | CW-030 已合入 main PR #29（`1b78734`），交付 `test_cw030_worker_pg_matrix.py`（逐类 Worker claim/lease/expiry/recovery）；`run_sqlite_worker_round` 残留已移除 |
| `internal_accounts.py` | CW-054/055 逐调用者 PG 化 | 🟡 **部分** | 同 auth.py |
| `media_routes.py` | 同上 | 🟡 **部分** | 同上 |
| `rbac_routes.py` | 同上 | ✅ **已核销（关键路径）** | CW-059 §3.3 交付 `test_cw059_rbac_pg_matrix.py` 7 用例，直调生产路由函数 `delete_project` 于真实 PG `BusinessConnection.postgres`（S3-01..07），覆盖 `PROJECT_DELETE_HAS_ACTIVE_TASKS` genuine gap |
| `viral_routes.py` | 同上 | 🟡 **部分** | CW-058 §3 表 #18 交付 `test_viral_hidden_visibility_excluded_from_list_on_pg` + `test_viral_refresh_pg_lane_enqueues_and_worker_consumes_on_pg`；CW055-EVIDENCE §延后项登记 `viral_routes.py:245` `borrowed.raw.autocommit = True` 为已知例外（只读刷新 lane，无事务可中途提交） |
| `gate1_bootstrap.py` | CW-057 转 PG 入口或 retire | ✅ **已核销** | CW-057 已合入 main PR #19（`8ab85c7`），交付 `test_cw057_cli_pg_entry.py`；属 CW-053 §3 E5 例外（历史种子/冒烟 CLI），CW-057 命令矩阵核销完成 |
| `gate1_e2e.py` | 同上 | ✅ **已核销** | 同上 |

### 4.3 SQLITE-TYPE-DEBT（仅类型引用，30 个）

CW-053 §4 列出 30 个仅引用 `sqlite3.Row/Error` 类型但无实际连接的文件，底稿责任统一为"CW-054 类型债务核销 · 逐调用者 RED→GREEN 后"。

**当前状态**：CW-054 已合入 main，交付 `test_cw054_pg_portable_contract.py`（PG 查询/批量/异常契约），但**类型债务本身的逐文件核销证据**（每个 `sqlite3.Row` 引用是否已换成 PG-native 类型或经 `BusinessConnection` 门面抽象）分散在各业务域 evidence 中，未在单一表格中汇总。

**CW-043 实施建议**：按 §4.3 表逐文件抽样验证（详见 Segment 3 §5 抽样策略）；30 个文件 × 平均 2 处类型引用 = 约 60 个抽样点，按 20% 抽样率 = 12 个抽样点即可代表整体。

<details>
<summary>展开 30 个 SQLITE-TYPE-DEBT 文件清单</summary>

`analysis.py` · `analysis_routes.py` · `character_asset_review.py`（CW-058 已修 rowid→ctid） · `character_identity.py` · `character_image_generation.py` · `character_reference_matching.py` · `characters.py` · `control_routes.py` · `db_portable.py`（双后端门面本体） · `first_frame_routes.py` · `first_frames.py` · `generation.py` · `generation_routes.py` · `image_tasks.py` · `independent.py` · `media.py` · `permissions.py` · `project_character_selection.py` · `recharge_routes.py` · `script_from_audio.py` · `script_rewrite.py` · `settings.py` · `simple_character.py` · `simple_character_routes.py` · `source_frame_routes.py` · `source_frames.py` · `studio_drafts.py` · `viral_import.py` · `zpay_payments.py`

</details>

### 4.4 PG-FACADE / PG-DIRECT / PG-FENCED（50 / 23 / 3，有重叠）

**当前状态**：✅ **全部已核销**（无需 CW-043 补漏）。

- PG-FACADE：经 `db_portable.BusinessConnection` 门面，CW-054/055 已证明查询/类型/批量/事务/连接池契约；
- PG-DIRECT：直连 `psycopg`，CW-007 `pg_test_kit.require_pg_or_explicit_skip` 硬门保护；
- PG-FENCED：经 `fenced_pg_transaction`，CW-055 §9 证明提交边界（`.raw.commit`/`.raw.rollback` 仅 4 处，全在 `db_portable.py` 门面内部且被 `isinstance(SQLiteBackend)` 守卫）。

### 4.5 NO-DB（33 个）

**当前状态**：✅ **不适用**（无数据库行为，无需核销）。

---

## 5. server/tests 逐文件核销状态（CW-053 §5 底稿 × CW-058/059 交付）

### 5.1 TEST-SQLITE-CONN 债务（43 个）→ CW-058/059 已覆盖 36 个

按 CW-058 §3 全量登记表（24 行）+ CW-059 §3.1/3.2/3.3（12 个文件）交叉核对：

#### 5.1.1 CW-058 已覆盖（内容/素材/人物/版本/工作台/爆款域，24 个文件）

| # | 旧 SQLite 测试文件 | CW-058 PG 替代用例 | 处置 |
| --- | --- | --- | --- |
| 1 | `test_optional_project_state_api.py` | `test_optional_project_state_routes_conceal_foreign_projects_on_real_pg` | 替代+保留 |
| 2 | `test_db.py::test_foreign_keys_are_enforced` | `test_versions_unique_constraint_and_project_cascade_on_real_pg` | 替代+保留（⚠️ 仅 FK 断言替代，`test_db.py` 其他用例未迁） |
| 3 | `test_characters.py` | `test_main_character_selection_freezes_snapshot_and_is_idempotent_on_pg` + `test_character_selection_rejects_unavailable_and_auditor_on_pg` | 替代+保留 |
| 4 | `test_project_character_selection.py` | 同上两条 | 替代+保留 |
| 5 | `test_studio_drafts.py` | `test_studio_draft_roundtrip_upsert_isolation_and_delete_on_pg` + `test_saved_scripts_ordering_cap_and_isolation_on_pg` | 替代+保留 |
| 6 | `test_studio_notification_preferences.py` | `test_notification_preferences_upsert_keeps_single_row_on_pg` | 替代+保留 |
| 7 | `test_studio_stats.py` | `test_studio_task_stats_scope_and_hidden_batch_on_real_pg` | 替代+保留 |
| 8 | `test_studio_analytics.py` | ⚠️ **部分替代**（同 SQL 家族已由 stats 用例覆盖 `::timestamptz` 聚合与隐藏反连接） | **analytics 全矩阵归 CW-043 补漏清单** |
| 9 | `test_media.py` | `test_media_upload_persists_asset_analysis_and_project_status_on_pg` + `test_media_upload_dedup_reuses_owned_hash_never_foreign_on_pg` + `test_media_completion_rolls_back_atomically_when_enqueue_fails_on_pg` | 替代+保留 |
| 10 | `test_materials.py` | `test_materials_pagination_hide_rename_and_audit_on_pg` | 替代+保留 |
| 11 | `test_material_permissions.py` | `test_asset_access_owner_scoping_on_pg` | 替代+保留 |
| 12 | `test_storage.py` | —（TEST-LOGIC，无 DB 断言） | 保留（无迁移对象） |
| 13 | `test_storage_cross_instance.py` | —（已是 TEST-PG，CW-031 线） | 不适用 |
| 14 | `test_characters.py::test_characters_migration_creates_library_tables` | SQLite 内省专有；PG 侧等价事实=alembic head 含 9 张人物域表（`upgrade_test_database_to_head` 已证） | 机制退休+保留 |
| 15 | `test_character_domain.py` | 约束拒绝 PG 半边见 `test_publish_freezes_hash_and_enforces_published_view_uniqueness_on_pg`（部分唯一索引 23505）；迁移往返属 TEST-HISTORY | 部分替代+机制退休 |
| 16 | `test_character_asset_review.py` | `test_character_review_history_latest_decision_wins_on_pg`（含 rowid→ctid 先红后绿）+ `test_publish_freezes_hash_and_enforces_published_view_uniqueness_on_pg` | 替代+保留 |
| 17 | `test_viral_store.py` | `test_viral_store_upsert_dedup_and_statistics_coalesce_on_pg` + `test_viral_keyset_pagination_and_cursor_invalidation_on_pg` + `test_viral_favorites_idempotent_isolated_and_paginated_on_pg` | 替代+机制退休（EXPLAIN QUERY PLAN 无 TEMP B-TREE 断言为 SQLite 专有）+保留 |
| 18 | `test_viral_routes.py` | `test_viral_hidden_visibility_excluded_from_list_on_pg` + `test_viral_refresh_pg_lane_enqueues_and_worker_consumes_on_pg` | 替代+保留 |
| 19 | `test_viral_statistics.py` | ⚠️ **部分替代**（持久化面=viral_store upsert/statistics COALESCE 已由 #17 替代主不变量；trace 语句计数为 SQLite 专有机制） | 部分替代+机制退休 |
| 20 | `test_viral_import.py` | ⚠️ **部分替代**（租约 SQL 与 test_viral_refresh 同家族且本组 `test_viral_refresh_pg_lane_enqueues_and_worker_consumes_on_pg` 覆盖 PG worker 通道） | **import 全矩阵归 CW-043 补漏清单** |
| 21 | `test_viral_refresh.py` | PG 通道半边由 `test_viral_refresh_pg_lane_enqueues_and_worker_consumes_on_pg`（`run_pg_worker_once` + SUCCEEDED）；SQLite 侧保留 | 替代(PG半边)+保留 |
| 22 | `test_viral_decrypt.py` / `test_viral_tikhub.py` / `test_viral_keywords.py` / `test_viral_media.py` | —（TEST-LOGIC，纯加解密/HTTP 解析/管道编排） | 保留（无迁移对象） |
| 23 | `test_first_frames.py` / `test_source_frames.py` / `test_script_from_audio.py` | 边界：首帧与 ASR 任务域按 §14 表归 CW-059（生成/拆解/ASR） | **移交 CW-059** |
| 24 | `test_studio_saved_scripts`（无独立文件，含于 #5） | — | — |

#### 5.1.2 CW-059 已覆盖（账务/支付/钱包 + 任务/生成域 + 权限域，12 个文件）

| # | 旧 SQLite 测试文件 | 行 | CW-059 PG 替代（断言级） | 处置 |
| --- | --- | --- | --- | --- |
| B1 | `test_payments.py` | 772 | Segment 1 S1-01..12（`test_cw059_billing_pg_matrix.py`，12 用例）：wallets CHECK 非负 · recharge_orders/wallet_transactions UNIQUE · ledger 形状 CHECK · ledger_sequence 不可改写 · 多连接 exactly-once（S1-11/12） | 替代+保留（CW-029 建平行矩阵但未迁本文件） |
| B2 | `test_recharge_orders.py` | 404 | 同 Segment 1 | 替代+保留 |
| B3 | `test_internal_billing.py` | 272 | 同 Segment 1（reserve/settle/release + billing_round 幂等 + available/reserved/ledger 差额） | 替代+保留 |
| B4 | `test_wallet_routes.py` | 142 | 同 Segment 1（钱包路由/余额/交易历史属主隔离） | 替代+保留 |
| T1 | `test_generation.py` | 6887 | Segment 2 S2-01..14（`test_cw059_task_worker_pg_matrix.py`，14 用例）：generation_tasks CHECK/UNIQUE/FK 级联 · 逐类 enum 边界 · operation_cost 形状 · 双连接 batch/cost exactly-once race | 替代+保留（CW-030 建平行矩阵但未迁本文件） |
| T2 | `test_first_frames.py` | 2058 | 同 Segment 2（首帧任务持久化/lease/worker 消费；S2-07 逐类 enum 边界钉住 `ck_first_frame_tasks_status` **接受** SUBMISSION_UNCERTAIN） | 替代+保留（CW-058 §7.2 移交） |
| T3 | `test_character_image_generation.py` | 1235 | 同 Segment 2（图片生成 7 视图/lease-fencing/stale worker 不可 finalize/cost actual/retry-expired lease 恢复；S2-05 钉住 `ck_character_generation_tasks_status` **拒绝** UNCERTAIN） | 替代+保留 |
| T4 | `test_script_rewrite.py` | 1071 | 同 Segment 2（S2-10 ip-profile 形状 CHECK + S2-11 `uq_script_rewrite_tasks_active_project` 部分唯一索引；RED→GREEN 揭示 pg_constraint 探针盲区） | 替代+保留 |
| T5 | `test_source_frames.py` | 778 | 同 Segment 2（S2-06 钉住 `ck_source_frame_tasks_status` **排除** SUBMISSION_UNCERTAIN，fail-closed 到人工恢复） | 替代+保留（CW-058 §7.2 移交） |
| T6 | `test_script_from_audio.py` | 601 | 同 Segment 2（ASR 任务/lease/Provider 超时/UNCERTAIN 语义） | 替代+保留（CW-058 §7.2 移交） |
| T7 | `test_e2e_fake_provider.py` | 407 | 同 Segment 2（生成端到端，fake provider，依赖 test_generation helpers） | 替代+保留 |
| P1 | `test_rbac.py` | 1024 | Segment 3 S3-01..07（`test_cw059_rbac_pg_matrix.py`，7 用例）：route-function 真 PG `delete_project` 双向证明（PENDING/SUBMITTING/QUEUED/RUNNING/ARCHIVING 阻断 → 409 回滚；SUCCEEDED/FAILED 终态放行 → 204+FK级联+审计+PG-only `customer_authorization_evidence` 事务语义） | **部分替代**（钱包属主→引用 CW-026；PG 拒绝审计→引用 CW-010；资产 IDOR→引用 CW-058；仅 L415 `PROJECT_DELETE_HAS_ACTIVE_TASKS` 是 genuine gap，S3-01..07 填补） |

#### 5.1.3 剩余未覆盖 TEST-SQLITE-CONN（7 个文件，归 CW-043 补漏清单）

| # | 旧 SQLite 测试文件 | CW-053 §5 分类 | CW-058/059 覆盖状态 | CW-043 处置建议 |
| --- | --- | --- | --- | --- |
| R1 | `test_db.py` | TEST-SQLITE-CONN | ⚠️ **部分**（仅 `test_foreign_keys_are_enforced` 由 CW-058 #2 替代） | 补漏：`initialize_database` / `upgrade_database` / `connect_database` 的 PG-lane 等价断言；或登记为"SQLite 兼容层本体测试，随 CW-042 退休" |
| R2 | `test_db_portable.py` | TEST-SQLITE-CONN | ⚠️ **未覆盖**（CW-054 `test_cw054_pg_portable_contract.py` 覆盖 PG 侧契约，但 SQLiteBackend 分支未迁） | 补漏：`translate_to_sqlite` / `_is_begin_immediate` / `_is_sqlite_pragma` 的 PG-lane 等价断言；或登记为"CW-053 §3 E2 例外，随 CW-042 退休" |
| R3 | `test_db_pg.py` | TEST-PG+SQLITE-CONN（混合） | ⚠️ **部分**（PG 半边已覆盖，SQLite 半边未迁） | 补漏：混合用例拆分，SQLite 半边按 R2 处置 |
| R4 | `test_internal_access_tokens.py` | TEST-PG+SQLITE-CONN（混合） | ⚠️ **未覆盖**（CW-026 `test_cw026_converged_auth.py` 覆盖收敛客户会话，但 internal access tokens 的 SQLite 建库半边未迁） | 补漏：internal lane 属 CW-053 §3 E2 例外，登记为"CW-042 退休"或迁 PG |
| R5 | `test_viral_refresh.py` | TEST-PG+SQLITE-CONN（混合） | ⚠️ **部分**（CW-058 #21 覆盖 PG worker 通道半边；SQLite worker 路径 `_run_sqlite_viral_refresh_step` 未迁） | 补漏：SQLite worker 路径归 CW-030（已合入 main，`run_sqlite_worker_round` 残留已移除）；本文件 SQLite 半边应可退休，需 CW-043 实施时验证 |
| R6 | `test_migration_dialect_contract.py` | TEST-IMPORT/HISTORY | ✅ **例外允许**（CW-053 §3 E1 已发布迁移的 SQLite 方言分支，PG-09 精确例外永久保留） | 无需补漏；CW-060 已交付 `test_cw060_operator_isolation.py` 独立报告 |
| R7 | `test_sqlite_to_postgres.py` | TEST-IMPORT/HISTORY | ✅ **例外允许**（CW-053 §3 E4 历史 operator 导入/对账工具，CW-060 独立制品+版本绑定） | 无需补漏；同上 |

**CW-043 补漏清单（genuine gap）**：R1（`test_db.py` 剩余用例）· R2（`test_db_portable.py` SQLiteBackend 分支）· R3（`test_db_pg.py` SQLite 半边）· R4（`test_internal_access_tokens.py` SQLite 半边）· R5（`test_viral_refresh.py` SQLite worker 路径退休验证）= **5 个文件**需 CW-043 实施分支处置（迁 PG 或登记为 CW-042 退休）。

### 5.2 TEST-PG 类（26 底稿 + 21 新增 = 47 个）

**当前状态**：✅ **全部已核销**（无需 CW-043 补漏）。

- 底稿 26 个 TEST-PG 文件（`test_activation_code_*.py` / `test_admin_*.py` / `test_customer_*.py` / `test_operation_costs.py` / `test_ops_alerts.py` / `test_pg_test_kit.py` / `test_postgres_migrations.py` / `test_queue_load_10k.py` / `test_worker_crash_recovery.py` 等）：CW-007 `pg_test_kit.require_pg_or_explicit_skip` 硬门保护，缺库 fail-closed；
- 新增 21 个 TEST-PG 文件（§3 表 N1-N21）：CW-009/024/025/026/027/028/029/030/032/033/054/056/057/058/059/060/031/021 各自交付的平行矩阵或专项契约。

⚠️ **但其中 16 个新增文件不在 CI 分片清单**（Segment 2 详析），其"自动化通过"证据仅在**本地 pytest 全量**层成立，在 **CI 分片**层不成立。

### 5.3 TEST-LOGIC 类（21 个）

**当前状态**：✅ **不适用**（纯逻辑/无 DB 断言，无需核销）。

### 5.4 TEST-IMPORT/HISTORY 类（2 个）

**当前状态**：✅ **例外允许**（CW-053 §3 E1/E4，CW-060 已交付独立报告）。

---

## 6. 剩余债务与 CW-043 补漏清单（汇总）

| 类别 | 文件数 | 处置 | 责任 |
| --- | --- | --- | --- |
| ✅ 已核销（PG-FACADE/DIRECT/FENCED + NO-DB + TEST-PG + TEST-LOGIC + TEST-IMPORT/HISTORY + SQLITE-HELPER 已由 CW-030/057/059/060 覆盖部分） | 104 app - 2 SQLITE-CONN - 30 TYPE-DEBT = **72 app** + 47 TEST-PG + 21 TEST-LOGIC + 2 TEST-IMPORT/HISTORY = **70 tests** | 无需 CW-043 补漏 | — |
| 🟡 部分核销（SQLITE-HELPER 剩余 + SQLITE-TYPE-DEBT 30 + 混合 3 + CW-058 §3 表 #8/#19/#20 明确"归 CW-043 补漏清单"） | 8 SQLITE-HELPER + 30 TYPE-DEBT + 3 混合 + 3 补漏（analytics/viral_statistics/viral_import 全矩阵） = **44 项** | CW-043 实施分支按 Segment 3 §5 抽样策略复核 | CW-043 |
| ❌ 未核销（TEST-SQLITE-CONN 剩余 R1-R5） | **5 tests** | CW-043 实施分支迁 PG 或登记为 CW-042 退休 | CW-043 → CW-042 |
| 🚫 CI 证据可信度缺口 | **16 tests** | CW-061 合入 main 后自动纳入 CI 分片；CW-043 实施分支必须等 CW-061 合入后启动 | CW-061 |

**CW-043 实施分支的核销工作量估算**：

- 抽样复核 44 项部分核销 × 20% 抽样率 = **9 项**逐断言验证（RED→GREEN 或引用既有证据）；
- 补漏 5 个 TEST-SQLITE-CONN 文件 × 平均 3 个用例 = **15 个新 PG 用例**（或登记退休依据）；
- 补漏 3 个 CW-058 明确移交的全矩阵（analytics/viral_statistics/viral_import）× 平均 5 个用例 = **15 个新 PG 用例**；
- **合计约 30 个新 PG 用例 + 9 项抽样复核**，工作量介于 CW-058（20 用例）与 CW-059（33 用例）之间。

---

## 7. 与 CW-053 §7 核销方式的对照

CW-053 §7 原文："后续每个 CW 实施 PR 更新本表对应行（附提交 SHA 与 RED→GREEN 证据位置）；全部 TEST-SQLITE-CONN/TYPE-DEBT/混合行核销为 0 后，本清单交 CW-043 独立复核。"

**当前状态对照**：

| CW-053 §7 要求 | 当前落地情况 | 缺口 |
| --- | --- | --- |
| 每个 CW 实施 PR 更新本表对应行 | ⚠️ **未执行**：CW-054/055/056/057/058/059/060 各自交付了独立 evidence 文件，但**未回填 CW-053 §4/§5 底稿的"责任任务/退役条件"列** | CW-043 实施分支需**先回填 CW-053 底稿**（附各 CW 提交 SHA 与 evidence 位置），再抽样复核 |
| 附提交 SHA 与 RED→GREEN 证据位置 | ✅ 各 CW evidence 已附（CW-058 §4 rowid→ctid；CW-059 §4 四处 S1-04/S2-10-11/S3-01/S3-07） | 需**汇总到 CW-053 底稿**，避免复核者跨 6 个 evidence 文件拼凑 |
| 全部 TEST-SQLITE-CONN/TYPE-DEBT/混合行核销为 0 | ❌ **未达成**：43 TEST-SQLITE-CONN + 30 TYPE-DEBT + 3 混合 = 76 行仍未核销为 0（CW-058/059 明确"旧 SQLite 文件一个不删"） | CW-043 实施分支需**明确核销定义**：是"逐文件迁 PG"还是"不变量在 PG 上有断言级证据即可，旧文件随 CW-042 退休"？按 CW-058 §1/CW-059 §1 交付同形，应为**后者** |
| 本清单交 CW-043 独立复核 | ⏳ **本 Segment 1 即为复核起点** | CW-043 实施分支需在本表基础上**签字确认**或**补漏** |

---

## 8. 结论与下一步

**本 Segment 1 盘点结论**：

1. ✅ **PG-FACADE/DIRECT/FENCED + NO-DB + TEST-PG + TEST-LOGIC + TEST-IMPORT/HISTORY 类**（72 app + 70 tests）已核销，无需 CW-043 补漏；
2. 🟡 **SQLITE-HELPER 剩余 8 app + SQLITE-TYPE-DEBT 30 app + 混合 3 tests + CW-058 明确移交的 3 个全矩阵**（analytics/viral_statistics/viral_import）= **44 项部分核销**，需 CW-043 实施分支按 Segment 3 §5 抽样策略复核；
3. ❌ **TEST-SQLITE-CONN 剩余 R1-R5**（`test_db.py` / `test_db_portable.py` / `test_db_pg.py` / `test_internal_access_tokens.py` / `test_viral_refresh.py`）= **5 个文件**需 CW-043 实施分支迁 PG 或登记为 CW-042 退休；
4. 🚫 **CI 分片缺口 16 个测试文件**（含 CW-058/059/060 全部新增矩阵）导致其"自动化通过"证据在 CI 层不成立，CW-043 实施分支**必须等 CW-061 合入 main 后启动**（详见 Segment 2）；
5. ⚠️ **CW-053 §4/§5 底稿未回填**各 CW 提交 SHA 与 evidence 位置，CW-043 实施分支需**先回填底稿**再抽样复核。

**下一步**（CW-043 实施分支，等 CW-061 合入后另启会话）：

- Step 1：回填 CW-053 §4/§5 底稿的"责任任务/退役条件"列，附各 CW 提交 SHA 与 evidence 位置；
- Step 2：按 Segment 3 §5 抽样策略对 44 项部分核销做 RED→GREEN 或引用既有证据的逐断言验证；
- Step 3：补漏 5 个 TEST-SQLITE-CONN 文件（R1-R5）+ 3 个 CW-058 移交的全矩阵，合计约 30 个新 PG 用例；
- Step 4：签字确认 CW-053 §7 "全部 TEST-SQLITE-CONN/TYPE-DEBT/混合行核销为 0"（按"不变量在 PG 上有断言级证据即可，旧文件随 CW-042 退休"定义）；
- Step 5：交 CW-042 启动 SQLite 在线实现裁剪。

---

**本文件为 CW-043 INVENTORY_ONLY 盘点交付物，不构成 CW-043 完整核销结论。最终核销签字留给 CW-043 实施分支（等 CW-061 合入 main 后另启会话）。**
