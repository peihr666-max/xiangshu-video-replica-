# CW-042 只读范围盘点与就绪度评估（INVENTORY_ONLY）

> **本文性质**：CW-042「裁剪已无在线消费者的 SQLite 实现」的**只读**前置盘点。
> 盘点基线 `origin/main = 475f995`（2026-09-12 fetch；初始开分支于 `c3be59f`，盘点期间 main 前进一个提交 `475f995` MIGRATION-GUARD-20260912 (#69)，已 rebase 并按 §9 复核受影响计数）。
> **零 `server/app/` 代码改动、零测试改动、零迁移改动**——本文只读源码与账本，产出范围界定与就绪度判定。
> **不声称 CW-042 已实施、已验收或已具备开工授权。** 实施仍须先取得 §2.4 的 owner 签认。
>
> **提前盘点的依据**：排班清单 §2.3 L68 已确立先例——「044 的**只读方案分析可以提前**；创建实现分支仍须等待适用正式前置合入 main」。本文对 CW-042 沿用同一原则，并遵守认领登记 §2 L30「前置未满足登记 WAITING 原因，**不创建实现分支**」：本分支 scope 为 `INVENTORY_ONLY`，非实现分支。

---

## 1. 就绪度判定

**结论：技术闸门已解除（8/9 前置合入 main），治理闸门未解除（CW-039 缺位 + CW-001 P1 签认反向约束）。不具备直接开工条件，具备立即盘点条件（即本文）。**

### 1.1 九项正式前置逐项实测

排班清单 §2.4 L104 定义 CW-042 正式前置为：CW-025、CW-031、CW-039、CW-043、CW-054、CW-055、CW-056、CW-057、CW-060。

以 `git log origin/main` 提交历史为准（**不以账本 §18 声明为准**，理由见 §1.2）：

| 前置 | 账本 §18 声明 | **main 实测** | squash SHA / PR |
| --- | --- | --- | --- |
| CW-025 全环境 PG 入口 | `[ ]` 待实施 | ✅ 已合入 | 见 `CW025-EVIDENCE.md` |
| CW-031 云端资产/授权下载 | `[ ]` 待实施 | ✅ MERGED+CLEANED | `f5e24c9` (#17) 交付 + `fd90a94` (#42) claim 回填 |
| CW-054 查询/行/异常契约 | `[ ]` 待实施 | ✅ 已合入 | `91014f6` (#14) |
| CW-055 事务/池/fencing | `[ ]` 待实施 | ✅ 已合入 | `e829ad1` (#13) |
| CW-056 升级矩阵 | `[ ]` 待实施 | ✅ 已合入 | `d3d66b2` (#15) |
| CW-057 维护/种子 CLI | `[ ]` 待实施 | ✅ 已合入 | `8ab85c7` (#19) |
| CW-060 隔离历史 SQLite 工具 | `[ ]` 待实施 | ✅ 已合入 | `d49f851` (#27) |
| **CW-043 全业务 PG 覆盖核销** | `[ ]` 待实施 | ✅ **Seg 1+2+3 与 Seg 4+ 均已合入** | `1389f98` (#43) + `2be7c3d` (#46) |
| **CW-039 副本演练与回滚手册定版** | `[ ]` 待实施 | ❌ **零提交，未完成** | main 历史无任何 CW-039 记录 |

**CW-043 是四处文档共同点名的 CW-042 真实技术闸门，现已打开：**

- 排班清单 §2.3 L80：「042 **完整清理仍等 043**」
- 开发计划 L269：「**CW-043 先于 CW-042**」
- 开发计划 L257 新顺序：「…CW-058/059 与 CW-060 → **CW-043 覆盖核销 → CW-042 去 SQLite** → CW-044/045 硬门」
- CW-053 §3 E2 退役条件：「**CW-043 全业务 PG 覆盖核销** + CW-042 执行裁剪」
- CW-025 完工标准（`CUSTOMER-TASK-EVIDENCE-V3.md` L47）：「最终 SQLite 在线实现移除**须等 CW-043**」

### 1.2 账本 §18 滞后发现项（提交集成人集中回填）

**本节不自行修改公共账本。** 依据 AGENTS.md 标准工作流第 8 条：「多任务并行时，**公共账本由集成人在对应 PR 内集中回填**，各任务提供独立证据」；且 `git log` 显示 `COORD-STATUS-AUTO`（最近 round 25，`da21017`）为在运行的自动登记机制。本任务非集成人 PR，故仅登记发现项，避免与自动轮次互相覆盖（历史已有 COORD-STATUS-AUTO 污染 §17 的教训）。

**发现项：§18 有 7 项已 squash 合入 main 却仍标 `[ ] 待实施与验收`**

| 账本行 | 任务 | §18 现值 | 应为 | 证据 SHA |
| --- | --- | --- | --- | --- |
| L496 | CW-031 | `[ ]` 待实施与验收 | 已 squash 合并入 main | `fd90a94` (#42) |
| L498 | CW-054 | `[ ]` 待实施与验收 | 已 squash 合并入 main | `91014f6` (#14) |
| — | CW-055 | `[ ]` 待实施与验收 | 已 squash 合并入 main | `e829ad1` (#13) |
| — | CW-056 | `[ ]` 待实施与验收 | 已 squash 合并入 main | `d3d66b2` (#15) |
| L501 | CW-057 | `[ ]` 待实施与验收 | 已 squash 合并入 main | `8ab85c7` (#19) |
| L509 | CW-060 | `[ ]` 待实施与验收 | 已 squash 合并入 main | `d49f851` (#27) |
| L513 | CW-043 | `[ ]` 待实施与验收 | Seg 1+2+3 与 Seg 4+ 均已合入 | `1389f98` (#43) + `2be7c3d` (#46) |

**回填时须同时核对 §17 与 §18 两行**：§17（V2 历史定义表，4 列）实施状态列只能是指针「转入§18同编号」，§17 L418 明文规定「当前实施状态只在 §18 登记」；§18（权威实时状态表，5 列）写最终合并状态。`grep "CW-0NN | W?"` 会命中两处，`Select -First 1` 只看第一处会误判。

**影响**：此滞后使每个后续开发者都必须重跑一遍 §1.1 的 git 取证才能判断前置是否齐备。建议随下一轮 COORD-STATUS-AUTO 集中回填。

---

## 2. CW-039 依赖性质分析与松绑申请

### 2.1 CW-039 为何是 CW-042 的正式前置（实质耦合，非形式挂名）

CW-056 的「零触碰」登记把 `server/scripts/sqlite_to_postgres.py`、`server/scripts/reconcile_customer_billing.py` 明确划归 **CW-034—039 / CW-060**；CW-053 §3 E4 同列为「历史 operator 导入/对账工具」。CW-039 的交付物是「副本演练与**切换回滚手册定版**」，而该手册的重建/回滚路径依赖 SQLite→PG 只读导入工具。CW-042 提前改动 SQLite 实现面，会侵蚀一条**尚未定版**的回滚路径。

同时注意：CW-040（前置含 CW-039）、CW-041（前置含 CW-039）与 CW-042 同属 W6 清理组。**CW-039 是整个 W6 物理清理链的共同闸门**，不是 CW-042 被单独卡住。

### 2.2 CW-039 在 pre-GA 阶段结构性不可完成

CW-039 前置为 CW-034/035/036/037/038，逐层展开：

- **CW-033**：账本 §18 L502 为 `[~] Pre-GA 准备完成 AUTOMATED_VERIFIED`，明文「`pg_ctl`/真实 `pg_basebackup`/WAL 归档取回/100 事实核验等 **GA 触发·冻结项未执行**」；实际恢复演练「待 CW-005 §5 数据批次盘点 + A/B/C 路线签认后启动」，且**阻塞于演练环境授权**（隔离机 + 空 PG16 + off-site archive）。
- **CW-005**：账本 §18 L472 明文「实际批次盘点 **pre-GA 无生产访问、GA 触发**」。
- **CW-034/035/036**：均为**条件任务**（按数据批次选 A/B/C），路线尚未签认。
- **CW-038**：前置含 CW-033 + CW-034/035/036。

⇒ CW-039 在 pre-GA 无法闭环。若按字面 9 项前置严格执行，CW-042 将直至 GA 之后才可开工。

### 2.3 CW-001 §6 P1 签认**不构成**提前授权（反向约束）

`CW001-RELEASE-BASELINE.md` §6 L206 与 §7 L213 签认原文：

> P1 | CW-044 依赖松绑 | pre-GA **仅要求** CW-040/041/042「**入口 fail-closed**」，**物理删除延后为独立清理批次** | 依据 data-deploy-audit §6「先关入口，物理清理另起追加迁移」；松绑后 CW-044 可在功能收敛后收口唯一客户 CI，不必等物理删除

已签认（owner phlong026，2026-09-09）。三点必须厘清：

1. **松绑对象是 CW-044 对 040/041/042 的依赖**，不是 CW-042 自身的前置链。
2. §5.3 锚点 3「内部/SQLite/sidecar 入口 fail-closed」明文「**关入口即可，物理删除延后**」，且其承载任务为 **CW-015/021/026**，不含 CW-042。
3. CW-042 的任务定义即「裁剪/移除 SQLite **业务运行实现**」= 物理删除本体。

⇒ **按现行签认，CW-042 的实体工作被显式推迟。不得以 P1 为依据提前实施物理删除。**

### 2.4 申请：将 CW-042 拆为 042-a / 042-b

请求 owner（phlong026）按与 P1 同构的逻辑签认以下拆分，并记入 `CW001-RELEASE-BASELINE.md` §6/§7：

| 子任务 | 范围 | 前置 | 时点 |
| --- | --- | --- | --- |
| **042-a** 入口 fail-closed 收口 | 仅收紧 internal/desktop lane 的 SQLite 回退入口，使其在客户生产 fail-closed；**不删除** `app/db.py`、`SQLiteBackend`、`translate_to_sqlite` | CW-025✅、CW-043✅、CW-054~057✅、CW-060✅（**8/9 已齐，不含 CW-039**） | pre-GA 可执行 |
| **042-b** 物理删除（原 CW-042 本体） | 本文 §3.1 全部可删项 + §4 三把锁同步处置 | 追加 **CW-039** + CW-040/041 入口关闭证据 | GA 触发后独立清理批次 |

**签认收益**：042-a 与锚点 3「关入口即可」完全一致，可立即消解 §1.2 之外的在线回退面；042-b 保留 CW-039 约束不动，回滚手册定版前不触碰实现本体。

**未获签认前**：CW-042 在认领登记中记 `WAITING`，原因为「CW-039 未合入 main；CW-001 P1 已将物理删除延后为独立清理批次」。

---

## 3. 裁剪清单（三栏界定）

CW-053 §3 E2 定义 CW-042 本体范围为：`server/app/db.py` **全部** + `server/app/db_portable.py` 的 `SQLiteBackend` / `translate_to_sqlite` / `_is_begin_immediate` / `_is_sqlite_pragma`。以下按「可删 / 永久保留 / 越界他任务」三栏精确界定，实测于行号级。

### 3.1 可删（CW-042 本体，042-b 范围）

| 对象 | 位置 | 规模 | 处置要点 |
| --- | --- | --- | --- |
| SQLite 兼容层本体 | `server/app/db.py` 全文件 | **53 行 / 5 符号**：`connect_database`(L13)、`initialize_database`(L26)、`upgrade_database`(L35)、`alembic_config`(L42)、`_sqlite_url`(L49) | 删文件前得先摘除 §3.1.1 的 8 个消费者（其中 6 个属本体） |
| SQLite 后端类 | `app/db_portable.py` `SQLiteBackend`(L259) | 文件共 **650 行**；类内引用 L481/525/530/534/552/557/566/578/618/629/649 | 全部在 db_portable.py 内部，无 app 外部直接引用 |
| SQL 方言翻译器 | `app/db_portable.py` `translate_to_sqlite`(L69) | 定义 L69；**实际调用点仅 L266、L526，均在 db_portable.py 内部**；L10/L57 为 docstring 提及 | **app 侧无外部消费者**；`viral_store.py:L9` 仅为 docstring 文字提及（非 import，实测该文件 `translate_to_sqlite(` 调用点为 0），改文案 1 行即可。真正阻力在测试侧（§5.2） |
| SQLite 事务/PRAGMA 判据 | `app/db_portable.py` `_is_begin_immediate`(L402)、`_is_sqlite_pragma`(L406) | 2 函数 | 随 `SQLiteBackend` 一并摘除 |
| 异常双继承的 sqlite3 基类 | `app/db_portable.py` `IntegrityConstraintError`(L216)：`class ...(sqlite3.IntegrityError, psycopg.IntegrityError)` | 1 处基类 | CW-054 §3.1/§13.4 明文「过渡性设计，CW-042 退役 SQLite lane 后摘除 sqlite3 基类」；摘除后仅继承 `psycopg.IntegrityError` |
| 本地设置密钥派生 | `app/local_settings_key.py` | — | CW-053 L120「CW-042 核销消费者后裁剪」；**但见 §5.1 的 conftest autouse 耦合，不可直接删** |
| settings 本地 keystore 分支 | `app/settings.py` L16/L387/L400-405 | 6 处 | CW-053 L142「CW-054 类型债务核销 → CW-042 裁剪」 |
| internal/desktop lane SQLite 回退分支 | 见 §3.1.1 | app/ 内 `connect_database(` 共 **10 处**（含 `db.py` 自身定义 L13 + 内部调用 L32 ⇒ **外部调用 8 处**）；`BusinessConnection.sqlite(` **8 处** | 全部经 `BusinessConnection.sqlite(...)` 包裹（CW-055 登记） |

#### 3.1.1 `app.db` 的 8 个 app 侧消费者（逐调用者先红后绿）

实测命令：`Get-ChildItem app -Recurse -Filter *.py | Select-String "from app\.db import"`（递归，含子目录）。

| # | 文件:导入行 | 导入符号 | SQLite 调用点（实测） | 是否属 042-b 可删 |
| --- | --- | --- | --- | --- |
| 1 | `app/auth.py:12` | `connect_database` | **L64** `BusinessConnection.sqlite(connect_database(Path(db_path)))`（请求级 DI `get_database` 回退；缺 `VIDEO_REPLICA_DB_PATH` 时 L57-62 抛 503 `DATABASE_NOT_CONFIGURED`） | ✅ 核心 |
| 2 | `app/customer_fence.py:56` | `connect_database` | **L645、L732**（两处 `raw = connect_database(Path(db_path))` → `BusinessConnection.sqlite(raw)`；L642 错误文案仍写 “require valid SQLite configuration”） | ✅ 核心 |
| 3 | `app/rbac_routes.py:31` | `connect_database` | **L219**（signed asset grant 校验） | ✅ 核心 |
| 4 | `app/media_routes.py:19` | `connect_database` | **L472**（signed object request） | ✅ 核心 |
| 5 | `app/viral_routes.py:32` | `connect_database` | **L226**（cover enrichment，`FilePath(db_path)`） | ✅ 核心，**但触发 §4.2 锁** |
| 6 | `app/bootstrap.py:19` | `initialize_database` | **L531** `with BusinessConnection.sqlite(initialize_database(Path(db_path))) as conn:` 凭据解密自检 | ✅ 核心 |
| 7 | `app/backup.py:30` | `connect_database` | **L292、L329**（历史 SQLite 备份工具） | ❌ **越界 → §3.3 / CW-040** |
| 8 | `app/internal_accounts.py:10` | `initialize_database` | **L111** 内部账号 CLI `main()` | ❌ **越界 → §3.3 / CW-041** |

⇒ 8 个消费者中 **6 个属 CW-042 本体，2 个越界**。这是本盘点最重要的范围界定结论：若不做此区分，CW-042 会改到 CW-040/041 的地盘。

**三个易误判为消费者的非消费者（实测排除）**：

| 文件 | 表面迹象 | 实测结论 |
| --- | --- | --- |
| `app/generation_worker.py` | 大量 SQLite 语义 | **不导入 `app.db`**；L27 `from app.db_pg import (...)`、L35 `from app.db_portable import BusinessConnection` ⇒ 已是纯 PG lane，**不属 CW-042** |
| `app/publish_worker.py:102` | 出现 `app.db` 字样 | 仅为**中文注释**提及资源连接扫描，非 import |
| `app/gate1_bootstrap.py`、`app/gate1_e2e.py` | CW-053 §3 E5 登记为「当前 SQLite 入口」 | **CW-057 已实际退役**，详见 §5.3 |

### 3.2 永久保留例外（**不在 CW-042 任何子范围内**）

| 对象 | 依据 | 保留理由 |
| --- | --- | --- |
| `server/migrations/versions/*.py` 中 dialect-guarded SQLite 分支 | CW-053 §3 **E1** / 硬红线 **PG-09** | revision 哈希冻结、**字节不改**；改写会使已升级老库对不上迁移链 |
| `server/scripts/sqlite_to_postgres.py` | CW-053 §3 **E4** + CW-056 零触碰登记 | 归 CW-034—039/CW-060；「仅历史输入（TEST-IMPORT/TEST-HISTORY）**长期保留**，不进在线包」。CW-060 (#27) 已隔离为 hashed operator artifact |
| `server/scripts/reconcile_customer_billing.py` | 同上 | 同上 |
| `server/alembic.ini` 默认 `sqlalchemy.url = sqlite:///data/app.db` | `migrations/env.py:resolve_migration_url` 已令 `VIDEO_REPLICA_DATABASE_URL` 优先 | 属迁移链历史默认值；改动需与 CW-056 升级矩阵回归锁一并评估，**不建议纳入 042-b** |

### 3.3 越界他任务（CW-042 不得触碰）

| 对象 | 正确归属 | 依据 |
| --- | --- | --- |
| `app/backup.py` + `deploy/systemd/video-replica-backup.*` | CW-060 隔离 → **CW-040 退休** | CW-053 §3 **E3**；退役条件「内部停写（CW-051）后归档为可恢复非在线制品」 |
| `app/gate1_bootstrap.py`、`app/gate1_e2e.py` | **CW-057 已退役完毕**（无需再动） | CW-053 §3 **E5** 责任任务为 CW-057（转 PG 或 retire）；实测 CW-057 (#19, `8ab85c7`) **已完成退役**，两文件均不再导入 `app.db` ⇒ **不属 CW-042 范围**，详 §5.3 |
| `app/internal_accounts.py` | **CW-041** 退出内部身份 | 内部账号管理 CLI（L111 `initialize_database(args.db_path)`），属内部身份面 |
| 桌面启动器 `client/src-tauri/resources/start-backend.bat`(L6-9) / `.sh`(L9) 强制 `VIDEO_REPLICA_DB_PATH` | **CW-021 / CW-040** | 二者均**强制要求** DB_PATH 且不注入 `VIDEO_REPLICA_DATABASE_URL`；删 SQLite 回退会直接打死 desktop lane，而 CW-040/041 未做 |
| `app/auth.py` 内部身份回退、`app/main.py` 入口面 | **CW-015 / CW-021 / CW-026** | CW-001 §5.3 锚点 3 承载任务 |

---

## 4. 三把必须同步处置的回归锁（实施地雷）

删实现而不同步处置以下三把锁，会得到**假红**或**静默失去守卫**。三把锁的位置与断言均已实测定位。

### 4.1 地雷 1 — CW-056 internal-lane 防误伤回归锁

- **位置**：`server/tests/test_cw056_supported_head_matrix.py:L541`，用例 `test_internal_lane_sqlite_migration_target_still_works`
- **作用**：以 **online** 模式（非 `--sql`）对 `sqlite:///{tmp_path}/cw056_internal_lane.db` 跑 `alembic upgrade head`，即动态升至当前 `HEAD_REVISION = "089_customer_api_keys"`（同文件 L60）并读回核对；用例 docstring 自述「防止一道切将 SQLite 迁移路径连带打断」
- **CW-056 原文（§9.2）**：「`app/db.py` SQLite 兼容层…**保留不动**。被 10 个 app 模块与 30+ 测试消费，退役前 internal/desktop lane 仍受支持。故 §9.2 的客户生产门禁**刻意不做全局拒绝**，并以防误伤回归锁钉住」
- **042-b 处置**：删除 `app/db.py` 的同一提交内**必须移除本用例**，否则必红。移除须在证据中说明「CW-043 已核销 PG 覆盖，防误伤前提消失」。⚠️ **但不得连带改动同文件的模块级常量**，见 §4.4。

### 4.2 地雷 2 — CW-055 autocommit 逃生口集合锁（**需 CW-055 owner 重新评审**）

- **位置**：`server/tests/test_db_pg.py:L1272-1282`，用例 `test_pool_borrow_autocommit_escape_hatch_stays_confined`
- **断言原文**：
  ```python
  files = {site.split(":", 1)[0] for site in _scan_app_sources(_AUTOCOMMIT_PATTERN)}
  assert files == {"viral_routes.py"}, (
      f"autocommit 逃生口集合发生变化: {sorted(files)}（需 CW-055 重新评审提交边界）"
  )
  ```
- **触发条件**：042-b 摘除 `viral_routes.py:L226` 的 SQLite lane 后，`files` 变为 `set()`，断言 `== {"viral_routes.py"}` **失败**
- **关键约束**：失败消息本身即规定「**需 CW-055 重新评审提交边界**」⇒ 这**不是 CW-042 单方可改的断言**。042-b 实施前必须取得 CW-055 owner 对「例外集合归空」的重新评审签字，并把 `assert files == set()` 的语义变更记入 CW-055 证据的追加段。
- **附带**：`tests/test_cw060_operator_isolation.py:L75` 亦引用 `server/app/viral_routes.py`，CW-060 隔离清单需同步核对。

### 4.3 地雷 3 — CW-055 中途提交静态锁（前提文案失效）

- **位置**：`server/tests/test_db_pg.py:L1255-1269`，用例 `test_pg_lane_has_no_mid_transaction_commit_call_sites`
- **docstring 前提**：「任何新增的 `.raw.commit()` / `.raw.rollback()` 都必须位于门面 `db_portable.py` 内部（**且被 SQLiteBackend 分支守卫**，已由上面的 spy 用例证明）」
- **触发条件**：042-b 删除 `SQLiteBackend` 后，该用例的**守卫前提描述失效**（断言本身仍绿，因其只检查 offenders 为空）
- **042-b 处置**：属**文档性失修**而非红灯，但必须同步修订 docstring，否则留下「引用已删除符号」的注释腐化。同时 `test_cw054_pg_portable_contract.py:L37`、`test_db_pg.py:L1260` 对 `SQLiteBackend` 的引用需一并清理。

---

## 4bis. 地雷 4 —— 迁移链守卫对 `test_cw056` 的 AST 耦合（**本次盘点期间新增**）

本项在初始基线 `c3be59f` 上**不存在**，由盘点期间合入的 `475f995`（MIGRATION-GUARD-20260912，PR #69）引入，rebase 后实测确认。

- **新机制**：`scripts/ci/migration_manifest.py` 把《并行开发迁移 Head 与 PR 冲突处置手册》的人工步骤机械化，提供 `--check`（免 PG 的 CI 早期门禁）/ `--record` / `--print-schema` / `--check-schema`
- **关键设计约束（其 docstring 自述第 2 条）**：「**不拥有业务常量**。`PUBLISHED_HEAD_REVISION` / `HEAD_REVISION` / 冻结矩阵等真源仍在 `server/tests/test_cw056_supported_head_matrix.py`；本脚本从该文件 **AST 读取**它们，并**独立重算后比对**」
- **实测读取点**：`migration_manifest.py:L49` `CW056_MODULE = SERVER_DIR / "tests" / "test_cw056_supported_head_matrix.py"`；L69-76 读取 `HEAD_REVISION`、`PUBLISHED_HEAD_REVISION`、`PUBLISHED_CHAIN_LENGTH`、`HEAD_SCHEMA_COUNTS`、`HEAD_TABLE_NAMES`、`HEAD_SCHEMA_DIGEST`；L375-387 断言迁移图 head == `HEAD_REVISION` 且已发布链长 == `PUBLISHED_CHAIN_LENGTH`
- **当前真值**：`HEAD_REVISION = "089_customer_api_keys"`(L60)、`PUBLISHED_HEAD_REVISION = "055_customer_batch_visibility"`(L65)、`PUBLISHED_CHAIN_LENGTH = 54`(L66)

⇒ **对 042-b 的新增约束**：§4.1 要求从 `test_cw056_supported_head_matrix.py` 移除 `test_internal_lane_sqlite_migration_target_still_works`，而该文件现在同时是**迁移守卫的常量真源**。移除用例时：

1. **绝不可删文件或改动模块级常量赋值**（AST 读取会直接红，且 `--check` 在 CI 早期步骤）；
2. 移除后必须跑 `python3 scripts/ci/migration_manifest.py --check` 作为 B2 批次的额外验证项；
3. 若 042-b 伴随任何迁移变动（本文 §3.2 已论证不应有），需额外 `--record` 并提交 `server/migrations/manifest.json`。

---

## 5. 新发现的结构性耦合（CW-053 清单未覆盖）

以下三项在本次行号级盘点中发现，**CW-053 §3/§4 的语义清单未登记**，建议回填进 CW-053 或直接在 042-b 规格中列明。

### 5.1 `local_settings_key` 已进入测试套件 autouse fixture 层（**最高风险**）

CW-053 L120 把 `app/local_settings_key.py` 的退役条件写为「CW-042 核销消费者后裁剪」，但实测其消费者包含 **`server/tests/conftest.py`**：

```python
# tests/conftest.py:L5
from app.settings import clear_local_settings_key_cache
# tests/conftest.py:L10 —— 位于 @pytest.fixture(autouse=True) 内
clear_local_settings_key_cache()
```

`autouse=True` 意味着**全测试套件每个用例都会执行**。因此 `local_settings_key` / `settings.py` 的本地 keystore 分支不是「无在线消费者的残留」，而是**测试基建的活跃依赖**。

⇒ **042-b 不得直接删 `local_settings_key.py`**；必须先把 conftest 的 autouse 缓存清理与本地 keystore 解耦（例如改为 PG lane 无操作或迁至专用 fixture），且该改动会影响全部 104 个测试文件的收集期行为，需独立 RED→GREEN 验证。

其余消费者（实测）：`app/bootstrap.py:L31,L540`、`app/settings.py:L16,L387,L400-405`、`tests/test_local_settings_key.py`（7 处专项）、`tests/test_media.py:L1074`、`tests/test_settings.py:L224,L372`。

### 5.2 `translate_to_sqlite` 的测试侧 fan-in 远大于 app 侧

- **app 侧**：`db_portable.py` 内部实际调用仅 **L266 / L526** 两处（L10/L57/L69 分别为 docstring、导出声明、函数定义）；`viral_store.py:L9` 为 docstring 文字（非 import） ⇒ **app 侧近乎零阻力**
- **测试侧**：`tests/test_db_portable.py` **25 处** + `tests/test_cw043_analytics_pg_matrix.py` **1 处** = **26 处**

`test_db_portable.py` 是 CW-054 交付的「既有门面单测扩充（TEST-LOGIC，**PG-free**）」，账本记载其规模为 19→57 用例，其中「27 条 `_NamedRow` vs **真实** `sqlite3.Row` 逐轴 parity 矩阵」正依赖 `translate_to_sqlite` 与真实 SQLite 行对象。

⇒ 删 `translate_to_sqlite` 会**作废 CW-054 的一整块 PG-free 交付物**。042-b 必须显式决定：这些 parity 用例是随 SQLite lane 一并退役（合理，因 PG lane 已有 `test_cw054_pg_portable_contract.py` 49 用例覆盖），还是迁移为纯 PG 断言。**该决定需 CW-054 owner 会签**，否则构成对已验收交付物的无授权删减。

### 5.3 `gate1_bootstrap.py` —— 正向确认：CW-053 E5 退役条件**已满足**（并记录本文前一版本的误判）

CW-053 §3 **E5** 将 `app/gate1_bootstrap.py`、`app/gate1_e2e.py` 的责任任务定为「**CW-057**（转 PG 或 retire）」，退役条件「CW-057 命令矩阵核销」。

**实测结果：退役已完成。** `app/gate1_bootstrap.py` docstring L9-19 原文：

> CW-057 (PG-01/PG-08): the historical SQLite form (``--db-path`` + ``initialize_database``) is retired. The seed only accepts a ``postgresql://`` DSN resolved through ``app.db_pg.resolve_cli_pg_dsn`` — a missing DSN, a ``sqlite://`` URL or a ``VIDEO_REPLICA_DB_PATH`` leftover fails closed with a fixed, credential-free message and never creates a database file.

实际导入面（L31-33）已全转 PG：`from app.db_pg import CliDatabaseConfigError, redact_postgres_dsn, resolve_cli_pg_dsn` / `from app.db_portable import BusinessConnection` / `from app.settings import SettingsRepository`；种子写入由 PG advisory lock（L38 `GATE1_BOOTSTRAP_LOCK_ID`）+ pristine-state 检查守护。

⇒ **E5 退役条件已满足，两文件不属 CW-042 任何子范围，042-b 无需触碰。** CW-053 §3 E5 行的「当前 SQLite 入口」描述已过期，建议随 §1.2 一并提交集成人更新。

> **本文前一版本的误判记录（保留以示取证纠正）**：初稿曾根据 CW-053 E5 的过期描述，断言「CW-057 已合入但 `gate1_bootstrap.py:L7` 仍为 `from app.db import initialize_database`，形成归属悬空债务」。经递归 grep + 直读文件后证实**该断言错误**：文件已不含任何 `app.db` 依赖。错因是将 CW-053（CW-057 合入**前**的盘点快照）当作当前事实。教训：**引用他任务证据文档的“当前状态”描述前，必须对目标文件重跑一次实测**。

---

## 6. 影响面量化（fan-in / fan-out，实测于 475f995）

| 节点 | 边类型 | fan-in 实测（475f995） | 042-b 处置 |
| --- | --- | --- | --- |
| `app/db.py`（53 行） | compile-time import | **8 个 app 模块** + **43 / 127 个测试文件** | 删文件；6 个 app 消费者改 PG，2 个越界不动 |
| `app/db_portable.py`（650 行） | compile-time import | **55 个 app 模块** | **门面保留**，仅删 SQLite 侧 4 个符号 |
| `connect_database(` 调用点 | runtime-call | app/ 共 **10 处**（含 db.py 自身 L13/L32）⇒ 外部 **8 处** | 随 internal lane 退役 |
| `BusinessConnection.sqlite(` | runtime-call | app/ **8 处** | 全部随 internal lane 退役 |
| `translate_to_sqlite` | runtime-call | app 侧实际调用 **2 处**（L266/L526，均 db_portable 内部）；测试侧 **26 处**（test_db_portable 25 + test_cw043_analytics_pg_matrix 1） | 见 §5.2，需 CW-054 owner 会签 |
| `SQLiteBackend`(L259) | compile-time | db_portable 内部 **11 处** + 测试 **2 处** | 随门面 SQLite 侧删除 |
| `local_settings_key` | runtime-call + **test-fixture** | app **2 模块 8 处**（bootstrap 2 + settings 6）+ tests **4 文件 12 处**（conftest 2、test_local_settings_key 7、test_media 1、test_settings 2） | 见 §5.1，**不可直接删** |
| 三把回归锁 | test-guard | `test_cw056_supported_head_matrix.py:L541`、`test_db_pg.py:L1272`、`test_db_pg.py:L1255` | 见 §4，须同提交处置 |
| `gate1_bootstrap.py` / `gate1_e2e.py` | — | **0**（已无 `app.db` 依赖） | **不属 CW-042**，见 §5.3 |
| `generation_worker.py` | — | **0**（L27 已走 `app.db_pg`） | **不属 CW-042**，见 §3.1.1 |

**未确认（本文无法回答，需运行时/人工验证）**：
- 43 个 SQLite 侧测试文件与 CW-043/058/059 已交付 PG 覆盖的**逐用例映射关系**——即哪些 SQLite 用例是「重复覆盖可安全删」、哪些是「PG 侧尚缺须先补」。CW-043 的核销清单（PR #43/#46）应含此映射，本文未展开逐条比对，**列为 042-b 规格的首项输入**。
- `bootstrap_runtime(db_path)` 的凭据解密自检在 PG lane 是否已有等价实现（CW-025 证据称已删 SQLite 分支，但 `bootstrap.py:L527` 实测仍存在）。

---

## 7. 建议实施批次与验证步骤（042-b 获授权后）

按依赖拓扑排序，每批独立 RED→GREEN，禁止跨批混合提交：

| 批次 | 内容 | 验证 |
| --- | --- | --- |
| **B0** | 取 CW-043 核销清单，产出「43 个 SQLite 侧测试文件 → PG 覆盖」逐用例映射 | 只读，映射表须覆盖 43/43，缺口=0 |
| **B1** | 摘除 §3.1.1 表中 6 个 app 消费者的 SQLite 回退分支（`auth` L64 / `customer_fence` L645,L732 / `rbac_routes` L219 / `media_routes` L472 / `viral_routes` L226 / `bootstrap` L531） | 逐调用者先红后绿；`npm run check:static` + 受影响专项 pytest |
| **B2** | 同步处置 §4 三把锁（含 CW-055 owner 对 `files == set()` 的重新评审签字），并遵守 §4bis 对 `test_cw056` 模块级常量的禁改约束 | 三把锁改动与其守护对象在**同一提交**；全量分片 pytest；`python3 scripts/ci/migration_manifest.py --check` 必须绿 |
| **B3** | 删 `db_portable.py` 的 `SQLiteBackend`/`translate_to_sqlite`/`_is_begin_immediate`/`_is_sqlite_pragma`；摘 `IntegrityConstraintError` 的 `sqlite3` 基类（CW-054 owner 会签 §5.2） | `test_cw054_pg_portable_contract.py` 49 用例须全绿；`test_db_portable.py` 退役项逐条登记 |
| **B4** | 删 `app/db.py` 全文件；解耦 §5.1 conftest autouse 后再裁 `local_settings_key` | 127 个测试文件收集期零错误；全量门禁 |
| **B5** | 清理 `viral_store.py:L9` docstring、`alembic.ini` 注释等文案腐化；账本 §17/§18 与证据登记 | 文档/链接检查 + secret 扫描 |

**收尾门禁**（AGENTS.md 标准工作流第 4 条 + 本地门禁前置原则）：`npm run check:static` + `bash scripts/ci/run-pytest-shards.sh`（或等价 `npm run check:sharded`），三门禁（secret 扫描 / Linux 质量门 / Windows NSIS）以 CI 为准。

两项因 `475f995` 而变化的收尾要求：

1. 本 worktree 若动测试文件，必须重生 CI 分片清单（`scripts/ci/build-test-shards.py`），否则 coverage 门禁红；B4 删 `app/db.py` 会使 43 个测试文件发生变动，属必须重生场景。
2. 新增迁移链守卫：`python3 scripts/ci/migration_manifest.py --check` 已进 CI 早期步骤（免 PG），042-b 每个批次都应跑一次，详 §4bis。

---

## 8. 并行冲突窗口评估

`git worktree list` 实测当前共 **20 个 worktree**，其中 `feat/customer-v3-*` 任务分支 **13 个**（CW-043×2、CW-044、CW-061、CW-063、CW-066、CW-067、CW-068、CW-070、CW-073、CW-075、CW-076、CW-078），另有 4 个 docs/chore 分支、本盘点分支，以及主 worktree 仍停在已合并的 `feat/customer-v3-cw056-pg-upgrade-matrix` 旧分支（`0a460b5`）。

其中 **8 个业务分支直接改后端**：CW-066 payment-provider、CW-067 recharge-schema、CW-068 publish-accounts、CW-070 wechat-callback、CW-073 device-slots、CW-075 discount-model、CW-076 registration、CW-078 api-keys。

042-b 的 B1/B3/B4 批次要改 `auth.py`（认证入口）、`db_portable.py`（**55 模块共享**、异常基类）、`customer_fence.py`（fencing 提交边界）——三者均为**全仓 fan-in 最高的共享节点**，与支付/注册/API-Key 分支的语义冲突概率高。项目规范「仅无冲突分支可并行」下，**建议 042-b 排在当前业务波次合流之后单独开窗**，而非与 13 个任务分支并行。

042-a（仅入口 fail-closed）改动面小得多，冲突风险可接受。

---

## 9. 本文边界声明

- 证据层级：**只读盘点**，不提升任何任务的 `CODE_PRESENT → AUTOMATED_VERIFIED` 层级。
- 本文**未**运行 pytest、**未**运行 `npm run check`、**未**启动 PG fixture、**未**改动任何 `server/app/`、`server/tests/`、`server/migrations/` 文件。
- 本文**不**构成 CW-042 的实施、验收或开工授权；实施须先取得 §2.4 的 owner 签认。
- 所有行号、计数、SHA 均实测于 `origin/main = 475f995`（初始取证于 `c3be59f`，rebase 后已逐项复核：`475f995` 仅改 CI/迁移守卫/分片清单/docs，**未触及本文测量的任何 `server/app/` 或 `server/tests/` 目标文件**；受影响计数只有测试文件总数 126→127，以及新增的 §4bis 地雷）；main 再前进后需重新取证。
- 本文交付前已做过一轮**全量数字自证**，纠正了初稿 5 处偏差：① `app.db` 消费者 10→**8**（`generation_worker.py` 实际不导入 `app.db`）；② `gate1_bootstrap` 「归属悬空」结论**错误**，CW-057 已实际退役（§5.3）；③ `db_portable` fan-in 50→**55**；④ `connect_database(` 19→**10**（外部 8）；⑤ 测试文件总数 104→**127**（rebase 前实测 126，`475f995` 新增 `test_migration_guard_manifest.py` 后为 127）。纠正过程见 §5.3 末尾的误判记录。

### 附录：取证命令（可复现，均已在 475f995 实跑）

```powershell
# 前置合入实测（不以账本声明为准）——于仓库根
git log --oneline origin/main | Select-String "CW-0(25|31|39|42|43|54|55|56|57|60)"
# → CW-039 与 CW-042 零命中；其余 8 项均命中

# fan-in 量化——于 server/ 目录
Get-ChildItem app -Recurse -Filter *.py | Select-String "from app\.db import"          # → 8 个 app 模块
(Get-ChildItem tests -Filter *.py | Select-String "from app\.db import" |
    Select-Object -ExpandProperty Filename -Unique).Count                              # → 43
(Get-ChildItem tests -Filter *.py).Count                                              # → 127
(Get-ChildItem app -Recurse -Filter *.py | Select-String "from app\.db_portable import").Count  # → 55
(Get-ChildItem app -Recurse -Filter *.py | Select-String "connect_database\(").Count   # → 10
(Get-ChildItem app -Recurse -Filter *.py | Select-String "BusinessConnection\.sqlite\(").Count # → 8
Get-ChildItem tests -Recurse -Filter *.py | Select-String "translate_to_sqlite" |
    Group-Object Filename                                                             # → test_db_portable 25 + test_cw043_analytics_pg_matrix 1
Get-ChildItem app,tests -Recurse -Filter *.py | Select-String "local_settings_key" |
    Group-Object Filename                                                             # → 7 文件（app 3 + tests 4）

# 三把回归锁定位
Get-ChildItem tests -Recurse -Filter *.py |
    Select-String "internal_lane_sqlite_migration_target_still_works"                  # → test_cw056_supported_head_matrix.py:L541
Select-String -Path tests\test_db_pg.py "^def test_pg_lane_has_no_mid_transaction|^def test_pool_borrow_autocommit"
# → L1255 / L1272

# gate1 退役正向核实（§5.3）
Get-ChildItem app -Recurse -Filter "gate1*" | Select-String "app\.db\b"                # → 零命中

# 占用查重（认领登记 §3）
Test-Path .git\codex-task-claims\CW-042                                               # → False（本文提交前）
git branch -a --list "*cw042*"; git worktree list | Select-String "cw042"              # → 仅本盘点分支
```
