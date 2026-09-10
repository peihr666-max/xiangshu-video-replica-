# CW-056 — 补齐空PG及受支持旧PG升级矩阵

> 目标证据层级：`AUTOMATED_VERIFIED`。本文件登记 CW-056 的改动前缺口盘点、
> supported_release_head→final_head 矩阵、已发布 revision 哈希冻结、schema 目录跨起点
> 等价、代表数据事实、identity/serial/ledger 下一写、失败状态可判定、offline `--sql`
> 与客户生产迁移目标门禁、缺 PG 硬门复验，以及 RED→GREEN 逐用例轨迹。
> 生产实际停写/升级执行归 CW-051，SQLite→PG 只读导入工具归 CW-034—039/CW-060，
> 均按规格明列剔除，不在本任务范围（见 §12）。

## 1. 任务信息（§14 模板）

| 字段 | 值 |
| --- | --- |
| 任务/工作包 | CW-056（W4）补齐空PG及受支持旧PG升级矩阵；DoD：建立 supported_release_head→final_head 表、所有登记起点各跑**独立**真实 PG 数据副本、漏项=0/skip=0、每个起点核对 schema 对象/关键事实/约束/下一写、失败后 alembic_version 与结构状态必须可判定、offline `--sql` 明确不作为交付升级脚本 |
| Owner / Reviewer | Owner：Qoder 代理（2026-09-10）；Reviewer：待 PR 独立 CodeReview |
| 分支 / 基线 SHA | `feat/customer-v3-cw056-pg-upgrade-matrix`；基线 `origin/main@d8f3352`（CW-016 #6 合并后） |
| 上游规格段落 | 收敛详细任务清单 §CW-056（line 588–601）；V3 清单 §18 CW-056 行（line 496）；PG-04 schema 与迁移（`docs/PostgreSQL唯一数据库实施与验收规范.md`）；CW-003 §1 受支持版本表；CW-053 §3 E1「字节不改」与 §7 L241 升级矩阵债务；CW-007 TEST-PG 硬门 |
| 改动文件 | 5 文件（+1291/−26）：新增 `server/tests/test_cw056_supported_head_matrix.py`（+1150，13 用例）、`server/migrations/env.py`（+83/−19）、`deploy/postgres/migrate.sh`（+17/−1）、`server/tests/test_postgres_migrations.py`（+35/−6）、`server/tests/pg_test_kit.py`（+6/−0，纯增量 allowlist）；另新增本证据文件。**零迁移版本文件改动**（`git diff --name-only` 与 `migrations/versions` 交集为空，PG-09 遵守） |
| 失败测试或回归锁定 | 新增 13 用例（A 组 7 项静态/CLI **刻意不挂 PG 门** + B 组 5 项 + C 组 1 项挂 CW-007 硬门）。RED 阶段 A 组 **3 failed / 4 passed**（3 项真实实现缺口），全文件首轮 **8 failed / 5 passed**，其中 **5 项为测试自身写法缺陷**（已逐项修正并登记于 §11.3），修正后收敛为 **3 failed / 10 passed**；GREEN 阶段 **37 passed**（13 新增 + 24 既有 `test_postgres_migrations`）零回归 |
| 实现结果 | §2 交付明细；§3 缺口盘点；§4 矩阵；§5 单 head 与哈希冻结；§6 schema 目录与代表数据；§7 下一写；§8 失败状态；§9 两道 env/migrate.sh 门禁 |
| 验证命令与通过数 | 见 §10、§11。ruff check / ruff format --check / mypy --strict（`server/app`，104 文件）全过；专项 37 passed；缺 PG 硬门 7 passed / 30 errors / **0 skipped**；服务端全量 pytest 见 §11.2 |
| 证据层级 | **AUTOMATED_VERIFIED**（真实 PostgreSQL 16.15 上取得矩阵升级、schema 目录等价、下一写与失败态证据，无 staging/真实链路依赖）。不提升 `STAGING_VERIFIED`：生产停写与升级执行归 CW-051 且需人工授权 |
| 安全与可观测性 | 无真实 API key/激活码/设备或 session token 进入代码、日志、测试夹具或 PR。矩阵播种数据全为合成值；`SEED_JSON` 只含业务词面（`乡墅复刻`/`众墅之家`）不含任何凭据。offline 与客户生产拒绝消息只回显**已解析的迁移目标 URL**，该 URL 来自运维自己导出的环境变量，且拒绝发生在任何连接建立之前 |
| 迁移与回滚 | **零迁移版本文件改动**（未新增 revision，未编辑任何已发布 `upgrade()`/`downgrade()` 函数体，并以内容级 sha256 把这一点机器化锁死——见 §5）。改动为纯增量门禁：offline 拒绝、客户生产非 PG 目标拒绝、migrate.sh 升级后 head 读回校验。回滚 = revert 本分支 |
| 外部授权记录 | 无（不涉及真实 ZPay / 付费 Provider / 生产 COS 变更 / 对外发码 / 灰度扩大 / 公网发布） |
| 未测试项 | `cargo test`、`npm audit`、客户浏览器 E2E、`npm run build`、前端 biome/vitest —— 均**只在 CI 门禁执行**；本任务前端与 Rust 侧零触碰。`deploy/postgres/migrate.sh` 未在真实 Linux 部署主机上端到端执行（无该环境），其正确性由 §9.3 的静态用例 + `alembic heads`/`current` 输出格式的源码级与实测级双重核验支撑 |
| Lore 提交 SHA | 本 PR squash 后回填 |

## 2. 交付明细（对照 CW-056「仅做剩余」四项）

| 规格「仅做剩余」原文 | 本任务交付 | 证据 |
| --- | --- | --- |
| 尚未冻结「所有已发且受支持 PG head」矩阵；当前仅覆盖若干起点，不能代表全部客户版本 | 以 CW-003 §1 表为唯一来源冻结 `SUPPORTED_RELEASE_HEADS`（4 个受支持版本 → 3 个 distinct head），矩阵起点 = distinct head ∪ {空库}；**漏项=0 由结构性断言保证**而非人工核对 | §4 |
| 迁移集成文件缺 PG 时整体 skip；必须改为必需门禁 | 该缺口已由 CW-007（PR#103 `df7020c`）的模块级 autouse `require_pg_or_explicit_skip` 关闭；本任务**为新迁移测试文件复验**该保证，并纠正 `test_postgres_migrations.py` 顶部仍宣称「自动 skip」的过期 docstring（与 CW-007 硬门直接矛盾，属文档级缺陷） | §10 |
| Alembic env 仍支持默认/SQLite 与 offline SQL；当前 offline 输出不能当可执行升级证据 | env.py 两道 fail-closed 门禁：offline 模式**无条件**拒绝（在 `context.configure` 之前 raise，零 SQL 泄出）；客户生产下非 PostgreSQL 迁移目标拒绝（`VIDEO_REPLICA_CUSTOMER_PRODUCTION` 为真时生效）。migrate.sh 去掉 `exec` 并增加升级后 head 读回比对 | §9 |
| 每个支持 head 需代表数据、完整约束/trigger/JSON/时间语义、identity/serial/ledger 下一写不碰撞和失败状态证据 | B 组每个起点跑**独立数据副本**：五类代表数据事实快照跨升级逐项相等、schema 完整目录摘要跨起点相等、JSON 字节级字面量与 timestamptz 非 UTC 偏移归一、identity/serial/ledger 下一写、039 非空审计降级拒绝；C 组失败态可判定 | §6、§7、§8 |

「增量验收」三项逐条对应：矩阵表 + 独立副本 + 漏项=0/skip=0 → §4、§10；每起点核对 schema/事实/约束/下一写 → §6、§7；失败后状态可判定 → §8。

## 3. 改动前缺口盘点（事实，非推断）

RED 阶段的 stderr 原文即改动前状态的直接证据，三类缺口定性不同：

| # | 缺口 | 改动前实测事实 | 定性 |
| --- | --- | --- | --- |
| 1 | offline `--sql` 不可作为交付升级脚本，但运行时**并未主动拒绝** | `alembic upgrade head --sql` 已输出 `INFO [alembic.runtime.migration] Generating static SQL` 并吐出部分脚本，之后才**偶然**崩在 `migrations/versions/009_idempotency_project_scope.py:81 → _rebuild → conn.exec_driver_sql(create_sql)`，报 `AttributeError: 'MockConnection' object has no attribute 'exec_driver_sql'` | **实现缺口**。偶然崩溃不是守卫：一旦 009 被修好，offline 会静默产出一份不可执行的脚本，而 DBA 可能拿它当升级证据跑。`alembic.ini:9-10` 早已声明「not supported for this chain」，M0 评审 M7 当时选择「文档说明」路线——**文档声明不等于强制执行** |
| 2 | 客户生产可把迁移跑到 SQLite 上 | 未设 `VIDEO_REPLICA_DATABASE_URL` 且 `VIDEO_REPLICA_CUSTOMER_PRODUCTION=true` 时，env.py 静默回落到 `alembic.ini:11` 的 `sqlalchemy.url = sqlite:///data/app.db`，实测崩在 alembic 自身的 batch 反射消息（`batch mode with dialect sqlite requires a live database connection ... to reflect the table "generation_tasks"`），**不是**一条指明客户生产边界的诊断 | **实现缺口**。失败是偶然的（依赖 batch 反射），且消息完全不提示「你在客户生产把迁移跑到了 SQLite」 |
| 3 | migrate.sh 升级后不校验结果 | 脚本正文为 `exec flock -n "$LOCK_FILE" .venv/bin/alembic upgrade head`，其后无任何读回；`exec` 替换进程，即使写了校验也不会执行 | **实现缺口**。`alembic upgrade head` 在库已处 head 时静默 no-op 并返回 0，运维据此认为「升级完成」，而实际部署的可能是旧代码配旧 schema |
| 4 | 受支持 head 矩阵未冻结 | 既有覆盖为「空 PG upgrade→downgrade→re-upgrade」、「040 head→当前 head」、「054 带钱包/生成代表数据升级」三处散点，起点集合未按 CW-003 §1 表穷举，也无漏项=0 的结构性断言 | **取证缺口 + 覆盖漏项**。行为本身正确（见 §6/§7/§8 的回归锁在实现前即通过），缺的是矩阵完整性与跨起点等价的自动化证明 |
| 5 | `test_postgres_migrations.py` 两处 smoke 用例硬编码 CI 夹具身份 | `test_user_identity` 断言角色名为写死的 `testuser`，在任何其他合法基座（如开发者自己的 postgres:16 容器、不同端口与角色）上必然失败，即使夹具完全健康 | **测试可移植性缺陷**。该缺陷已由 CW-055 §8.1.3 line 178 登记并明示「CW-056 迁移矩阵范围内可一并收口」，本任务按建议修法收口（见 §13） |

## 4. supported_release_head → final_head 矩阵（必交证据①）

来源：CW-003 §1 受支持版本表（git 证据可追溯部分）。head **不按文件名数字排序**推断，而是对每个发布 SHA 的 `migrations/versions/` 目录用 git 重算得出——历史上出现过 032 重新指向 029 的分支改写（M5 评审 P1-3），文件名序会骗人。

| 受支持版本 | 发布提交 | 该版本当时的 head revision | 矩阵起点 | 目标 | 结果 |
| --- | --- | --- | --- | --- | --- |
| 0.1.12 | `d9a5576` | `053_activation_code_archive` | ✓ | `081_oral_unit_price` | PASS |
| 0.1.13 | `bc0248e` | `054_admin_free_grant_adjustments` | ✓ | `081_oral_unit_price` | PASS |
| 0.1.15 | `80a8e40` | `054_admin_free_grant_adjustments` | 与 0.1.13 同 head，起点集去重 | `081_oral_unit_price` | PASS（同一起点） |
| 0.1.16 | `59e10ed` | `055_customer_batch_visibility` | ✓ | `081_oral_unit_price` | PASS |
| —（全新安装） | — | 空库 | ✓ | `081_oral_unit_price` | PASS |

**漏项=0 的结构性保证**：`test_supported_release_head_matrix_is_frozen_and_complete` 断言三件事——(1) `MATRIX_STARTING_HEADS` 恰好等于 `SUPPORTED_RELEASE_HEADS` 的 distinct head 值集 ∪ `{""}`，故「往受支持版本表加一个版本却忘了加起点」会直接失败，漏项不可能靠人工核对遗漏；(2) 起点无重复，否则同一 head 会被静默重复计数、矩阵看起来更满而实际覆盖没变；(3) 每个登记起点都必须是 `081_oral_unit_price` 的**祖先**（`_is_ancestor` 沿 `down_revision` 回溯，tuple 形态递归全分支），否则「起点→head」这个矩阵项本身无意义。

**每个起点跑独立真实 PG 数据副本**：`matrix_database` fixture 为每个参数化用例单独 create/drop `cw056_head_matrix_test`，进出各清理一次，绝不跨用例复用；C 组失败态用**不同名**的 `cw056_failstate_test`（`failstate_database` fixture），把「故意留在 upgrade 失败态的库」的爆炸半径钉在失败态本身，避免污染下一轮矩阵起点。两个库名均已登记进 `pg_test_kit.RECORDED_TEST_DATABASES` allowlist（该 allowlist 是 create/drop helper 的准入名单，未登记名一律拒绝）。

## 5. 单 head 与已发布 revision 哈希冻结（必交证据②）

| 不变量 | 冻结值 | 断言方式 |
| --- | --- | --- |
| 迁移链单 head | `081_oral_unit_price` | `test_migration_chain_has_single_linear_head` 断言 `ScriptDirectory.get_heads() == [HEAD_REVISION]`——恰一个且就是它，不是「至少一个」 |
| branch points | 无 | 同用例遍历 `walk_revisions()`，断言不存在任何 `down_revision` 为 tuple 的 revision——完全线性链，无分叉无合并点 |
| base revision | 恰 1 个 | 同用例断言 `down_revision is None` 的 revision 恰好一个。多 base 会让「已发布链」不再唯一，冻结哈希随之失去意义 |
| 已发布链终点 | `055_customer_batch_visibility` | 其后 056–081 尚未随任何受支持版本发布 |
| 已发布链长度 | **54**（冻结） | `test_published_migration_chain_bytes_are_frozen` 断言 `len(chain) == PUBLISHED_CHAIN_LENGTH`，并核对 `chain[0]` 的 down_revision 为 None（起于单一 base）、`chain[-1][0] == PUBLISHED_HEAD_REVISION` |
| 链总长 | 79（**刻意不冻结**） | 磁盘上 `migrations/versions/*.py` 实测 79 个文件。刻意不作为断言冻结：每次追加修复迁移都必然改变它，冻结会让「只追加」这一被允许的操作反过来要求改常量。冻结边界只划在**已发布**部分（止于 055） |
| 已发布链**内容级** sha256 | `1154d46f2b136845004b16de388eb1bc10c25d9dce996ebea8367366b720587e` | revision id + 父子关系 + **迁移文件字节** 一并纳入 |
| 已发布链**关系级** sha256 | `4f27304401324fe1f453bb19e96fe178b4bb9e850501ff1cdefe45105e1f5f1a` | 仅 revision id + 父子关系，与内容级并列断言 |

两个哈希并列的理由：只冻结关系抓不到「有人编辑了已发布迁移的 `upgrade()`/`downgrade()` 函数体」，而那正是「只追加修复迁移」（PG-09）要禁止的；只冻结内容则在失配时无法区分「改了文件体」与「改了链拓扑」。两条断言的报错因此可直接指向根因。

**冻结范围止于 055 是刻意的**：把未发布的 056–081 也纳入哈希，会让每次新增迁移都必须改常量——那不是「冻结已发布历史」而是「冻结开发中」，会立刻退化成橡皮图章。

行尾口径：`.gitattributes` 的 `* text=auto eol=lf` 保证 `.py` 在工作区跨平台同为 LF，故直接 `read_bytes()` 无需行尾规范化（该文件记载过 CRLF-only 重写 `bd73072` 的教训）。本次 GREEN 实测通过即证明磁盘字节与冻结值一致，CI Linux 同构。

## 6. schema 目录跨起点等价与代表数据事实（必交证据③）

### 6.1 两级结构等价断言

空库起点与三个旧 head 起点升级到 `081` 后，**完整 schema 目录摘要逐项相等**——全新安装路径与升级路径收敛到同一结构。摘要由 `information_schema` + `pg_catalog` 的完整对象清单（tables / functions / sequences 三类）计算 sha256 得出：

```
HEAD_SCHEMA_DIGEST = 9a8ac71b4dd8f183b85012da0ec7206bc8e6b54e6bc47927aceb001b77696211
inventory 形状：tables=76 / functions=11 / sequences=3
```

摘要之外并列一组**冻结计数**，使漂移时的报错能直接指出是哪一类对象变了：

| 口径 | 值 | 口径说明 |
| --- | --- | --- |
| tables | 76 | 与 `HEAD_TABLE_NAMES`（76 项表名全集）互为两级断言 |
| columns | 894 | |
| identity_columns | **0** | 本链不使用 SQL 标准 identity，序列语义全靠 serial/trigger |
| sequences | 3 | |
| jsonb_columns | **0** | JSON 全存 TEXT，故 §6.2 比对**字节级字面量** |
| timestamptz_columns | 16 | |
| triggers | 18 | `information_schema.triggers` 的**行数**（BEFORE UPDATE 与 BEFORE DELETE 各算一行），故 18 行对应 10 个 distinct trigger |
| partial_indexes | 25 | |
| unique_constraints | 27 | |
| check_constraints | 221 | |
| foreign_keys | 145 | |
| primary_keys | 76 | |

为什么计数不够、必须再加表名全集：计数只能证明「数量没漂」，证明不了「同一批表」——掉一张旧表再建一张新表，`tables` 仍是 76。表名集合失配时的报错可直接列出 missing/unexpected。

### 6.2 五类代表数据事实跨升级一致

`owner` / 钱包 / 订单 / session / 任务五类共 12 张表，按 `FACT_COLUMNS` 的**固定列投影**取快照，升级前后逐项相等。

刻意不用 `SELECT *`：迁移会**追加**列，星号投影的形状升级前后必然不同，那是假红而非事实丢失。只取已实测证明在 053/054/055 三起点均存在的列。

覆盖表：`users`、`projects`、`generation_batches`、`generation_tasks`、`wallets`、`wallet_transactions`、`recharge_orders`、`activation_code_batches`、`activation_codes`、`customer_devices`、`customer_session_state`、`customer_session_events`。

播种数据满足真实约束而非绕过它：`wallet_transactions` 必须符合 `ck_wallet_transactions_shape`（RESERVE 要求 `available_delta=-1, reserved_delta=1, task_id NOT NULL, billing_round NOT NULL, recharge_order_id NULL`；CHARGE 要求 `available_delta>0, reserved_delta=0, recharge_order_id NOT NULL, task_id NULL, billing_round NULL`）。

### 6.3 JSON 与时间语义

- **JSON**：head 上 `jsonb_columns = 0`，JSON 全存 TEXT，故比对**字节级字面量**。`SEED_JSON = '{"prompt":"乡墅复刻","nested":{"n":1,"arr":[1,2,3]},"owner":"众墅之家"}'` 含嵌套对象与数组，升级后必须逐字节相同（键序、空白、Unicode 均不得被改写）。
- **时间**：刻意播**非 UTC 偏移** `SEED_TS = '2026-09-05 08:30:00+08'`，验证 timestamptz 归一到 UTC 后仍指同一时刻（`SEED_TS_UTC = '2026-09-05 00:30:00+00'`）。这锁的是「同一瞬间」语义，不是「同一字面量」。

## 7. identity / serial / ledger 下一写不碰撞（必交证据④）

| 项 | head 事实 | 验证 |
| --- | --- | --- |
| identity 列 | `identity_columns = 0` | 本链不用 SQL 标准 identity，故「下一写」风险全落在 serial 与 trigger 上 |
| serial 序列起点 | `pg_sequences.start_value` 来自 `pg_sequence.seqstart`，是**声明值而非易变值** | 只有 `last_value`（来自 `pg_sequence_last_value()`）易变；断言取 `start_value` 故可冻结、可重复跑 |
| `wallet_transactions.ledger_sequence` | 由 **063** 创建；053/054/055 三起点均**不存在该列** | 升级前用 `information_schema.columns` 断言该列不存在（这是「升级后 NULL 可归因」的前提），升级后：既有行保持 NULL（063 **刻意不回填**）、首次写入取 1、显式赋值被 trigger 以 `database assigned` 拒绝 |
| 单例行表 serial 碰撞 | `runtime_settings` / `viral_runtime_controls` 连写会走 serial | 按 **app 真实写入形态**验证：app 全部显式赋 `id=1`，故不存在 `DEFAULT VALUES` 路径下的碰撞。连写用两个 actor（`cw056-admin` / `cw056-admin-2`）使第二次写入走 UPDATE 分支 |

`ledger_sequence` 的三起点断言写法本身是一条被修正的缺陷：初版在**升级前**直接 `SELECT ledger_sequence`，而该列由 063 创建、三个起点都早于它，必然抛 `UndefinedColumn`（详见 §11.3）。修正后改为断言「列不存在」，语义更强：它正是升级后既有行 NULL 的归因依据。

## 8. 失败状态可判定（必交证据⑤）

C 组在 `055` 起点注入 `CREATE TABLE` 冲突后执行 upgrade，断言失败态**完全可判定**：

| 断言 | 实测结果 | 依据 |
| --- | --- | --- |
| `alembic_version` 行数 | **恰好 1 行** | 无多 head 残留 |
| 指针位置 | 停在 **`053_activation_code_archive`** | 054 已执行成功也一并回滚——PostgreSQL 事务 DDL + alembic 在 PG 上默认整条链单事务 |
| 056 及之后创建的表 | **零半建**（`to_regclass` 全部为 NULL） | 取 `operation_cost_rates`(056) / `daily_external_prices`(058) / `oral_tasks`(065) / `studio_drafts`(067) |
| 冲突表自身 | 列仍为 `["cw056_bogus"]`，未被半途改写 | |
| 起点已有数据 | 用户行不丢 | |

**防空转元断言**：初版选错了表名（详见 §11.3），其中一处断言因表名在 head 上根本不存在而**无条件通过**——`to_regclass` 对拼错的名字同样返回 NULL。修正后每张受检表都先断言 `late_table in HEAD_TABLE_NAMES`，表名拼错时元断言先失败，「半建检查」不可能再空转。

## 9. offline `--sql` 与客户生产迁移目标门禁

### 9.1 offline 无条件拒绝（`run_migrations_offline`）

改为在 `context.configure` **之前**直接 raise，故**零 SQL 泄出**（改动前会先吐出部分脚本再偶然崩溃，见 §3 缺口 1）。两条独立理由写进拒绝消息本身，运维无需翻文档：

1. Alembic 硬编码 offline `alembic_version.version_num` 为 `VARCHAR(32)`（M0 评审 M7），而本项目 revision id 达 33+ 字符，stamped 版本行插不进去；
2. offline 给迁移的是 `MockConnection`，009 的 `exec_driver_sql` 与所有无 `copy_from` 的 `batch_alter_table` 都会抛错，导致脚本必然是半份。

**为什么无条件、不区分 lane**：仓库内 offline 模式**零消费方**——`sql=True` 在 `server/` 全树零出现（穷尽 grep），`--sql` 只出现在本任务新增的测试与 `alembic.ini:9-10` 的既有声明里；且第 2 条理由（009 的 `exec_driver_sql`）与方言无关，SQLite lane 同样崩。既然无人消费且两条 lane 都产不出可执行脚本，保留一个「内部可用」的假象只会让 DBA 误取。

### 9.2 客户生产拒绝非 PostgreSQL 迁移目标（`resolve_migration_url`）

新增 `_reject_non_postgres_migration_target()`，仅在 `VIDEO_REPLICA_CUSTOMER_PRODUCTION` 为真（truthy 集合 `{1,true,yes,on}`，与 `app.db_pg` 及其他 customer-fenced 模块同一约定）且解析出的目标不是 PostgreSQL 时 raise。

**校验点刻意放在 `_to_psycopg_url` 转换之前的 raw URL 上**：否则 `postgresql+psycopg://` 前缀不匹配 `postgresql://`，已带驱动限定的合法 DSN 会被误拒。`_is_postgres_url()` 同时接受 `postgresql://`、`postgres://` 与 `postgresql+` 前缀，覆盖运维可能合法导出的每一种写法。

**为什么刻意不做全局拒绝**：`app/db.py:alembic_config` 显式把 `sqlalchemy.url` 设为 SQLite，`initialize_database` 经它进入 alembic，被 10 个 app 模块与 30+ 测试消费。该 internal/desktop lane 在 CW-043 允许 CW-042 退役兼容层之前**仍受支持**（CW-053 §3 E2）。全局拒绝会立刻打断该 lane 与那 30+ 测试。`test_internal_lane_sqlite_migration_target_still_works` 作为**防误伤回归锁**存在：它走 online 模式（不是 `--sql`，因为 offline 对 SQLite 同样崩在 009，用它当回归锁会假红）跑通 SQLite lane 到 `081`，并读回 `alembic_version` 核对。

### 9.3 两道门禁的优先级

`run_migrations_offline()` **先**调用 `resolve_migration_url()` 再 raise offline 拒绝。理由：客户生产下「你把迁移目标指到了 SQLite」是更可操作的诊断，不能被通用的 offline 拒绝遮蔽。`test_customer_production_rejects_sqlite_migration_target` 刻意同时触发两个条件（`--sql` + 不设 DSN + `customer_production=true`），把这条优先级钉死。

### 9.4 migrate.sh 升级后 head 读回校验

去掉 `exec`（`exec` 替换进程，其后任何校验都不执行），升级后比对：

```bash
EXPECTED_HEAD="$(.venv/bin/alembic heads | awk 'NR == 1 {print $1}')"
ACTUAL_HEAD="$(.venv/bin/alembic current | awk 'NR == 1 {print $1}')"
if [ -z "$EXPECTED_HEAD" ] || [ "$ACTUAL_HEAD" != "$EXPECTED_HEAD" ]; then
    echo "migration did not reach the expected head: current='${ACTUAL_HEAD}' expected head='${EXPECTED_HEAD}'" >&2
    exit 70
fi
```

`awk '{print $1}'` 的提取正确性经**源码级 + 实测级**双重核验：

- 源码级：`alembic/command.py:current()` 逐 revision 打印 `rev.cmd_format(verbose)`；`script/base.py:_head_only()` 在 revision id 之后才追加 `" (head)"` / `" (effective head)"` / `" (current)"` / `" (branchpoint)"` / `" (mergepoint)"`。revision id 本身不含空白，故 `$1` 恒为纯 id。
- 实测级：`alembic heads` → `081_oral_unit_price (head)`；`alembic current` 在**未迁移**库上 → stdout 为空（`ACTUAL_HEAD=""` ≠ 期望 → exit 70，守卫方向正确）；已迁移至 head 时为 `081_oral_unit_price (head) (current)`，停在旧 revision 时为 `<旧 id> (current)`——三种形态 `$1` 均正确。
- 版本锁：`server/pyproject.toml` 精确钉 `alembic==1.17.2`，输出格式不受上游漂移影响。

`NR == 1` 只取第一行的前提是**单 head**，该前提由 §5 的 `test_migration_chain_has_single_linear_head`（heads 恰一行 + branch points 为空）独立锁死；一旦将来出现分叉，那条用例会先失败，不会让本脚本静默取错。

保留既有 fail-closed 前置不动：`VIDEO_REPLICA_DATABASE_URL:?` / `VIDEO_REPLICA_CUSTOMER_PRODUCTION:?`、truthy `case` 校验（exit 64）、`validate_customer_production`、`flock`。head 校验是只读的，故在锁释放后执行安全。

alembic 1.17.1+ 另提供 `alembic current --check-heads`（不符时抛 `DatabaseNotAtHead`）作为格式无关的替代守卫；本任务**刻意未采用**，因为显式比对能给出同时指名 actual 与 expected 的运维可读消息，而 `--check-heads` 的失败输出不含这两个值，凌晨排障时信息量更低。

## 10. 缺 PG 不得 skip（硬门复验）

规格 CW-056 明列「迁移集成文件缺 PG 时整体 skip；必须改为必需门禁」，完工标准要求 **0 skip**。该门禁已由 CW-007 的 `require_pg_or_explicit_skip`（`pytest.fail` 而非 skip）落地，但 CW-056 新增了迁移测试文件，故**为新文件复验**该保证而非假定它继承。

实测：`TEST_POSTGRESQL_URL` 指向死端口 5999、**不设** `VIDEO_REPLICA_TEST_ALLOW_PG_SKIP`，跑 `test_cw056_supported_head_matrix.py` + `test_postgres_migrations.py`：

```
.......EEEEEEEEEEEEEEEEEEEEEEEEEEEEEE                                    [100%]
7 passed, 30 errors in 45.55s          rc=1
```

进度行本身即证据：**7 个点、30 个 `E`、零个 `s`**（skip 字符数为 0），rc=1 硬失败。归属算术吻合：7 passed = A 组 7 项（刻意不挂 PG 门）；30 errors = 本文件 B/C 组 6 项 + `test_postgres_migrations.py` 24 项（模块级 autouse fixture 在 setup 阶段失败，故为 error 而非 failed）。

**A 组 7 项刻意不挂 PG 门**：它们不接触数据库（静态断言、alembic CLI 拒绝路径、SQLite lane、脚本正文检查），无 PG 时也应继续把关——否则会恰好在最缺 PG 的环境里同时失去矩阵完整性、哈希冻结与两道门禁的守卫。这与 CW-055 对 3 项纯静态用例的处理同一理由。

## 11. 验证结果

### 11.1 专项 RED→GREEN

| 阶段 | 命令范围 | 结果 |
| --- | --- | --- |
| RED（A 组） | `test_cw056_supported_head_matrix.py` A 组 7 项 | **3 failed / 4 passed in 3.00s**——3 项失败恰是标注 `# RED` 的三处真实实现缺口 |
| RED（全文件首轮） | 同文件全部 13 项 | **8 failed / 5 passed in 9.38s**——含 5 项测试自身写法缺陷造成的假红 |
| RED（修正测试缺陷后） | 同文件全部 13 项 | **3 failed / 10 passed in 11.71s**——失败集合收敛为且仅为 3 处真实缺口 |
| GREEN | `test_cw056_supported_head_matrix.py` + `test_postgres_migrations.py` | **37 passed in 48.76s**（13 新增 + 24 既有），rc=0，**零回归** |
| 缺 PG 硬门 | 同上两文件，DSN 指向死端口 | **7 passed / 30 errors / 0 skipped in 45.55s**，rc=1（§10） |
| 静态门禁 | `ruff check server`、`ruff format --check server`、`mypy --strict`（`server/app`） | 全过；mypy 报 `Success: no issues found in 104 source files` |

`ruff format --check` 是 `npm run check` 链条的一环（`package.json` 中 `ruff check server && ruff format --check server && mypy ... && pytest ...`），故 `env.py` 与新测试文件均已 `ruff format`；`test_postgres_migrations.py` 本就 format-clean。

**B/C 组 6 项在实现前即通过，是回归锁而非 RED→GREEN**，其价值在于防止未来漂移。此处**不以「先红后绿」冒充**：它们证明的是「行为一直正确，但此前无自动化覆盖」——空库与三个旧起点升级到 head 后 schema 完整目录摘要相等、失败态回滚干净、039 非空审计降级拒绝保留。其中 `test_audit_lineage_downgrade_refusal_is_preserved` 特别值得定性：039 的降级拒绝是**条件性**的（空审计表允许降级、非空则 `RuntimeError` 且指针不动、审计行仍在），改动前该行为完全无覆盖，属**覆盖漏项而非实现漏项**。

### 11.2 服务端全量 pytest 与失败归因

在本机隔离 PG（`vs-pg-cw056`，`127.0.0.1:5435`，库 `customer_v3_test`，角色 `devuser`）上跑全量，并与 CW-055 任务树的全量（`vs-pg-dev`，`localhost:5434`）做失败 ID 集合对照。**本任务只声明相对基线零回归**；全量绿的最终判定权归 CI（§12）。

| 运行 | 树 | 结果 |
| --- | --- | --- |
| 基线 | CW-055 工作树（含 CW-055 的 15 项新用例） | `34 failed, 2181 passed, 5 skipped, 38 errors in 2020.26s (0:33:40)` |
| 本次 | 本任务树（含本任务 13 项新用例） | `28 failed, 2185 passed, 5 skipped, 38 errors in 2930.80s (0:48:50)` |

对照方法：提取两次运行的 failed+error **测试 ID 全集**做集合运算（`.dev-env/cw056_diff.ps1`，运行时索引取路径 + HashSet 对称差；本次失败 ID 清单落 `.dev-env/cw056_ids.txt`，66 行）。结果：**66（本次）⊂ 72（基线），ONLY_IN_CW056 = ∅ → 零新增失败**；`ONLY_IN_BASELINE` 恰 6 项，逐项归因如下。

| # | 消失项 | 归因 |
| --- | --- | --- |
| 1 | `test_postgres_migrations.py::test_user_identity` | **本任务真实修复**。基线树该用例硬编码 `current_user == "testuser"`，而基线 DSN 角色为 `devuser` → 恒失败（AssertionError）；本任务改为 `_expected_fixture_identity()` 从 `TEST_POSTGRESQL_URL` 解析期望 (role, database) → 通过。自证性不对称：兄弟用例 `test_database_creation` 硬编码的库名 `customer_v3_test` 恰等于 DSN 库名故基线也通过——两者只差「硬编码值是否恰好等于环境值」，与该任务改动方向严格对齐（§13） |
| 2—5 | `test_cw009_security_matrix_export.py`（4 项） | **基线运行器的 locale 编码缺陷，与本任务零关系**。4 项均经 `MATRIX_PATH.read_text()`（无 encoding 参数 → `encoding='locale'`）读含中文的 `docs/evidence/CW009-SECURITY-MATRIX.md`，在中文 Windows（locale=cp936/gbk）下抛 `UnicodeDecodeError: 'gbk' codec can't decode byte 0x94 in position 11`；traceback 证明 `open()` 已成功、失败在 `f.read()`，且 `MATRIX_PATH` 由 `Path(__file__)` 纯运算得到（pytest 输出里 `WindowsPath('E:/浼楀涔嬪鐖嗘鐭棰戝垱浣?…')` 仅是 cp936 控制台对正确路径的显示失真，非实际路径损坏）。本任务 runner 显式设 `PYTHONUTF8=1`/`PYTHONIOENCODING=utf-8`，Python UTF-8 mode 下 `io.text_encoding(None)` 返回 `utf-8`，同一代码即通过 |
| 6 | `test_security_contracts.py::test_no_sentry_sdk_enters_the_server_runtime` | 同上（`(REPO_ROOT / "server" / "pyproject.toml").read_text()` 抛 `UnicodeDecodeError: 'gbk' codec can't decode byte 0x99 in position 885`）。`REPO_ROOT = Path(__file__).resolve().parents[2]` 为纯路径运算、路径无误 |

**跨树算术闭合**（消除 collect 总数差）：基线树 2258 项（=34+2181+5+38）含 CW-055 的 15 项新用例，本树 2256 项（=28+2185+5+38）含本任务 13 项新用例 → 两树共同基线部分按「总数−本任务新增」计各 **2243** 项（2258−15 = 2256−13 = 2243），即两次运行除各自新增用例集外收集面一致；共同部分 passed 2166（=2181−15）→ 2172（=2185−13），**+6 恰等于消失的 6 项**，failed 34→28（−6），skipped 与 errors 恒定。

**恒定项说明**：`5 skipped` 两树一致（CW-007 硬门完整，无缺库跳过）；`38 errors` 两树一致且全部落在 `test_oral_domain.py`（Windows 缺 ffmpeg 的既有环境缺口，本任务零触碰）。

**并发说明**：CW-054 的全量（22:46–23:25，`localhost:5434`/vs-pg-dev）与本运行（23:01–23:49）重叠 24 分钟，但两者 PG 容器物理隔离（5434 vs 5435，仅库名同为 `customer_v3_test`）→ 无 fixture 污染；重叠的可见影响仅为 CPU 争抢拉长耗时（48m50s；同类运行历史耗时 21–34 分钟）。

### 11.3 RED 阶段五处测试自身写法缺陷（诚实登记）

首轮全文件 RED 的 8 项失败中 **5 项不是产品缺口**，而是初版测试写法错误；另有 2 处缺陷不产生假红，反而更危险（一处**假绿**、一处会误导后续复用者）。逐项登记以免复用同一夹具时重犯：

| # | 用例 | 初版错误 | 现象 | 修正 |
| --- | --- | --- | --- | --- |
| 1 | `test_supported_head_matrix_upgrade_...[053/054/055]` | 在**升级前**直接 `SELECT ledger_sequence`，而该列由 **063** 创建，三个起点都早于它 | `psycopg.errors.UndefinedColumn: column "ledger_sequence" does not exist`，三个参数全红。讽刺的是断言消息本身已写着「053 has no ledger_sequence column」——事实已知却写了跑不了的查询 | 改为用 `information_schema.columns` 断言该列**不存在**。语义更强：这正是「升级后既有行 NULL 可归因」的前提 |
| 2 | `test_supported_head_matrix_upgrade_...[空库]` | 单例行表连写前未播种 actor，而 `runtime_settings.updated_by_user_id` 是 `users` 的外键；空库起点没有任何用户 | `psycopg.errors.ForeignKeyViolation: runtime_settings_updated_by_user_id_fkey ... Key (updated_by_user_id)=(cw056-admin) is not present in table "users"` | 新增 `SINGLETON_WRITE_ACTORS` 常量，写入前用 `ON CONFLICT (id) DO NOTHING` 建 actor |
| 3 | `test_failed_upgrade_leaves_deterministic_state` | 「半建表」检查选了 `user_queue_cursors`，而它由 **041** 创建，早于 053 起点，本来就存在 | `AssertionError: user_queue_cursors was half-created by the failed upgrade`——假红，把正常存在的表当成半建残留 | 改用 056/058/065/067 创建的 4 张表（`operation_cost_rates`/`daily_external_prices`/`oral_tasks`/`studio_drafts`），逐一 grep 迁移文件确认归属 |
| 4 | 同上 | 另一处半建检查用了 `independent_creation_tasks`，而该表**在 head 上根本不存在**（075 只给 `generation_batches` 加列，不建新表） | **假绿**：`to_regclass` 对不存在的名字同样返回 NULL，断言无条件通过。比假红更危险——它会一直「通过」下去 | 新增 `LATE_TABLES_AFTER_PUBLISHED_HEAD` 常量 + **防空转元断言** `assert late_table in HEAD_TABLE_NAMES`：表名拼错时元断言先失败 |
| 5 | `test_internal_lane_sqlite_migration_target_still_works` | 初版打算用 `--sql` 触发 SQLite lane | 会假红：offline 对 SQLite 同样崩在 009 的 `MockConnection.exec_driver_sql` 缺失，该缺陷**与方言无关**，用它当回归锁测不到「客户生产门禁不误伤 internal lane」这件事 | 改走 **online** 模式（也正是 `app/db.py.upgrade_database` 的真实路径），跑通 SQLite lane 到 `081` 并读回 `alembic_version` 核对 |

另有一处非缺陷但需登记的工具级教训：`ruff check` 报 E501（112 > 100），源于 counts 漂移的 dict comprehension 内联在 f-string 里；提取为 `drifted` 局部变量后通过。

## 12. 范围边界与延后项（诚实登记）

| 延后项 | 归属 | 本任务现状 |
| --- | --- | --- |
| 生产实际停写 / 升级执行 | CW-051 | 规格「剔除重复开发」明列。本任务只证明升级**矩阵**在真实 PG 上收敛，不执行任何生产升级、不产出停写窗口方案 |
| `server/scripts/sqlite_to_postgres.py`、`server/scripts/reconcile_customer_billing.py` | CW-034—039 / CW-060 | 两文件出现在规格 CW-056 的「文件/对象」列表里，但同一节的「剔除重复开发」明确把 SQLite→PG 只读导入工具划归 CW-034—039/CW-060。**零触碰**。登记此矛盾以免后续复核误判为漏做 |
| `app/db.py` SQLite 兼容层 | CW-042 / CW-043（CW-053 §3 E2） | **保留不动**。被 10 个 app 模块与 30+ 测试消费，退役前 internal/desktop lane 仍受支持。故 §9.2 的客户生产门禁**刻意不做全局拒绝**，并以防误伤回归锁钉住 |
| 077 `op.execute` 把 `CURRENT_TIMESTAMP` 写入 TEXT 列的跨方言格式分歧 | 未指派（本任务登记为**已知观察项**） | 077 的 `UPDATE script_from_audio_tasks SET ... completed_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP` 中，两列在 068 建表时为 `sa.Text()`。PG 通过赋值 I/O 转换接受该写入，但产出文本格式（`2026-09-10 22:24:49.123456+08`）与 SQLite 的 UTC 格式（`YYYY-MM-DD HH:MM:SS`）不同。**本任务已证明该语句在真实 PG 上可解析可执行**（矩阵四个起点升级均经过 077），未证明的是「存在 legacy 重复行时写入的字面量格式」——该场景属带生产数据升级，归 CW-051。修它需编辑已发布迁移，PG-09 禁止，故不在本任务处理 |
| 077 的 `retryable=0` 在 PG 上的合法性 | — | **已澄清为非风险**：068 建表时 `retryable` 为 `sa.Integer()`（PG 上映射 `INTEGER`），故 `retryable=0` 因类型而合法，不是侥幸通过。此处登记是因为「SQLite 布尔存整数」的直觉会让人误判该语句在 PG 上必炸 |
| `test_script_from_audio_migration.py` 移植到真实 PG | CW-058（升级矩阵部分已由本任务覆盖） | CW-053 §7 L241 把该债务分派为「CW-056 空/旧 PG 升级矩阵 + CW-058 迁移」。**升级矩阵部分已核销**：077 的 `down_revision=076`，落在 055→081 路径上，故矩阵四个起点均在真实 PG 上执行了它的 `batch_alter_table` 与方言分支 `create_index`（`sqlite_where` / `postgresql_where` 并存），其产物 `script_from_audio_tasks` 已在 `HEAD_TABLE_NAMES` 冻结目录内。剩余部分（把该测试文件本身改写为 PG-native）仍属 CW-058，见 §13 |
| 生产 / staging 真实链路 | CW-051 等 + 人工授权 | 不提升 `STAGING_VERIFIED`；证据层级停在 `AUTOMATED_VERIFIED` |
| Windows `fcntl` 兼容 | **不入库** | `pg_test_kit.py` 顶部 `import fcntl` 在 Windows 是收集期硬阻塞。为不污染并行分支（改它会让 CW-055/056/031 都带同一份 CW-007 基座改动，squash 后重复入 main），shim 放在**仓库外** `.dev-env\pyshim\fcntl.py`，仅经 `PYTHONPATH` 注入。CI Linux 不受影响，仓库内零改动 |
| 全量绿的最终判定权 | CI | 本任务只声明**相对基线零回归**（§11.2）。CI Linux 门禁（含 postgres:16 service 与 `TEST_POSTGRESQL_URL`）为最终全量门 |

## 13. 跨任务闭环

| 上游登记 | 原文位置 | 本任务处置 |
| --- | --- | --- |
| 硬编码角色名 `testuser` | `docs/evidence/CW055-EVIDENCE.md` §8.1.3 line 178：「硬编码角色名 `testuser` \| `tests/test_postgres_migrations.py:159` \| 从 DSN 解析期望角色，而非写死 \| **CW-056 迁移矩阵范围内可一并收口**」 | **已按建议修法收口**。新增 `_expected_fixture_identity()` 用 `sqlalchemy.engine.make_url` 从 `TEST_POSTGRESQL_URL` 解析期望的 (role, database)，`test_database_creation` / `test_user_identity` 改用解析值。断言的不变量因此回到它本该是的样子——连接确实落在**请求的**角色与库上（无重定向、无静默默认），而不是「某一个环境的名字被烤进了测试套件」。DSN 本身是否允许使用，由 `pg_test_kit.assert_safe_test_database` 独立把关。`sqlalchemy>=2.0.52` 是 `pyproject.toml` 直接依赖，import 安全 |
| `test_postgres_migrations.py` 过期 docstring | 同文件顶部原宣称缺 PG 时「自动 skip」 | **已纠正**为与 CW-007 硬门一致的表述，并写明 `VIDEO_REPLICA_TEST_ALLOW_PG_SKIP=1` 的显式退出**不计入 PG 验收证据**。文档与门禁矛盾本身是缺陷：它会让复核者以为一份 skip 全绿的运行可以当证据 |
| CW-053 §7 升级矩阵债务 | `docs/evidence/CW053-DB-SEMANTIC-INVENTORY.md` L241、L42、L280 | **升级矩阵部分核销**，依据见 §12 对应行；CW-058 部分保持未核销 |

## 14. 签认记录

| 角色 | 结论 | 日期 |
| --- | --- | --- |
| 数据库负责人 | 待签认 | — |
| 迁移复核 | 待 PR CodeReview | — |
| 集成负责人 | 待签认 | — |
