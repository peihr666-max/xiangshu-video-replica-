# 0822flash 评审汇总

> 客户版 V3（T01–T07）持续代码评审账本。每完成一个任务的中文 Lore 提交即在此追加评审记录；评审以当前提交的代码、证据文档与实机验证为准。
>
> 评审基线：HEAD `9f60eea`（T07 合并点）· 评审日期：2026-08-22

## 1. 评审范围与方法

- **范围**：T01–T07 共 7 个任务提交 + M0 评审修复 3 个提交（C1/H1–H4/M1–M9/LOW）。
- **方法**：
  1. 深度阅读全部核心实现（`db_pg.py`、`bootstrap.py`、`generation_worker.py`、`main.py`、`backup.py`、`sqlite_to_postgres.py`、`reconcile_customer_billing.py`、`migrations/env.py`、025 迁移）。
  2. 干净基线（HEAD）全量回归：`pytest tests` → **634 passed**。
  3. 实机复现验证关键疑点（时区规范化、journal 行为、账务不变量）。
  4. 专项 agent 交叉评审（安全 / 测试覆盖）。
  5. 证据一致性核对（blob SHA ↔ 证据文档 ↔ HEAD）。

## 2. 提交清单与状态

| 任务 | 提交 SHA | 类型 | 核心内容 | 评审状态 |
| --- | --- | --- | --- | --- |
| T01 | `7e75576` | 规格 | 冻结 V3 主规格与文件映射 | ✅ 通过 |
| T02 | `7b81df8` | 基线 | P0 全量回归基线 + 证据 | ✅ 通过 |
| T03 | `66b520e` | 测试基建 | PG16 fixture + 连接隔离 | ✅ 通过 |
| T04 | `8130321` | 文档 | SQLite 方言清单 | ✅ 通过（详见 §5.4 补强建议） |
| T05 | `c152766` | 核心代码 | PG 运行时基座（DSN/池/事务/fail-closed） | ⚠️ 通过，1 项 HIGH（API 入口缺 fail-closed，SH1） |
| T06 | `d797e6d` | 迁移 | Alembic 001→025 全链 PG 升降级 | ✅ 通过（1 项 LOW） |
| T07 | `9f60eea` | 核心代码 | SQLite→PG 导入/对账/回滚 | ⚠️ 有条件通过，1 项 HIGH（资金不变量测试缺失，TC-H1）+ 多项 MEDIUM |
| fix(P0) | `30f0d39` | 修复 | C1 追加 025 + H2 CI 内嵌 PG16 | ✅ 通过 |
| fix(P1/P2) | `0fa8516` | 修复 | H1 worker 退出 + H3 迁移 DSN + M1–M6 | ✅ 通过 |
| fix(docs) | `35e3418` | 文档 | 证据文件归位 + 台账补齐 | ✅ 通过 |
| T08 | `14e0b1f` → `e50f931`(#39 squash) | 核心代码 | PG 账务约束扩展（provider/pricing_scope 条件约束） | ✅ 通过，干净基线 636 全绿（无 HIGH/MEDIUM，2 项观察） |
| fix(t08 review) | `572649f` → 并入 `e50f931` | 修复 | 026 补齐 admin_sessions（T09 schema 落地）+ trade_no 绑定 paid + T07 PG-only 表例外 | ✅ 通过，干净基线 638 全绿，**T09R/TC08-O1 均已解决** |

> 注：2026-08-22 开发窗口将 T08 分支（含 `14e0b1f` + `e5d1b82` 评审文件 + `572649f`）squash 为 PR #39 的 `e50f931` 合并进 main。**代码内容与已评审版本逐字节一致**（已核 `admin_sessions`/`PG_ONLY_TABLES`），squash 不改变实现；旧版评审文件（T01–T07 内容）随之进入 main。当前工作区评审文件为更新版（含 T08/T08-review 评审），尚未提交。
| chore | `7e00854` | 工作流 | AGENTS.md pre-push 提交清单（防外部/评审提交混入任务分支，即本文件旧版被 squash 进 #39 的教训） | ✅ 已查看，纯文档无代码风险 |

## 3. 验证证据

### 3.1 干净基线全量回归（HEAD 9f60ea=T07 合并点；HEAD 14e0b1f=T08 合并点，均 worktree 隔离 + 真实 PG16 fixture）

```text
uv run pytest tests -q          # T01–T07 基线（9f60eea）
634 passed, 1 warning in 109s   # 1 warning = StarletteDeprecationWarning（httpx，非本项目代码）

uv run pytest tests -q          # T08 干净基线（14e0b1f，不含工作区 T09 开发代码）
636 passed, 1 warning in 103s   # 与 T08-EVIDENCE 声称一致，确认 T08 无回归

uv run pytest tests -q          # T08 review 修复（572649f，主工作区已同步提交）
638 passed, 1 warning in 102s   # 与提交声称一致；T09 的 admin_sessions + PG_ONLY_TABLES 例外落地
```

专项：
| 测试文件 | 结果 |
| --- | --- |
| `tests/test_db_pg.py`（T05） | 20 passed |
| `tests/test_sqlite_to_postgres.py`（T07，含 5 项真实 PG16 集成） | 24 passed |
| `tests/test_postgres_migrations.py`（T03/T06/T08） | 11 passed（T08 + admin_sessions + trade_no 用例全过） |

> 历史备注：`572649f` 提交前，工作区 T09 的 admin_sessions 未提交改动曾导致全量 3 个 T07 测试失败（`table contract differs extra=1`）——提交后已通过（PG_ONLY_TABLES 例外生效）。

### 3.2 实机复现验证

| 疑点 | 结论 |
| --- | --- |
| DELETE journal mode 下 `BEGIN IMMEDIATE` 是否创建 `-journal`（writer fence 是否误触 quiescent 检查） | 实测：**不创建**（仅真实写入才创建 journal）。`_writer_fence` 只 BEGIN+ROLLBACK 不写，安全 |
| 钱包余额 = `wallet_transactions` 流水累计的不变量是否成立 | `internal_billing.py`/`zpay_payments.py` 均为同一事务内 UPDATE 余额 + INSERT 流水，**不变量成立**，对账查询前提有效 |
| T07 证据文档 blob SHA ↔ HEAD | **4 个文件 SHA 全部一致** |
| M0 C1 修复（025 索引重建 + downgrade 守卫） | 升级/降级演练通过；已结算账务拒绝回滚守卫存在 |

### 3.3 CI 门禁确认

- H2：`.github/workflows/ci.yml` 已内嵌 `postgres:16-alpine` service + `TEST_POSTGRESQL_URL`，PG 测试在 CI 真实执行而非静默 skip。
- T07 证据：GitHub Actions Run #189 三门禁（Secret scan / Linux quality gate / Windows Tauri+NSIS）全绿；Linux 门禁服务端 628 项通过。

## 4. 发现总表

| # | 级别 | 任务 | 位置 | 摘要 | 状态 |
| --- | --- | --- | --- | --- | --- |
| SH1 | **HIGH** | T05/P1 | `server/app/main.py:56-65` | **API 入口缺失数据库模式 fail-closed 校验**：`_lifespan` 仅 `close_pg_pool()`，无 `resolve_database_config`/`validate_customer_production`。bootstrap 与 worker 均有校验，唯独对外服务的 FastAPI 入口没有。当前 systemd `ExecStartPre=bootstrap` 是编排层缓解，Docker/k8s/裸 uvicorn 路径可静默回退 SQLite（M0 H1 要消灭的 fail-open 场景） | **建议尽快修复**：`_lifespan` 内加进程内校验 |
| TC-H1 | **HIGH** | T07 | `reconcile_customer_billing.py` | **8/17 对账 mismatch code 无直接测试**，其中 3 个是资金完整性不变量（`wallet_missing_for_ledger_owner`、`unpaid_order_has_charge`、`charge_without_order`，已 grep 证实 0 覆盖）。若这些 SQL 有方言差异或静默返回 0 的 bug，对账会漏报真实资金漂移而测试无法发现 | **建议合并前补齐**资金不变量最小夹具测试 |
| SM1 | MEDIUM | T07 | `backup.py:282-313` | `backup_database`/`restore_database` 用固定 `.tmp` 名 + 先 unlink 再 connect，无 `O_EXCL`/随机名（快照路径却有）——symlink/TOCTOU 竞争可覆盖任意运行用户可写文件 | 复用 `_create_private_file`（`O_EXCL` + uuid） |
| SM2 | MEDIUM | T07 | `backup.py:275-314` | `backup`/`restore` 输出权限依赖进程 umask（默认 0644），快照路径有 `chmod 0600`+断言，备份路径没有——共享目录下全库（凭据/账务）可被他人读取 | 发布后显式 `os.chmod(0600)` |
| SM3 | MEDIUM | T07 | `sqlite_to_postgres.py:540,551-562` | `--postgres-url` 强制把含密码 DSN 放 argv，`ps aux`/shell history 可见 | 改用 `VIDEO_REPLICA_DATABASE_URL` env 或 stdin |
| TC-M1 | MEDIUM | T07 | `reconcile_customer_billing.py:345-358`、`sqlite_to_postgres.py:278-283` | Float/Numeric/Decimal/NaN 规范化**端到端零覆盖**：schema 有 Float 列（`estimated_cost`/`actual_cost`/`cost_amount`），但夹具从不写入非 NULL 数值——对账最难的数值类型未被验证 | 补 float/NaN/-0.0 夹具与单测 |
| TC-M2 | MEDIUM | T05 | `test_db_pg.py:184-199` | `test_pg_transaction_rolls_back_on_error` **非自包含**（已实证）：`CREATE TABLE IF NOT EXISTS` 与 INSERT 在同一回滚事务内，独立/乱序运行会 UndefinedTable，依赖前置用例建表 | 事务外预建表/TRUNCATE |
| TC-M3 | MEDIUM | T07 | `sqlite_to_postgres.py:445-452` | `_validate_snapshot`（SHA-256 证据复验 + 0600）无"篡改快照/放宽权限 → 导入拒绝"的直接测试——证据链完整性锚点未验证 | 补篡改拒绝用例 |
| TC-M4 | MEDIUM | T07 | `reconcile_customer_billing.py:902-976` | PG 侧 `asset_reference_json_invalid` 分支（`pg_input_is_valid`）无测试，现有覆盖仅 SQLite 侧 | 真实 PG 写畸形 JSON 断言 |
| TC-M5 | MEDIUM | T07 | `sqlite_to_postgres.py:272-306` | `_convert_value` fail-closed 分支（非法 boolean 抛错、UUID/date/timestamp 解析失败）仅被快乐路径间接覆盖 | 补单测 |
| SL1 | LOW | T05 | `db_pg.py:70-75,251-259` | `PgReadyInfo.dsn` 携带完整含密码 DSN，当前仅 log 未泄，但字段对外可见，未来误用即泄露 | 返回脱敏 DSN 或移除字段 |
| SL2 | LOW | T07 | `sqlite_to_postgres.py:418-427`、`reconcile_customer_billing.py:1121-1124` | 报告文件默认 0644 写入，低熵行摘要可被离线暴力还原 | 写前 `chmod 0600` |
| SL3 | LOW | T05 | `db_pg.py:159-170` | `POOL_MAX_ENV` 无上限钳制，环境污染可致连接打满 PG | 加硬上限（如 32） |
| F1 | LOW | T07 | `reconcile_customer_billing.py:364-370` | timestamp/timestamptz canonical 未做 UTC 归一化；PG 会话时区非 UTC 时对账误报 `table_hash_mismatch`（实机复现）。**当前 schema 全为 TEXT 列、无 timestamptz，无实际影响面**；但 canonical 已含 timestamp 分支，T19/SES-01 引入 PG 原生时间列（租约、epoch）前应修复 | 待 T19 前修复 |
| F2 | LOW | T05 | `db_pg.py` | 测试断言依赖 `pool._check` 私有属性（已注释标注）；psycopg_pool 私有 API 脆弱，升级需回归 | 观察 |
| F3 | LOW | T06 | `migrations/env.py:54-76` | `widen_postgres_version_table` 每次 upgrade 都执行 `ALTER TYPE`，幂等但冗余 | 观察 |
| F4 | LOW | T04 | `T04-SQLITE-INVENTORY.md` | M0 H4 补强后已覆盖 `sqlite_where` 部分索引，但清单仍可补充 025 追加式修复的登记 | 观察 |
| F5 | INFO | T07 | 全表 `created_at` 类列 | `CURRENT_TIMESTAMP` 作为 TEXT 存储时，SQLite 产 `YYYY-MM-DD HH:MM:SS`（无微秒/时区），PG 产 `...ffffff+00`；迁移原样拷贝故对账一致，但迁移后**新老数据时间文本格式漂移**，若未来按 ISO 解析/排序需统一 | 观察 |
| T09R | ~~阻断风险~~ **已解决** | T09→`572649f` | 026 `admin_sessions` + T07 `PG_ONLY_TABLES` | 上轮发现：T09 将 admin_sessions 仅 PG 建表会破坏 T07 对账契约。**`572649f` 已解决**：T07 工具新增 `PG_ONLY_TABLES` 例外（reconcile + sqlite_to_postgres 双处），空表预期、非空 fail-closed（`test_real_pg_import_rejects_non_empty_target_only_table`）；已实测提交后 T07 测试恢复通过 | ✅ 已解决 |
| TC08-O1 | INFO→**已解决** | T08→`572649f` | 026 `_PROVIDER_TRADE_NO` | 上轮发现：zpay 非 PAID 状态可携带 trade_no，可能占用全局唯一 trade_no 导致真实回调失败（squatting）。**`572649f` 已修复**：trade_no 严格绑定 paid 状态（paid⇒present，非 paid⇒absent），与 `confirm_recharge_payment` 原子 UPDATE 一致 | ✅ 已修复 |
| TC08-O3 | LOW | `572649f` | 026 `ck_admin_sessions_expires_after_created` | `expires_at > created_at` 为 TEXT 字典序比较，依赖两端格式一致：`created_at` 用 `CURRENT_TIMESTAMP`（`YYYY-MM-DD HH:MM:SS.ffffff+00` 空格分隔），若 T09 应用写入 `expires_at` 用 ISO `T` 分隔（`datetime.isoformat()`），字典序 `T`(0x54) > 空格(0x20) 可能产生假阴性。T09 实现时需统一写入格式 | T09 时注意 |
| TC08-O4 | LOW | `572649f` | reconcile + sqlite_to_postgres `PG_ONLY_TABLES` | PG-only 表例外在 `reconcile_connection_pair` 与 `_validate_schema` 双处重复实现（未来新增 PG-only 表需改两处）；`_pg_table_row_count` 用 f-string 拼表名（当前 table ∈ 常量集安全，用 `sql.Identifier` 更严谨） | 观察 |
| TC08-O2 | INFO | T08/T07 | 026 设计 | T07 导入前 SQLite 源必须 `alembic upgrade head` 到 026（revision 一致性校验强制；026 对 SQLite 为 no-op 但版本会被记录）。T07-EVIDENCE 维护窗口流程未明示此步骤，可补一句 | 文档补充 |

## 5. 分任务评审详情

### 5.1 T01 — V3 规格冻结（`7e75576`）

- 3 文件，纯文档。冻结 V3 主规格、六段迁移主题、唯一文件映射。无代码风险。
- 证据台账（`CUSTOMER-TASK-EVIDENCE-V3.md`）T01 行登记完整。

### 5.2 T02 — P0 回归基线（`7b81df8`）

- 17 文件，全部为证据日志与 SHA256 清单。提交内含服务端/客户端/Web/Tauri 全量回归日志。
- 证据层级 `LOCALLY_VERIFIED`，符合定义。

### 5.3 T03 — PG16 fixture（`66b520e`）

- `scripts/pg-fixture.sh`：本地 PG16 容器生命周期管理（start/stop/test），DSN 与 CI 一致。
- `test_postgres_migrations.py` 新增 98 行真实 PG 迁移测试；`pyproject.toml` 引入 psycopg/psycopg_pool 依赖。
- 后续 P1 修复补 CI service 后，本任务 CI 缺口关闭（H2）。

### 5.4 T04 — SQLite 方言清单（`8130321`）

- 582 行清单覆盖 32 个模块。M0 H4 指出漏掉 `sqlite_where` 部分索引类别，后经 025 修复与 `test_migration_dialect_contract.py` AST 静态契约补强。

### 5.5 T05 — PG 运行时基座（`c152766` + P1 `0fa8516`）

**核心实现 `db_pg.py` 评审：**

- ✅ `resolve_database_config`：DSN 优先、SQLite 回退、非法 scheme 拒绝；生产模式缺 URL 显式 `RuntimeError` fail-closed。
- ✅ `validate_customer_production`：生产模式拒绝 SQLite 目标 + 拒绝 `DB_PATH` 残留（歧义配置即错误）。
- ✅ `get_pg_pool`：线程安全懒加载、`check_connection` 探活、`max_lifetime=3600`/`max_idle=600`/`timeout=30`（M1）。
- ✅ `pg_transaction`：isolation 收窄为 `Literal` 白名单 + 取连接前 fail-fast（M3，杜绝 SQL 拼接注入）。
- ✅ `pg_server_now`/`check_pg_ready`：服务端时钟唯一真源；`_as_datetime` isinstance 直返（M4）。
- ✅ `close_pg_pool` 接入 FastAPI lifespan / bootstrap / worker 退出（M2）。

**fail-closed 语义核对：** bootstrap 与 generation_worker 均在触碰任何 SQLite 文件前解析模式并校验客户生产边界；worker PG 模式 `SystemExit` 非 0（H1，防 systemd 误判健康）。

**问题：**
- F2：`test_pool_applies_hygiene_parameters` 断言 `pool._check`（私有属性），依赖 psycopg_pool 内部实现。已注释标注，可接受但升级需回归。

### 5.6 T06 — 迁移全链（`d797e6d` + P0 `30f0d39`）

- `env.py`：`widen_postgres_version_table` 解决长 revision id（017 等 >32 字符）；显式 commit DDL 修复隐式事务缺陷；H3 后 `resolve_migration_url` 统一 env 优先 + psycopg 方言重写。
- 方言守卫：009 FK 依赖解绑/重挂、012/017/022 补 `postgresql_where`、014 标识符上限与 ctid 排序。
- **C1 修复**：022 `terminal_round` 部分索引在 PG 退化为全表唯一导致 RESERVE→SETTLE 冲突，追加 025 仅在 PG 重建，SQLite no-op；downgrade 对已结算账务显式拒绝（No-Go 禁删流水）。
- F3：`ALTER TYPE` 每次 upgrade 重复执行，幂等但冗余（无实际风险）。

### 5.7 T07 — SQLite→PG 导入/对账（`9f60eea`）

**`backup.py`：** 快照 0600、`O_EXCL` 私有创建、hard-link 不覆盖发布、writer fence + 前后 hash/size/mtime/data_version 三重校验、WAL/journal sidecar 与持久 journal_mode 拒绝、`PRAGMA integrity_check`。

**`sqlite_to_postgres.py`：** 事务级 advisory lock 防并发 cutover；revision 一致性校验；未 validated FK 拒绝；目标非空且不分叉才允许；按 FK 依赖拓扑分批导入；类型转换白名单；序列重置；单事务 + 全量对账通过才提交；重复执行返回 `already_reconciled`。

**`reconcile_customer_billing.py`：** 有界内存增量多重集指纹（count/sum/xor/squares）；SQLite 与 PG 双端一致 canonical 化；钱包/PAID-CHARGE/账务轮次/owner/资产引用五组 SQL 聚合不变量；DSN 脱敏 + 异常消息 allowlist + 600 字符截断（安全优先）；报告仅含计数与摘要，无业务值。

**问题：**
- F1：**timestamp 时区规范化缺陷（LOW，实机复现）**。
  - 现象：`canonical_value` 对 `timestamp`/`timestamptz` 直接 `parsed_datetime.isoformat()`，未归一化时区。SQLite 源端存 UTC（`+00:00`）；PG 读回 tz-aware 值保留**服务器会话时区**偏移。
  - 实机证据：SQLite canonical `2026-08-21T10:00:00.123456+00:00` vs PG `SET TIME ZONE 'Asia/Shanghai'` 读回 canonical `2026-08-21T18:00:00.123456+08:00` → 两端不一致。
  - 影响面：**已核全迁移链，所有时间列均为 `sa.Text()` + `CURRENT_TIMESTAMP`，无任何 timestamptz 列**，故当前对账不触发（TEXT 直接字符串比较）。但 `canonical_value` 已实现 timestamp 分支，且 T19/SES-01（租约、session epoch "使用 PG 时间"）几乎必然引入原生时间列——届时在非 UTC 时区 PG 上会误报 `table_hash_mismatch`。
  - 修复建议（T19 前）：`canonical_value` 对 `timestamp`/`timestamptz` 分支统一 `.astimezone(UTC).isoformat()`，并补"PG 会话时区非 UTC 下对账仍一致"回归测试；`_convert_value` 对无时区输入显式假定 UTC。
- F5：`CURRENT_TIMESTAMP` 作为 TEXT 的格式漂移——SQLite 产 `YYYY-MM-DD HH:MM:SS`（无微秒/时区），PG 产 `YYYY-MM-DD HH:MM:SS.ffffff+00`。迁移原样拷贝故对账一致，但迁移后新老数据文本格式不一致，若未来按 ISO 解析/排序需统一。

### 5.8 M0 修复提交（`30f0d39` / `0fa8516` / `35e3418`）

- C1（025 索引）与 H2（CI PG16）已在 §5.6/§3.3 覆盖。
- H1/H3/M1–M6/LOW-1/3 逐项代码核对全部落地（见 §5.5 与提交说明）。
- M8（证据文件归位 `docs/evidence/`）与 M9（任务清单 header 纠偏）在 `35e3418` 完成。

### 5.9 T08 — PG 账务约束扩展（`14e0b1f`）

**026 迁移（PG-only，025 先例）评审：**

- 替换 022 的 4 个约束（provider / pricing_scope / amount_minimum / amount_step），新增 provider_scope 配对、provider_status、provider_trade_no、customer_price_floor 共 4 个条件约束。
- **保留的 022 不变量核对无误**：`status IN ('PENDING','PAID','CLOSED','FAILED')` 四态、`amount % charged = 0`、`credits * charged = amount`、price snapshots > 0、trade_no 非空白、全部部分唯一索引。026 只收窄/条件化 zpay 专属约束，activation_code/admin_adjustment 仍需满足账务一致性（`credit_calculation` 等）——测试基线数据（credits=10, charged=1000, amount=10000）逐条满足。
- **downgrade 守卫**：存在 `provider != 'zpay' OR pricing_scope != 'INTERNAL'` 行时显式拒绝降级（与 025 的 No-Go 禁删流水一致）；空账本对称恢复 022 约束。
- **跨任务兼容（T07 ↔ T08）已实测**：SQLite 跑 026 为 no-op，但 alembic_version 记录为 026；schema 保持 022 形状（仍含 `provider='zpay'` 约束）。故 T07 导入对账的 revision 一致性（SQLite=PG=026）与行指纹均保持。前提是 SQLite 源 upgrade 到 head（见 TC08-O2）。

**验证证据：** 4 合法形状 + 12 非法形状（PG `CheckViolation`）+ downgrade 守卫测试；`test_pg_billing_provider_shapes_accepted_and_rejected` 单独复跑幂等通过；干净基线全量 **636 passed**（与 T08-EVIDENCE 一致，确认无回归）。之前工作区复现的顺序不稳定已随 T08 提交消失（根因是 T08 未提交时的中间状态）。

**发现：** 无 HIGH/MEDIUM。观察项 TC08-O1/O2（见 §4）。证据文档 `T08-EVIDENCE.md` 约束模型表与实现一致，证据层级 `AUTOMATED_VERIFIED` 合理。

### 5.10 T08 review 修复（`572649f`）— 026 补齐 + trade_no 绑定 + T07 PG-only 例外

回应上轮评审 T09R / TC08-O1 的修复提交：

1. **T09R 解决**：`admin_sessions` 数据层落地 026（PG-only），T07 工具新增 `PG_ONLY_TABLES` 概念——空表在 target head 上预期，非空即分歧状态 fail-closed。`reconcile_connection_pair` 与 `_validate_schema` 双处实现，语义一致（空表不进对账 digest，非空拒绝）。已实测：提交后之前失败的 3 个 T07 测试恢复通过。
2. **TC08-O1 解决**：`_PROVIDER_TRADE_NO` 收紧为「paid⇒必有 trade_no，非 paid⇒必无」——消除非 PAID 行占用全局唯一 trade_no 的 squatting 风险，与 `confirm_recharge_payment` 原子 UPDATE 匹配。
3. **admin_sessions 表设计评审**：digest-only（session_digest/csrf_digest/ip/ua digest，明文 secret 不进库）、`actor_user_id` FK→users（真实 actor 可追溯）、`session_digest` 全局 UNIQUE、过期/撤销字段、`idx_admin_sessions_actor_status` 审计索引、downgrade 对称删除。符合 dev doc §11.2/§15。
4. **测试**：`test_pg_admin_sessions_schema_and_invariants`（unique/expiry/FK/索引）、trade_no squatting 拒绝、非空 target-only 表拒绝。

**验证：** 受影响 35 passed；全量 **638 passed**（与提交声称一致）。**无回归，无 HIGH/MEDIUM**。

**发现：** TC08-O3/O4（见 §4，LOW 观察）。T09 实现时需注意 admin_sessions 时间列 TEXT 比较的格式一致性（TC08-O3）。

## 6. 专项评审补充

### 6.1 安全专项（security-reviewer，25s 全文件扫描）

**总体风险：MEDIUM**（无 CRITICAL）。已核对无发现：SQL 注入面全安全（PG `psycopg.sql.Identifier`/参数化、SQLite 双引号转义、isolation 白名单）；DSN 脱敏与异常 allowlist 到位；无硬编码 secret；并发锁设计正确。

**HIGH #1（已复核属实）**：API 入口 fail-closed 缺口（见 §4 SH1）。
**MEDIUM #2-4**：backup/restore symlink 竞争、备份输出权限、CLI DSN 暴露（见 §4 SM1-3）。
**LOW #5-7**：`PgReadyInfo.dsn` 含密码字段、报告文件 0644、连接池无上限（见 §4 SL1-3）。
**环境提示**：本机 `pip-audit` 报 aiohttp 3.13.5 漏洞为未锁定本机环境传递依赖（非本项目依赖），建议本机升级 aiohttp ≥3.14.x。

### 6.2 测试覆盖专项（code-reviewer，51 项真实执行含 PG-only）

**覆盖亮点（已肯定）**：生产 fail-closed 三态矩阵、快照 TOCTOU 防线（fence/并发/篡改终检/WAL 头）、事务 commit/rollback/SERIALIZABLE 冲突、advisory lock 冲突、真实 PG 全链迁移 + C1 行级回归、导入幂等/回滚/分叉拒绝、隐私面（DSN 脱敏、`safe_error_message`）均有测试。

**HIGH：8/17 对账 mismatch code 无测试**（见 §4 TC-H1），含 3 个资金不变量。
**MEDIUM #1-5**（见 §4 TC-M1~TC-M5）：Float/Numeric 零覆盖、回滚用例非自包含、`_validate_snapshot` 篡改拒绝、PG 侧畸形 JSON、`_convert_value` fail-closed。
**LOW 盲区**：`import_sqlite_to_postgres` 组合层无端到端、`_write_report` 无测试、`require_validated_postgres_foreign_keys` 无真实 `NOT VALID` 场景、`_reset_sequences` 为死代码（schema 无 identity/serial 列）、`_pool_bounds` 非法 env 无测试、`test_production_*` 依赖宿主 env 干净。

### 6.3 综合结论与优先级

| 优先级 | 处理项 | 建议窗口 |
| --- | --- | --- |
| P0 | SH1：`main.py` `_lifespan` 加进程内 fail-closed 校验 | 任何客户生产部署前 |
| P0 | TC-H1：补齐 3 个资金不变量 + 5 个 schema/行级 mismatch 的最小夹具测试 | T07 收尾/下一轮评审前 |
| P1 | SM1/SM2：backup/restore 权限与 symlink（复用 `_create_private_file`） | 客户生产迁移演练前 |
| P1 | TC-M1：Float/Numeric/NaN 端到端或单测 | 客户生产迁移演练前 |
| P1 | SM3：CLI DSN 改环境变量 | 迁移演练前 |
| P2 | TC-M2~M5、SL1~3、F1（T19 前）、F2~F5、TC08-O1~O4 | 随迭代排期 |

> 评审结论：T01–T08（含 review 修复）实现质量与既有测试整体扎实（干净基线 638 全绿、证据一致），上轮 **T09R/TC08-O1 两项已由 `572649f` 解决**。剩余 **SH1 与 TC-H1 两项 HIGH 建议在客户生产联调前处理**，其余为 MEDIUM/LOW 迭代项。

## 7. 后续监控与追加机制

- **自动监控**：已建立持久化 cron 任务（ID `f7da335b`，cron `13,43 * * * *`，每 30 分钟），检查 git 是否出现晚于评审基线的新中文 Lore 提交，发现即深度评审并追加到本文件；无新提交则不动。任务 7 天后自动过期，需续期时重新创建；取消可用 CronDelete。
- **评审基线（状态真源）**：§2 提交清单最后一行 = 已评审到的最新 SHA。当前基线 `7e00854`（HEAD；任务代码基线为 `e50f931` = T08 PR #39 squash，代码内容与已评审的 `14e0b1f`+`572649f` 一致）。
- **T08 已提交**（`14e0b1f` + review 修复 `572649f`）：评审见 §5.9/§5.10，干净基线 638 全绿。上轮 T09R（admin_sessions 破坏 T07 对账）已由 PG_ONLY_TABLES 例外解决；TC08-O1（trade_no squatting）已由约束收紧解决。
- **开发窗口进行中：T09（DB-08，per-operator admin session）应用层**。`admin_sessions` 数据层已随 `572649f` 落地 026（PG-only）；T09 剩余工作为 session/CSRF/RBAC/fail-closed 应用层。工作区当前仅剩评审文件修改（未提交）。
- 每个新任务的中文 Lore 提交合并后，对照 §2 提交清单追加一行，并在 §4 追加该任务的发现，评审详情按 §5 样式新增小节。
