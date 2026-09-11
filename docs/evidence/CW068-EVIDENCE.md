# CW-068 — C5 发布管理第一阶段·发布账号授权（代码与测试证据）

任务：CW-068（C5 发布管理**第一阶段＝账号授权最小闭环**；正式发布链路留第二阶段另立任务）
分支：`feat/customer-v3-cw068-publish-accounts`（独立 worktree `E:/众墅之家爆款短视频创作/.worktrees/CW-068-publish-accounts`）
基线：`origin/main@a093f61`（CW-061 合入后）—— ⚠️ **开工后 origin/main 已前进到 `ced3e82`（领先 5 个提交：#45/#46/#49/#50/#55），合并前置动作见 §8.5，必读**
裁剪来源（**只读参考，不派生、不堆叠**）：`origin/feat/c5-publish-module@7e5450a`（落后 main 84 提交、领先 6，merge-base `6ab503c`；分支自身基线实测 `test_publish.py` 24 passed / ruff / format / mypy 全绿）
上游规格：CW-002 §3「若纳入须先补专用验收矩阵」+ §7 范围变更签认 + **§8 发布管理专用验收矩阵 A1–A16**；`docs/未接通能力边界-任务拆解-2026-09-06.md` C5 行
平台供应商（**均为项目所有者自有仓库，无第三方授权问题**）：`github.com/phlong026/douyin_publisher@f61418d`、`github.com/phlong026/weixinshipinhao_publisher@ee4babe`
证据层级：**AUTOMATED_VERIFIED**（真实 PG 16 测试全绿 + 三门禁）。真实平台探测/发布链路**不得标 PRODUCTION_GO**——按硬红线需真实凭据人工授权，本轮不涉真实 Cookie。
编号变更（2026-09-12，撞号处置）：本任务立项时自证编号 **CW-062** 空闲并据此认领；开工后另一条并行 CW-062 线（**PR #50**「CW-062: verify and register the main Linux-gate dual-bomb fixes」，纯 docs）已先行 **squash 合并入 main（`5c43fb7`）**，巡检提交 `ced3e82` 又把 CW-062 登记进账本归属该 gate 修复。两条线各自 `.git/codex-task-claims/CW-062/claim.json` 本机原子认领、互不可见 → **跨机器撞号**。经 owner 决策，本「发布账号授权」任务**重编号 CW-062 → CW-068**（五路清查 CW-063~080 后最小的完全空闲号；CW-064 被 PR #48 预留，CW-065/066/067/069/070/073 均被占）。全量替换覆盖 11 个文件（代码/测试/账本/证据）：证据文件 `CW062-EVIDENCE.md → CW068-EVIDENCE.md`、分支 `…cw062-publish-accounts → …cw068-publish-accounts`、claim 目录 `CW-062 → CW-068`、PG 容器/库 `vs-pg-cw062 / cw062_publish_accounts_test → vs-pg-cw068 / cw068_publish_accounts_test`、worktree 目录 `CW-062-publish-accounts → CW-068-publish-accounts`。**gate 版 CW-062（PR #50，已在 main）与本任务 CW-068 从此互不相干。**

---

## 1. 交付差额（对立项计划逐条收口）

| 计划要求 | 实际交付 | 差额 |
| --- | --- | --- |
| 治理四项与代码同一 PR（CW002 §3/§5/§7 修订 + 专用验收矩阵 + 拆解账本回填 + 认领登记） | 四项全部落地：CW002 追加 §8（A1–A16 + §8.2 明确不验收 3 条）、§7 追加 2026-09-11 范围变更签认且**保留 09-09 原签认原文不篡改**；拆解账本 C5 行 `⏸ 暂缓` → `🔨 开发中（第一阶段：账号授权）` 并登记泄露 Cookie 事件已闭环；认领登记 L20 表格行 + L28 详情段 | 无 |
| 迁移 `082_publish_accounts` 只建 accounts 表 | `server/migrations/versions/082_publish_accounts.py` 101 行，`down_revision = "081_oral_unit_price"`，只建 `publish_accounts`，`downgrade()` 只 drop 该表 | 额外保留 `idx_publish_accounts_verify_queue`（计划只提 `idx_publish_accounts_user_created`）——见 §3.1 |
| head 断言机械更新「9 个测试文件」 | **10 个测试文件**，多出 `test_cw056_supported_head_matrix.py`，且该文件**不是机械替换**而是 CW-056 冻结矩阵的实质同步 | 计划低估，见 §3.2 / §3.3 |
| `publish.py` 979 → 约 500 行 | **392 行** | 比计划更小：额外删除 8 个 phase-1 零调用方符号，见 §2.1 |
| `publish_routes.py` 108 → 约 50 行，只注册 4 端点 | **76 行**，恰 4 端点 | 无 |
| `publish_worker.py` 289 → 约 120 行，只留 verify round | **160 行**，只留 verify round | 计划**完全未预见**：删除整条 SQLite lane 以修复 CW-060 注册表违规，见 §2.3 |
| `publishers/` + `vendor/` 整体搬入 | 21 个文件（4 个本仓口径 + 17 个 vendor）全部搬入 | 无 |
| `test_publish_accounts.py` SQLite→PG，「10 条用例」 | **11 条用例**，561 行，真实 PG lane | A10 并发断言是第 11 条，见 §4.2 |
| 前端 3 个语义冲突文件人工合并 | 6 个文件接线（含计划外的 `studio.css`） | 见 §5.1 |
| 收尾三门禁全绿 | secret / static / desktop / e2e / CI-7 / 四片 pytest 全部实跑通过 | 未跑真 `run-pytest-shards.sh`，理由见 §6.6 |

## 2. 后端范围切分

### 2.1 `server/app/publish.py`：978 → **392** 行

原文件有显式 `# ---` 分节，按节裁剪。**保留**：`PublishLeaseLostError`、`_now`/`_now_text`；accounts 模型 5 个；共享 helper `_bad_request`/`_not_found`/`_require_owned_account`；accounts 段全部（`_account_response`/`_text_or_none`/`create_account`/`list_accounts`/`delete_account`/`request_account_verify`）；worker 段 `PublishLease`/`_claim`/`claim_account_verify_work`/`finalize_account_verify`。

**删除**：records 模型 5 个；records-only helper `_clean_tags`/`_parse_schedule`/`_iso_schedule_text`/`_require_owned_asset`；records 段全部 10 个函数（含 `published_total`）；worker 段 `_PUBLISH_CANDIDATE_SQL`/`claim_publish_work`/`prepare_publish_work`/`finalize_publish_work`。

**类型收窄**：`PublishLease.kind: Literal["account_verify", "publish"]` → `Literal["account_verify"]`，`_claim` 的 `kind` 参数同步收窄。

**必需的解耦改造（计划已预见，本阶段的技术核心）**：原 `_quarantine_expired_publishes()` 同时 UPDATE `publish_records` 与 `publish_accounts`，而 `claim_account_verify_work` 会调它——在本阶段**只有 `publish_accounts` 表**的库上会直接崩。拆出 `_quarantine_expired_verifies()`（只 UPDATE `publish_accounts` 的 verify 中断复位），verify claim 只调这个；原函数随 records 一起删除。该解耦由 A12 用例 `test_claim_verify_does_not_touch_publish_records` 机器锁定。

**比计划多删的 8 个 phase-1 零调用方符号**（这是 392 < 500 的原因，逐个 `git grep` 确认零引用）：`PublishCredentialError`（计划说保留，但 phase 1 零抛出点/零捕获点）、`_validate_account_for_platform`、`_conflict`、`_MAX_ATTEMPTS`、`logger` + `import logging`、`PublishPlatform`、`json`、`InvalidToken`、`PublishResult`。同时删除 `run_publish_round` 的 `storage: StorageAdapter` 参数，连带删 `storage_key_from_uri`/`get_media_storage`/`tempfile` 等 import 与 storage 预热（封面属第二阶段）。

### 2.2 `server/app/publish_routes.py`：108 → **76** 行

只注册 4 个 accounts 端点：`GET /accounts`、`POST /accounts`、`DELETE /accounts/{id}`、`POST /accounts/{id}/verify`；6 个 records 端点全删。`server/app/main.py` 干净自动合并，保留 `from app.publish_routes import router as publish_router` + `app.include_router(publish_router)`。**未改** `server/app/studio_routes.py`（`published_total` 属 records 范围），消掉一个语义冲突。

### 2.3 `server/app/publish_worker.py`：289 → **160** 行（含计划外的 CW-060 修复）

保留 `_dispatch_probe` 与 `run_publish_round` 的 **verify 段**（claim → `_dispatch_probe` → finalize）；删除 `_dispatch_publish`/`perform_publish_delivery`/`_write_temp`/`_suffix_of` 与 publish 段。模块 docstring 从「drains queued publishes and account probes」改为只 account probes；保留「慢发布绝不阻塞 H3 轮询」的独立进程理由说明。

**计划外的真实缺陷与修复（本任务唯一由 CW-068 引入的门禁失败）**：四片 pytest 跑出 `test_cw060_operator_isolation.py::test_historical_sqlite_surface_consumers_are_registered` 失败，`AssertionError: {'server/app/publish_worker.py'}`。

- **根因**：CW-060 把「历史 in-app SQLite 表面的反向消费者」冻结成一份**只减不增**的注册表 `_APP_DB_CONSUMERS`（8 项），守卫用 `rglob("*.py")` + 子串匹配 `from app.db import` 扫描 `server/app` 与 `server/scripts`。我从分支搬入的 `publish_worker.py` 带着 `from app.db import connect_database`，成为未登记的新成员。CW-060 docstring 第 3 条边界明写「the set **cannot grow silently**, and CW-042 **shrinks** it deliberately」，L64-65 注释明写「CW-042 **prunes** the list when the lane exits」。
- **修法抉择：消除 import，而非登记进注册表**。登记会让守卫失去意义，且 CW-068 的**新**代码引入历史 SQLite 表面属架构倒退（CW-025 已把全环境收敛到 PG-only，CW-030 已移除 Worker 的 SQLite 业务入口）。权威先例：`generation_worker.py` 零 `app.db`，只 import `db_pg` + `db_portable`。
- **实施**：删除 `_open_sqlite_txn`/`_sqlite_round`/`run_sqlite_forever` 与 `from app.db import connect_database`、`from pathlib import Path`；`db_pg` import 补 `close_pg_pool`；`main()` 的 PG 分支改为 `try: run_pg_forever(...) finally: close_pg_pool()` + `return`，SQLite 分支改为**防御性 RuntimeError**，形态与文案逐字对齐 `generation_worker.py` L1691-1697 的 CW-025/CW-030 治理结论。
- **修复过程中的陷阱（值得后人警惕）**：删除 import 后守卫**仍然失败**——因为守卫是朴素子串匹配，我新写的解释性注释里含 `「from app.db import」` 字面量，同样被计入。改写注释避开连续字面量，并把该陷阱写进注释本身。**结果：`test_cw060_operator_isolation.py` 7 passed**（原 1 failed / 6 passed）。
- **副作用核查**：`test_publish_accounts.py` 的 A11 用例只用 `run_publish_round` + monkeypatch `_dispatch_probe` + 自定义 PG `open_txn`，不碰 SQLite lane；`git grep --untracked` 确认三个被删符号的引用全在自身内部。删除后 `test_publish_accounts.py` **11 passed in 10.11s**。

### 2.4 `server/app/publishers/`：21 个文件整体保留

`base.py`(62)/`douyin_adapter.py`(110)/`channels_adapter.py`(93)/`__init__.py` + `vendor/` 17 个文件。**理由**：`probe_douyin` 经 `_load_publisher()` 内联 import vendor，**探测本身就依赖 vendor**，无法只留 base。`publish_to_douyin`/`publish_to_channels` 一并保留（110/93 行的内聚单元，拆开反而增加第二阶段成本），但本轮无调用方、不由测试覆盖——如实登记为 CODE_PRESENT，见 §8.2。

## 3. 迁移 082 与 CW-056 冻结矩阵

### 3.1 `082_publish_accounts.py`（101 行）

`revision = "082_publish_accounts"`，`down_revision = "081_oral_unit_price"`。**只建 `publish_accounts`**：`id`/`user_id`(FK users ON DELETE CASCADE)/`platform`/`display_name`/`cookie_enc`/`security_sdk_enc`/`status`/`verify_requested`/`last_verified_at`/`error_message` + lease 三件套(`lease_owner`/`lease_expires_at`/`attempt_count`) + timestamps；三条 CHECK：`platform IN ('douyin','wechat_channels')`、`status IN ('connected','invalid')`、`verify_requested IN (0,1)`；`downgrade()` 只 drop `publish_accounts`。SQLAlchemy 便携写法（`sa.Text()` 时间戳 + `CURRENT_TIMESTAMP`）与 main 的 081 风格一致，**类型不改写**。文件名从分支的 `publish_module` 改为 `publish_accounts`，与实际范围一致；`publish_records` 建表段与其索引全删。

**计划外保留 `idx_publish_accounts_verify_queue`**（计划只提 `idx_publish_accounts_user_created`）：它直接服务 `_VERIFY_CANDIDATE_SQL` 的候选筛选，删掉会让 verify 队列全表扫。已在真实 PG 上确认该索引**非 partial**，故不影响 CW-056 的 `partial_indexes` 冻结计数（仍为 25）。

### 3.2 head 断言：**10** 个测试文件（计划估 9 个）

`assert alembic_versions == ["081_oral_unit_price"]` → `["082_publish_accounts"]`，共 20 处匹配行：`test_db.py`(4) / `test_character_domain.py`(4) / `test_customer_devices.py`(2) / `test_postgres_migrations.py`(2) / `test_recharge_orders.py`(2) / `test_settings.py`(2) / `test_activation_code_schema.py`(1) / `test_characters.py`(1) / `test_internal_billing.py`(1) / **`test_cw056_supported_head_matrix.py`(1)**。计划漏掉了最后一个。（`server/tests/pg_test_kit.py` 也出现该串，但那只是本任务新增的注册注释，非 head 断言，不计入。）

### 3.3 CW-056 冻结矩阵的实质同步（计划未预见，非机械替换）

`test_cw056_supported_head_matrix.py` 除 `HEAD_REVISION` 外，还须同步四项冻结常量——这是「追加迁移」对既有治理断言的真实成本：

| 常量 | 081 → 082 | 依据 |
| --- | --- | --- |
| `HEAD_SCHEMA_COUNTS.tables` / `.primary_keys` | 76 → **77** | 新建 `publish_accounts` |
| `HEAD_SCHEMA_COUNTS.columns` | 894 → **909** | +15 列 |
| `HEAD_SCHEMA_COUNTS.check_constraints` | 221 → **224** | +3（platform / status / verify_flag 三条 CHECK） |
| `HEAD_SCHEMA_COUNTS.foreign_keys` | 145 → **146** | +1（`user_id → users.id ON DELETE CASCADE`） |
| `HEAD_SCHEMA_COUNTS.partial_indexes` / `.triggers` | 25 / 18 **不变** | 082 两个索引均非 partial、未加触发器（真实 PG 核验） |
| `HEAD_TABLE_NAMES` | +`publish_accounts`（76 → 77 项） | counts 只证「数量没漂」，表名集合才证「同一批表」 |
| `HEAD_SCHEMA_DIGEST` | `9a8ac71b…` → **`a23fa2756885009a3faa9af9d73472c21667bbce057283cdbf3d64dd456bf071`** | 由 cw068 freeze probe 在**真实 PG 16-alpine** 上重算，非手填 |
| `LATE_TABLES_AFTER_PUBLISHED_HEAD` | +`publish_accounts`（4 → 5 项） | 链尾迁移建表，是「失败不留半结构」的**最强哨兵** |

**`PUBLISHED_HEAD_REVISION` 保持 `055_customer_batch_visibility` 未动** → CW-056 `test_published_migration_chain_bytes_are_frozen` **零回归**。该断言只锁已发布链（止于 055、长度 54、内容级 sha256），链总长「刻意不冻结」（把未发布 revision 纳入哈希会让每次新增迁移都必须改常量，那不是「冻结已发布历史」而是「冻结开发中」）→ 追加 082 不触碰冻结范围。注释里的「056–081 尚未随任何受支持版本发布」同步改为「056–082」。

## 4. PG 测试与 A1–A16 映射

### 4.1 SQLite → PG 夹具改造（最大单项工作量）

**业务 SQL 无需改写**——已核实 `db_portable.py`(T21/SES-04) 说明业务层写的是 PG-canonical SQL（`%s`/`RETURNING`/`FOR UPDATE SKIP LOCKED`/`now() + interval`），SQLite lane 通过有界翻译层降级（`FOR UPDATE [SKIP LOCKED]` → 移除）。所以改造只在**夹具层**：

- `db_path: Path` + `BusinessConnection.sqlite(connect_database(db_path))` → `pg_test_kit.resolve_test_dsn()` + `require_pg_or_explicit_skip()` + `create_test_database()` + `upgrade_test_database_to_head()`，PG lane 连接
- 所有 `sqlite3.connect(db_path)` 直读断言（密文落库校验）→ psycopg 直连 PG 查询
- 在 `pg_test_kit.RECORDED_TEST_DATABASES` 注册 `cw068_publish_accounts_test`，附引用任务与测试文件的注释（对齐 cw054/cw056/cw057/cw058/cw059 既有注释风格）
- 合成凭据夹具沿用分支写法（`_DOUYIN_COOKIE = "sessionid=douyin-test-cookie-value; ttwid=1" + "0"*32`），避开仓库密钥扫描

### 4.2 A1–A12 → 11 个用例（全部真实 PG，`test_publish_accounts.py` 561 行）

| 矩阵 | 用例 | 锁定内容 |
| --- | --- | --- |
| A1 | `test_create_douyin_account_requires_security_sdk` | 抖音缺 `security_sdk` → 422 `PUBLISH_SECURITY_SDK_REQUIRED` |
| A2 | `test_channel_account_omits_security_sdk` | 视频号只需 cookie，`security_sdk_required == False` |
| A3 + A4 | `test_create_account_roundtrip_and_credential_never_returned` | 回显 platform/display_name/`status=="connected"` + GET 可列；**凭据不回传**（含 `repr()` 全文，且不得存在 `cookie`/`security_sdk` 字段） |
| A5 | `test_cookie_is_encrypted_at_rest` | **密文落库**：`cookie_enc` 为 Fernet 密文（`gAAAAA` 前缀）且 ≠ 明文；`security_sdk_enc` ≠ 明文；明文不出现在库中任何位置 |
| A6 | `test_accounts_are_user_scoped` | **用户隔离（读）** |
| A7 | `test_delete_account_is_owner_scoped` | **用户隔离 + 解绑**：他人 DELETE 404（不泄露存在性），本人 200 `deleted == True`，解绑后列表空 |
| A8 | `test_verify_request_marks_account` | **探测发起 + 隔离**：本人 200 `submitted == True`、`verify_requested` 落 1；他人 404 |
| A9 | `test_account_verify_claim_and_finalize` | 租约 `kind == "account_verify"`；二次 claim 返回 `None`；`finalize(ok=False)` → `invalid`/0/`error_message` |
| **A10** | `test_verify_claim_skip_locked_across_concurrent_connections` | **PG 专有并发抢占**：两条独立 PG 连接并发 claim 同一 verify 请求，`FOR UPDATE SKIP LOCKED` 下只有一个拿到租约，另一个 `None` |
| A11 | `test_worker_round_verifies_invalid_account` | worker 轮次闭环：claim → `_dispatch_probe` → finalize；`processed == 1`；probe 收到**解密后的真实 cookie** 与正确 platform；账号转 `invalid` |
| **A12** | `test_claim_verify_does_not_touch_publish_records` | **范围切分锁**：在只有 `publish_accounts`、没有 `publish_records` 的库上正常工作，证明 `_quarantine_expired_verifies()` 解耦成功 |

A13（迁移链）由 §3.2 的 10 个文件 head 断言 + §3.3 的 CW-056 冻结矩阵覆盖；A14/A15（前端）见 §5.3；A16（供应商静态门口径）见 §6.1。

**A10 是迁 PG 的核心收益**：SQLite lane 因翻译层移除 `FOR UPDATE [SKIP LOCKED]`，**结构上无法覆盖**并发抢占语义。该用例用两条真实独立 PG 连接验证租约互斥，是分支的 SQLite 版 `test_publish.py` 24 条里不存在的能力。

### 4.3 本轮不迁

records 相关 14 条用例（`test_create_record_*`/`test_record_*`/`test_claim_respects_schedule_*`/`test_claim_serializes_*`/`test_finalize_publish_*`/`test_worker_round_publishes_*`/`test_stats_includes_published_total`）随 records 代码一起留到第二阶段。

### 4.4 mutation 验证（证明断言非空洞）

对 A5（密文落库）与 A15（前端凭据不回显）做了变异验证：故意把加密改为明文落库 / 把前端表单提交后不清空 → 对应用例**精确转红**，恢复后转绿。证明这两条安全断言真的在执行，而非恒真。

## 5. 前端接线

### 5.1 实际改动 6 个文件（计划 4 个 + 计划外 `studio.css`）

| 文件 | +/- | 内容 |
| --- | --- | --- |
| `client/src/studio/MainPages.tsx` | +327 / −47 | 接通 ProfilePage「发布账号」tab：移除两处占位（原 L1779 `description="平台账号授权接口尚未接入，暂不可添加账号。"`、L1859 `<p>发布账号服务尚未接入</p>`），改为真实授权流——平台选择（抖音/视频号）、Cookie 粘贴（抖音额外 security_sdk）、连接提交、账号列表、发起校验、解绑。**不回显任何凭据明文** |
| `client/src/studio/MainPages.test.tsx` | +215 / −0 | 新增 `describe("CW-068 发布账号管理（正式模式）")` 5 个用例 |
| `client/src/studio/live.ts` | +61 / −0 | accounts 四个真实调用 + `PUBLISH_PLATFORM_LABELS` |
| `client/src/api.ts` | +55 / −0 | accounts 四个 API 客户端函数与类型 |
| `client/src/studio/types.ts` | +15 / −0 | `StudioPublishAccount` 等类型 |
| `client/src/studio/studio.css` | +13 / −0 | **计划外**，见下 |
| `package.json` | +1 / −0 | 只加 `"dev:publish-worker"` script |

`client/src/api.ts`、`types.ts`、`fixtures.ts` 在 merge-tree 预演里是干净自动合并，但**未整取分支版本**——分支增量混着 records。`fixtures.ts` 的 `published_total: 156` 与 `types.ts` 的 `StudioStats.published_total` **完全未取**（属第二阶段）。

**`studio.css` +13 是计划偏离**（计划原文「本轮不动 studio.css」）：新增 `.studio-publish-connect` 与 `.studio-publish-platform-options` 两条 accounts 范围规则。**理由**：分支的 studio.css 增量确属 accounts 范围且 merge-tree 无冲突；若改为借用 `.content-platform-options`，会让 `MainPages.tsx` 出现**全文件唯一的跨样式表依赖**（`content.css` 仅由 `ContentPages.tsx` import；main 的 `MainPages.tsx` 使用 `content-*` 类数量 = 0）。`content.css` **保持不动**（其增量 `.content-publish-record-actions` 属 records）。

`package.json` 的 `dev:publish-worker` 按 main 的 CW-025 约定包 `bash scripts/dev-with-pg.sh`，且按字母序插在 `dev:client` 后（分支原文无 wrapper、插在 `dev:worker` 后——因分支早于 CW-025，`git cat-file -e 7e5450a:scripts/dev-with-pg.sh` → RC=128 证实该脚本在分支上不存在）。

### 5.2 计划外：`requestSeq` 请求序号守卫（修复分支遗留的真实并发竞态）

分支实现存在竞态：初次加载的在途响应若晚于提交请求返回，会用**旧快照覆盖**刚连接/刚解绑的账号列表。修复：引入 `requestSeq` 单调序号，只有最新序号的响应才允许落地。配套三处加固：connect 的 append 改为**幂等 upsert**；verify 补**立即 `reload()`**；延迟刷新 timer 在组件卸载时 `clearTimeout`。

### 5.3 计划外：补齐 A14 要求但分支缺失的「最后校验时间」

CW002 §8 A14 明确要求账号列表含「昵称·平台·状态·**最后校验时间**」，而分支实现只有前三项。新增 `publishAccountVerifiedText()`，与状态合并进同一 `<small>` 以保持既有 CSS 契约（`.studio-publish-account small { margin-left:auto }`）。账号行的 span/small 改为**单表达式模板字符串**（确定性单文本节点），使 `getByText("抖音 · 张工说乡墅")` 全串精确匹配可靠。

其余对齐矩阵用词的偏离：解绑按钮文案 `解绑`（分支为 `删除`）、notify `发布账号已解绑。`（分支 `发布账号已删除。`）；空态 description 改写为「连接后即可在此发起登录态校验；正式发布能力将在下一阶段开放。」（分支原文提「发布管理」属第二阶段）；`PublishAccountsSummary` 的 review 分支渲染**两个**示例账号（分支只渲染一个），避免审核模式观感回归；`PUBLISH_PLATFORM_LABELS` 从 `live.ts` import（分支在 `MainPages.tsx` 内重复声明了一份）。

### 5.4 A14 / A15 → 5 个用例

`describe("CW-068 发布账号管理（正式模式）")`：`未接通占位提示已移除`、`连接发布账号：填写 Cookie 后提交并回显列表`、`抖音未填 security_sdk 时给出明确提示`、`发起校验与解绑走真实接口并刷新列表`（以上 A14）、`凭据明文不出现在 DOM`（A15，innerHTML + `toHaveValue` 双断言）。分支只有 2 条，其余 3 条为本任务新增。

### 5.5 本轮不动（消掉语义冲突）

`ContentPages.tsx`（发布页）、`ContentPages.test.tsx`、`AnalyticsPage.test.tsx`、`content.css` **零改动**。首页「累计已发布」指标**保持 `value: review ? "156" : "—"` 诚实降级不变**（`published_total` 属 records 范围），仅按计划在该处补注释说明第一/第二阶段口径。

## 6. 验证记录

本机：Windows 10（`MINGW64_NT-10.0-19045`）、host `PC-202609071434`、Node.js **v24.19.0**（满足抖音签名的 ≥ 18 前置）、真实 PG 16 容器。PG 资源隔离：容器 `vs-pg-cw068`@**5441**、专属库 `cw068_publish_accounts_test`，不触碰他任务在用的 5432/5434–5438/5440。

### 6.1 后端专项与静态门（CI 精确口径，root 下执行）

```
uv run pytest tests/test_publish_accounts.py -q  → 11 passed in 10.11s
uv run pytest tests/test_cw060_operator_isolation.py -q → 7 passed（修复前 1 failed / 6 passed）
uv --cache-dir .uv-cache run --project server --locked ruff check server          → All checks passed!
uv --cache-dir .uv-cache run --project server --locked ruff format --check server → 321 files already formatted
uv --cache-dir .uv-cache run --project server --locked python -m mypy --config-file server/pyproject.toml server/app
                                                                                  → Success: no issues found in 120 source files
uv sync --locked                                                                  → RC=0（56 包，证明 uv.lock 与 pyproject 同步）
bash scripts/verify_no_secrets.sh                                                 → No hardcoded secrets detected in runtime contract surface. RC=0
python3 scripts/ci/build-test-shards.py --check-coverage                          → coverage OK: 117 discovered test file(s) fully covered  RC=0
```

以上全部在**修复 `publish_worker.py`（§2.3）与 manifest 行尾（§8.1 第 22 项）之后重跑**，非修复前的旧结果。A16 供应商静态门口径由 ruff/format/mypy 三绿 + secret 扫描共同覆盖：`app/publishers/vendor/**` 排除出 ruff check / ruff format / mypy（`pyproject.toml` +12 行：`ruff exclude` + `[[tool.mypy.overrides]] ignore_errors/follow_imports`），但 **secret 扫描仍覆盖该目录**，且沿用分支已主动排除含 PEM 模板的 `ucenter_ticket.umd.js` 的裁剪结果，未重新引入。

### 6.2 client 门禁

```
node_modules\.bin\biome.cmd check  → 202 files
node_modules\.bin\tsc.cmd -b       → RC=0
node_modules\.bin\vitest.cmd run   → 80 files, 1301 tests passed（20.27s）
npm run check:e2e                  → 15 files
```

### 6.3 desktop 门禁

```
npm run build                    → RC=0
npm run build:admin              → RC=0
npm run verify:customer-bundle   → RC=0（扫 17 文件、禁止命中 0、阳性对照 6/6 命中 → 自证非空洞）
```

`npm run check:tauri` **本机无法执行**（未安装 cargo/rustc，`'cargo' is not recognized`）。判据：`git diff --stat a093f61 -- client/src-tauri` 与 `e2e/` 均为**空**（逐字节相同）→ 不在本任务爆炸半径，登记为环境限制。

### 6.4 pytest 四片（各片独立 PG 容器）

| 分片 | 结果 | 说明 |
| --- | --- | --- |
| shard-0 | 1 failed / 685 passed / 784.83s | 唯一失败 = CW-060 注册表守卫，**已修复**（§2.3） |
| shard-1 | 首轮**无 summary**（stdout 冻结在 2046 字节）→ **串行独占重跑 1 failed / 585 passed / 1 skipped in 405.20s** | 唯一失败 = 既有 GBK 项；**`test_publish_accounts.py` 11 条在分片上下文全绿** |
| shard-2 | 25 failed / 572 passed / 724.40s | 全部既有（cw033×22 + storage×3） |
| shard-3 | 5 failed / 736 passed / 1 skipped / 736.26s | 全部既有（cw009×4 + analytics×1） |

**shard-1 首轮挂起的归因（环境资源竞争，非代码）**，四重判据：① 挂起点 `test_first_frames.py` 单独跑 → **38 passed in 33.54s，RC=0**；② 驱动器日志显示**4 片的 `rc=` 全部为空**（含已跑完并有 summary 的 shard-0/2/3），且 4 个 `WaitForExit()` 在**同一秒 00:34:18** 返回 → `Start-Process -PassThru` + `$p.ExitCode` 组合的驱动器缺陷，无法区分「崩溃」与「完成」；③ 终端历史可见**同机 CW-063 的后台 pytest `rc=-1`** 在同一时间窗被异常终止 → 主机级资源压力（4 片并行 pytest + 我的 4 个 PG 容器 + 9 个他任务容器）；④ `cv2`/`PIL`/`numpy` **只在 vendor 的函数内联 import**，`test_first_frames.py` 与 main 零 diff 且不 import 它们 → 排除本任务新增的 `opencv-python-headless 5.0.0.93` / `numpy 2.5.3`。串行独占重跑比 4 片并行更快（405s vs 13 分钟无输出）且完整，teardown `docker rm -f` RC=0。

### 6.5 31 个既有失败的 baseline 归因（决定性对照，非推测）

**方法**：新建 detached worktree `.worktrees/CW-068-BASELINE` @ `a093f61`（= 我的基线），从其 CWD 跑同一批测试。**对照有效性已预先验证**：CW-068 venv 里有 `_editable_impl_video_replica_api.pth`，若 `app` 解析到 CW-068 代码则对照失效；实测从 baseline CWD 跑 `python -c "import app; print(app.__file__)"` → `CW-068-BASELINE\server\app\__init__.py`（CWD 在 `sys.path` 中优先于 `.pth` 注入）✓。

| # | 测试文件 | 失败数 | baseline 复现 | `PYTHONUTF8=1` 转绿 | 根因 | CW-068 关联 | 新 main `2be7c3d` 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `test_cw033_pitr_drill_validation` | 22 | ✅ | ❌ | `subprocess.run` 执行 `.sh`，Windows 无解释器关联 → `FileNotFoundError [WinError 2]`（`subprocess.py:1538`） | 无 | 仍失败（Windows 特有，CI Linux 绿） |
| 2 | `test_cw009_security_matrix_export` | 4 | ✅ | ✅ | `MATRIX_PATH.read_text()` 无 `encoding=` → GBK 解码 UTF-8 md 失败 | 无 | 仍失败 |
| 3 | `test_storage_cross_instance` | 3 | ✅ | ❌ | PG lane 按设计拒绝 `X-Dev-User-Id`（CW-026/CW-031）→ 401 `SESSION_TOKEN_REQUIRED` ≠ 期望 503 | 无 | **CW-043 已修** |
| 4 | `test_studio_analytics` | 1 | ✅ | ❌ | 日期敏感：`range_completed` 期望 5 实得 4（`range_days==7`、`len(daily)==7` 均通过；迁移链含 082 正常跑完） | 无 | **CW-043 已修** |
| 5 | `test_security_contracts` | 1 | ✅ | ✅ | `test_security_contracts.py:110` `read_text()` 无 `encoding=` → GBK 解码 `pyproject.toml` 失败（baseline byte `0x99` position 885 / 我的 `0xa7` position 994，因我加了中文注释使文件变长） | 无 | 仍失败 |
| 6 | **`test_cw060_operator_isolation`** | **1** | **❌ CW-068 独有** | — | `publish_worker.py` 引入历史 `app.db` 导入面，违反 CW-060「只减不增」注册表 | **✅ 已修复并验证 7 passed** | 不适用 |

`PYTHONUTF8=1` 归因跑：**26 failed / 46 passed / 1 skipped in 13.02s**——cw009×4 与 security_contracts×1 **转绿**、cw060 **7 passed**；26 = cw033 22 + storage 3 + analytics 1，逐项吻合。

**归因正确性获并行任务独立印证**：CW-043（`2be7c3d`，PR #46）在**不知道本任务归因**的情况下修掉了表中 #3 与 #4，其修复注释逐字印证我的根因判断——`test_studio_analytics.py`：「不冻结时该用例是**日期炸弹**（北京日期每越过一天，窗口就滑出一颗种子，计数随之变化）」；`test_storage_cross_instance.py`：「CW-026 收敛后客户 lane 只认 Bearer 会话（dev 身份 401），故闸门断言迁移到真实会话模式」。CW-043 删除了用 `X-Dev-User-Id` 的 `media_client` fixture，改用 `customer_lane` + Bearer token。

### 6.6 未跑真 `bash scripts/ci/run-pytest-shards.sh` 的理由与替代

立项计划与认领登记都写「收尾全量走 `scripts/ci/run-pytest-shards.sh`」，**实际未跑该脚本**，改用**语义等价的 PowerShell 驱动器**（同容器名/端口/镜像/DSN/manifest/pytest 命令/teardown）。五条理由：

1. **端口硬冲突**：脚本默认 5433–5436，与他任务在用的 5434/5435/5436 冲突，必须偏离为 `CI_SHARD_BASE_PORT=5443`；
2. **并行已被证实有害**：4 片并行导致进程被资源竞争终止（shard-1 挂起 + 同机 CW-063 `rc=-1`）；
3. **必然 RC≠0**：31 个既有 Windows 失败使脚本无法给出「全绿」信号，读数无意义；
4. **等价性可核**：驱动器脚本 `.dev-env/cw068_t10_shard1_solo.ps1` 与 shard 日志全部保留在 worktree **外**（零 git 污染），逐参数与脚本对齐；
5. **最终裁决在 CI**：31 个失败全部是 Windows 特有（`.sh` subprocess / GBK locale / 日期敏感 / PG lane 身份头），Linux 门禁不受影响。

另：立项时 git-bash 曾出现 Cygwin 共享内存中毒（`cygheap_user::init: NtSetInformationToken (TokenDefaultDacl), 0xC0000022`），本会话已自愈并**用真 bash 重跑了 secret 扫描**（RC=0）。

## 7. 与相邻任务的边界

- **CW-002**：§3 规定「publishing 若纳入须先补专用验收矩阵」——本 PR 在同一提交内补齐 §8（A1–A16 + §8.2），§7 追加 2026-09-11 范围变更签认且**保留 09-09 原签认原文不篡改**。
- **CW-025 / CW-030**：`publish_worker.py` 的 PG-only 形态与防御性 RuntimeError 逐字对齐 `generation_worker.py` L1691-1697 的既有治理结论，**不新创范式**（§2.3）。
- **CW-043**（`2be7c3d`，PR #46）：独立修掉了本任务归因表中 #3 #4 两组既有失败，注释逐字印证根因（§6.5）。**冲突面见 §8.5**。
- **CW-056**：`test_published_migration_chain_bytes_are_frozen` 只锁已发布链（止于 `055`、长度 54、内容级 sha256），链总长刻意不冻结 → 追加 082 **零回归**；但 `HEAD_SCHEMA_COUNTS`/`HEAD_TABLE_NAMES`/`HEAD_SCHEMA_DIGEST`/`LATE_TABLES_AFTER_PUBLISHED_HEAD` 四项须实质同步（§3.3）。
- **CW-060**：其「历史 SQLite 表面反向消费者只减不增」注册表是本任务唯一引入的门禁失败的来源，修法为消除 import 而非登记（§2.3）。
- **CW-061**：其 CI-7 fail-closed 覆盖率守卫（`build-test-shards.py --check-coverage`）要求 committed manifest 覆盖全部测试文件——这正是 §8.5 合并前置动作的强制机制来源。本任务重生 manifest 后守卫 RC=0（117 文件）。
- **第二阶段（另立任务）**：records 全链路、封面、定时、`published_total`、`publishing` 页、小红书。

## 8. 诚实边界

### 8.1 计划偏离清单（24 项，逐条登记不隐藏）

| # | 类别 | 计划原文 | 实际交付 | 理由 |
| --- | --- | --- | --- | --- |
| 1 | 迁移 | 只提 `idx_publish_accounts_user_created` | **额外保留** `idx_publish_accounts_verify_queue` | 直接服务 `_VERIFY_CANDIDATE_SQL`；真实 PG 核验为非 partial，不影响 CW-056 `partial_indexes` 计数 |
| 2 | 迁移 | head 断言「9 个测试文件」 | **10 个** | 漏了 `test_cw056_supported_head_matrix.py` |
| 3 | 迁移 | 该文件按「机械字符串更新」处理 | **实质同步四项冻结常量** | 见 §3.3，非机械替换 |
| 4 | 后端 | 保留 `PublishCredentialError` | **删除** | phase 1 零抛出点 / 零捕获点 |
| 5 | 后端 | `run_publish_round` 保留 `storage` 参数 | **删除该参数** | 连带删 `storage_key_from_uri`/`get_media_storage`/`tempfile` import 与 storage 预热（封面属第二阶段） |
| 6 | 后端 | `publish.py` → 约 500 行 | **392 行** | 额外删 8 个 phase-1 零调用方符号（`_validate_account_for_platform`/`_conflict`/`_MAX_ATTEMPTS`/`logger`+`import logging`/`PublishPlatform`/`json`/`InvalidToken`/`PublishResult`），逐个 `git grep` 确认零引用 |
| 7 | 后端 | 未预见 | **删除 `publish_worker.py` 整条 SQLite lane**（175→160 行） | CW-060 注册表违规，见 §2.3。**计划完全未预见，是四片 pytest 扫出来的** |
| 8 | 依赖 | `uv.lock` 同步 | 用 `uv lock` **增量重解析**，非整取分支版 | 分支 lock 落后 main 84 提交 |
| 9 | 依赖 | 未预见上界 | `opencv-python-headless>=4.5.0` 解析到 **5.0.0.93**、连带 `numpy 2.5.3` | main 的 `uv.lock` 原本零 opencv/pillow/numpy/curl-cffi（只有 `requests 2.34.2`）；已排除其与 shard-1 挂起的关联（§6.4 判据④） |
| 10 | 前端 | `package.json` 只加一行 script | 同，但**包 `bash scripts/dev-with-pg.sh` 且按字母序插在 `dev:client` 后** | 对齐 main 的 CW-025 约定；分支早于 CW-025（`git cat-file -e 7e5450a:scripts/dev-with-pg.sh` → RC=128） |
| 11 | 前端 | 3 个文件「干净自动合并」 | **未整取分支版本** | 分支增量混着 records；`fixtures.ts` 的 `published_total: 156` 与 `types.ts` 的 `StudioStats.published_total` **完全未取** |
| 12 | 前端 | 「本轮不动 `studio.css`」 | **+13 行两条 accounts 规则** | 避免 `MainPages.tsx` 出现全文件唯一的跨样式表依赖，见 §5.1 |
| 13 | 前端 | 未预见 | **新增 `requestSeq` 竞态守卫** | 修复分支遗留的真实并发缺陷，见 §5.2 |
| 14 | 前端 | A14 要求「最后校验时间」 | **分支缺失，本任务补齐** | 见 §5.3 |
| 15 | 前端 | — | 解绑文案 `解绑`/notify `发布账号已解绑。` | 对齐 A14 用词（分支为 `删除`/`已删除`） |
| 16 | 前端 | — | 空态 description 改写 | 分支原文提「发布管理」属第二阶段 |
| 17 | 前端 | — | `PublishAccountsSummary` review 分支渲染**两个**示例账号 | 分支只渲染一个，避免审核模式观感回归 |
| 18 | 前端 | — | 前端测试 **5 条**（分支 2 条） | 新增 `未接通占位提示已移除`/`发起校验与解绑走真实接口并刷新列表`/`凭据明文不出现在 DOM` |
| 19 | 前端 | — | `PUBLISH_PLATFORM_LABELS` 从 `live.ts` import | 分支在 `MainPages.tsx` 内重复声明了一份 |
| 20 | 前端 | — | 账号行 span/small 改单表达式模板字符串 | 确定性单文本节点，使 `getByText` 全串精确匹配可靠 |
| 21 | 测试 | 「10 条用例」 | **11 条** | A10 并发断言是第 11 条 |
| 22 | CI | 未预见 | shard manifest 由 `build-test-shards.py --shards 4` **重生成**，LPT 重排 17 个既有文件归属（+18/−17） | 新文件用 1.0s default 成本估计（实测 9.5–12.4s），**刻意不用 `--from-log`** |
| 23 | CI | 未预见 | shard manifest 行尾 **CRLF→LF** 字节级转换 | Python Windows text-mode 产物；对齐 `.gitattributes` 首行 `* text=auto eol=lf`（其注释明写「prevents CRLF-only rewrites like bd73072 from ever reaching CI again」）。已核实 committed blob 本就是 LF（`git diff --stat` = 18/17 而非全 117 行重写）→ CI 无风险，但仍消除 warning 与对 git 隐式规范化的依赖 |
| 24 | 治理 | — | **回填修正三处立项文档失准** | ① CW002 §8 A13 行「9 个测试文件」→ 10 个 + 冻结矩阵实质同步说明；② CW002 §8 前言 `describe("C5 …")` → 实际代码为 `describe("CW-068 …")`（对齐同文件 `CW-016` 前缀惯例）；③ 认领登记 L28 同①。**历史签认原文（CW002 §7 的 09-09 记录）未篡改** |

### 8.2 CODE_PRESENT 未验证面（比计划预估更大，如实登记）

**决定性证明**：`git grep --untracked -n -E 'publishers|probe_douyin|probe_channels|publish_to_douyin|publish_to_channels' -- server/tests` → **零命中（RC=1）**。

即整个 `server/app/publishers/`（**21 个文件**：4 个本仓口径 `__init__.py`/`base.py`(62)/`douyin_adapter.py`(110)/`channels_adapter.py`(93)，+ 17 个 vendor 文件含 9 个 `.py`、5 个 `.js`、1 个 `.json`、2 个 `VENDOR-NOTES.md`）**无任何测试直接执行**。A11 用例是 monkeypatch `worker_mod._dispatch_probe` **打桩绕过** → 连 `probe_douyin`/`probe_channels` 也未被执行，**比计划预估的「`publish_to_*` 无调用方」范围更大**。`base.py` 的 `PublishResult` 与 `PublisherUnavailableError`/`PublisherAuthError`/`PublisherError`/`PublisherProbeResult`（后 4 个在分支里也是 0 refs）同属此面。

保留理由（计划已述）：`probe_douyin` 经 `_load_publisher()` 内联 import vendor，**探测本身就依赖 vendor**，无法只留 base；`publish_to_*` 是 110/93 行的内聚单元，拆开反而增加第二阶段成本。

### 8.3 安全与可观测性

- **Fernet 密文落库**：`cookie_enc`/`security_sdk_enc`，A5 用例断言 `gAAAAA` 前缀 + 明文不出现在库中任何位置（**mutation 已验**）。
- **API 不回传凭据**：A4 断言响应体含 `repr()` 全文不得出现 cookie/security_sdk，且不得存在同名字段。
- **前端不回显**：A15 innerHTML + `toHaveValue` 双断言（**mutation 已验**），提交后清空表单。
- **日志只记 `type(exc).__name__`**：`probe_douyin` 失败文案为固定中文（`"抖音登录态校验失败，请重新连接账号"`），不把异常消息（可能含凭据片段）写进日志或 `error_message`。
- **用户隔离**：读/删/verify 三处 owner-scoped，他人一律 404（不泄露存在性），A6/A7/A8 覆盖。
- **vendor 排除出静态门口径，但 secret 扫描仍覆盖**；沿用分支已排除含 PEM 模板的 `ucenter_ticket.umd.js` 的裁剪结果。
- **运行前置**：抖音签名依赖服务端 **Node.js ≥ 18**（`_require_node()` 用 `shutil.which("node")` fail-fast，缺失时给用户可读中文提示 `_UNAVAILABLE_MESSAGE = "服务端缺少 Node.js 18+ 环境（抖音发布签名依赖），请联系管理员安装后重试"`）。本机 v24.19.0 满足；**需写入部署文档作为服务端前置条件**。
- **泄露 Cookie 安全事件已闭环**：用户确认原仓库泄露的视频号登录态已作废、仓库已删除/转私有（GitHub API `users/phlong026/repos` 返回 `[]`），已在拆解账本登记。

### 8.4 第一阶段明确不验收（同 CW002 §8.2）

- **正式发布链路全部留第二阶段**：`publish_records` 表、records 6 端点、worker publish round、封面资产、定时发布、平台 item id / 短链回写、`published_total`、`publishing` 页。
- **首页「累计已发布」保持 `review ? "156" : "—"` 诚实降级不变**。
- **小红书暂缓**：三平台中唯一无自有实现，另立后续任务；`platform` CHECK 只含 `douyin`/`wechat_channels`。
- **真实平台探测/发布链路未测**：按硬红线需真实凭据人工授权。全部用例使用合成凭据（`sessionid=douyin-test-cookie-value; ttwid=1` + `"0"*32`），`_dispatch_probe` 在测试中被 monkeypatch 替换，**不触网**。

### 8.5 ⚠️ 基线已过时 + 跨机器撞号重编号：合并前置动作清单（集成人必读）

**事实 1（基线漂移）**：本分支基线 `a093f61`，开工后 `origin/main` 已 fast-forward 到 **`ced3e82`**，领先 **5** 个提交：

```
ced3e82 COORD-STATUS-AUTO: patrol rounds 14-15 — register CW-061/CW-062/PR #49-51 and refresh counts (#55)
5c43fb7 CW-062: verify and register the main Linux-gate dual-bomb fixes (#50)
7190f2e ADMIN-UI-AUDIT: audit admin console pages and rebuild the login gate (#49)
2be7c3d test(CW-043): Segment 4+ 独立核销全业务 PG 测试覆盖（analytics + viral_import 补漏） (#46)
ad19e52 COORD-STATUS-AUTO: patrol rounds 13-14 — full ledger repair and snapshot refresh through a093f61 (#45)
```

**事实 2（撞号 → 重编号）**：`5c43fb7`（PR #50）是**另一条并行 CW-062 线**（Linux 门禁双炸弹修复，纯 docs），已 squash 合并入 main；`ced3e82` 巡检又把 CW-062 登记进账本归属该 gate 修复。本「发布账号」任务与它**跨机器撞号**，经 owner 决策重编号 **CW-062 → CW-068**（详见文首「编号变更」）。重编号顺带**消除一个真实冲突**：本任务证据文件原也叫 `docs/evidence/CW062-EVIDENCE.md`，与 PR #50 同名文件构成 add/add 冲突；已重命名 `CW068-EVIDENCE.md`，冲突不复存在。

`git merge-base HEAD origin/main` = `a093f61` → 与 main 无历史分叉。经 owner 决策：**rebase 到 `ced3e82`** 后走 Draft PR → CI 三门禁 → squash merge，按下列清单处置冲突。

**测试文件数账**：`a093f61` = 116 → `ced3e82` = **118**（CW-043 `2be7c3d` 新增 `test_cw043_analytics_pg_matrix.py`、`test_cw043_viral_import_pg.py`；#49/#50/#45/#55 均不增 server pytest 文件，故发现数仍 118）→ rebase 合并后应为 **119**（本任务 +`test_publish_accounts.py`）。本分支工作区重生成的 manifest 只覆盖 **117**（116 + 本任务 1；不含 CW-043 两个新文件），**rebase 后必须在合并树上重跑 `build-test-shards.py --shards 4` 才能达 119**。

**rebase 冲突面精确为 6 个文件**（经 `git diff --name-only a093f61 ced3e82` ∩ 本任务文件核实；原始交集 7 个，重编号把 `CW062-EVIDENCE.md` 改名 `CW068-EVIDENCE.md` 后消除 1 个 → 6 个；其余全部零交集）：

| 文件 | 冲突性质 | 处置（必须照做） |
| --- | --- | --- |
| `server/tests/pg_test_kit.py` | 双方在 `RECORDED_TEST_DATABASES` 的**同一插入点**（`"cw059_rbac_test",` 之后、`# Suites still doing their own admin CREATE/DROP…` 之前）各加注册项 → **必然文本冲突** | **两项都保留**：CW-043 的 `cw043_analytics_test` + `cw043_viral_import_test`，与本任务的 `cw068_publish_accounts_test`。`frozenset` 无序，先后不影响语义；各自的注释块也一并保留 |
| `scripts/ci/test-shards/shard-0.txt`<br>`shard-1.txt`<br>`shard-2.txt`<br>`shard-3.txt` | 双方都用 `build-test-shards.py` **重生成** → **必然冲突** | **不可手工合并**。在合并后的树上重跑 `python3 scripts/ci/build-test-shards.py --shards 4`，再跑 `--check-coverage` 断言应为 `coverage OK: 119 discovered test file(s) fully covered`。**若跳过此步，CW-061 的 CI-7 fail-closed 守卫会因缺 CW-043 两个新文件而报红**（这正是该守卫的设计意图：迫使重生清单，而非降级 sequential） |
| `docs/客户云版任务认领登记.md` | main 侧有 CW-062(gate,#50)/CW-061/#49/patrol(#55) 行，本任务 rebase 时加 **CW-068** 行 → 表格同区插行冲突 | **所有行都保留**：main 的 CW-062(gate)/ADMIN-UI-AUDIT/CW-061 行与本任务 CW-068 行并列（表格行无序语义）。本任务追加的「CW-068 认领详情」段落 main 未触碰，可自动合并 |

**零冲突面（已核）**：CW-043 改的 `test_storage_cross_instance.py`、`test_studio_analytics.py` 本任务**未触碰**；origin/main（CW-043 + #45 + #49 + #50 + #55）改的 docs（`CW043-IMPLEMENTATION-EVIDENCE.md`、`ADMIN-UI-AUDIT-20260911-EVIDENCE.md`、`CW062-EVIDENCE.md`(gate 版)、`管理端页面综合排查分析-2026-09-11.md`、`客户版V3任务进度快照.md`、`客户版任务清单-V3.md`、`客户云版开发顺序排班与Worktree协作清单.md`）与本任务改的 docs（`未接通能力边界-任务拆解-2026-09-06.md`、`CW002-SCOPE-DECISIONS.md`、`CUSTOMER-TASK-EVIDENCE-V3.md`）**文件级零交集**。⚠️ 两处例外：① `客户云版任务认领登记.md`——#49/#50/#55 都改了它（与本任务同区插行），升入上方冲突表；② `docs/evidence/CW062-EVIDENCE.md`——PR #50 的 gate 版与本任务原同名文件构成 add/add 冲突，**已由重编号重命名为 `CW068-EVIDENCE.md` 消除**。

**合并后既有失败数会从 31 降到 27**：CW-043 已修掉 `test_storage_cross_instance`×3 与 `test_studio_analytics`×1（§6.5 表中 #3 #4）；剩余 27 = cw033×22 + cw009×4 + security_contracts×1，**全部为 Windows 本机特有**（`.sh` subprocess / GBK locale），CI Linux 门禁不受影响。

### 8.6 其他未测项与环境限制

- `npm run check:tauri` 本机无 Rust 工具链未执行；`client/src-tauri/**` 与 `e2e/` 与基线逐字节相同（§6.3）。
- 未在真实宿主机执行 `deploy/customer` 全流程（属 CW-032/CW-047 范围，本任务未触碰）。
- 全量 pytest 与三门禁**最终以 CI（Linux）为准**；本机 31 个既有失败全部为 Windows 特有。
- `uv.lock` 新增 `curl-cffi 0.16.3`/`opencv-python-headless 5.0.0.93`/`pillow 12.3.0`/`numpy 2.5.3`，`uv sync --locked` RC=0 证实与 `pyproject.toml` 同步。
- 本任务已 commit（`6c758c2`，重编号后 amend 为单提交，msg `CW-068: ship C5 publish-account authorization (phase-1 minimal loop)`）；经 owner 决策走 **rebase → Draft PR → CI 三门禁 → squash merge**。push 前 `git ls-remote` 对该分支零命中（尚未推远程），rebase 到 `ced3e82` 后才 push。

## 9. Section 14 Ledger Record

```text
任务/工作包：CW-068 / C5 发布管理第一阶段（发布账号授权最小闭环）
Owner / Reviewer：Qoder session 代 honor.pei / 待 PR 分配
分支 / 基线 SHA：feat/customer-v3-cw068-publish-accounts / 基线 origin/main@a093f61（⚠️ origin/main 已前进到 ced3e82，领先 5 个提交 #45/#46/#49/#50/#55，本任务 rebase 到 ced3e82，合并前置动作见 §8.5）；裁剪来源只读参考 origin/feat/c5-publish-module@7e5450a（不派生不堆叠）
上游规格段落：CW002-SCOPE-DECISIONS.md §3（纳入须先补矩阵）+ §7（2026-09-11 范围变更签认，保留 09-09 原文）+ §8（发布管理专用验收矩阵 A1–A16、§8.2 明确不验收 4 条）；docs/未接通能力边界-任务拆解-2026-09-06.md C5 行
改动文件：server/app/{publish.py(392,新),publish_routes.py(76,新),publish_worker.py(160,新),main.py(+2)}、server/app/publishers/**(21 文件,新)、server/migrations/versions/082_publish_accounts.py(101,新)、server/tests/{test_publish_accounts.py(561,新),pg_test_kit.py,test_db.py,test_activation_code_schema.py,test_character_domain.py,test_characters.py,test_customer_devices.py,test_internal_billing.py,test_postgres_migrations.py,test_recharge_orders.py,test_settings.py,test_cw056_supported_head_matrix.py}、server/{pyproject.toml(+12),uv.lock(+204)}、client/src/{api.ts(+55),studio/{MainPages.tsx(+327/-47),MainPages.test.tsx(+215),live.ts(+61),types.ts(+15),studio.css(+13)}}、package.json(+1)、scripts/ci/test-shards/shard-{0,1,2,3}.txt(+18/-17)、docs/evidence/{CW002-SCOPE-DECISIONS.md(+44/-2),CW068-EVIDENCE.md(新)}、docs/{客户云版任务认领登记.md(+3),未接通能力边界-任务拆解-2026-09-06.md(+4/-2),CUSTOMER-TASK-EVIDENCE-V3.md}
失败测试或回归锁定：新增 11 条 PG 用例锁 A1–A12（含 A10 FOR UPDATE SKIP LOCKED 并发抢占、A12 范围切分锁）+ 5 条前端用例锁 A14/A15；A5/A15 经 mutation 验证非空洞；四片 pytest 扫出并修复 CW-060 注册表违规（本任务唯一引入的失败）；CW-056 冻结矩阵四项常量实质同步后 bytes 冻结断言零回归
实现结果：抖音/视频号手工粘贴 Cookie 连接、Fernet 密文落库、凭据零回传、用户隔离、异步登录态探测（claim/finalize 租约 + worker 轮次）、前端「发布账号」tab 真实接线（含修复分支遗留的 requestSeq 竞态）；正式发布链路（records/worker publish round/封面/定时/published_total）按计划全部留第二阶段；小红书暂缓
验证命令与通过数：pytest tests/test_publish_accounts.py → 11 passed；tests/test_cw060_operator_isolation.py → 7 passed；ruff check server → All checks passed；ruff format --check server → 321 files；mypy server/app → 120 files Success；uv sync --locked → RC=0；bash scripts/verify_no_secrets.sh → RC=0；build-test-shards.py --check-coverage → 117 files RC=0；client biome 202 files / tsc -b RC=0 / vitest 80 files 1301 tests passed / check:e2e 15 files；desktop build+build:admin+verify:customer-bundle 全 RC=0；pytest 四片 shard-0 685P / shard-1 585P（串行独占重跑）/ shard-2 572P / shard-3 736P，31 个既有失败经 a093f61 baseline worktree 逐项复现归因
证据层级：AUTOMATED_VERIFIED（真实 PG 16 容器 vs-pg-cw068@5441、专属库 cw068_publish_accounts_test）；真实平台探测/发布链路**不得标 PRODUCTION_GO**（需真实凭据人工授权）
安全与可观测性：Fernet 密文落库（A5 mutation 已验）；API 与前端均不回传/不回显凭据（A4/A15 mutation 已验）；读/删/verify 三处 owner-scoped 他人 404 不泄露存在性；日志只记 type(exc).__name__ 不落异常消息；vendor 排除出 ruff/format/mypy 但 secret 扫描仍覆盖，沿用排除含 PEM 模板的 ucenter_ticket.umd.js；泄露 Cookie 事件已闭环（用户确认作废、仓库已删/转私有、GitHub API 返回 []）；运行前置 Node.js ≥ 18（shutil.which fail-fast + 可读中文提示）
迁移与回滚：新增 head 082_publish_accounts（down_revision 081_oral_unit_price），只建 publish_accounts，downgrade() 只 drop 该表；已发布链冻结范围止于 055 未动，CW-056 bytes 冻结断言零回归；HEAD_SCHEMA_DIGEST 于真实 PG 16-alpine 重算为 a23fa2756885009a3faa9af9d73472c21667bbce057283cdbf3d64dd456bf071
外部授权记录：平台供应商为项目所有者自有仓库（phlong026/douyin_publisher@f61418d、phlong026/weixinshipinhao_publisher@ee4babe），无第三方授权问题；真实平台凭据授权 None（本轮不涉真实 Cookie）
未测试项：整个 server/app/publishers/（21 文件）无测试直接执行 = CODE_PRESENT（A11 monkeypatch _dispatch_probe 打桩，probe_douyin/probe_channels 与 publish_to_* 均未执行）；真实平台探测/发布链路；check:tauri（本机无 Rust 工具链，src-tauri 与 e2e 零改动）；未跑真 run-pytest-shards.sh（5 条理由见 §6.6）；deploy/customer 真实宿主机全流程
Lore 提交 SHA：已 commit（6c758c2，重编号 amend，rebase 到 ced3e82）；合并后见 PR squash SHA
```


