# CW042A-EVIDENCE — CW-042-a 入口 fail-closed 收口（2026-09-12）

> 任务：CW-042-a（owner 签认拆分，决策正本 `docs/evidence/COORD-W6-UNBLOCK-20260912.md` D1；范围界定 `docs/evidence/CW042-SCOPE-INVENTORY.md` §2.4/§3）。
> 分支 `feat/customer-v3-w6-unblock`（W6 统一批次），基线 `origin/main@55220f7`。

## 1. 交付内容

**唯一生产码改动：`server/app/db.py`**（+31 行，042-a 本体文件）——新增进程级扼流点 `_refuse_sqlite_in_customer_production()`，挂入 `connect_database` 与 `upgrade_database`（`initialize_database` 经二者覆盖）三个入口的最前面（任何文件系统副作用之前）：

- 触发条件：`VIDEO_REPLICA_CUSTOMER_PRODUCTION` 为真值（`1/true/yes/on`，与 `bootstrap._TRUTHY` 同集）。
- 行为：抛 `RuntimeError`，消息**固定、无凭据、含行动指引**（gate1_bootstrap 退役先例同款）：
  `customer production is PostgreSQL-only: the SQLite lane (VIDEO_REPLICA_DB_PATH / app.db entry points) is not available here; configure VIDEO_REPLICA_DATABASE_URL instead`
- 效果：所有经 `app.db` 的运行时 SQLite 入口（`connect_database` app 侧 10 处、`BusinessConnection.sqlite` 8 处的底层通道，含 internal_accounts CLI、backup CLI、desktop bootstrap 助手）在客户生产**进程级** fail-closed；HTTP 面的等价守卫已由 CW-025 lifespan 承担（`app/main.py` `internal lane is not allowed in customer production`，test_admin_auth L1323/1338 已有测试），两者互补。
- **未删除任何实现**：`app/db.py` 的连接/升级函数体逐字保留，`SQLiteBackend`/`translate_to_sqlite` 零触碰（042-b 范围，保留 CW-039 约束）。
- 常量重复说明：`CUSTOMER_PRODUCTION_ENV` 在 `admin_auth_routes.py`/`control_routes.py`/`control_auth.py` 已有三处同值声明（既有约定），`app/db.py` 本地第四处——`app.db` 不能反向 import `app.bootstrap`（bootstrap 顶层导入 `app.db`，会成环），惰性导入则给每条 SQL 路径加锁开销，取与既有三处同款的最直读方案。

## 2. 为什么是 app/db.py 扼流点（而非逐调用点改造）

盘点 §3.1.1 实测：8 个 app 侧消费者中 6 个属 042 本体、2 个越界（backup.py→CW-040、internal_accounts.py→CW-041）。逐调用点改造会跨 6+ 文件且与越界任务文件交叉；`app/db.py` 是全部越界与本体消费者的**共同底层通道**（internal_accounts.main→`initialize_database`、backup.main→`connect_database`），在其上加守卫**零越界改动**即同时闭合本体与两个越界面的进程级入口，且天然满足 042-a「不删实现、只收紧入口」的定义。HTTP 请求级 DI（`auth.get_database`）在客户生产被 CW-025 lifespan 前置拦截，双保险成立。

## 3. RED→GREEN 验证（TDD）

- 新增 `server/tests/test_cw042a_sqlite_entry_failclosed.py` 14 用例：
  - RED 阶段（守卫未加）：**9 failed / 5 passed**——失败恰好为全部生产态拒绝用例（connect/initialize/upgrade 三入口 + 5 个真值变体 + 固定消息断言），通过项为 5 个非生产态对照。
  - GREEN 阶段（守卫加入）：**14 passed**（真实 sqlite3，非 mock）。
- 用例覆盖：三入口逐一拒绝且**零文件系统副作用**（断言目标 .db 文件不存在）；真值变体 `1/TRUE/Yes/on/" true "`；非真值 `0/false/""/production-off` 与未设置时内部 lane 保持可用（`initialize_database` 全链建库 + `PRAGMA foreign_keys=1` + sqlite_master 含 users）；固定消息逐字断言 + 凭据不泄漏（构造含 `postgresql://op:hunter2@…` 的假想场景断言消息不含）。

## 4. 回归与边界

- 内部 lane 回归冒烟：`test_db.py` + `test_local_settings_key.py` **35 passed**（internal lane 全功能保持）。
- CW-056 internal-lane 迁移回归锁（盘点 §4.1 地雷 1，`test_internal_lane_sqlite_migration_target_still_works`）不受影响：该锁经 alembic 直连 sqlite URL，不经过 `app/db.py` 扼流点；专项批次实跑确认（见 §6）。
- 迁移守卫（MIGRATION-GUARD）：本任务零迁移文件改动，`migration_manifest.py --check` rc=0。
- 明确不做（042-b 保留项）：删 `app/db.py`/`SQLiteBackend`/`translate_to_sqlite`、`local_settings_key` 裁剪（盘点 §5.1 conftest autouse 耦合）、三把回归锁处置、CW-055 逃生口集合重评审。

## 5. 全量复跑回归披露与修复（stash 归因法）

全量复跑（1:30:43，42F/2827P/1S @5444，基线 55220f7）分类：22 pitr（平台例外）+ 17 viral（**滚动日期窗口时间炸弹**——fixture 固定日期过期所致，与改动面无关；FIX-TESTBASE #78 于本批次 CI 窗口内修复，rebase 后 35/35 复证）+ **3 例本守卫引起的回归**：`test_analysis.py::test_customer_production_refuses_fake_video_analysis_provider`、`test_character_identity_api.py::test_customer_production_rejects_fake_source_inspector_override`、`test_first_frames.py::test_customer_production_rejects_fake_first_frame_quality_override`。根因：三测试为断言生产态拒绝逻辑（503 FAKE_PROVIDER 类），把 `connect_database` 写在生产旗标**之后**当作测试载体——守卫按设计在连接时拦截。归因实证（stash 后干净基线 1P1F→挂守卫即红）。**修复=重排为「先建连接、后升旗标」**（测试意图与断言逐字保留，注明 CW-042-a 交互），3 passed。经验登记：042-a 之后，模拟生产态的单测不得把 SQLite 连接放在生产旗标之后；经 `app.db` 建连的运行时入口在生产态已被统一拒绝。

## 6. 诚实边界

- 本扼流点覆盖**进程内**经 `app.db` 的入口；直连 `sqlite3.connect` 的代码路径不在其射程（盘点 §3.1.1 实测 app 侧业务面无此类直连；测试侧直连属 TEST 基建，非客户生产面）。
- alembic 直连 sqlite URL 的路径（CW-056 锁、operator 工具、迁移链本身）刻意不守卫——属 TEST-IMPORT/TEST-HISTORY/operator 制品域（CW-056/CW-060 登记在案）。
- 全量 pytest 与 CI 三门禁以 push 后 CI 为准；本机批次结果见 §6。
