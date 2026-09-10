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
| 分支 / 基线 SHA | `feat/customer-v3-cw055-pg-txn-pool-fencing`；PR **#13**。基线沿革：初版 `origin/main@d8f3352`（CW-016 #6 合并后，commit `f17da93`）→ 三次 rebase：`e06b13c`（CW-017 #9 后，head `a3ccc5c`）→ `eac6f4d`（CW-018 #11 后，head `f784f9d`，+ 证据提交 `2861872`）→ **`0d08608`（CW-019 #12 后，代码提交 `7d4e12b` + 本证据提交为分支顶端，当前）**。三次 rebase 均**无代码冲突**：本任务只改 `server/app/db_pg.py` + `server/tests/test_db_pg.py`，与 CW-017/CW-018/CW-019 的 client·deploy·CI 改动面零交集；账本 `docs/客户版任务清单-V3.md` 各方各改 1 行（rebase 后实测行号：CW-017 行 482、CW-018 行 483、CW-019 行 484、CW-055 行 **499**），本任务行与最近的 CW-019 行相距 15 行，超出 git 合并的 3 行上下文窗口故自动合并。相对 `origin/main@0d08608` 的 diff 面仍精确为 **4 文件**（含本节在内的最终计数为 **+994/−10**），`git log origin/main..HEAD` 只有本任务 2 个提交，**无 CW-019 内容渗入本 PR**。第三次 rebase 不是例行追基线，而是必需的：CW-019 在 main 上修掉了正卡住本 PR Linux 门的 main 侧 flake，详见 §8.5 |
| 上游规格段落 | 收敛详细任务清单 §CW-055（line 573–586）；V3 清单 §18 CW-055 行（rebase 至 `0d08608` 后为 line 499）；PG-03 事务与连接池（`docs/PostgreSQL唯一数据库实施与验收规范.md`）；CW-007 TEST-PG 硬门（`docs/evidence/CW007-EVIDENCE.md`） |
| 改动文件 | 2 文件（+618/−9）：`server/app/db_pg.py`（+77/−8）、`server/tests/test_db_pg.py`（+541/−1）——这两个数字**三次 rebase 后逐字未变**；另新增本证据文件（+375/−0，新建文件故 insertions = 行数）与 §18 账本 CW-055 行（+1/−1）。PR 合计 **4 文件 +994/−10**（375+1+77+541 / 0+1+8+1）。**零迁移文件改动**，`db_portable.py`/`customer_fence.py`/`auth.py`/`generation_worker.py`/`bootstrap.py` 全部零改动 |
| 失败测试或回归锁定 | 新增 15 用例（12 项挂 `pg_hard_gate` + 3 项纯静态/纯配置）。RED 阶段 **6 failed / 9 passed**，其中 4 项为真实实现缺口（`ImportError: POOL_TIMEOUT_ENV` / `POOL_TIMEOUT_CEILING`），2 项为测试自身写法缺陷（已修正，见 §8）。GREEN 阶段 **15 passed**；专项合跑 **164 passed** 零回归 |
| 实现结果 | §2 交付明细；§3 缺口盘点；§4 SQLSTATE 矩阵；§5 提交边界证明；§6 池耗尽与连接卫生；§7 缺 PG 硬失败 |
| 验证命令与通过数 | 见 §8。ruff check / ruff format --check / mypy 全过；专项 164 passed；服务端全量 pytest 见 §8.1；**CI 三门禁实测见 §8.4**（head `a3ccc5c`：Linux 4 分片全量 **2257 passed / 1 skipped / 0 failed / 0 errors**，三门禁全绿）；**第二轮 CI 的 Linux 门 failure 及其归因与处置见 §8.5**（判定为 main 侧既有 flake，已由 CW-019 在 main 修复） |
| 证据层级 | **AUTOMATED_VERIFIED**（真实 PG 16.15 上取得 RED→GREEN 轨迹与矩阵证据，无 staging/真实链路依赖）。不提升 `STAGING_VERIFIED`：生产/staging 切换归 CW-051 且需人工授权 |
| 安全与可观测性 | 无真实 API key/激活码/设备或 session token 进入代码、日志、测试夹具或 PR。新增能力即脱敏本身：池耗尽 WARNING 经 `redact_postgres_dsn` 输出，`test_pool_exhaustion_logs_a_redacted_diagnostic` 双向钉住（口令**不得**出现、脱敏 DSN **必须**出现），口令由 DSN 解析取得而非写死，兼容本机 `devpass` 与 CI `testpass` |
| 迁移与回滚 | **零迁移文件改动**（未新增 revision，未触碰冻结区间）。改动纯增量：新增 `POOL_TIMEOUT_ENV` 旋钮（默认值与改动前完全一致，未配置时行为不变）+ 池耗尽 WARNING 日志。回滚 = revert 本分支 |
| 外部授权记录 | 无（不涉及真实 ZPay / 付费 Provider / 生产 COS 变更 / 对外发码 / 灰度扩大 / 公网发布） |
| 未测试项 | `cargo test`、`npm audit`、客户浏览器 E2E、`npm run build`、前端 biome/vitest —— 均**只在 CI 三门禁执行**；本任务前端与 Rust 侧零触碰。**CI 后逐项消解见 §8.4.3**：前端 biome/vitest/tsc 与 `cargo fmt --check`+`cargo check` 已实际执行；`cargo test`、浏览器 E2E、`npm run build`、`npm audit` 4 项被 path-filter 正当跳过，义务留 CW-045 最终候选，**本文件未将其记为已验证** |
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

**全量绿的最终判定权在 CI**：上述 72 项在 CI Linux（`postgres:16-alpine` + `scripts/pg-fixture.sh` 的 `testuser@5433` + 已装 ffmpeg + UTF-8 locale + `/usr/bin/env` 存在）条件下预期全绿，但**本机无法证明**，故本文件不以「全量绿」作结，只声明「本分支相对基线零回归」，全量门禁结果留待 push 后由 CI 出具（见 §1 未测试项）。**→ CI 已出具，实测结果见 §8.4：72 项在 CI Linux 全部转 passed，本节的环境归因由实测证实，不再停留在推断。**

### 8.2 RED 阶段两处测试自身缺陷（诚实登记）

RED 的 6 项失败中有 2 项**不是**产品缺口，而是初版测试写法错误。登记以免后续复用同一夹具时重犯：

| 用例 | 初版错误 | 现象 | 修正 |
| --- | --- | --- | --- |
| `test_failed_transaction_does_not_poison_the_returned_connection` | 把 `CREATE TABLE t055_poison` 放进**将被回滚**的那个事务里 | `psycopg.errors.UndefinedTable: relation "t055_poison" does not exist`——测的是 DDL 回滚，不是池卫生 | DDL 与 `TRUNCATE` 前置到一个独立已提交事务 |
| `test_sqlstate_recovery_matrix[40001_serialization_failure]` | SERIALIZABLE 事务只**读** `t055_serial`，写入却落在 `t055_ledger`/`t055_balance`（不同键） | `Failed: DID NOT RAISE Error`——未构成 SSI 依赖环，PG 不报 40001 | 补「同键写回」`UPDATE t055_serial SET v = v + 100 WHERE id = 1`，与既有 `test_pg_transaction_serializable_write_conflict` 同构 |

### 8.3 mypy 发现并修复的类型缺口

`ConnectionPool.conninfo` 在 psycopg_pool 3.3 的类型是 `str | Callable[[], str]`（callable 形态用于轮换凭据）。直接把 `pool.conninfo` 传给 `redact_postgres_dsn(dsn: str)` 被 `mypy --strict` 拒绝：`Argument 1 … has incompatible type "str | Callable[[], str]"; expected "str"`。修复：新增 `_redacted_pool_dsn(pool)` 把两种形态收敛成 `str` 再交给唯一脱敏器，避免在日志路径上散落 `callable()` 判断，也保证将来若启用凭据轮换不会静默丢失脱敏。

### 8.4 CI 三门禁实测结果（兑现 §8.1.3 的「判定权在 CI」）

§8.1.3 明确把全量绿的最终判定权交给 CI，本节登记 CI 实际出具的结果，不使用旧 SHA 的通过态代替当前结果（COORD §5）。

首次 push 的运行（head `a3ccc5c`，base `e06b13c`，PR #13，`mergeable=true` / `mergeable_state=clean`，run `34490151124`）。工作流为**分支内**的 `.github/workflows/ci.yml`，即含 PR #8（`2751200`）path-filter + 4 分片 pytest 的版本，不是旧的单进程门禁：

| 门禁 | Job ID | 结论 |
| --- | --- | --- |
| Secret scan | `102914472934` | **success** |
| Linux quality gate | `102914551757` | **success** |
| Windows Tauri and NSIS | `102914551747` | **success**（`DESKTOP_CHANGED=false`，14 个构建步骤按 path-filter 跳过，门禁本身保持绿） |
| Select runner / Detect changes | `102914473001` / `102914472620` | success |

#### 8.4.1 Linux quality gate 步骤级结果

| 步骤 | 内容 | 结论 |
| --- | --- | --- |
| 10 Run static quality checks | `npm run check:static` 全链 | success |
| 11 Run sharded PostgreSQL pytest | 4 分片并行，每片独立 PG 容器 | success |
| 12–17 | E2E PG fixture / Playwright 安装 / 浏览器 E2E / `cargo test` / `npm run build` / `npm audit` | **skipped**（path-filter：本任务未改桌面与前端文件） |
| 18 Stop PostgreSQL fixture | — | success |

步骤 10 的逐项实测输出（`check:static` = `verify_no_secrets.sh` + client `check` + `check:e2e` + `check:tauri` + ruff×2 + mypy）：

```
bash scripts/verify_no_secrets.sh      通过（无输出即无命中）
biome check .                          Checked 199 files in 1238ms. No fixes applied.
tsc -b && vitest run                   通过
biome check e2e                        通过
cargo fmt --check && cargo check       Finished `dev` profile [unoptimized + debuginfo] in 1m 18s
ruff check server                      All checks passed!
ruff format --check server             295 files already formatted
mypy server/app                        Success: no issues found in 104 source files
```

注意 `check:tauri` 只是 `cargo fmt --check` + `cargo check`，**不等于** `cargo test`（后者是被跳过的步骤 15）；`check:e2e` 只是 `biome check e2e` 静态检查，**不等于**浏览器 E2E（被跳过的步骤 14）。二者不可互相顶替，详见 §8.4.3。

#### 8.4.2 分片全量 pytest：2258 项账目与本机 72 项的闭环

`scripts/ci/run-pytest-shards.sh` 以 4 分片并行，每片连自己的 `postgres:16-alpine` 容器（端口 5433–5436，库 `customer_v3_test`，角色 `testuser`），PG 大版本与本机 16.15 一致；分片清单为已提交评审的 `scripts/ci/test-shards/shard-{0..3}.txt`：

| 分片 | 测试文件数 | 结果 | 耗时 |
| --- | :-: | --- | --- |
| shard 0（含 `tests/test_db_pg.py`） | 24 | **659 passed**, 1 warning | 617.84s |
| shard 1 | 23 | **529 passed**, 1 warning | 625.75s |
| shard 2 | 26 | **511 passed, 1 skipped**, 1 warning | 647.74s |
| shard 3（含 `test_customer_fencing.py`、`test_db_portable.py`） | 26 | **558 passed**, 1 warning | 571.03s |
| 合计 | 99 | **2257 passed, 1 skipped, 0 failed, 0 errors** | `==> All 4 shards passed.` |

与 §8.1 本机全量的账目对照：

| 运行环境 | failed | passed | skipped | errors | 合计 |
| --- | :-: | :-: | :-: | :-: | :-: |
| 本机 Windows + Docker PG 16.15（§8.1） | 34 | 2181 | 5 | 38 | **2258** |
| CI Linux 4 分片 + PG 16-alpine | **0** | **2257** | **1** | **0** | **2258** |

两侧**测试项总数完全相同（2258）**，账目闭合：本机 `34 failed + 38 errors = 72` 项在 CI 上**全部转为 passed**（本机 5 skipped 中 4 项在 CI 执行并通过、1 项仍 skip，故 CI 侧 `2181 + 72 + 4 = 2257`）。这与 §8.1.1 基线对照实验得到的「72 = 72、测试 ID 集合相等、对称差为空」逐数吻合，构成**独立第三方取证**：

- §8.1.3 的**预期**（ffmpeg 存在 + UTF-8 locale + `/usr/bin/env` 存在 + `testuser@5433` 基座 → 72 项全绿）已被 CI **实测证实**，归因从论证升级为事实；
- 同时反证这 72 项确属 **Windows 本机环境/仓库可移植性缺陷**，与 CW-055 的改动无因果关系——CI 侧 `tests/test_db_pg.py` 所在分片 659 项零失败。

诚实边界（两处，不夸大）：

1. 分片脚本只在**失败时**才 `cat` 分片日志，故 CI 侧只留下**分片级**汇总数，没有 `tests/test_db_pg.py` 的单文件计数。CW-055 新增 15 用例的逐项 RED→GREEN 轨迹仍以 §8 本机实测（15 passed / 1.72s）为证据来源；CI 证明的是「它们所在的 24 文件分片 659 项零失败」。
2. 上表是 head `a3ccc5c`（base `e06b13c`）的运行结果。其后为对齐 COORD §5「合并前重新确认 base、head 和有效检查」，分支又 rebase 两次：至 `eac6f4d` 得 head `f784f9d`（+ 记录本节证据的提交 `2861872`），再至 `0d08608` 得代码提交 `7d4e12b`（记录本节的证据提交在其上，为分支顶端）。**本节表格只对 `a3ccc5c` 成立，不代替其后任何 head 的结果**；`2861872` 上跑了第二轮 CI 并且 Linux 门 **failure**，其归因与处置见 §8.5；rebase 后分支顶端的三门禁以 PR #13 检查页为准。三个 head 之间 `server/app/db_pg.py`、`server/tests/test_db_pg.py` 内容逐字节相同（rebase 无代码冲突）。

#### 8.4.3 §1「未测试项」在 CI 后的实际消解（逐项，不含糊）

§1 曾把 5 项列为「只在 CI 三门禁执行」。CI 的 path-filter 并未全部执行它们，故逐项更正，避免把「门禁绿」误读成「这些都验过了」：

| §1 未测试项 | CI 在 head `a3ccc5c` 上的实际 | 义务去向 |
| --- | --- | --- |
| 前端 biome/vitest | **已执行**（步骤 10：`biome check .` 199 files、`vitest run`、`tsc -b`） | 已消解 |
| `cargo test` | **仍未执行**（步骤 15 skipped）。已执行的 `check:tauri` 只是 `cargo fmt --check` + `cargo check` | CW-045 最终候选 |
| 客户浏览器 E2E | **仍未执行**（步骤 14 skipped）。已执行的 `check:e2e` 只是 `biome check e2e` | CW-045 最终候选 |
| `npm run build` | **仍未执行**（步骤 16 skipped）。`tsc -b` 只覆盖类型构建，不产出制品 | CW-045 最终候选 |
| `npm audit` | **仍未执行**（步骤 17 skipped） | CW-044（CI 收口）/ CW-045 |

4 项被跳过是 path-filter 对「server-only 改动」的**正当**结果，不等于义务消解；Windows NSIS 门禁同理（`DESKTOP_CHANGED=false` → 构建步骤全跳过但 job 结论为 success）。这些门禁在最终候选 SHA 上仍须真实执行（COORD §2.4 CW-045）。

#### 8.4.4 三门禁结论

head `a3ccc5c` 上 secret / Linux 质量 / Windows NSIS **三门禁全绿且无一失败步骤**。合并仍须 COORD §5 要求的**独立评审**与由用户或已授权执行者完成的 squash merge；本文件不代为签认（见 §10）。该结论**不外推**到其后的 head，见 §8.5。

### 8.5 第二轮 CI（head `2861872`）Linux 门 failure 的完整归因与处置

§8.4 记录的是 head `a3ccc5c`。其后 rebase 至 `eac6f4d` 并追加证据提交 `2861872`，触发第二轮 CI，**Linux 质量门 failure**。本节登记事实、归因与处置，不以 §8.4 的全绿态掩盖它。

#### 8.5.1 第二轮事实（run `34493487488` / job `102925977210`，head `2861872`，base `eac6f4d`）

| 门禁 | 结论 |
| --- | --- |
| Secret scan | success |
| Windows Tauri and NSIS | success（`DESKTOP_CHANGED=false`，构建步骤按 path-filter 跳过） |
| Select runner / Detect changes | success |
| **Linux quality gate** | **failure** |

Linux job 内：步骤 10 静态门 **success**（15:10:25→15:12:41Z）；**步骤 11 分片 pytest failure**（15:12:41→16:02:14Z，49.5 分钟，**未撞 60 分钟 job 上限**，非超时）；步骤 12–17 skipped。

| 分片 | 结果 | 耗时 |
| --- | --- | --- |
| shard 0 | PASS 659 passed | 2767.79s（§8.4 同分片为 617.84s，**慢 4.5 倍**） |
| shard 1 | PASS 529 passed | 2822.65s |
| **shard 2** | **FAIL(rc=1) 1 failed / 510 passed / 1 skipped** | 2937.22s |
| shard 3 | PASS 558 passed | 2228.07s |

shard 0/1/3 的通过数与 §8.4 **逐项完全一致**（659/529/558），只有 shard 2 恰好一个用例翻面（§8.4 为 511 passed / 0 failed）。失败用例：

```
FAILED server/tests/test_bootstrap_all_env_pg_gate.py::test_concurrent_api_worker_startup_does_not_race_schema_migration
E   AssertionError: 并发启动 2 失败: the pool 'video-replica-pg' is closed
E   assert PoolClosed("the pool 'video-replica-pg' is closed") is None
```

#### 8.5.2 归因：main 侧既有 flake，**不是 CW-055 引入**（七条独立证据）

1. **改动面不含该文件**。本 PR 相对 main 只有 4 文件（`docs/evidence/CW055-EVIDENCE.md`、账本 1 行、`server/app/db_pg.py`、`server/tests/test_db_pg.py`）。`server/app/bootstrap.py` 与 `server/tests/test_bootstrap_all_env_pg_gate.py` 均**不在其中**。
2. **关池点未被本任务触碰**。竞态的一端是 `bootstrap.py:618` —— `_run_runtime_bootstrap()` 结尾**无条件**调用 `close_pg_pool()`（注释「bootstrap is a short-lived process: release the pooled connections before exit (M0 review M2)」），另一端是 `db_pg.py` 的 `close_pg_pool()`。二者都不落在 CW-055 的任何 hunk 内（hunk 覆盖新行 317–323 与 352 起）。
3. **新旋钮在 CI 中处于默认态**。`VIDEO_REPLICA_PG_POOL_TIMEOUT` 全仓仅出现于 `db_pg.py:39` 的常量定义，`.github/`、`server/tests/conftest.py`、`deploy/`、`scripts/` 均未设置它 → CI 中 `_pool_timeout()` 返回 `DEFAULT_POOL_TIMEOUT`，与改动前 `timeout=DEFAULT_POOL_TIMEOUT` 硬编码**逐位等价**。
4. **异常类型不同，新分支不会捕获它**。CW-055 新增的是 `except PoolTimeout`（借用超时）；本次失败是 `PoolClosed`（池已关闭），两者是 `psycopg_pool.errors` 下的不同类。且该分支只记一条脱敏 WARNING 后 `raise`，**不改变任何控制流**。
5. **同一份代码在 `a3ccc5c` 上通过**。§8.4 的 shard 2 是 511 passed / 0 failed。`a3ccc5c` 与 `2861872` 之间只差一个 **docs-only** 提交（`git diff --stat` 只含 `docs/`），被测代码逐字节相同。
6. **main 自身独立复现同一失败**。`main@e06b13c`（CW-017 #9，run `34474527736` / job `102863607112`）Linux 门 **failure**，失败步骤同为步骤 11，shard 2 记 `1 failed, 510 passed, 1 skipped, 1 warning in 591.86s`，失败用例与错误消息**逐字相同**（`test_concurrent_api_worker_startup_does_not_race_schema_migration` / `PoolClosed("the pool 'video-replica-pg' is closed")`），计数与本轮逐项一致。该 commit 不含本任务任何改动。
7. **同代码不同结果 ⇒ flake 而非确定性红**。`main@91eab3f`（COORD-SCHEDULE #10 = `eac6f4d` + 8 份纯文档）的 Linux 门 **18 步全部执行且全 success**，含步骤 11 分片 pytest、步骤 14 浏览器 E2E、步骤 15 Rust tests。代码面与 `eac6f4d` 相同而结论相反，只能由非确定性解释。同理 `main@eac6f4d` 自身的 Linux 门 failure 落在**步骤 10** 的 vitest（`src/studio/StudioWorkspace.test.tsx` 报 `Unable to find role="dialog" and name "生成确认 · 数字人口播"`，1 failed / 78 passed），而本 PR 第二轮在**同一 base** 上步骤 10 为 success；CW-019 的 §18 账本行也自述该 vitest 时序 flake 曾「完全掩盖」其后端断言失败。

竞态机制（在 main 自身代码中可直接读出，非推断）：该测试用 3 个 `threading.Thread` **并发**调用 `bootstrap._run_runtime_bootstrap()`，三者共享模块级单例连接池 `video-replica-pg`；线程 A 执行到 `bootstrap.py:618` 关闭全局池时，线程 B 仍在池中借用连接 → `PoolClosed`。慢 runner（本轮 shard 耗时为 §8.4 的 4.5 倍）拉长了窗口，故本轮才暴露。

#### 8.5.3 该 flake 已由 CW-019 在 main 修复（本任务不越界自行修）

`origin/main@0d08608`（CW-019 #12）内含一个独立子提交：

> **`fix(CW-025): stabilize bootstrap concurrency test — serialize 3 calls instead of 3 threads`**
> 「The test … launched 3 threads concurrently calling `_run_runtime_bootstrap()`, all sharing the module-level global pool 'video-replica-pg'. Thread A closes/recreates the pool while Thread B is mid-use → PoolClosed race. … **the race is unrelated to CW-019 or CW-018 code changes** but was blocking PR #12's gate.」

它把测试改名为 `test_api_worker_startup_does_not_race_schema_migration`，将 3 线程并发改为**串行调用 3 次**（核心断言「零次 `alembic upgrade`」保留），并在 docstring 记下根因：「全局连接池 `video-replica-pg` 为模块级单例，并发 3 线程共用同一 pool 会导致 PoolClosed 竞争（CI transient flake #34490081699）」。

这与 §8.5.2 的独立定位逐字吻合，且 CW-019 作者明确声明该竞态与业务代码改动无关 —— 构成对「非 CW-055 引入」的**第三方印证**。

本任务**不自行修它**：该测试属 CW-025、`bootstrap.py` 属运行时引导，二者都在 CW-055 的文件边界之外（COORD §5「只补明确差额」与认领登记的文件边界）。修它会让本 PR 夹带跨任务改动，squash 后与他人在 main 上的同一修复重复。

#### 8.5.4 处置：第三次 rebase 至 `0d08608`

不采用「重跑失败 job 刷绿」——那是在 flake 上赌博，且违反 §5「不能用旧 SHA 通过代替当前结果」的精神。改为 rebase 到已含修复的最新 main，一次同时满足 §1「新分支必须从更新后的 origin/main 创建」与 §5 line 160「合并前重新确认 base、head 和有效检查」：

| 核验项 | 结果 |
| --- | --- |
| rebase 冲突 | **0**（`Successfully rebased`，`diff --diff-filter=U` 为空，全仓无冲突标记） |
| 新 base / 代码提交 | `origin/main@0d08608` / `7d4e12b`；`merge-base --is-ancestor origin/main HEAD` = **True**。分支顶端为记录本节的证据提交（一个提交无法包含自己的 SHA，故此处不写死，实际 head 以 PR #13 检查页与 claim.json 登记为准） |
| 本分支提交数 | **2**（`7d4e12b` 代码 + 证据提交），无外来提交 |
| diff 面 | 仍精确 **4 文件**，与 rebase 前逐项相同（rebase 刚完成时为 +915/−10；计入本节 §8.5 证据后最终为 **+994/−10**）。两个代码文件的 +77/−8 与 +541/−1 **三次 rebase 后逐字未变** |
| flake 修复已继承 | `test_bootstrap_all_env_pg_gate.py:190` 为 `test_api_worker_startup_does_not_race_schema_migration`；`threading.Thread` 在该文件**零残留** |
| CW-019 的 CI 改动是否伤及本 PR | 否。CW-019 给 `ci.yml` 新增 `Build admin bundle` 与 `Verify customer bundle excludes admin and internal entries` 两步，二者**均门控 `if: needs.changes.outputs.desktop == 'true'`**；本 PR 是 server-only（`desktop=false`）故两步跳过，不产生 CW-019 自述的「构建被跳过而断言照跑」语义破损 |
| 本地复验（base `0d08608`，rebase 后、push 前） | `bash scripts/verify_no_secrets.sh` → `No hardcoded secrets detected in runtime contract surface.`，**EXIT=0**；专项 `tests/test_db_pg.py`+`test_customer_fencing.py`+`test_db_portable.py` → **164 passed / 1 warning / 59.10s**，与历次专项计数一致，**零回归** |
| 第二轮失败用例在本机的直接复验 | `tests/test_bootstrap_all_env_pg_gate.py` → **50 passed / 1 skipped / 1.20s**（rc=0）；再以 `-k race_schema_migration` 定向确认它真被执行而非被 skip：`collected 51 items / 50 deselected / 1 selected` → `test_api_worker_startup_does_not_race_schema_migration` **PASSED**。即 §8.5.1 失败的那个用例，在其串行新形态下本机通过 |
| 测试资源隔离 | PG 用 `vs-pg-dev` 端口 **5434**（`TEST_POSTGRESQL_URL=postgresql://devuser:devpass@localhost:5434/customer_v3_test`），与同时存活的 `vs-pg-cw056`(5435)、`vs-pg-cw031`(5436) 及 CI 收敛线(5433) 全部隔离；cwd 锁定本 worktree 的 `server/`（专用 runner `.dev-env\run-cw055-pytest.ps1`），**未落到正被 CW-056 占用且带未提交改动的主 worktree**；Windows `fcntl` shim 仍经仓外 `.dev-env\pyshim` 的 `PYTHONPATH` 注入，仓内零改动 |

#### 8.5.5 结论与未消解项

- §8.4 的全绿结论只对 head `a3ccc5c` 成立；head `2861872` 的 Linux 门为 **failure**，本文件如实登记，不隐藏。
- 该 failure 经七条证据判定为 **main 侧既有 flake**，与 CW-055 无因果关系，且已由 CW-019 在 main 修复。
- **rebase 后分支顶端的三门禁结果以 PR #13 检查页为准**，本文件不以 `a3ccc5c` 的通过态代替，也不预先声明新 head 全绿。
- §8.4.3 的 4 项未执行义务（`cargo test`、浏览器 E2E、`npm run build`、`npm audit`）在新 head 上预期**仍未执行**（server-only → path-filter 跳过），另加 CW-019 新增的 2 个 admin bundle 步骤同样跳过；义务仍留 CW-044/CW-045，**未记为已验证**。
- 旁证：`main@91eab3f` 的 push 事件下 18 步全跑（push 无 base 故 path-filter 全真），说明这 4 项在 main 的 push 流水线上确会真实执行 —— 但那是 main 的证据，不能顶替本 PR 的验证。

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
