# CW-060 证据文件 — 隔离既有历史 SQLite 工具与兼容测试

任务：CW-060（W5 · 代码与测试增量 · 数据工具负责人 + QA；PG-09 历史工具隔离责任任务）
分支：`feat/customer-v3-cw060-isolate-historical-sqlite-tools`（独立 worktree `E:/众墅之家爆款短视频创作/.worktrees/CW-060-isolate-historical-sqlite-tools`，从 `origin/main@8ab85c7` 创建——该提交即 CW-057 #19 的 squash 合入）
前置核验：CW-005（W0 #107 26e596c 已签认）、CW-007（#103 df7020c）、CW-053（e817d93 + #107）、CW-056（#15 d3d66b2）均已在 main。
授权说明：用户 2026-09-11 明示「可以开发前置，只要满足前置条件完成即可进入开发」——CW-060 是 CW-032 的最后一项未满足前置（当时无人认领），故由本会话领取开发。
上游规格：V3 收敛清单「CW-060 隔离既有历史SQLite工具与兼容测试」；PG-09（历史工具隔离）；排班清单 §2.2 CW-060 行（与054约定DB分发边界、和056迁移目录交接——两者均已合入，边界见 §7）。

---

## 1. 交付差额（对「仅做剩余」逐条收口）

| 审计/定义 remaining | 本 PR 处置 |
| --- | --- |
| 把 legacy 采集/可选工作副本规范化/只读导入组织为独立 operator 包并绑定最终 head/hash | 新增 `deploy/operator/build_operator_package.py`：组装注册的传递源闭包（两个历史 CLI + `app/backup.py`/`app/db.py`/`app/db_pg.py` + `migrations/` + `alembic.ini` + `pyproject.toml`/`uv.lock`），产出 `manifest.json`（文件清单+SHA-256+来源 commit+唯一 Alembic head）与 `manifest.sha256`；同树两次构建字节相同（可复建，有专项断言） |
| 从在线 app 包移出或明确隔离 app.backup；构建客户镜像时显式排除 SQLite scripts/backup timer 并做实物扫描 | `deploy/customer-git-rollout.sh` build 段：`rm -f $BUILD_CTX/server/app/backup.py` + 违规路径循环（`server/app/backup.py`、`server/scripts` 任一出现在构建上下文即 PRECHECK_FAILED exit 1）+ 镜像内实物扫描（`! test -e` 三连 + rglob 文件名扫描，命中即构建失败）；`server/scripts/` 从未被复制进客户上下文（契约断言钉住）；`video-replica-backup.timer` 不在客户链（CW-057 守卫继续有效） |
| 登记已发布 migration 例外 | 证据 §5 例外清单 + `test_migration_dialect_contract.py` 的 `LEGACY_EXEMPTIONS`（既有，引用不重复开发）+ 制品 manifest 的 `database_head` 单头绑定 |
| 缺 PG 时 TEST-IMPORT/HISTORY fail 而非伪通过 | 专项断言：`test_sqlite_to_postgres.py` 使用 `pg_test_kit.require_pg_or_explicit_skip()` 硬门（缺 PG 默认失败，仅显式 env 才 skip）；`test_migration_dialect_contract.py` 登记为纯 AST 静态（无 skip 路径、无可伪通过的 PG 依赖） |
| 核对全部反向消费者 | `test_historical_sqlite_surface_consumers_are_registered`：`app.db`/`app.backup` 的全部导入方与冻结注册表逐一相等，静默增长即失败；裁剪由 CW-042 显式收缩注册表 |

**剔除重复（不重写）**：T07 快照/导入/对账算法与既有测试零改动零重验（`sqlite_to_postgres.py`、`reconcile_customer_billing.py`、`app/backup.py`、`app/db.py` 本 PR 全部零字节改动——`git diff --name-only` 可证）；已发布 revision 不改写。

## 2. operator 制品（构建器契约）

- 位置：`deploy/operator/build_operator_package.py`（仅标准库，任何 Python 3.12+ 可运行，不进 app import 图——有专项断言）。
- 闭包 allowlist（`PACKAGE_FILES`，新增文件须评审）：`server/{alembic.ini,pyproject.toml,uv.lock}`、`server/app/{backup,db,db_pg}.py`、`server/scripts/{__init__,sqlite_to_postgres,reconcile_customer_billing}.py`、`server/migrations/env.py`、`server/migrations/versions/*.py`。业务面（main/bootstrap/routes/settings 等）进不来（有排除断言）。
- 版本绑定：`manifest.json.source_tree.commit_sha` = 构建时 `git rev-parse HEAD`；`source_tree.dirty` 如实登记工作区状态（不伪造干净构建）；`database_head` = 对 `migrations/versions` 的 AST 图遍历唯一头（多头/缺父/branch_labels 一律 fail）。
- 可复建：无时间戳、排序键、排序文件清单；同树两次构建 `manifest.json` 字节相同 + 逐文件相同（专项）。
- 入口：`python -m scripts.sqlite_to_postgres`、`python -m scripts.reconcile_customer_billing`（manifest.entry_points 固定登记）；`manifest.sha256` 锁定 manifest 本体。

## 3. 客户镜像排除（rollout 契约）

- 构建上下文：`rm -f $BUILD_CTX/server/app/backup.py`；forbidden 循环覆盖 `server/app/backup.py` 与 `server/scripts`。
- 镜像内：Dockerfile RUN 链新增 `! test -e` ×3（backup.py、sqlite_to_postgres.py、reconcile_customer_billing.py 的镜像内路径）+ Python rglob 文件名扫描（命中即 docker build 失败）。
- 运行时 import 检查不受影响：`app/backup.py` 在 server/app 内零导入方（消费者注册表可证），镜像内排除后 `import app.main, ...` 链不受影响。
- 本机未实跑 docker build（rollout 脚本需要真实旧镜像与 compose 站点）；契约以脚本内容断言 + CW-019 既有 `test_customer_git_rollout.py` 全绿兜底，实物镜像扫描的执行留在发布窗（诚实登记）。

## 4. 反向消费者注册表（CW-042 裁剪输入）

- `from app.db import`（9 文件）：`server/app/{auth,backup,bootstrap,customer_fence,generation_worker,internal_accounts,media_routes,rbac_routes,viral_routes}.py` —— 全部为 internal/desktop lane 的 per-request 遗留路径；客户 PG lane 运行时不依赖（CW-025 lifespan 契约）；裁剪归 CW-042。
- `from app.backup import`（1 文件）：`server/scripts/sqlite_to_postgres.py`（operator 工具自身）。
- 注册表为机器断言：集合不相等即测试失败——消费者只能经评审增删。

## 5. 例外与分类登记（TEST-IMPORT / TEST-HISTORY）

| 范围 | 分类 | 例外内容 | 入口隔离 | 退役 |
| --- | --- | --- | --- | --- |
| `server/app/db.py` | TEST-HISTORY（运行时遗留） | raw sqlite3 `initialize_database`/`connect_database` | internal lane 请求级解析；客户镜像运行时未调用（消费者注册表钉住） | CW-042 |
| `server/app/backup.py` | TEST-HISTORY（operator） | SQLite 快照/备份/恢复 | 仅 operator 制品与 internal backup unit（已退出客户链）；客户镜像构建期物理排除 | CW-040/CW-042 |
| `server/scripts/sqlite_to_postgres.py`、`reconcile_customer_billing.py` | TEST-IMPORT | 一次性导入/对账算法（不重写） | 仅 operator 制品入口；不注册路由、不进启动图 | 保留（版本化 operator 制品） |
| `server/app/db_portable.py` SQLite lane | TEST-HISTORY | BusinessConnection sqlite facade | 内部 lane；客户镜像依赖其 PG lane | CW-042 |
| `migrations/` SQLite 方言分支 | TEST-HISTORY | 已发布 revision 原文不改写 | 仅离线迁移执行 | 永久（已发布） |
| `test_migration_dialect_contract.py` 的 `LEGACY_EXEMPTIONS`（022 的 `uq_wallet_transactions_terminal_round`） | TEST-HISTORY | sqlite_where 缺失的历史豁免 | 纯 AST，豁免不得增长 | 永久（追加修复在 025） |

## 6. 验证记录（本机 Windows）

- 新增专项 `tests/test_cw060_operator_isolation.py`（7 用例，全离线）：制品可复建（两次构建 manifest 字节相同）、commit/head/文件哈希三方一致、业务面排除、rollout 排除契约（上下文 rm+循环、镜像 ! test -e ×3、rglob 扫描、scripts 不复制）、消费者注册表相等、TEST-IMPORT/HISTORY 硬门契约、构建器无 app 导入 → **7 passed**。
- 交叉回归：`test_customer_git_rollout.py`（CW-019 契约）+ `test_internal_deployment.py` + `test_cw057_cli_pg_entry.py`（PG 项在 vs-pg-dev@5434）+ `test_sqlite_to_postgres.py`（TEST-IMPORT 全套真实 PG）→ **93 passed**，证明 rollout 修改未破坏既有发布契约、历史套件在真实 PG 上行为不变。
- 静态门：ruff check 全过、ruff format 303 files 无修正、mypy --strict app 104 files 无问题。
- 无新增 PG 资源：本任务离线（不申请测试库；无 pg_test_kit 白名单变更）。
- 全量 pytest 与三门禁以 CI 为准（本机 ffmpeg/`.sh` 类环境性失败按 CW-054/055/057 证据基线归因，不在本机追绿）。

## 7. 与相邻任务的边界

- **CW-057（已合入 #19）**：本 PR 不触碰其任何文件；其「历史工具只能从 CW-060 隔离入口执行」的完工要求由本 PR 的制品化+注册表正式承接；CW-057 的客户链守卫（无 `app.backup`/`video-replica-backup` 引用）在本 PR 的 rollout 改动后依然全绿。
- **CW-042**：本任务只登记消费者、不裁剪实现；注册表即其裁剪清单输入。
- **CW-040**：internal backup systemd 单元仍保留（退出动作归 CW-040），本任务未改其内容。
- **CW-033/CW-035/CW-036/CW-048**：operator 制品即其「CW-060 隔离入口」的可达形态；实际数据批次操作仍归各自任务授权。

## 8. 诚实边界

- docker 构建与镜像实物扫描未在真实发布窗执行（需要真实站点与旧镜像）；脚本级契约与既有 rollout 测试兜底，实物扫描执行登记给下一次发布。
- 制品「一次性 job」形态（如需在无源码主机执行）留待 CW-035/036 触发时按批次扩展；当前交付为源码级可复建制品（满足「可复建、版本化、哈希锁定」完工标准）。
- 证据等级 `AUTOMATED_VERIFIED`（本地自动化，历史输入兼容范围）；不宣称数据迁移完成。
