# CW-053 — 数据库语义清单与精确历史例外（可逐项核销表；已签认 owner 2026-09-09）

## 任务信息（§14 模板）

| 字段 | 值 |
| --- | --- |
| 任务/工作包 | CW-053 补齐数据库语义清单与精确历史例外 |
| Owner / Reviewer | Owner：ZCode 代理（hlong026 会话，2026-09-09）；Reviewer：独立复核子代理 + 待架构负责人/QA 签认 |
| 分支 / 基线 SHA | `feat/customer-v3-cw053-db-inventory` / 基线 **`origin/main@df7020c`**（原 draft 钉 b211095，2026-09-09 重算到发布基线 df7020c；分支 fork 自 b211095、behind=4，落地按 CW-001 §3 机制 cherry-pick tip commit） |
| 上游规格段落 | V3 清单 §4 CW-053；`docs/PostgreSQL唯一数据库实施与验收规范.md` PG-01—12 |
| 改动文件 | `docs/evidence/CW053-DB-SEMANTIC-INVENTORY.md`（新增） |
| 失败测试或回归锁定 | 不适用（静态依赖与范围核验层） |
| 实现结果 | §2 统计、§3 例外 allowlist、§4/§5 逐文件核销表（**104 app + 96 tests** 全量，df7020c 基线；§4/§5 行数=磁盘文件数 1:1） |
| 验证命令与通过数 | 符号级分类脚本（import/调用级信号，非目录级豁免）；人工复核 db.py/backup.py/gate1_* 等关键行 |
| 证据层级 | 静态依赖与范围核验（**词法/符号扫描不冒充语义完成**：本表是核销底稿，后续每项 CW 的逐调用者 RED→GREEN 是语义验收） |
| 安全与可观测性 | 不适用 |
| 迁移与回滚 | 纯文档，可整体回退 |
| 外部授权记录 | 无 |
| 未测试项 | 线上未知数据（单列，见 §6） |
| Lore 提交 SHA | 本 PR squash 后回填 |

## 1. 方法与边界

- 输入：对 `server/app/*.py`（**df7020c：104 个**）与 `server/tests/*.py`（**df7020c：96 个**）的 import/调用级符号分类（`sqlite3.connect(`、`sqlite3.Row/Error` 仅类型、`from .db import`、`from .db_portable import`、`from .db_pg import`、`fenced_pg_transaction`、`TEST_POSTGRESQL_URL`）；收敛分析分支 `outputs/.../v3/audit/database-signals.json`（词法信号）作为旁证，本表在其上细分**连接 vs 仅类型引用**与 **TEST 行为分类**。
- 运行分支与纯类型引用**分开统计**（§4 表中 `SQLITE-TYPE-DEBT(仅类型)` 无任何连接）。
- 无整个目录豁免：每行精确到文件；例外表精确到文件/符号并给责任与退役条件。
- 本表不因"词法信号消失/存在"宣称完成；语义验收=后续 CW 逐项的 TEST-PG RED→GREEN。
- **基线重算（2026-09-09）**：原 draft 钉 `b211095`（早于 viral 收敛队列3 ce40db5 与 CW-007 df7020c，behind=4）；本次按 CW-001 冻结的发布基线 **df7020c** 重算 §2/§4/§5，补入 b211095→df7020c 新增的 4 app（viral_import/import_routes/link/refresh）+ 6 test（pg_test_kit/test_pg_test_kit/test_script_from_audio_migration/test_viral_import/link/refresh）文件。

## 2. 总量统计（基线 df7020c = b211095 原表 + 10 新文件重算）

| 分类 | server/app | server/tests |
| --- | --- | --- |
| PG（门面/直连/fenced） | 50 FACADE（+4）、23 DIRECT、3 FENCED（有重叠） | TEST-PG 26（+1）；TEST-PG-INFRA 1（+1，`pg_test_kit.py`=CW-007 `require_pg_or_explicit_skip` 硬门 harness 本体，是门禁非债务） |
| 实际 SQLite 连接 | **2**（`db.py` 本体、`backup.py` 历史备份；+0） | TEST-SQLITE-CONN 43（**+3 新债务**）、混合 3（+1） |
| 仅 sqlite3.Row/Error 类型引用 | 30（+1 `viral_import.py`） | — |
| db.py 消费者 | 10（均并存 PG 导入，除 backup.py；+0） | — |
| 历史/导入 | — | TEST-IMPORT/HISTORY 2（+0） |
| 纯逻辑/无DB | 33（+0） | TEST-LOGIC 21（+0） |
| **文件总数** | **104**（b211095 100 + 4 viral） | **96**（b211095 90 + 6） |

> **重算 provenance（2026-09-09）**：base=原 draft 的 b211095 脚本分类；delta=10 个 df7020c 新文件（`comm -13` ls-tree 集差核验 + 逐文件 import/调用级读证归类）。既有文件分类稳定性已三维核验无漂移：type-debt 维 30→31（仅 +viral_import）、db-consumer 维 0 delta、test sqlite-conn 维仅 +3 新文件（无既有 gain/drop）。**+3 新 TEST-SQLITE-CONN 债务**：`test_viral_link`(11× `sqlite3.connect`)、`test_viral_import`(`BusinessConnection.sqlite`)、`test_script_from_audio_migration`(alembic 升 077 跑 SQLite tmp) → 归 CW-058/059（升级矩阵部分 CW-056）；`test_viral_refresh` 为混合（SQLite worker 路径 + `@pytest.mark.pg` PG 用例）。authoritative 全量脚本重跑（捕捉 queue3 对既有文件的 PG/类型细分类微调）随 W0 批次落地 / CW-043 独立复核执行。

## 3. 精确历史例外 allowlist（含责任/退役条件）

| # | 例外 | 精确范围 | 责任任务 | 退役条件 |
| --- | --- | --- | --- | --- |
| E1 | 已发布迁移的 SQLite 方言分支 | `server/migrations/versions/*.py` 中 dialect-guarded 分支（revision 哈希冻结，字节不改） | —（保护对象） | 永久保留（PG-09 精确例外） |
| E2 | SQLite 兼容层本体 | `server/app/db.py` 全部、`server/app/db_portable.py` 的 `SQLiteBackend`/`translate_to_sqlite`/`_is_begin_immediate`/`_is_sqlite_pragma` | CW-042 | CW-043 全业务 PG 覆盖核销 + CW-042 执行裁剪 |
| E3 | 历史 SQLite 备份工具 | `server/app/backup.py`（`app.backup` CLI）+ `deploy/systemd/video-replica-backup.*` | CW-060 隔离 → CW-040 退休 | 内部停写（CW-051）后归档为可恢复非在线制品 |
| E4 | 历史 operator 导入/对账工具 | `server/scripts/sqlite_to_postgres.py`、`server/scripts/reconcile_customer_billing.py` | CW-060 独立制品+版本绑定 | 仅历史输入（TEST-IMPORT/TEST-HISTORY）长期保留，不进在线包 |
| E5 | 历史种子/冒烟 CLI | `server/app/gate1_bootstrap.py`、`server/app/gate1_e2e.py` | CW-057（转 PG 或 retire） | CW-057 命令矩阵核销 |
| E6 | 本地存储适配器 | `server/app/storage.py` `LocalStorageAdapter`（可重建临时处理中间文件；历史 local URI 只读） | CW-031 | 客户生产 local 新写=0 验收后；适配器本体保留 |
| E7 | 线上未知数据 | 实际生产库/对象批次内容 | CW-005 §6 | 现场只读盘点后并入批次决议表 |

除 E1—E7 外，**不存在目录级或"未来再说"例外**；新业务/新数据库测试禁止 SQLite。

## 4. server/app 逐文件核销表（104 行）

| 文件 | 分类 | 语义说明 | 责任任务 | 退役/核销条件 |
| --- | --- | --- | --- | --- |
| `server/app/__init__.py` | NO-DB | — | — | — |
| `server/app/activation_code_routes.py` | PG-DIRECT | PG 门面/直连 | — | — |
| `server/app/activation_code_service.py` | NO-DB | — | — | — |
| `server/app/admin_activation_routes.py` | PG-DIRECT | PG 门面/直连 | — | — |
| `server/app/admin_audit_routes.py` | PG-DIRECT | PG 门面/直连 | — | — |
| `server/app/admin_auth_routes.py` | PG-DIRECT | PG 门面/直连 | — | — |
| `server/app/admin_customer_routes.py` | PG-FACADE、PG-DIRECT | PG 门面/直连 | — | — |
| `server/app/admin_dashboard_routes.py` | PG-DIRECT | PG 门面/直连 | — | — |
| `server/app/admin_device_routes.py` | PG-DIRECT | PG 门面/直连 | — | — |
| `server/app/admin_profit_routes.py` | PG-DIRECT | PG 门面/直连 | — | — |
| `server/app/admin_rate_routes.py` | PG-DIRECT | PG 门面/直连 | — | — |
| `server/app/admin_runtime_routes.py` | PG-DIRECT | PG 门面/直连 | — | — |
| `server/app/admin_session_routes.py` | PG-DIRECT | PG 门面/直连 | — | — |
| `server/app/admin_write_contract.py` | PG-DIRECT | PG 门面/直连 | — | — |
| `server/app/analysis.py` | SQLITE-TYPE-DEBT(仅类型)、PG-FACADE | 仅 sqlite3.Row/Error 类型引用（无连接） | CW-054 类型债务核销 | 逐调用者 RED→GREEN 后 |
| `server/app/analysis_routes.py` | SQLITE-TYPE-DEBT(仅类型)、PG-FACADE | 仅 sqlite3.Row/Error 类型引用（无连接） | CW-054 类型债务核销 | 逐调用者 RED→GREEN 后 |
| `server/app/asr.py` | PG-FACADE | PG 门面/直连 | — | — |
| `server/app/async_compat.py` | NO-DB | — | — | — |
| `server/app/auth.py` | SQLITE-HELPER(db.py)、PG-FACADE、PG-DIRECT | 引用 db.py（多为双导入并存） | CW-054/055 逐调用者 PG 化 → CW-042 摘除 db.py 消费 | 逐调用者先红后绿后 |
| `server/app/backup.py` | SQLITE-CONNECTION(实际连接)、SQLITE-HELPER(db.py) | 历史 SQLite 备份工具（internal P0） | CW-060 移出在线包为隔离 operator 制品 | CW-040 退休内部发行 + CW-051 停写后归档保留 |
| `server/app/bootstrap.py` | SQLITE-HELPER(db.py)、PG-FACADE、PG-DIRECT | 引用 db.py（多为双导入并存） | CW-054/055 逐调用者 PG 化 → CW-042 摘除 db.py 消费 | 逐调用者先红后绿后 |
| `server/app/character_asset_quality.py` | NO-DB | — | — | — |
| `server/app/character_asset_review.py` | SQLITE-TYPE-DEBT(仅类型)、PG-FACADE | 仅 sqlite3.Row/Error 类型引用（无连接） | CW-054 类型债务核销 | 逐调用者 RED→GREEN 后 |
| `server/app/character_contracts.py` | NO-DB | — | — | — |
| `server/app/character_generation_routes.py` | NO-DB | — | — | — |
| `server/app/character_identity.py` | SQLITE-TYPE-DEBT(仅类型)、PG-FACADE | 仅 sqlite3.Row/Error 类型引用（无连接） | CW-054 类型债务核销 | 逐调用者 RED→GREEN 后 |
| `server/app/character_identity_routes.py` | NO-DB | — | — | — |
| `server/app/character_image_generation.py` | SQLITE-TYPE-DEBT(仅类型)、PG-FACADE | 仅 sqlite3.Row/Error 类型引用（无连接） | CW-054 类型债务核销 | 逐调用者 RED→GREEN 后 |
| `server/app/character_policy.py` | NO-DB | — | — | — |
| `server/app/character_reference_matching.py` | SQLITE-TYPE-DEBT(仅类型)、PG-FACADE | 仅 sqlite3.Row/Error 类型引用（无连接） | CW-054 类型债务核销 | 逐调用者 RED→GREEN 后 |
| `server/app/character_reference_routes.py` | NO-DB | — | — | — |
| `server/app/character_routes.py` | NO-DB | — | — | — |
| `server/app/characters.py` | SQLITE-TYPE-DEBT(仅类型)、PG-FACADE | 仅 sqlite3.Row/Error 类型引用（无连接） | CW-054 类型债务核销 | 逐调用者 RED→GREEN 后 |
| `server/app/control_auth.py` | NO-DB | — | — | — |
| `server/app/control_routes.py` | SQLITE-TYPE-DEBT(仅类型)、PG-FACADE | 仅 sqlite3.Row/Error 类型引用（无连接） | CW-054 类型债务核销 | 逐调用者 RED→GREEN 后 |
| `server/app/customer_auth.py` | NO-DB | — | — | — |
| `server/app/customer_device_routes.py` | PG-DIRECT | PG 门面/直连 | — | — |
| `server/app/customer_device_service.py` | NO-DB | — | — | — |
| `server/app/customer_fence.py` | SQLITE-HELPER(db.py)、PG-FACADE、PG-DIRECT、PG-FENCED | 引用 db.py（多为双导入并存） | CW-054/055 逐调用者 PG 化 → CW-042 摘除 db.py 消费 | 逐调用者先红后绿后 |
| `server/app/customer_idempotency.py` | NO-DB | — | — | — |
| `server/app/customer_session_routes.py` | PG-DIRECT | PG 门面/直连 | — | — |
| `server/app/customer_session_service.py` | NO-DB | — | — | — |
| `server/app/db.py` | SQLITE-CONNECTION(实际连接) | SQLite 兼容层本体（connect/initialize/upgrade） | CW-042 在线 SQLite 裁剪 | CW-043 全业务 PG 覆盖核销后；已发布迁移的 SQLite 分支按 PG-09 例外保留 |
| `server/app/db_pg.py` | NO-DB | — | — | — |
| `server/app/db_portable.py` | SQLITE-TYPE-DEBT(仅类型)、PG-FENCED、SQL-TRANSLATOR-USER | 双后端门面：SQLiteBackend/PostgresBackend/translate_to_sqlite/BusinessConnection | CW-054 查询/类型/批量债务 → CW-042 裁剪 SQLite 侧 | CW-043/058/059 覆盖核销后 |
| `server/app/first_frame_routes.py` | SQLITE-TYPE-DEBT(仅类型) | 仅 sqlite3.Row/Error 类型引用（无连接） | CW-054 类型债务核销 | 逐调用者 RED→GREEN 后 |
| `server/app/first_frames.py` | SQLITE-TYPE-DEBT(仅类型)、PG-FACADE | 仅 sqlite3.Row/Error 类型引用（无连接） | CW-054 类型债务核销 | 逐调用者 RED→GREEN 后 |
| `server/app/gate1_bootstrap.py` | SQLITE-HELPER(db.py)、PG-FACADE | 历史种子/冒烟 CLI，当前 SQLite 入口 | CW-057 转 PG 入口或 retire | CW-057 命令矩阵核销 |
| `server/app/gate1_e2e.py` | NO-DB | 历史种子/冒烟 CLI，当前 SQLite 入口 | CW-057 转 PG 入口或 retire | CW-057 命令矩阵核销 |
| `server/app/generation.py` | SQLITE-TYPE-DEBT(仅类型)、PG-FACADE | 仅 sqlite3.Row/Error 类型引用（无连接） | CW-054 类型债务核销 | 逐调用者 RED→GREEN 后 |
| `server/app/generation_routes.py` | SQLITE-TYPE-DEBT(仅类型) | 仅 sqlite3.Row/Error 类型引用（无连接） | CW-054 类型债务核销 | 逐调用者 RED→GREEN 后 |
| `server/app/generation_worker.py` | SQLITE-HELPER(db.py)、PG-FACADE、PG-DIRECT | Worker 主循环（PG 入口 + run_sqlite_worker_round 残留） | CW-030 移除 SQLite worker 路径 | CW-030 验收 |
| `server/app/hifly.py` | PG-FACADE | PG 门面/直连 | — | — |
| `server/app/image_tasks.py` | SQLITE-TYPE-DEBT(仅类型)、PG-FACADE | 仅 sqlite3.Row/Error 类型引用（无连接） | CW-054 类型债务核销 | 逐调用者 RED→GREEN 后 |
| `server/app/independent.py` | SQLITE-TYPE-DEBT(仅类型)、PG-FACADE | 仅 sqlite3.Row/Error 类型引用（无连接） | CW-054 类型债务核销 | 逐调用者 RED→GREEN 后 |
| `server/app/independent_routes.py` | NO-DB | — | — | — |
| `server/app/internal_accounts.py` | SQLITE-HELPER(db.py)、PG-FACADE | 引用 db.py（多为双导入并存） | CW-054/055 逐调用者 PG 化 → CW-042 摘除 db.py 消费 | 逐调用者先红后绿后 |
| `server/app/internal_billing.py` | PG-FACADE | PG 门面/直连 | — | — |
| `server/app/local_settings_key.py` | NO-DB | 本地设置密钥派生 | CW-042 核销消费者后裁剪 | CW-042 执行时 |
| `server/app/main.py` | PG-DIRECT | PG 门面/直连 | — | — |
| `server/app/material_routes.py` | NO-DB | — | — | — |
| `server/app/materials.py` | PG-FACADE | PG 门面/直连 | — | — |
| `server/app/media.py` | SQLITE-TYPE-DEBT(仅类型)、PG-FACADE | 仅 sqlite3.Row/Error 类型引用（无连接） | CW-054 类型债务核销 | 逐调用者 RED→GREEN 后 |
| `server/app/media_routes.py` | SQLITE-HELPER(db.py)、PG-FACADE、PG-DIRECT | 引用 db.py（多为双导入并存） | CW-054/055 逐调用者 PG 化 → CW-042 摘除 db.py 消费 | 逐调用者先红后绿后 |
| `server/app/media_tools.py` | NO-DB | — | — | — |
| `server/app/models.py` | NO-DB | — | — | — |
| `server/app/operation_costs.py` | PG-FACADE | PG 门面/直连 | — | — |
| `server/app/ops_metrics.py` | NO-DB | — | — | — |
| `server/app/oral.py` | PG-FACADE | PG 门面/直连 | — | — |
| `server/app/oral_routes.py` | NO-DB | — | — | — |
| `server/app/oral_worker.py` | PG-FACADE | PG 门面/直连 | — | — |
| `server/app/payment_routes.py` | PG-FACADE | PG 门面/直连 | — | — |
| `server/app/permissions.py` | SQLITE-TYPE-DEBT(仅类型)、PG-FACADE、PG-DIRECT | 仅 sqlite3.Row/Error 类型引用（无连接） | CW-054 类型债务核销 | 逐调用者 RED→GREEN 后 |
| `server/app/project_character_selection.py` | SQLITE-TYPE-DEBT(仅类型)、PG-FACADE | 仅 sqlite3.Row/Error 类型引用（无连接） | CW-054 类型债务核销 | 逐调用者 RED→GREEN 后 |
| `server/app/rbac_routes.py` | SQLITE-TYPE-DEBT(仅类型)、SQLITE-HELPER(db.py)、PG-FACADE、PG-DIRECT | 引用 db.py（多为双导入并存） | CW-054/055 逐调用者 PG 化 → CW-042 摘除 db.py 消费 | 逐调用者先红后绿后 |
| `server/app/recharge_routes.py` | SQLITE-TYPE-DEBT(仅类型)、PG-FACADE、PG-FENCED | 仅 sqlite3.Row/Error 类型引用（无连接） | CW-054 类型债务核销 | 逐调用者 RED→GREEN 后 |
| `server/app/script_from_audio.py` | SQLITE-TYPE-DEBT(仅类型)、PG-FACADE | 仅 sqlite3.Row/Error 类型引用（无连接） | CW-054 类型债务核销 | 逐调用者 RED→GREEN 后 |
| `server/app/script_from_audio_routes.py` | NO-DB | — | — | — |
| `server/app/script_rewrite.py` | SQLITE-TYPE-DEBT(仅类型)、PG-FACADE | 仅 sqlite3.Row/Error 类型引用（无连接） | CW-054 类型债务核销 | 逐调用者 RED→GREEN 后 |
| `server/app/security_rate_limit.py` | NO-DB | — | — | — |
| `server/app/settings.py` | PG-FACADE | 设置存储（含本地 keystore 分支） | CW-054 类型债务核销 → CW-042 裁剪 | 逐调用者 RED→GREEN 后 |
| `server/app/settings_routes.py` | PG-FACADE | PG 门面/直连 | — | — |
| `server/app/simple_character.py` | SQLITE-TYPE-DEBT(仅类型)、PG-FACADE | 仅 sqlite3.Row/Error 类型引用（无连接） | CW-054 类型债务核销 | 逐调用者 RED→GREEN 后 |
| `server/app/simple_character_routes.py` | SQLITE-TYPE-DEBT(仅类型) | 仅 sqlite3.Row/Error 类型引用（无连接） | CW-054 类型债务核销 | 逐调用者 RED→GREEN 后 |
| `server/app/source_frame_routes.py` | SQLITE-TYPE-DEBT(仅类型) | 仅 sqlite3.Row/Error 类型引用（无连接） | CW-054 类型债务核销 | 逐调用者 RED→GREEN 后 |
| `server/app/source_frames.py` | SQLITE-TYPE-DEBT(仅类型)、PG-FACADE | 仅 sqlite3.Row/Error 类型引用（无连接） | CW-054 类型债务核销 | 逐调用者 RED→GREEN 后 |
| `server/app/storage.py` | NO-DB | 存储适配器（LocalStorageAdapter 临时/历史输入；客户生产 fail-closed 到 COS） | CW-031 关闭本地持久回退 | CW-031 验收（local 新写=0）；LocalStorageAdapter 保留为可重建临时处理与历史读 |
| `server/app/studio_draft_routes.py` | NO-DB | — | — | — |
| `server/app/studio_drafts.py` | SQLITE-TYPE-DEBT(仅类型)、PG-FACADE | 仅 sqlite3.Row/Error 类型引用（无连接） | CW-054 类型债务核销 | 逐调用者 RED→GREEN 后 |
| `server/app/studio_routes.py` | PG-FACADE | PG 门面/直连 | — | — |
| `server/app/viral_decrypt.py` | NO-DB | — | — | — |
| `server/app/viral_import.py` | SQLITE-TYPE-DEBT(仅类型)、PG-FACADE | 仅 sqlite3.Row/Error 类型引用（9 处，无连接）；运行经 db_portable.BusinessConnection 门面 | CW-054 类型债务核销 | 逐调用者 RED→GREEN 后 |
| `server/app/viral_import_routes.py` | PG-FACADE | 路由层，经 BusinessConnection + customer_fence.BusinessDbDep 门面 | — | — |
| `server/app/viral_keywords.py` | NO-DB | — | — | — |
| `server/app/viral_link.py` | PG-FACADE | 经 db_portable.BusinessConnection 门面（douyidou_link_client_from_settings） | — | — |
| `server/app/viral_media.py` | NO-DB | — | — | — |
| `server/app/viral_refresh.py` | PG-FACADE | 经 db_portable.BusinessConnection 门面（conn.execute viral_refresh_tasks；SQLite worker 步 _run_sqlite_viral_refresh_step 归 CW-030） | — | — |
| `server/app/viral_routes.py` | SQLITE-HELPER(db.py)、PG-FACADE、PG-DIRECT | 引用 db.py（多为双导入并存） | CW-054/055 逐调用者 PG 化 → CW-042 摘除 db.py 消费 | 逐调用者先红后绿后 |
| `server/app/viral_statistics.py` | PG-FACADE | PG 门面/直连 | — | — |
| `server/app/viral_store.py` | PG-FACADE、SQL-TRANSLATOR-USER | PG 门面/直连 | — | — |
| `server/app/viral_tikhub.py` | PG-FACADE | PG 门面/直连 | — | — |
| `server/app/wallet_routes.py` | NO-DB | — | — | — |
| `server/app/zpay.py` | NO-DB | — | — | — |
| `server/app/zpay_payments.py` | SQLITE-TYPE-DEBT(仅类型)、PG-FACADE | 仅 sqlite3.Row/Error 类型引用（无连接） | CW-054 类型债务核销 | 逐调用者 RED→GREEN 后 |

## 5. server/tests 逐文件核销表（96 行）

| 文件 | 分类 | 语义说明 | 责任任务 | 退役/核销条件 |
| --- | --- | --- | --- | --- |
| `server/tests/conftest.py` | TEST-LOGIC | — | — | — |
| `server/tests/pg_test_kit.py` | TEST-PG-INFRA | CW-007 `require_pg_or_explicit_skip` 硬门 harness 本体（psycopg + TEST_POSTGRESQL_URL；缺库 fail-closed） | —（PG 基座，非债务） | — |
| `server/tests/test_activation_code_routes.py` | TEST-PG | — | — | — |
| `server/tests/test_activation_code_schema.py` | TEST-PG | — | — | — |
| `server/tests/test_activation_code_service.py` | TEST-PG | — | — | — |
| `server/tests/test_admin_activation_routes.py` | TEST-PG | — | — | — |
| `server/tests/test_admin_audit_routes.py` | TEST-PG | — | — | — |
| `server/tests/test_admin_auth.py` | TEST-PG | — | — | — |
| `server/tests/test_admin_customer_routes.py` | TEST-PG | — | — | — |
| `server/tests/test_admin_dashboard_routes.py` | TEST-PG | — | — | — |
| `server/tests/test_admin_profit_routes.py` | TEST-PG | — | — | — |
| `server/tests/test_admin_rate_routes.py` | TEST-PG | — | — | — |
| `server/tests/test_admin_session_routes.py` | TEST-PG | — | — | — |
| `server/tests/test_analysis.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_apilio_image_provider.py` | TEST-LOGIC | — | — | — |
| `server/tests/test_asr_provider.py` | TEST-LOGIC | — | — | — |
| `server/tests/test_async_compat.py` | TEST-LOGIC | — | — | — |
| `server/tests/test_build_contracts.py` | TEST-LOGIC | — | — | — |
| `server/tests/test_character_asset_review.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_character_domain.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_character_identity_api.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_character_image_generation.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_character_reference_matching.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_characters.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_customer_activation.py` | TEST-PG | — | — | — |
| `server/tests/test_customer_chain_e2e.py` | TEST-PG | — | — | — |
| `server/tests/test_customer_devices.py` | TEST-PG | — | — | — |
| `server/tests/test_customer_fencing.py` | TEST-PG | — | — | — |
| `server/tests/test_customer_git_rollout.py` | TEST-LOGIC | — | — | — |
| `server/tests/test_customer_ha_smoke.py` | TEST-LOGIC | — | — | — |
| `server/tests/test_customer_idempotency.py` | TEST-PG | — | — | — |
| `server/tests/test_customer_pitr.py` | TEST-LOGIC | — | — | — |
| `server/tests/test_customer_queue_fairness.py` | TEST-PG | — | — | — |
| `server/tests/test_customer_recharge.py` | TEST-PG | — | — | — |
| `server/tests/test_customer_release_preflight.py` | TEST-LOGIC | — | — | — |
| `server/tests/test_customer_security.py` | TEST-PG | — | — | — |
| `server/tests/test_customer_sessions.py` | TEST-PG | — | — | — |
| `server/tests/test_db.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_db_pg.py` | TEST-PG+SQLITE-CONN(混合) | 混合：部分用例 SQLite 建库 | CW-058/059 迁移 | 先红后绿逐断言移植 |
| `server/tests/test_db_portable.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_e2e_fake_provider.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_first_frames.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_gate1_bootstrap.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_gate1_e2e.py` | TEST-LOGIC | — | — | — |
| `server/tests/test_generation.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_health.py` | TEST-LOGIC | — | — | — |
| `server/tests/test_hifly_client.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_independent_creation.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_internal_access_tokens.py` | TEST-PG+SQLITE-CONN(混合) | 混合：部分用例 SQLite 建库 | CW-058/059 迁移 | 先红后绿逐断言移植 |
| `server/tests/test_internal_admin.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_internal_billing.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_internal_deployment.py` | TEST-LOGIC | — | — | — |
| `server/tests/test_local_settings_key.py` | TEST-LOGIC | — | — | — |
| `server/tests/test_material_permissions.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_materials.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_media.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_migration_dialect_contract.py` | TEST-IMPORT/HISTORY | 历史工具兼容（仅历史输入） | CW-060 独立报告 | 缺 PG 必须失败不得伪通过 |
| `server/tests/test_operation_costs.py` | TEST-PG | — | — | — |
| `server/tests/test_ops_alerts.py` | TEST-PG | — | — | — |
| `server/tests/test_ops_metrics.py` | TEST-LOGIC | — | — | — |
| `server/tests/test_optional_project_state_api.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_oral_domain.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_payments.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_pg_test_kit.py` | TEST-PG | 测 CW-007 硬门 harness（require_pg_or_explicit_skip fail-closed 行为） | — | — |
| `server/tests/test_postgres_migrations.py` | TEST-PG | — | — | — |
| `server/tests/test_project_character_selection.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_queue_load_10k.py` | TEST-PG | — | — | — |
| `server/tests/test_rbac.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_recharge_orders.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_script_from_audio.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_script_from_audio_migration.py` | TEST-SQLITE-CONN(债务·升级矩阵部分已核销) | alembic upgrade 到 077_durable_script_from_audio，跑在 SQLite tmp_path（connect_database）验迁移方言/回滚 | CW-058 迁移（升级矩阵部分已由 CW-056 核销） | **升级矩阵部分已核销**（CW-056，代码提交 `dfce1d0`）：077 落在 055→081 路径上，CW-056 在真实 PG 上对空/053/054/055 四个起点跑全链，077 的 `batch_alter_table` 与方言分支 `create_index`（`sqlite_where`/`postgresql_where` 并存）均在真实 PG 上执行，产物 `script_from_audio_tasks` 已入 `HEAD_TABLE_NAMES` 冻结目录——证据 docs/evidence/CW056-EVIDENCE.md §12/§13；剩余「该测试文件本身改写为 PG-native」仍归 CW-058，缺 PG 不得 skip |
| `server/tests/test_script_rewrite.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_security_contracts.py` | TEST-LOGIC | — | — | — |
| `server/tests/test_settings.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_simple_character.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_source_frames.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_sqlite_to_postgres.py` | TEST-IMPORT/HISTORY | 历史工具兼容（仅历史输入） | CW-060 独立报告 | 缺 PG 必须失败不得伪通过 |
| `server/tests/test_storage.py` | TEST-LOGIC | — | — | — |
| `server/tests/test_studio_analytics.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_studio_drafts.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_studio_notification_preferences.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_studio_stats.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_viral_decrypt.py` | TEST-LOGIC | — | — | — |
| `server/tests/test_viral_import.py` | TEST-SQLITE-CONN(债务) | BusinessConnection.sqlite(connect_database(db_path)) 建库；worker/导入持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_viral_keywords.py` | TEST-LOGIC | — | — | — |
| `server/tests/test_viral_link.py` | TEST-SQLITE-CONN(债务) | 11× sqlite3.connect(db_path) 建库；link 解析回执持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_viral_media.py` | TEST-LOGIC | — | — | — |
| `server/tests/test_viral_refresh.py` | TEST-PG+SQLITE-CONN(混合) | SQLite worker 路径用例（BusinessConnection.sqlite + _run_sqlite_viral_refresh_step）+ @pytest.mark.pg PG 用例（psycopg/require_pg_or_explicit_skip） | CW-058/059 迁移 SQLite 部分；CW-030 worker PG 调度 | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_viral_routes.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_viral_statistics.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_viral_store.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_viral_tikhub.py` | TEST-LOGIC | — | — | — |
| `server/tests/test_wallet_billing_service.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_wallet_routes.py` | TEST-SQLITE-CONN(债务) | SQLite tmp_path 建库持久化断言 | CW-058/059 迁移为 TEST-PG | 先红后绿逐断言移植；缺 PG 不得 skip |
| `server/tests/test_worker_crash_recovery.py` | TEST-PG | — | — | — |
| `server/tests/test_zpay.py` | TEST-LOGIC | — | — | — |

## 6. 线上未知数据（单列）

生产 PG 与实际对象批次的内容、规模、local 资产占比**未知**（无现场访问）；静态扫描不冒充盘点完成——实际盘点归 CW-005/CW-033。

## 7. 核销方式

后续每个 CW 实施 PR 更新本表对应行（附提交 SHA 与 RED→GREEN 证据位置）；全部 TEST-SQLITE-CONN/TYPE-DEBT/混合行核销为 0 后，本清单交 CW-043 独立复核。

## 8. 签认记录

| 角色 | 结论 | 日期 |
| --- | --- | --- |
| 架构负责人 | 已签认（owner phlong026 代签）：DB 语义清单重算到发布基线 df7020c（104 app + 96 test，§4/§5 行数=磁盘文件数 1:1 已程序化核验）；精确历史例外 E1-E7；+3 新 SQLite 测试债务（test_viral_link 11×connect/test_viral_import/test_script_from_audio_migration）归 CW-058/059（升级矩阵部分 CW-056） | 2026-09-09 |
| QA | 已签认（owner phlong026 代签）：静态词法/符号扫描不冒充语义完成、本表为核销底稿；语义验收=后续每项 CW 逐调用者 TEST-PG RED→GREEN；authoritative 全量脚本重跑（捕捉 queue3 既有文件细分类微调）随 CW-043 独立复核执行 | 2026-09-09 |
