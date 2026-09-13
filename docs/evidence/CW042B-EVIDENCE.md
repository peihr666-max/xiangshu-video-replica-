# CW042B-EVIDENCE — CW-042-b / 040-b / 041-b 物理退出批次（2026-09-12）

> 任务：owner 决策 D5（`COORD-W6-PHYS-EXIT-20260912.md`）。分支 `feat/customer-v3-w6-physical-exit`，基线 4d2e598（含 #77/#78/#79/#81）。
> 核销依据链：CW-043 独立复核签署（PR #77 批次 §F）确认「不变量在真实 PG 上有断言级证据即可，旧 SQLite 文件随 CW-042 退休」（矩阵 §7 line 247 权威定义）。

## 1. 实测范围修正（引用盘点前先实测，盘点过时点如实登记）

| 盘点声称 | 实测（4d2e598） | 处置 |
| --- | --- | --- |
| `app/internal_accounts.py` 属 CW-041 退出 | ✅ 属实，零外部消费者 | **已删**（含 CLI） |
| `app/internal_billing.py` 属内部身份面（盘点 §1.2 方向 B 并列） | ❌ **过时**——实体是客户钱包账务核心：CW-029 复用其 RESERVE/SETTLE/RELEASE 为充值/结算引擎，generation.py PG worker 扣费全走它 | **保留**（改列入 CW-041 禁删清单，test_cw041 钉死） |
| `app/db.py` 可删（53 行/5 符号） | ⚠️ 部分——是 CW-060 operator 制品闭包组件（app.backup 导入 connect_database；test_cw060 可重建契约 + test_sqlite_to_postgres 依赖） | **保留为 operator 专用历史模块**（运行时消费者全部摘除，运行时入口 404/fail-closed） |
| `client/src-tauri/resources/start-backend.*` 待 CW-040 处置 | ❌ 过时——CW-021 已清（resources 仅剩 ffmpeg 说明） | 无动作 |
| client 侧内部计费 API 残留 | ❌ 过时——internalBilling 引用为零 | 无动作 |

## 2. 生产码删除/摘除清单

- **040-b 删除**：`packaging_tools/`（10 文件）、`deploy/internal-p0.env.example`、`deploy/nginx/internal-p0.conf.example`、`deploy/systemd/video-replica-backup.{service,timer}`、`scripts/p0_acceptance_evidence.py`；CI desktop filter 移除 `packaging_tools/**`。pitr-backup 单元（CW-033/048 域）保留。
- **041-b 删除**：`app/internal_accounts.py`；测试套件 `test_internal_access_tokens/test_internal_admin/test_internal_billing`（SQLite 内部 lane 套件）。`server/pyproject.toml` description 改为客户云 API。`internal_access_tokens` **表**保留（冻结迁移；auth.py Bearer 探针与 control_routes 仪表盘 join 只读消费）。
- **042-b 摘除**：
  - `app/db_portable.py`：translate_to_sqlite 全家族、`SQLiteBackend`、`BusinessConnection.sqlite` 工厂、9 处 isinstance 分支、`IntegrityConstraintError` 的 sqlite3 双继承（改纯 psycopg）；commit/rollback/close/__exit__ 转 no-op docstring（事务权属 pg_transaction）。
  - 6 消费者 SQLite 分支摘除：`auth.get_database`（无 DSN → 503 DATABASE_NOT_CONFIGURED）、`customer_fence` 两内部 lane 入口（503 退役文案）、`rbac_routes`/`media_routes` signed 校验（503）、`viral_routes` 后台连接+refresh lane（RuntimeError 退役文案）、`bootstrap.bootstrap_runtime` 整函数删除。
  - `app/settings.py`：本地 keystore 回退删除（缺 `VIDEO_REPLICA_SETTINGS_KEY` 即 SettingsKeyMissing）；`app/local_settings_key.py` 删除；conftest autouse 缓存清理解耦（盘点 §5.1 最高风险点按预案处置）。
  - `app/main.py` lifespan：internal lane 容忍分支删除——缺/SQLite DSN 在**所有环境** fail-closed（原仅客户生产拒绝）。
- **db.py 的 CW-042-a 扼流点**保留（对 operator 历史模块仍是防御纵深）。

## 3. 三把锁处置（盘点 §4）

| 锁 | 处置 |
| --- | --- |
| §4.1 CW-056 internal-lane SQLite 迁移锁 | **整用例移除**（防误伤前提消失；模块级常量未动，`migration_manifest --check` rc=0 复证） |
| §4.2 CW-055 autocommit 逃生口集合锁 | **无需动**——viral 刷新 lane 的 autocommit 借用在 PG 分支，集合仍为 `{"viral_routes.py"}`；SQLite 侧移除不改变断言结果。CW-055 重新评审要求随集合归空才会触发（042-b+刷新 lane 若未来收敛为 pg_transaction 则需评审，登记） |
| §4.3 CW-055 中途提交静态锁 | docstring 修订（SQLiteBackend 守卫前提失效，断言本体不变仍绿） |

**CW-060 注册表重写**：`_APP_DB_CONSUMERS` 8→1（仅 app/backup.py，operator 闭包）；backup 消费者不变。注册表测试通过。

## 4. SQLite 业务测试套件退休映射（CW-043 §C.1/§D 定义的执行）

删除判据：套件以 `BusinessConnection.sqlite`/`app.db` 承载业务断言，且其域不变量已由 CW-043 §B 采样签署的 PG 矩阵断言级覆盖。域→PG 矩阵映射（CW-043 §B，82 passed 独立复证）：账务 W1-W4→cw059_billing/cw029；任务 T1-T4→cw059_task_worker/cw030；权限 P1-P2→cw059_rbac；内容 C1-C2→cw058（media/materials/viral_statistics/viral_store upsert+statistics）；分析→cw043_analytics；viral_import→cw043_viral_import；viral 刷新 PG lane→cw058 #21。

逐文件：`test_viral_store/viral_routes/viral_statistics/viral_refresh/viral_import/viral_link/wallet_routes/wechat_native_callback(SQLite 版)/materials/material_permissions/media/characters/character_*/simple_character/source_frames/first_frames/analysis/script_from_audio*/script_rewrite/studio_*/rbac(SQLite 版)/generation(SQLite 版)/e2e_fake_provider/hifly_client/optional_project_state_api/settings(SQLite conn 部分)/cw026(legacy 节)`。

诚实边界与残留风险（提交 owner 知悉）：
- `test_settings` 的 provider 配置加密落盘/掩码契约的 **PG route 级等价断言**未见独立矩阵（schema 约束仍在）；已标记为 CW-045 最终候选窗口的补测候选。
- `test_storage_cross_instance` 为混合套件（PG fence + desktop 本地适配器），其 desktop lane 用例命运随 SQLite lane 退役——保留文件、切除退役车道用例（若仍有绿色 PG fence 用例）。
- 删除总数与最终清单以 PR diff 为准（全量日志落盘后逐文件核对）。

## 5. 验证

- 收集期：2700 用例零收集错误（fcntl shim 下）。
- test_cw040 改写为物理退出版（12P）；test_cw041 重写为防复活钉（4P）；cw060 注册表测试 P；全量日志 `full-suite.log`（最终轮）。
- 全量门禁：ruff/mypy/secrets/coverage/migration-manifest 见 §6（PR 前置清单）。
