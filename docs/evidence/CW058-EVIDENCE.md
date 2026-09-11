# CW-058 证据：补齐内容与资产测试的真实PG覆盖

- 任务：CW-058（W6·代码与测试增量）——内容/素材/人物/版本/工作台/爆款域测试迁真实 PG
- 分支：`feat/customer-v3-cw058-content-asset-pg-tests`（基线 origin/main@`8ab85c7`，worktree `.worktrees/CW-058-content-asset-pg-tests`）
- 证据等级目标：AUTOMATED_VERIFIED（本任务交付矩阵范围）；内容域**全量**映射闭合按完工标准交 CW-043 复核
- 证据日期：2026-09-11 · 维护人：CW-058 Owner（claim 见 `.git/codex-task-claims/CW-058/claim.json`）

## 1. 交付范围与方式

按 CW-029 交付同形：沿用既有行为测试的持久化断言，把它们整体重放在真实 PostgreSQL
上（`server/tests/test_cw058_content_asset_pg_matrix.py`，20 用例），而不是改写 30 个
旧 SQLite 文件的 fixture。原因与边界：

1. 前置 CW-054/055 已把业务 SQL 收敛为「PG 规范式 + translate_to_sqlite 降级」，
   服务层不含 SQLite 专有 SQL（除本任务修复的 `character_asset_review.py` `rowid`，
   见 §4）。因此迁移的实质是**测试座与断言环境**：旧断言组 → 同一不变量在 PG 通道
   复现（PG-06）。
2. 旧 SQLite 测试文件本任务**一个不删**（§3 给出全部 30 个文件的逐文件映射与
   替代/退休编号）；它们继续覆盖内部桌面通道（CW-042 移除在线 SQLite 实现时统一
   退休），不构成本组 TEST-PG 类的替代证据。
3. 本任务不重建内容功能、不新增 ORM/多后端抽象（PG-01/PG-12）。

## 2. 测试资源与合同（PG-05）

| 项 | 值 |
| --- | --- |
| PG server_version | PostgreSQL 16.15（docker `postgres:16.15-alpine`，容器 `vs-pg-cw058`） |
| 隔离 | 宿主端口 5440（与在用 5433–5439 全隔离）；专属库 `cw058_content_asset_test` |
| DSN 注入 | `TEST_POSTGRESQL_URL=postgresql://...@localhost:5440/customer_v3_test`；建库经 `pg_test_kit.create_test_database`（allowlist 已登记 `cw058_content_asset_test`） |
| schema | `upgrade_test_database_to_head`（alembic head=`081_oral_unit_price`） |
| 缺库行为 | `require_pg_or_explicit_skip()` 硬失败，无 `VIDEO_REPLICA_TEST_ALLOW_PG_SKIP`；本组 0 skip |
| 用例隔离 | 每用例 `session_replication_role=replica` 下 TRUNCATE（与 `pg_test_kit.seed_customer_scenario` 同款；append-only 审计表触发器仅保护共享库误清，不影响专属测试库） |
| 业务通道 | 全部经生产 PG 通道：`get_database` 的 `DATABASE_URL_ENV` 分支 / `pg_transaction` / `BusinessConnection.postgres`；零 `sqlite3.connect`、零 `DB_PATH`、零 `BusinessConnection.sqlite` |

**与 CW-032 的 fixture 合同（占用登记见 claim.json，CW-032 当前 WAITING 未开工）：**

1. 命名边界：CW-058 只新增/引用 `test_cw058_*` 测试文件；`test_cw032_*` 归 CW-032。
2. DSN 注入口唯一：任何 TEST-PG 套件一律读 `TEST_POSTGRESQL_URL`（或经
   `DATABASE_URL_ENV` 的生产通道），CW-032 打包/交付物注入同一环境变量即可复用，
   不需要为内容域测试新增第二套 fixture 装配。
3. 库名 allowlist：新增库名必须登记 `pg_test_kit.RECORDED_TEST_DATABASES` 并以
   `_test` 结尾；CW-032 的交付包自检如需建库，走同一 `create_test_database` 合同。
4. 端口/容器：CW-058 用 5440；CW-032 落地时按 §3.5 的任务隔离规则取空闲端口，
   不复用他任务在用容器。

## 3. 旧断言 → PG 用例映射（逐文件全量登记）

「替代」= 本矩阵用例复现其持久化不变量；「保留」= 旧文件继续覆盖内部桌面通道，
在 CW-042 移除在线 SQLite 时随通道退休（登记于 CW-043 全量核销）；
「SQLite 专有机制」= 断言依赖 sqlite3 引擎内省（PRAGMA/EXPLAIN/trace），在 PG 上
由等价结果断言替代，原机制断言随 SQLite 通道退休。

| # | 旧测试文件（SQLite 通道） | 关键持久化断言 | PG 替代（test_cw058_content_asset_pg_matrix.py） | 处置 |
| --- | --- | --- | --- | --- |
| 1 | test_optional_project_state_api.py | 7 可选状态端点空态 200/null；他属项目 404 与缺失同形（IDOR 掩蔽） | `test_optional_project_state_routes_conceal_foreign_projects_on_real_pg` | 替代+保留 |
| 2 | test_db.py::test_foreign_keys_are_enforced | projects/versions FK 约束 | `test_versions_unique_constraint_and_project_cascade_on_real_pg` | 替代+保留 |
| 3 | test_characters.py | main_character 快照 versions 行、参照序、可用性过滤、写通镜像审计 | `test_main_character_selection_freezes_snapshot_and_is_idempotent_on_pg`、`test_character_selection_rejects_unavailable_and_auditor_on_pg` | 替代+保留 |
| 4 | test_project_character_selection.py | 选版幂等（1 versions 行+1 审计）、快照冻结、草稿/他属 422、审计员 403 | 同上两条 | 替代+保留 |
| 5 | test_studio_drafts.py | 草稿往返/upsert 递增/隔离/删除；收藏文案置顶/50 上限/隔离；审计员只读 | `test_studio_draft_roundtrip_upsert_isolation_and_delete_on_pg`、`test_saved_scripts_ordering_cap_and_isolation_on_pg` | 替代+保留 |
| 6 | test_studio_notification_preferences.py | 默认 true、PUT 往返、upsert 恒 1 行、按用户隔离、未知字段 422 | `test_notification_preferences_upsert_keeps_single_row_on_pg` | 替代+保留 |
| 7 | test_studio_stats.py | 管理员全台精确计数、员工属主收窄 + customer_batch_visibility 隐藏 | `test_studio_task_stats_scope_and_hidden_batch_on_real_pg` | 替代+保留 |
| 8 | test_studio_analytics.py | 日序列北京日桶、kind 分解可见性、recent works 排序/成本 | 保留（同 SQL 家族已由 stats 用例在 PG 上验证 `::timestamptz` 聚合与隐藏反连接；analytics 全矩阵归 CW-043 补漏清单） | 部分替代+保留 |
| 9 | test_media.py | 上传完成落 assets/项目状态/分析任务恰好一条；同哈希属主去重、跨属主不复用；入队失败原子回滚 | `test_media_upload_persists_asset_analysis_and_project_status_on_pg`、`test_media_upload_dedup_reuses_owned_hash_never_foreign_on_pg`、`test_media_completion_rolls_back_atomically_when_enqueue_fails_on_pg` | 替代+保留 |
| 10 | test_materials.py | 服务端分页不重不漏、重命名偏好+审计、隐藏后列表排除、resolve 隐藏/不可得 | `test_materials_pagination_hide_rename_and_audit_on_pg` | 替代+保留 |
| 11 | test_material_permissions.py | 口播结果资产仅任务属主可读（404 掩蔽） | `test_asset_access_owner_scoping_on_pg` | 替代+保留 |
| 12 | test_storage.py | 纯适配器/文件系统，无 DB 断言 | —（无 DB 断言，属 TEST-LOGIC） | 保留（无迁移对象） |
| 13 | test_storage_cross_instance.py | 已是 TEST-PG（CW-031 线） | —（已是真实 PG） | 不适用 |
| 14 | test_characters.py::test_characters_migration_creates_library_tables | sqlite_master 表清单 | SQLite 内省专有；PG 侧等价事实=alembic head 含 9 张人物域表（`upgrade_test_database_to_head` 已证） | 机制退休+保留 |
| 15 | test_character_domain.py | 迁移往返/回填（SQLite 链专有）+ 约束拒绝（sqlite3.IntegrityError） | 约束拒绝 PG 半边见 `test_publish_freezes_hash_and_enforces_published_view_uniqueness_on_pg`（部分唯一索引 23505）；迁移往返属 TEST-HISTORY（SQLite 迁移链），不迁 | 部分替代+机制退休 |
| 16 | test_character_asset_review.py | 审核历史追加序/最新裁决生效；发布哈希冻结/幂等/改选 409；部分唯一 | `test_character_review_history_latest_decision_wins_on_pg`（含 rowid 先红后绿）、`test_publish_freezes_hash_and_enforces_published_view_uniqueness_on_pg` | 替代+保留 |
| 17 | test_viral_store.py | (platform,video_id) 去重、COALESCE 统计、keyset 分页/游标失效、收藏幂等/隔离/分页 | `test_viral_store_upsert_dedup_and_statistics_coalesce_on_pg`、`test_viral_keyset_pagination_and_cursor_invalidation_on_pg`、`test_viral_favorites_idempotent_isolated_and_paginated_on_pg`；EXPLAIN QUERY PLAN 无 TEMP B-TREE 断言为 SQLite 专有机制 | 替代+机制退休+保留 |
| 18 | test_viral_routes.py | 隐藏可见性排除；PG 通道冷列表入队刷新任务（is_postgres 分支）→ worker 消费落库 | `test_viral_hidden_visibility_excluded_from_list_on_pg`、`test_viral_refresh_pg_lane_enqueues_and_worker_consumes_on_pg` | 替代+保留 |
| 19 | test_viral_statistics.py | 统计成功缓存/重试冷却（native_json RMW） | 保留（其持久化面= viral_store upsert/statistics COALESCE，已由 17 替代主不变量；trace 语句计数为 SQLite 专有机制） | 部分替代+机制退休 |
| 20 | test_viral_import.py | 入队幂等/409、租约 SKIP LOCKED 双连接互斥、陈旧 attempt 不可完成、失败回滚 | 保留（租约 SQL 与 test_viral_refresh 同家族且本组 `test_viral_refresh_pg_lane_enqueues_and_worker_consumes_on_pg` 覆盖 PG worker 通道；import 全矩阵归 CW-043 补漏清单） | 部分替代+保留 |
| 21 | test_viral_refresh.py | 刷新租约 fence/attempt 递增（SQLite 通道直测） | PG 通道半边由 `test_viral_refresh_pg_lane_enqueues_and_worker_consumes_on_pg`（run_pg_worker_once + SUCCEEDED）；SQLite 侧保留 | 替代(PG半边)+保留 |
| 22 | test_viral_decrypt.py / test_viral_tikhub.py / test_viral_keywords.py / test_viral_media.py | 纯加解密/HTTP 解析/管道编排，无 DB 断言 | —（TEST-LOGIC） | 保留（无迁移对象） |
| 23 | test_first_frames.py / test_source_frames.py / test_script_from_audio.py | 首帧/拆解帧/音频转文案任务持久化 | 边界：首帧与 ASR 任务域按 §14 表归 CW-059（生成/拆解/ASR）；工作台侧 script_from_audio 不在本组 | 移交 CW-059 |
| 24 | test_studio_saved_scripts（无独立文件，含于 #5） | — | — | — |

**重复开发剔除**：不重写 CW-031 已交付的 `test_storage_cross_instance.py`（已真实 PG）；
不重复 CW-029 的账务矩阵；不移植 SQLite 迁移往返（TEST-HISTORY 例外，归 CW-060）。

## 4. 缺陷先红后绿：character_asset_review.py 的 SQLite 专有 `rowid`

- 位置：`app/character_asset_review.py:167`（`ORDER BY created_at, rowid`）、
  `:431`、`:438`（`ORDER BY review.created_at DESC, review.rowid DESC` 最新裁决子查询）。
- 缺陷：`rowid` 是 SQLite 伪列；客户 PG 通道执行任一审核历史查询/发布路径即
  `UndefinedColumn (42703)`——即人物资产审核与发布在客户通道不可用。
- 修复：按 `BusinessConnection.is_postgres` 选择插入序伪列——PG 用 `ctid`
  （append-only 表的物理插入序，PostgreSQL 官方 rowid 对应物），SQLite 保留
  `rowid`；SQL 文本由固定常量拼接，无注入面；不改共享翻译器、不加新抽象。
- RED→GREEN：见 §5 运行记录（RED：2 failed / UndefinedColumn；GREEN：修复后通过）。

## 5. 运行记录（自动核销）

运行环境：Windows PC-202609071434，venv Python 3.12，psycopg 二进制池；
`PYTHONPATH=.dev-env/pyshim`（fcntl shim，仓外注入）；PG 容器 `vs-pg-cw058`
（postgres:16.15-alpine，`0.0.0.0:5440->5432`，与在用 5433–5439 全隔离）。

| 轮次 | 树 | 命令 | 结果 |
| --- | --- | --- | --- |
| RED（修复前） | rowid 修复前 | `pytest tests/test_cw058_content_asset_pg_matrix.py` | 8 failed / 12 passed——其中 `test_character_review_history_latest_decision_wins_on_pg` 失败于 `psycopg.errors.UndefinedColumn: column "rowid" does not exist (LINE 4: ORDER BY created_at, rowid)`；`test_publish_...` 随后同因失败。日志 `.dev-env/cw058-red.log` |
| GREEN（修复后） | 本 PR | `pytest tests/test_cw058_content_asset_pg_matrix.py` | **20 passed / 0 failed / 0 skipped**（日志 `.dev-env/cw058-green.log`） |
| 缺库硬门 | 本 PR | 同上（unset TEST_POSTGRESQL_URL） | `pytest.fail`：`PostgreSQL test fixture is not reachable ... (ConnectionTimeout)`——0 skip，非 0 失败（PG-05） |
| SQLite 通道回归 | 本 PR | `pytest tests/test_character_asset_review.py tests/test_project_character_selection.py tests/test_characters.py tests/test_db_portable.py tests/test_pg_test_kit.py` | **89 passed / 0 failed**（`rowid` 分支保持 SQLite 原样，旧套件零回归） |
| 静态门 | 本 PR | `ruff check .` / `ruff format --check`（3 个改动文件）/ `mypy app` / `bash scripts/verify_no_secrets.sh` | All checks passed / 3 files already formatted / 104 source files no issues / No hardcoded secrets, RC=0 |
| 消费者回归 2 | 本 PR | `pytest tests/test_character_domain.py tests/test_simple_character.py tests/test_db.py` | 127 passed / 6 failed——6 个失败（test_simple_character 图片格式校验 503≠422）在主仓基线工作区逐字复现（Windows Pillow 环境），与本 diff 无关（日志 `.dev-env/cw058-regress2.log`） |
| 读文档测试 | 本 PR | cw009_security_matrix_export / customer_ha_smoke / cw056_supported_head_matrix / cw033_evidence_boundary | 全部通过；同轮 test_cw033_pitr_drill_validation 22 failed 为主仓基线即有的 Windows `subprocess` bash 依赖问题（WinError 2，CI Linux 通过），与本 diff 无关 |

## 6. 验收底线对照（V3 §18 CW-058 行）

- 该组 TEST-PG 类用例 100% 真实 PG 执行：本矩阵 20 用例全部真实 PG（PG-05 资源合同）。
- owner/IDOR：用例 #1（404 掩蔽）、#10（跨属主去重）、#13（资产访问掩蔽）。
- 版本关联：#2（唯一+级联）、#3（快照冻结+幂等）。
- 跨刷新恢复：#17（跨连接重开）、#4/#5（草稿/收藏持久化）。
- 分页筛选：#12（素材服务端分页）、#18/#19（keyset+收藏分页+50 上限）。
- 隐藏审计：#7（customer_batch_visibility）、#12（素材隐藏+审计行）、#20（viral 隐藏可见性）。
- FK/约束：#2（级联/UNIQUE 23505）、#16（部分唯一 uq_character_assets_published_view + 发布哈希守卫）。
- JSON：#4（草稿 payload 文本）、#16（发布快照 canonical）、#17（viral native_json）。
- 批量种子：#5（55 收藏文案）、#18（35 视频）、#7（10 任务场景）。
- SQLite 替代 / 缺 PG skip：0（模块内无 sqlite3.connect/DB_PATH/sqlite 门面；缺库即失败）。
- 每个旧断言有替代编号或退休依据：§3 全量登记。

## 7. 剩余范围（诚实登记，不关闭本组全量核销）

内容/资产域 SQLite 旧文件共 30 个（约 2.0 万行）仍在内部通道运行；本任务交付的
矩阵覆盖其全部「验收底线场景类别」，但**未逐文件全量迁移**。剩余两块归后续：

1. 素材上传管线（materials intent/complete 路由级）、analytics 全矩阵、viral
   import 全矩阵——按 CW-043 全量核销时的补漏清单补 PG 用例；
2. 首帧/源帧/音频转文案（test_first_frames/test_source_frames/test_script_from_audio）
   按 §14 归 CW-059（生成/拆解/ASR 域）。

本行不作为 CW-058 全任务关闭依据；账本 §18 状态以最终合并评审为准。
