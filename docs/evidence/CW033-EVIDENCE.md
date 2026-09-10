# CW-033 — 数据与资产快照恢复演练（Pre-GA 准备批次）

> **范围红线**：CW-033 属于 CW-001 §5.5 **GA 触发·冻结**清单（W5 CW-033~039），
> 前置条件是 CW-005 §5 真实数据批次盘点 + 处置路线（A/B/C）签认，pre-GA 阶段
> 无真实客户数据、无生产 archive、无 staging 环境访问权限。本次交付仅覆盖
> **仓库侧可自动化的准备面**：drill 脚本运行时校验锁 + 证据骨架 + 账本状态更新；
> 实际 `pg_ctl` 恢复、真实 `pg_basebackup` 基准备份、WAL 归档取回、100 事实核验
> 均**保持 GA 触发**，本文件不宣称上述任一项已完成。

## 任务信息（§14 模板）

| 字段 | 值 |
| --- | --- |
| 任务/工作包 | CW-033 制作可恢复的数据与资产演练快照 → 执行数据与资产快照恢复演练（W5 复验） |
| Owner / Reviewer | Owner：ZCode 代理（hlong026 会话，2026-09-10）；Reviewer：待独立复核子代理 + PR review；GA 触发批次需数据负责人 + 业务负责人 + owner phlong026 三方签认（见 CW-005 §7） |
| 分支 / 基线 SHA | `feat/customer-v3-cw033-snapshot-recovery-drill`，基线 `9a70918`（= CW-009 tip = 当前 origin/main） |
| 上游规格段落 | `docs/客户版任务清单-V3.md` §17/§18 CW-033；`docs/PostgreSQL唯一数据库实施与验收规范.md` PG-07/PG-08；`docs/客户版部署与灰度手册.md` §PITR；`docs/evidence/CW001-RELEASE-BASELINE.md` §5.5（GA 冻结）；`docs/evidence/CW005-DATA-DISPOSITION.md` §3（复用清单）§5（批次决议）§7（未执行事实） |
| 改动文件 | 新增 `server/tests/test_cw033_pitr_drill_validation.py`（drill 脚本运行时校验面回归锁，14 test functions 展开为 23 用例）、`server/tests/test_cw033_evidence_boundary.py`（证据层级/边界自守卫，7 用例）、`docs/evidence/CW033-EVIDENCE.md`（本文件）；更新 `docs/客户版任务清单-V3.md` §18 CW-033 状态行、`docs/CUSTOMER-TASK-EVIDENCE-V3.md` 登记 CW-033 条目 |
| 失败测试或回归锁定 | Pre-GA 阶段无 red→green 转换（drill 脚本已由 T38 交付）；本批次锁定的是 **运行时行为回归**：`test_cw033_pitr_drill_validation.py` 以子进程真调用 `deploy/postgres/pitr-restore-drill.sh`，覆盖 T38 结构性 grep 未触达的 fail-fast 路径（label 正则 4 例、manifest 路径 3 例、port 校验 5 例、CLI usage 1 例、drill env 门禁 4 例、recovery root/db/user 校验 5 例，加上锚点 1 例合计 23）；`test_cw033_evidence_boundary.py` 是自守卫——若未来有人把证据层级升到 STAGING_VERIFIED/REAL_CHAIN_VERIFIED/PRODUCTION_GO 而未在 CW-005 §5 取得签认，测试即失败 |
| 实现结果 | drill 脚本参数/env/recovery-root 校验面 23 用例全绿；证据边界自守卫 7 用例全绿（合计 CW-033 专项 30）；CW-033 账本状态从 `[ ] 待实施与验收` 更新为 `[~] Pre-GA 准备完成（AUTOMATED_VERIFIED，GA 触发条件保留）`；本证据文件与账本登记同步 |
| 验证命令与通过数 | 见 §验证记录（本地 macOS 实测：CW-033 专项 30/30；`npm run check` 全仓门禁 client 1267/1267 + server 2172 passed / 1 warning in 991.09s + secret/ruff/format/mypy/cargo 全绿） |
| 证据层级 | **AUTOMATED_VERIFIED**（drill 脚本校验面 + 证据边界自守卫；**未**升至 STAGING_VERIFIED/REAL_CHAIN_VERIFIED/PRODUCTION_GO——GA 触发条件未满足，见 §GA-blocked 清单） |
| 安全与可观测性 | drill 脚本 fail-fast 全部走 stderr，无 secret/激活码/token/DSN 输出；测试用 `_drill_env()` 显式剥离开发者 shell 的 `VIDEO_REPLICA_*` 变量，防误命中；测试断言 `pg_ctl`/archive helper 未被调用（副作用检查：recovery_root 无子目录、无端口绑定）；证据边界测试锁定"证据文件不得越级宣称"这一红线 |
| 迁移与回滚 | 无 Alembic revision；纯测试 + 文档，revert 即回滚；drill 脚本本体与 T38 交付的 `pitr-backup.sh`/`pitr-preflight.sh`/`pitr-fetch-wal.sh`/`pitr_recovery_facts.py` 零改动 |
| 外部授权记录 | 无；未调用真实 PG archive、off-site 存储、staging 环境、生产 COS、ZPay、付费 Provider、外部发码、灰度或公网发布 |
| 未测试项 | 见 §GA-blocked 清单 |
| Lore 提交 SHA | 本 PR squash 后回填 |

## Pre-GA 已交付面（可自动化验证的部分）

### 1. drill 脚本运行时校验面回归锁

`server/tests/test_cw033_pitr_drill_validation.py` — 14 test functions 展开为 23 用例（含 parametrize），通过 `subprocess.run` 真调用 `deploy/postgres/pitr-restore-drill.sh`，覆盖 `pitr_preflight` 触发之前的所有 fail-fast 路径：

| 分组 | 用例 | 断言 |
| --- | --- | --- |
| CLI label 正则 | `label-too-short` / `label-path-traversal` / `label-contains-space` / `label-contains-dollar` | exit 64 + `PITR backup label is invalid` |
| CLI manifest 路径 | `test_missing_manifest_argument_is_rejected` / `test_relative_manifest_path_is_rejected` / `test_absolute_but_nonexistent_manifest_is_rejected` | exit 64 + `recovery manifest must be an existing absolute path` |
| CLI port 校验 | `port-non-numeric` / `port-zero` / `port-negative` / `port-above-max` / `port-leading-zero` | exit 64 + `recovery port is invalid` |
| CLI usage | `test_unknown_cli_flag_prints_usage_and_exits_64` | exit 64 + `usage:` |
| drill env 门禁 | `test_missing_drill_env_var_refuses_to_run` / `test_missing_drill_confirm_var_is_rejected` / `test_non_staging_drill_env_is_rejected` / `test_wrong_drill_confirm_string_is_rejected` | 缺变量→非零退出 + 变量名进 stderr；值错→exit 64 + 明确文案 |
| recovery root/db/user | `test_missing_recovery_root_var_is_rejected` / `test_relative_recovery_root_is_rejected` / `test_nonexistent_recovery_root_is_rejected` / `test_invalid_recovery_db_name_is_rejected` / `test_invalid_recovery_user_is_rejected` | exit 64 + 对应文案；且 `recovery_root` 下无子目录被创建（副作用零） |

**为什么这一层是 pre-GA 可交付的**：这些校验路径在 `pitr_preflight` 之前触发，
不依赖真实 `pg_ctl`、`pg_basebackup`、`pg_verifybackup`、`psql` 或 WAL 归档，
本地 macOS/Linux 均可跑，且**不触碰任何生产数据**——满足 CW-001 §5.5 冻结红线。

**T38 与本批次的分工**：T38 交付了脚本 + 结构性 grep 契约测试（`test_customer_pitr.py`
断言脚本体内包含 `pg_basebackup`/`--wal-method=stream`/`recovery.signal` 等原语），
但从未真跑过脚本；本批次补齐**运行时行为回归锁**——若未来有人重排校验顺序、
删掉一条 fail-fast、或把 `exit 64` 改成静默 `exit 0`，本套件会失败。

### 2. 证据边界自守卫

`server/tests/test_cw033_evidence_boundary.py` — 7 用例，锚定以下红线：

| 用例 | 断言 |
| --- | --- |
| `test_cw033_evidence_file_exists` | `docs/evidence/CW033-EVIDENCE.md` 存在 |
| `test_cw033_evidence_level_is_capped_at_automated_verified` | Evidence Level 行必须含 `AUTOMATED_VERIFIED`；出现 `STAGING_VERIFIED`/`REAL_CHAIN_VERIFIED`/`PRODUCTION_GO` 的每一行都必须带否定/GA-block 语义线索（`not`/`未`/`不得`/`blocked`/`GA 触发` 等），否则失败 |
| `test_cw033_evidence_names_the_ga_trigger_freeze_anchors` | 必须交叉引用 CW-001（GA 冻结）、CW-005（数据处置框架）、CW-048（PITR/RTO/RPO 归属） |
| `test_cw033_evidence_lists_ga_blocked_items_explicitly` | 必须有 `**Untested Items**` 或 `未测试项`；且列出 `pg_ctl`/`pg_basebackup`/`WAL` 作为 GA-blocked 制品 |
| `test_cw033_evidence_contains_section_14_ledger_record` | 必须含 §14 中文字段：任务/工作包、Owner / Reviewer、分支 / 基线 SHA、证据层级、未测试项 |
| `test_task_ledger_marks_cw033_as_in_progress_with_pre_ga_scope` | `docs/客户版任务清单-V3.md` §18 CW-033 状态必须为 `[~]` + `AUTOMATED_VERIFIED` + `GA` + `CW033-EVIDENCE.md` |
| `test_customer_task_evidence_ledger_registers_cw033` | `docs/CUSTOMER-TASK-EVIDENCE-V3.md` 必须含 `## CW-033 ...` 章节 + 指向本文件 |

**为什么需要自守卫**：CW-033 是 GA 触发任务，pre-GA 阶段的证据层级最容易被
后续贡献者（人或代理）误升——比如某次会话拿到 staging 访问权限后跑了一次演练，
就把 Evidence Level 改成 `STAGING_VERIFIED`，绕过 CW-005 §5 的数据批次签认。
本套件把"越级宣称"变成 CI 失败，强制回到 CW-001/CW-005 的冻结锚点走签认流程。

## GA-blocked 清单（未测试项，保持 GA 触发）

以下动作在 pre-GA 阶段**不得执行、不得宣称**，触发条件见 CW-005 §5：

| 项 | 需要的能力 | pre-GA 缺失 | GA 触发条件 |
| --- | --- | --- | --- |
| `pg_basebackup --wal-method=stream` 真实基准备份 | 生产/staging PG16 实例 + `pitr-backup` libpq 服务身份 + off-site archive helper | 无生产访问；无真实客户数据 | CW-005 §5 数据批次盘点完成 + 路线 A/B/C 签认 |
| WAL 归档 + `assert-wal` 外部取回验证 | 真实 archive_command/archive_library 配置 + off-site 存储 | 无 | 同上 + staging 环境启用 |
| `pg_ctl -D <recovery_dir> start` 隔离副本恢复 | 真 base backup 制品 + 真 WAL 序列 + `pg_verifybackup` 校验通过的 recovery_dir | 无 | 同上 |
| `pitr_recovery_facts.py verify` 100 事实跨域核验 | 恢复后的隔离 PG 副本 + 真实 activation/recharge_order/wallet_transaction/customer_session_state 数据 | 无真实数据 | 同上 |
| PITR RTO/RPO 测量 | 完整恢复演练 + 时间戳记录 | 无 | **归 CW-048**，不在 CW-033 范围 |
| 逻辑快照 → 物理备份语义等价证明 | 生产 PITR 时间线 | 无 | 归 CW-048；CW-033 不得用逻辑快照冒充 PITR（`客户版部署与灰度手册.md` §PITR 红线） |
| 处置路线 A/B/C 决议 | CW-005 §5 批次决议表实际行 | 无 | 数据负责人 + 业务负责人签认后启动 CW-034/035/036/037 |

**触发路径**：CW-005 §5 数据批次盘点 → 路线签认（A/B/C） → 对应条件任务
（CW-034 保留客户 PG / CW-035 空 PG 导入 / CW-036 选择性合并 / CW-037 local 资产迁移）
→ CW-033 在 staging 环境执行完整恢复演练 → CW-048 验证 PITR/RTO/RPO。

## 验证记录

### 开发期专项（本地 macOS，无 PG fixture 依赖）

```bash
$ cd server && uv run python -m pytest tests/test_cw033_pitr_drill_validation.py tests/test_cw033_evidence_boundary.py tests/test_customer_pitr.py -q
```

实测通过数（2026-09-10，本地 macOS，node v24.14.1，Python 3.13.13）：
- `test_cw033_pitr_drill_validation.py` → **23 passed**（14 test functions，其中 label/port 使用 parametrize 展开为多例）
- `test_cw033_evidence_boundary.py` → **7 passed**
- `test_customer_pitr.py` → **11 passed**（T38 遗留结构性契约，未改动）
- 合计 41 passed

### 任务收尾门禁（AGENTS.md §验证命令 第 3 步）

```bash
$ bash scripts/pg-fixture.sh start    # Docker PG16 on :5433
$ npm run check                        # 全仓门禁，本任务唯一一次全量
$ bash scripts/pg-fixture.sh stop
```

实测通过数（2026-09-10）：

| 门 | 结果 |
| --- | --- |
| Secret 扫描 | ✅ No hardcoded secrets detected in runtime contract surface |
| Client biome + tsc + vitest | ✅ Checked 199 files；**1267/1267 passed**（首跑 StudioWorkspace.test.tsx:2112 flake，单独跑 82/82 + 重跑全量 1267/1267 通过；与 CW-033 无关） |
| E2E format check | ✅ |
| Tauri cargo check | ✅ Finished dev profile（2 条既存 dead_code 警告 `CREDENTIALS_FILE`/`DPAPI_ENTROPY` 与 CW-033 无关） |
| Server ruff check | ✅ All checks passed! |
| Server ruff format --check | ✅ 293 files already formatted |
| Server mypy app | ✅ Success: no issues found in 104 source files |
| Server full pytest | ✅ **2172 passed, 1 warning in 991.09s (16:31)**（其中 CW-033 专项 30 全绿：drill 校验面 23 + 证据边界 7） |

CI 三门禁（secret 扫描 / Linux 质量门 / Windows NSIS）以 PR 页面为准。

## 交叉引用

| 上游/下游 | 关系 |
| --- | --- |
| T38 / `docs/evidence/T38-EVIDENCE.md` | 交付了 drill 脚本 + 结构性契约测试；CW-033 补齐运行时行为回归锁 |
| CW-001 §5.5 / `docs/evidence/CW001-RELEASE-BASELINE.md` | GA 触发·冻结清单的锚点；CW-033 状态行必须与之兼容 |
| CW-005 §3/§5/§7 / `docs/evidence/CW005-DATA-DISPOSITION.md` | §3 复用工具清单（本 CW 依赖的 `pitr_recovery_facts.py`/`pitr-*.sh`）；§5 批次决议表（GA 触发前置）；§7 明确 CW-033 在签认前保持 conditional |
| CW-048 / PITR/RTO/RPO 验证 | 下游任务；CW-033 完成 staging 恢复演练后交由 CW-048 验证时间指标 |
| CW-056 / 空库 + 旧 PG 升级矩阵 | 平行任务；CW-033 的恢复目标 PG 版本必须与 CW-056 升级矩阵的 head 一致 |
| `docs/PostgreSQL唯一数据库实施与验收规范.md` PG-07/PG-08 | 规范层要求；CW-033 是 PG-08 "PG 备份必须实际恢复到隔离 PG" 的执行任务 |
| `docs/客户版部署与灰度手册.md` §PITR | 运维手册；CW-033 演练步骤最终纳入该手册的 GA 版 |

## Section 14 Ledger Record

```text
任务/工作包：CW-033 / 制作可恢复的数据与资产演练快照 → 执行数据与资产快照恢复演练（W5 复验，Pre-GA 准备批次）
Owner / Reviewer：Owner：ZCode 代理（hlong026 会话，2026-09-10）；Reviewer：待独立复核子代理 + PR review；GA 触发批次需数据负责人 + 业务负责人 + owner phlong026 三方签认
分支 / 基线 SHA：feat/customer-v3-cw033-snapshot-recovery-drill / 基线 9a70918（= CW-009 tip = origin/main）
上游规格段落：docs/客户版任务清单-V3.md §17/§18 CW-033；docs/PostgreSQL唯一数据库实施与验收规范.md PG-07/PG-08；docs/客户版部署与灰度手册.md §PITR；docs/evidence/CW001-RELEASE-BASELINE.md §5.5；docs/evidence/CW005-DATA-DISPOSITION.md §3/§5/§7
改动文件：新增 server/tests/test_cw033_pitr_drill_validation.py（drill 脚本运行时校验面回归锁）、server/tests/test_cw033_evidence_boundary.py（证据层级/边界自守卫）、docs/evidence/CW033-EVIDENCE.md（本文件）；更新 docs/客户版任务清单-V3.md §18 CW-033 状态行、docs/CUSTOMER-TASK-EVIDENCE-V3.md 登记 CW-033 条目；drill 脚本本体与 T38 交付的 pitr-*.sh/pitr_recovery_facts.py 零改动
失败测试或回归锁定：本批次锁定的是运行时行为回归（T38 结构性 grep 未触达的 fail-fast 路径）——test_cw033_pitr_drill_validation.py 以子进程真调用 drill 脚本，覆盖 label/manifest/port/CLI/drill-env/recovery-root 六组 fail-fast；test_cw033_evidence_boundary.py 是自守卫，若证据层级被误升 STAGING_VERIFIED/REAL_CHAIN_VERIFIED/PRODUCTION_GO 而 CW-005 §5 无对应签认，CI 即失败
实现结果：drill 脚本参数/env/recovery-root 校验面 23 用例全绿；证据边界自守卫 7 用例全绿（CW-033 专项合计 30）；CW-033 账本状态从 [ ] 待实施与验收 更新为 [~] Pre-GA 准备完成（AUTOMATED_VERIFIED，GA 触发条件保留）；证据文件与账本登记同步；未宣称任何 GA-blocked 项已完成
验证命令与通过数：pytest tests/test_cw033_pitr_drill_validation.py tests/test_cw033_evidence_boundary.py tests/test_customer_pitr.py -q → 41 passed（本地 macOS，无需 PG fixture）；ruff check + ruff format --check + mypy app → 全绿；npm run check 全仓门禁 → secret 扫描 ✅ + client biome/tsc/vitest 1267/1267 ✅ + e2e format ✅ + tauri cargo ✅ + server ruff/format/mypy 104 modules ✅ + server full pytest **2172 passed / 1 warning in 991.09s（16:31）** ✅（node v24.14.1 + Docker PG16 fixture on :5433；client 首跑 StudioWorkspace.test.tsx:2112 flake，重跑 1267/1267 通过，与 CW-033 无关）
证据层级：AUTOMATED_VERIFIED（drill 脚本校验面 + 证据边界自守卫；未升至 STAGING_VERIFIED/REAL_CHAIN_VERIFIED/PRODUCTION_GO——GA 触发条件未满足）
安全与可观测性：drill 脚本 fail-fast 全部走 stderr，无 secret/激活码/token/DSN 输出；测试用 _drill_env() 显式剥离开发者 shell 的 VIDEO_REPLICA_* 变量防误命中；测试断言 pg_ctl/archive helper 未被调用（副作用检查：recovery_root 无子目录、无端口绑定）；证据边界测试锁定"证据文件不得越级宣称"红线
迁移与回滚：无 Alembic revision；纯测试 + 文档，revert 即回滚；drill 脚本本体零改动
外部授权记录：无；未调用真实 PG archive、off-site 存储、staging 环境、生产 COS、ZPay、付费 Provider、外部发码、灰度或公网发布
未测试项：pg_basebackup 真实基准备份；WAL 归档 + assert-wal 外部取回；pg_ctl 隔离副本恢复；pitr_recovery_facts.py verify 100 事实跨域核验；PITR RTO/RPO 测量（归 CW-048）；逻辑快照→物理备份语义等价证明（归 CW-048）；处置路线 A/B/C 决议（归 CW-005 §5 + CW-034/035/036/037）——全部 GA 触发，见 §GA-blocked 清单
Lore 提交 SHA：本 PR squash 后回填
```
