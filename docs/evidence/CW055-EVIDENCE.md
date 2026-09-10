# CW-055 — 补齐 PG 事务、连接池与提交边界验证

> 目标证据层级：`AUTOMATED_VERIFIED`。本文件登记 CW-055 的改动前缺口盘点、
> RED→GREEN 逐用例轨迹、SQLSTATE→幂等恢复矩阵、提交边界的「行为 + 静态」双重证明、
> 缺 PG 硬失败验证与全量门禁结果。业务域全量映射核销（CW-058/059）与容量基准
> （CW-047）按规格明列剔除，不在本任务范围（见 §9）。

## 1. 任务信息（§14 模板）

| 字段 | 值 |
| --- | --- |
| 任务/工作包 | CW-055（W4）补齐 PG 事务、连接池与提交边界验证；DoD：补齐已迁调用者的 TEST-PG 回归与 RED→GREEN、证明全调用链未中途提交、增加池耗尽/断连/异常事务回收/死锁·serialization·timeout 的 SQLSTATE→幂等恢复矩阵、缺 PG 不得 skip、验证序列值不可回滚不被误断言 |
| Owner / Reviewer | Owner：Qoder 代理（2026-09-10）；Reviewer：待 PR 独立 CodeReview |
| 分支 / 基线 SHA | `feat/customer-v3-cw055-pg-txn-pool-fencing`；基线 `origin/main@d8f3352`（CW-016 #6 合并后） |
| 上游规格段落 | 收敛详细任务清单 §CW-055（line 573–586）；V3 清单 §18 CW-055 行（line 495）；PG-03 事务与连接池（`docs/PostgreSQL唯一数据库实施与验收规范.md`）；CW-007 TEST-PG 硬门（`docs/evidence/CW007-EVIDENCE.md`） |
| 改动文件 | 2 文件（+618/−9）：`server/app/db_pg.py`（+77/−8）、`server/tests/test_db_pg.py`（+541/−1）；另新增本证据文件。**零迁移文件改动**，`db_portable.py`/`customer_fence.py`/`auth.py`/`generation_worker.py` 全部零改动 |
| 失败测试或回归锁定 | 新增 15 用例（12 项挂 `pg_hard_gate` + 3 项纯静态/纯配置）。RED 阶段 **6 failed / 9 passed**，其中 4 项为真实实现缺口（`ImportError: POOL_TIMEOUT_ENV` / `POOL_TIMEOUT_CEILING`），2 项为测试自身写法缺陷（已修正，见 §8）。GREEN 阶段 **15 passed**；专项合跑 **164 passed** 零回归 |
| 实现结果 | §2 交付明细；§3 缺口盘点；§4 SQLSTATE 矩阵；§5 提交边界证明；§6 池耗尽与连接卫生；§7 缺 PG 硬失败 |
| 验证命令与通过数 | 见 §8。ruff check / ruff format --check / mypy 全过；专项 164 passed；服务端全量 pytest 见 §8.1 |
| 证据层级 | **AUTOMATED_VERIFIED**（真实 PG 16.15 上取得 RED→GREEN 轨迹与矩阵证据，无 staging/真实链路依赖）。不提升 `STAGING_VERIFIED`：生产/staging 切换归 CW-051 且需人工授权 |
| 安全与可观测性 | 无真实 API key/激活码/设备或 session token 进入代码、日志、测试夹具或 PR。新增能力即脱敏本身：池耗尽 WARNING 经 `redact_postgres_dsn` 输出，`test_pool_exhaustion_logs_a_redacted_diagnostic` 双向钉住（口令**不得**出现、脱敏 DSN **必须**出现），口令由 DSN 解析取得而非写死，兼容本机 `devpass` 与 CI `testpass` |
| 迁移与回滚 | **零迁移文件改动**（未新增 revision，未触碰冻结区间）。改动纯增量：新增 `POOL_TIMEOUT_ENV` 旋钮（默认值与改动前完全一致，未配置时行为不变）+ 池耗尽 WARNING 日志。回滚 = revert 本分支 |
| 外部授权记录 | 无（不涉及真实 ZPay / 付费 Provider / 生产 COS 变更 / 对外发码 / 灰度扩大 / 公网发布） |
| 未测试项 | `cargo test`、`npm audit`、客户浏览器 E2E、`npm run build`、前端 biome/vitest —— 均**只在 CI 三门禁执行**；本任务前端与 Rust 侧零触碰 |
| Lore 提交 SHA | 本 PR squash 后回填 |

## 2. 交付明细（对照 CW-055「仅做剩余」五项）

| 规格要求（收敛清单 §CW-055 line 580–585） | 实现 |
| --- | --- |
| ① 补齐每个已迁调用者修改前 TEST-PG 回归与 RED→GREEN | 本任务**未修改任何调用者**：`db_portable.py`/`customer_fence.py`/`auth.py`/`generation_worker.py` 零改动（缺口盘点结论见 §3——它们的 no-op 提交契约本就成立）。因此不存在「修改前回归」对象。改动限于 `db_pg.py` 池层，属纯增量；已迁调用者的 TEST-PG 回归由 §8 专项合跑（`test_customer_fencing.py` 61 项 + `test_db_portable.py` 19 项全绿）与全量门禁覆盖 |
| ② 当前证据不足以证明全调用链均未中途提交 | §5 双重证明：**行为 spy**（在真实 psycopg 连接上替换 `commit`/`rollback`，遍历 5 种门面调用形态，断言底层从未被触达）+ **静态调用点扫描**（`app/*.py` 全域 `.raw.commit(`/`.raw.rollback(` 仅允许存在于门面 `db_portable.py` 内部）。二者共同覆盖全部 84 处 `BusinessConnection.postgres` 构造点，无需逐个跑行为测试 |
| ③ 增加池耗尽有界失败、断连、异常事务回收、死锁/serialization/timeout 的 SQLSTATE→幂等恢复矩阵 | §4 矩阵：4 类失败（57014 / 40001 / 40P01 / 业务异常）× 4 项恢复性质（完整回滚、连接可复用、幂等重试只扣一次、再次重试不重复扣费）= 16 条断言全绿；§6 池侧 5 用例（有界失败、脱敏日志、归还恢复、异常事务不污染返池、服务端断连回收） |
| ④ 缺 PG 不得 skip | §7：DSN 指向不可达端口且无显式豁免 → **24 errors 硬失败、零 skip**；仅 `VIDEO_REPLICA_TEST_ALLOW_PG_SKIP=1` 时才 24 skipped（CW-007 硬门，不计证据）。新增 12 项 PG 用例全部落在该门下 |
| ⑤ 验证序列值不可回滚这一 PG 事实不会被误断言 | `test_sequence_values_are_not_returned_by_a_rollback`：钉住「回滚丢弃行但**不归还**序列号」——`burned == kept + 1` 且 `after > burned`，同时 `SELECT v` 只剩 `["kept","after"]`。防止后续把正常的序列空洞当缺陷，或反过来用「id 连续」掩盖真正的重复分配 |

## 3. 改动前缺口盘点（事实，非推断）

| 盘点项 | 结论 | 取证方式 |
| --- | --- | --- |
| PG lane 连接构造点 | `app/` 全域 **84 处** `BusinessConnection.postgres(...)`，分布 10 文件：`generation_worker` 67、`recharge_routes` 5、`viral_routes`/`rbac_routes`/`customer_fence`/`bootstrap` 各 2、`admin_customer_routes`/`auth`/`control_routes`/`media_routes` 各 1 | `Select-String -Path app\*.py -Pattern 'BusinessConnection\.postgres'` |
| 裸 sqlite3 连接 | `app/` 内 19 处 `connect_database(` / `sqlite3.connect`，**全部**被 `BusinessConnection.sqlite(...)` 包裹，属 internal/桌面 lane（CW-025 已注明归 CW-030/040/042/043）；不构成 PG lane 的中途提交面 | grep + 逐处核对 |
| 绕过门面的底层提交 | `app/` 内 `.raw.commit(` / `.raw.rollback(` **仅 4 处**，全在 `db_portable.py` 门面实现内部（`commit`/`rollback`/`__exit__` 两处），且均被 `isinstance(self._backend, SQLiteBackend)` 守卫 → PG lane 永不执行 | grep，已固化为静态用例 |
| 唯一逃生口 | `viral_routes.py:245` `borrowed.raw.autocommit = True`：爆款刷新 lane 直接 `pool.connection()` 借用、不经 `pg_transaction()`。因置 autocommit，无事务可中途提交 | grep，已固化为枚举用例 |
| 池借用超时 | **真实缺口**：`get_pg_pool()` 硬编码 `timeout=DEFAULT_POOL_TIMEOUT`（30.0），无 env 旋钮 → 「第 N+1 借用必须在**配置** timeout 内失败」既不可测也不可运维 | 4 用例 RED（`ImportError`） |
| 池耗尽可观测性 | **真实缺口**：`pg_transaction()` 不捕获 `PoolTimeout`；`app/` 与 `tests/` 全域**零处** `PoolTimeout` / `psycopg_pool.errors` 引用 → 耗尽时运维只看到裸异常，无法区分「池配小了」与「PG 不可达」，且无脱敏诊断日志 | grep + RED |
| 改动前已存在、本任务复验而非重建的基线 | `check=ConnectionPool.check_connection`、`max_lifetime=3600`/`max_idle=600`、`statement_timeout=300000`、`idle_in_transaction_session_timeout=60000`、isolation allowlist、`POOL_MAX_CEILING=64`、`redact_postgres_dsn`、`fenced_pg_transaction` 持有最终提交权、PG lane `BusinessConnection.commit/rollback` 为刻意 no-op | 既有 69 用例 + 本任务新增用例复验 |

**盘点结论**：CW-055 的「证据不足」在提交边界一侧是**取证缺口而非实现缺陷**（契约本就成立，但无自动化证明）；在池一侧是**两处真实实现缺口**（超时可配置性、耗尽脱敏日志）。二者分别用 §5 与 §6 收口，未对已成立的契约做任何改动——尤其**未把 no-op commit 改成业务层中途提交**（CW-055 完工标准明令禁止）。

## 4. SQLSTATE → 幂等恢复矩阵（必交证据③）

统一夹具建在共享测试库：`t055_ledger`（`idem TEXT NOT NULL UNIQUE` + `CHECK (amount > 0)` + IDENTITY 主键）、`t055_balance`（余额行，seed 1000）、`t055_lock`（死锁用双行 a/b）、`t055_serial`（SSI 同键读改写用）。每个参数化用例各自 `_seed_billing()` 复位，扣费额 100。

| 用例 id | 触发方式 | SQLSTATE | ① 完整回滚 | ② 连接可复用 | ③ 幂等重试只扣一次 | ④ 再次重试不重复扣费 |
| --- | --- | --- | :-: | :-: | :-: | :-: |
| `57014_query_canceled` | 落账后 `SET LOCAL statement_timeout='30ms'` + `SELECT pg_sleep(1)` | 57014 QueryCanceled | ✅ 余额 1000 / 账本 0 行 | ✅ | ✅ 余额 900 / 账本 1 行 | ✅ 余额 900 / 账本 1 行 |
| `40001_serialization_failure` | SERIALIZABLE 读 `t055_serial` → 并发事务同键读改写并**提交** → 本事务同键写回 + 落账 | 40001 SerializationFailure | ✅ | ✅ | ✅ | ✅ |
| `40p01_deadlock_detected` | 本事务持 a；对手线程持 b 并阻塞在 a（此时**尚无环**）；本事务再请求 b 闭环 | 40P01 DeadlockDetected | ✅ | ✅ | ✅ | ✅ |
| `business_error` | 落账后 `raise RuntimeError("business rule rejected the charge")` | 无（业务异常，非 `psycopg.Error`） | ✅ | ✅ | ✅ | ✅ |

② 的断言形态：紧接着的借用连接 `info.transaction_status != INERROR` 且 `SELECT 1` 成功。
①③④ 的断言形态：`(余额, 账本行数)` 三元组精确比对，而非仅「无异常」。

**死锁用例的确定性构造**：PG 由「最后进入等待的一方」检出死锁并中止自身。若两侧同时进入等待，谁输取决于 `deadlock_timeout` 计时器先后，用例会 flaky。本用例先让对手阻塞在 a 上（此时无环、对手不进入死锁检测），再由本事务请求 b 闭环，并把对手 `deadlock_timeout` 抬到 `5s`、本事务压到 `20ms`，使检出者恒为本事务。对手线程在 `finally` 中 `join(30)`，避免它持有的池连接泄漏到下一个用例（`_close_pool_between_tests` autouse fixture 会 `close_pg_pool()`）。该用例在**首次 RED 运行即通过**，非事后调参。

**SERIALIZABLE 用例的必要条件**：必须对**同一键**先读后写才构成 SSI 依赖环。初版只读 `t055_serial` 而写 `t055_ledger`/`t055_balance`（不同键）→ PG 不报 40001（RED 表现为 `DID NOT RAISE`）。修正为「读 `t055_serial` → 并发同键提交 → 本事务同键写回」，与既有 `test_pg_transaction_serializable_write_conflict` 同构。对手只动 `t055_serial`、不动余额与账本，因此矩阵的统一断言「余额未动 / 账本 0 行」仍然成立。

**「不重复付费」的实现形态**：`_charge_idempotent()` 以账本表的 UNIQUE 幂等键为**唯一**去重事实源，捕获 `UniqueViolation` 后返回 `False`。重试安全性不依赖调用方记住上次结果——超时/断连场景下调用方本就无法知道上次是否落账，这正是必须把幂等性下沉到数据库约束的原因。

## 5. 提交边界证明（必交证据②：全调用链未中途提交）

| 证明类型 | 用例 | 手法与为何可信 |
| --- | --- | --- |
| 行为：门面不触达底层提交权 | `test_pg_lane_facade_never_calls_underlying_commit_or_rollback` | 在**真实** psycopg 连接上以实例属性替换 `commit`/`rollback` 为记录型 spy（`psycopg.Connection` 无 `__slots__`，已实测可替换），遍历 `bc.commit()` / `bc.rollback()` / `with bc:` / `with bc.transaction():` / `with bc.transaction(isolation="SERIALIZABLE"):` 五种调用形态，断言 spy 记录为空。断言点刻意置于外层 `pg_transaction` 退出**之前**——退出时 `conn.transaction()` 自己会合法提交一次，放在外面会产生假阳性 |
| 行为：`commit()` 不提前发布 | `test_pg_lane_facade_commit_never_publishes_early` | 用**第二条连接的可见性**证明（不依赖日志或桩）：外层事务未退出前，门面 `commit()` 之后的 3 行写入对 observer 连接完全不可见（`COUNT=0`）；`rollback()` 也没能废弃外层事务（raw 侧仍见 3 行）；外层退出后 3 行一次性全部可见。DDL 与 `TRUNCATE` 刻意放在前一个**已提交**事务里，避免 ACCESS EXCLUSIVE 锁阻塞 observer |
| 静态：调用点收口 | `test_pg_lane_has_no_mid_transaction_commit_call_sites` | 扫描 `app/*.py`，任何 `.raw.commit(` / `.raw.rollback(` 若出现在门面 `db_portable.py` 之外即失败，并列出具体 `文件:行号`。行为测试只能覆盖跑到的路径，此扫描把不变量钉在源码层，防未来新增旁路（84 处构造点分布于 10 文件，无法逐个跑行为测试） |
| 静态：逃生口可枚举 | `test_pool_borrow_autocommit_escape_hatch_stays_confined` | `.raw.autocommit = True` 的文件集合必须恰为 `{viral_routes.py}`。断言文件集合而非行号，避免无关编辑导致脆断；新增任何一处都会让用例失败，逼出显式评审 |

## 6. 池耗尽有界失败与连接卫生（必交证据③的池侧）

| 用例 | 断言与设计理由 |
| --- | --- |
| `test_pool_timeout_is_configurable_and_capped`（纯配置，**不挂** PG 门） | `_pool_timeout()`：空值→默认 30.0；`"0.5"`→0.5；非数字 / `0` / 负值→默认；`999999`→`POOL_TIMEOUT_CEILING=300.0`。**0 与负值必须回落**：在 psycopg_pool 里它们等于「不等待」，会把容量抖动直接变成请求失败。**上限必须存在**：一个被误配成数小时的 timeout 会把「有界失败」退化回 2026-09-07 评审 §7-0 那种无限期挂住（实测曾拖停公平队列 19 分钟），故与单语句超时同量级取 300s |
| `test_pool_exhaustion_fails_within_the_configured_timeout` | `POOL_MAX=2` 占满后第 3 次借用抛 `PoolTimeout`，且 `0.4s ≤ elapsed < 30.0s`。**下界**证明它真的等到了配置超时（而非因别的原因立即失败），**上界**证明它受配置值约束而非硬编码默认 |
| `test_pool_exhaustion_logs_a_redacted_diagnostic` | 抛出的异常文本与 `app.db_pg` 的 WARNING 日志均**不含** DSN 口令；同时日志**必须含**脱敏 DSN（`postgresql://<user>@localhost:5434/customer_v3_test`），否则失去定位价值。口令由 DSN 解析取得而非写死，兼容本机 `devpass` 与 CI `testpass`；用例开头断言口令非空，避免退化成空断言 |
| `test_pool_recovers_once_connections_are_returned` | `POOL_MAX=1` 下耗尽失败后，归还连接的下一次借用立即成功——耗尽是**有界失败**而非永久损坏 |
| `test_failed_transaction_does_not_poison_the_returned_connection` | `POOL_MAX=1` 强制下一借用者拿到**同一条**物理连接：事务异常后该连接 `transaction_status != INERROR` 且能正常执行语句。若池未复位，借用者会撞上 `InFailedSqlTransaction`（"current transaction is aborted"），把一次业务失败放大成整链路连锁失败。DDL 必须先在自己已提交的事务里建——否则它随失败事务一起回滚（PG 的事务性 DDL），后续断言会退化成 `UndefinedTable` |
| `test_pool_recycles_a_server_side_terminated_connection` | 连接归还池后从池外 `pg_terminate_backend` 杀掉它（模拟 PG 重启 / 网络闪断 / OOM killer 三类同构故障），下一次借用必须拿到**不同 backend pid** 且可用——证明 `check=ConnectionPool.check_connection` 真的在换掉死连接，而不只是配置上写了 |

**日志断言的取舍说明**：本测试文件多数用例刻意避开日志断言（见 `test_worker_main_dispatches_to_pg_forever_loop` 的理由：全局 logging 状态可能被其他测试污染）。但脱敏本身就是本任务的交付物，必须验日志。为降低污染风险，断言按 `record.name == "app.db_pg"` 过滤，只认该 logger 自己发出的记录，不依赖 root handler 的全局配置。

**嵌套耗尽不重复记录**：`pg_transaction()` 用 `acquired` 标志区分「本层借用失败」与「内层嵌套 `pg_transaction` 的耗尽向上冒泡」。只在前者记日志——嵌套 `pg_transaction` 是仓库既有的真实模式（如 SERIALIZABLE 用例内层再开事务），不加区分则一次池耗尽会被 N 层嵌套放大成 N 条 WARNING，掩盖真实故障规模。

## 7. 缺 PG 不得 skip（必交证据④）

| 场景 | 结果 |
| --- | --- |
| DSN 指向不可达端口 5499，**未**设显式豁免 | **60 passed, 24 errors**（硬失败，**零 skip**） |
| 同上 + `VIDEO_REPLICA_TEST_ALLOW_PG_SKIP=1` | 60 passed, **24 skipped**（显式豁免，按 CW-007 不计入证据） |

24 = 本模块全部挂 `pg_hard_gate` 的用例（既有 12 项 + 本任务新增 12 项，其中 SQLSTATE 矩阵为 1 函数 × 4 参数）。硬门由 CW-007 的 `require_pg_or_explicit_skip()` 提供（缺 PG 时 `pytest.fail` 而非 `skip`），本任务复验其在**新增**用例上同样生效。

新增的 3 个纯静态 / 纯配置用例（`test_pool_timeout_is_configurable_and_capped`、`test_pg_lane_has_no_mid_transaction_commit_call_sites`、`test_pool_borrow_autocommit_escape_hatch_stays_confined`）**刻意不挂** PG 门：它们不接触数据库，无 PG 时也应继续把关，而非跟着 skip——否则会恰好在最缺 PG 的环境里同时失去提交边界守卫。

## 8. 验证结果

本机 Windows 22H2 + Docker PG **16.15**（容器 `vs-pg-dev`，端口 **5434**，库 `customer_v3_test`，角色 `devuser`，SUPERUSER + CREATEDB）。端口与收敛线 `scripts/pg-fixture.sh`（5433 / `testuser`）**刻意隔离**，避免两套基座互踩；PG 大版本与 CI 的 `postgres:16-alpine` 一致。

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| RED（实现前） | `pytest tests/test_db_pg.py -k "<15 项>"` | **6 failed, 9 passed**。4 项 `ImportError: cannot import name 'POOL_TIMEOUT_ENV' / 'POOL_TIMEOUT_CEILING' from 'app.db_pg'` = 真实实现缺口；2 项为测试自身写法缺陷（见下） |
| GREEN（实现后） | 同上 | **15 passed**（1.72s） |
| 专项回归 | `pytest tests/test_db_pg.py tests/test_customer_fencing.py tests/test_db_portable.py` | **164 passed**（84 + 61 + 19），零回归（52.03s） |
| 缺 PG 硬失败 | `TEST_POSTGRESQL_URL=…:5499/… pytest tests/test_db_pg.py` | **60 passed, 24 errors**（见 §7） |
| 服务端 lint | `ruff check app/db_pg.py tests/test_db_pg.py` | **All checks passed!** |
| 服务端格式 | `ruff format --check` 同文件 | **2 files already formatted** |
| 服务端类型 | `mypy app/db_pg.py` | **Success: no issues found in 1 source file** |
| 改动面自检 | `git diff --numstat` | 仅 2 文件；`db_pg.py` 的 6 个 hunk 全部落在 CW-055 相关段落，`ruff format` 未波及无关行 |
| **服务端全量 pytest** | `pytest tests -q`（本分支唯一一次全量） | 见 §8.1 |

### 8.1 服务端全量 pytest 与失败归因（实测对照，非推断）

**本分支唯一一次全量运行**（`pytest tests -q`，Windows 本机 + Docker PG 16.15）：

```
34 failed, 2181 passed, 5 skipped, 1 warning, 38 errors in 2020.26s (0:33:40)
```

72 项 failed/error **全部**落在 6 个测试文件，`tests/test_db_pg.py` 零项、CW-055 新增 15 项零项。逐桶归因与**独立取证方式**（每条都不依赖「看起来像环境问题」这种推断）：

| 桶 | 数量 | 根因（原始错误文本） | 独立取证 |
| --- | :-: | --- | --- |
| `test_oral_domain.py` | 38 errors | `app.media_tools.MediaToolUnavailable: 未找到 ffmpeg，请确认安装包完整或配置 VIDEO_REPLICA_FFMPEG_DIR` —— session 级夹具 `oral_test_media` 在 setup 阶段即抛错，故为 error 而非 failed | `Get-Command ffmpeg` → **False**；`$env:VIDEO_REPLICA_FFMPEG_DIR` → **空** |
| `test_cw033_pitr_drill_validation.py` | 22 failed | `FileNotFoundError: [WinError 2]`，来自 `_winapi.CreateProcess` | 读源码 `tests/test_cw033_pitr_drill_validation.py:58`：`subprocess.run(["/usr/bin/env", "bash", ...])` —— **硬编码 POSIX 路径** `/usr/bin/env`，Windows 上不存在。该文件是 CW-033 PITR 演练脚本的 Linux 专属契约测试，构造上即不可在 Windows 跑 |
| `test_simple_character.py` | 6 failed | HTTP `503` + `SIMPLE_CHARACTER_IMAGE_VALIDATION_UNAVAILABLE`（期望 422/201）—— 图片校验依赖同一外部媒体工具链 | 同 ffmpeg 桶；`assert 503 == 422` / `assert 503 == 201` 形态与「校验器不可用即降级 503」的既有设计一致 |
| `test_cw009_security_matrix_export.py` | 4 failed | `UnicodeDecodeError: 'gbk' codec can't decode byte 0x94` | `locale.getencoding()` → **cp936**。`Path.read_text()` 未传 `encoding`，Windows 回落 locale=GBK 读 UTF-8 文档即炸；CI Linux locale 为 UTF-8 故通过 |
| `test_security_contracts.py` | 1 failed | `UnicodeDecodeError: 'gbk' codec can't decode byte 0x99 in position 885`，位置 `tests/test_security_contracts.py:110` 的 `read_text()` | 同上（cp936）。**注意**：runner 已设 `PYTHONIOENCODING=utf-8`，但该变量只影响 stdio，不影响 `read_text()` 的默认编码，故未能规避 |
| `test_postgres_migrations.py::test_user_identity` | 1 failed | `AssertionError: unexpected user devuser` / `assert 'devuser' == 'testuser'` | 用例把角色名**硬编码**为 `testuser`（CI `scripts/pg-fixture.sh` 基座）。本机基座刻意隔离为 `devuser@5434`（见 §8），故必然不等。同文件其余用例全绿，说明连接与迁移本身正常 |

合计 38 + 22 + 6 + 4 + 1 + 1 = **72 = 34 failed + 38 errors**，账目闭合。

#### 8.1.1 基线对照实验（把归因从论证升级为实测）

上述归因若只停在「根因看起来与 CW-055 无关」，仍属推断。故追加对照实验：把 CW-055 **唯一改动的 2 个文件**（`app/db_pg.py`、`tests/test_db_pg.py`）临时回退到 `origin/main@d8f3352` 版本，其余工作树状态、环境变量、PG 基座、pytest 版本完全不变，重跑这 6 个文件：

```
34 failed, 133 passed, 1 skipped, 1 warning, 38 errors in 152.17s (0:02:32)
```

随后按**测试 ID 集合**（而非仅计数）做对称差比对：

| 比对项 | 结果 |
| --- | --- |
| 全量运行的 failed/error ID 数 | 72 |
| 基线对照的 failed/error ID 数 | 72 |
| 两个集合是否相等 | **True**（`only in full-run = 0`、`only in baseline = 0`） |
| 失败集合中含 `db_pg` / `pool_` / `sqlstate` 的 ID | **0 个** |

即：**移除 CW-055 的全部改动后，失败集合逐项不变**。这排除了「CW-055 引入了失败」与「CW-055 恰好掩盖了别处失败」两种可能，零回归结论成立。

对照实验的工程细节：回退用 `git checkout -- <2 files>`（此时 HEAD 即基线，因 CW-055 尚未提交），运行前把改动副本备份到仓库外目录、运行后无条件拷回并复核 `git status` 仍为 `M` 两文件，避免实验本身吃掉工作成果。

#### 8.1.2 比对脚本的一次假绿（诚实登记）

首版比对脚本以 `read_text(encoding="utf-8", errors="replace")` 读日志，解析出 **0 个** ID，却输出 `identical sets: True` —— 空集与空集当然相等，属**假绿**，若直接采信就等于用坏掉的工具给自己签发零回归证明。根因：PowerShell 5.1 的 `Tee-Object -FilePath` 写 **UTF-16LE（BOM `FF FE`）**，按 UTF-8 解码后每行都是乱码，正则必然不匹配。修正为按 BOM 选择 `utf-16`/`utf-8` 解码，并加硬守卫：**任一集合解析为 0 项即 `SystemExit` 报错**，不允许空集参与比对。修正后才得到上表的 72/72。

教训：比对类取证脚本必须先自证「能解析出非空结果」，否则它的通过态与失败态不可区分。

#### 8.1.3 未在本任务修复的 Windows 可移植性缺陷（登记为后续项）

三个根因中有两个是**仓库自身的可移植性缺陷**，而非纯本机缺件。仓库存在 `docs/Windows内测与运维手册.md`，Windows 是真实目标平台，故登记如下；但修复它们会触碰 CW-009 / CW-033 的测试文件，超出 CW-055「仅做剩余」范围，且会污染三个并行分支的改动面，因此**本任务不修**：

| 缺陷 | 位置 | 建议修法 | 归属 |
| --- | --- | --- | --- |
| `read_text()` 未指定编码 | `tests/test_security_contracts.py:110`、`tests/test_cw009_security_matrix_export.py` | 显式 `encoding="utf-8"`（仓库其他处已是此惯例） | CW-009 相关，另开 |
| 硬编码 `/usr/bin/env` | `tests/test_cw033_pitr_drill_validation.py:58` | 用 `shutil.which("bash")` 解析，或整体加 Linux-only 跳过标记 | CW-033 相关，另开 |
| 硬编码角色名 `testuser` | `tests/test_postgres_migrations.py:159` | 从 DSN 解析期望角色，而非写死 | CW-056 迁移矩阵范围内可一并收口 |

**全量绿的最终判定权在 CI**：上述 72 项在 CI Linux（`postgres:16-alpine` + `scripts/pg-fixture.sh` 的 `testuser@5433` + 已装 ffmpeg + UTF-8 locale + `/usr/bin/env` 存在）条件下预期全绿，但**本机无法证明**，故本文件不以「全量绿」作结，只声明「本分支相对基线零回归」，全量门禁结果留待 push 后由 CI 出具（见 §1 未测试项）。

### 8.2 RED 阶段两处测试自身缺陷（诚实登记）

RED 的 6 项失败中有 2 项**不是**产品缺口，而是初版测试写法错误。登记以免后续复用同一夹具时重犯：

| 用例 | 初版错误 | 现象 | 修正 |
| --- | --- | --- | --- |
| `test_failed_transaction_does_not_poison_the_returned_connection` | 把 `CREATE TABLE t055_poison` 放进**将被回滚**的那个事务里 | `psycopg.errors.UndefinedTable: relation "t055_poison" does not exist`——测的是 DDL 回滚，不是池卫生 | DDL 与 `TRUNCATE` 前置到一个独立已提交事务 |
| `test_sqlstate_recovery_matrix[40001_serialization_failure]` | SERIALIZABLE 事务只**读** `t055_serial`，写入却落在 `t055_ledger`/`t055_balance`（不同键） | `Failed: DID NOT RAISE Error`——未构成 SSI 依赖环，PG 不报 40001 | 补「同键写回」`UPDATE t055_serial SET v = v + 100 WHERE id = 1`，与既有 `test_pg_transaction_serializable_write_conflict` 同构 |

### 8.3 mypy 发现并修复的类型缺口

`ConnectionPool.conninfo` 在 psycopg_pool 3.3 的类型是 `str | Callable[[], str]`（callable 形态用于轮换凭据）。直接把 `pool.conninfo` 传给 `redact_postgres_dsn(dsn: str)` 被 `mypy --strict` 拒绝：`Argument 1 … has incompatible type "str | Callable[[], str]"; expected "str"`。修复：新增 `_redacted_pool_dsn(pool)` 把两种形态收敛成 `str` 再交给唯一脱敏器，避免在日志路径上散落 `callable()` 判断，也保证将来若启用凭据轮换不会静默丢失脱敏。

## 9. 范围边界与延后项（诚实登记）

| 延后项 | 归属 | 本任务现状 |
| --- | --- | --- |
| 业务域全量映射核销 | CW-058 / CW-059 | 规格明列剔除，未触碰 |
| 容量基准 / 压测 | CW-047 | 规格明列剔除。本任务的池用例只验证**行为契约**（有界失败 / 回收 / 复用 / 脱敏），**不产出任何容量数字**，不声称池尺寸已定型 |
| internal lane 请求级 `DB_PATH` / SQLite 通道 | CW-030 / CW-040 / CW-042 / CW-043 | `app/` 内 19 处 `connect_database(` 全部经 `BusinessConnection.sqlite(...)`，属该 lane。本任务只证明它们**不构成 PG lane 的中途提交面**，不移除、不改动 |
| `viral_routes.py` 刷新 lane 的 `autocommit=True` 直连池借用 | 未指派（本任务登记为**已知例外**） | **保留**。该 lane 只读刷新、无事务可中途提交，故不违反提交边界；已用静态用例把例外集合钉成 `{viral_routes.py}`，新增即失败逼出评审。若要彻底收口需改其连接获取方式，超出 CW-055「仅做剩余」范围 |
| 生产 / staging 真实链路 | CW-051 等 + 人工授权 | 不提升 `STAGING_VERIFIED`；证据层级停在 `AUTOMATED_VERIFIED` |
| Windows `fcntl` 兼容 | **不入库** | `pg_test_kit.py:20 import fcntl` 在 Windows 是收集期硬阻塞（`ModuleNotFoundError`）。为不污染三个并行分支（改它会让 CW-055/056/031 都带同一份 CW-007 基座改动，squash 后重复入 main），shim 放在**仓库外** `.dev-env\pyshim\fcntl.py`，仅经 `PYTHONPATH` 注入。CI Linux 不受影响，仓库内零改动 |

## 10. 签认记录

| 角色 | 结论 | 日期 |
| --- | --- | --- |
| 后端负责人 | 待签认 | — |
| 独立安全/代码复核 | 待 PR CodeReview | — |
| 集成负责人 | 待签认 | — |
