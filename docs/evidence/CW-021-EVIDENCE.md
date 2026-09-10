# CW-021 — 删除桌面本地后端启动与管理资源（W3）

## Task Information

| Field | Value |
| --- | --- |
| **Task ID** | CW-021 / W3「删除桌面本地后端启动与管理资源」 |
| **Owner** | 桌面负责人（ZCode 会话 sess_0d6c74dc，用户授权流水线执行者） |
| **Reviewer** | CodeReview 自检（push 前）+ PR CI 三门禁 + owner 评审 |
| **Branch / Base SHA** | `feat/customer-v3-cw021-remove-local-backend` / 开工基线 `origin/main@63902364b05890f9`（＝CW-020 PR #18 squash 合并 6390236，前置唯一缺口已闭合） |
| **Worktree** | `E:/众墅之家爆款短视频创作/.worktrees/CW-021-remove-local-backend`（排班 §4 规定路径；claim: `.git/codex-task-claims/CW-021/claim.json`，基线与领取时间见 claim） |
| **Date** | 2026-09-11 |
| **Evidence Level** | `AUTOMATED_VERIFIED`（实机签名安装/解包与旧版本升级实机归 CW-024/CW-046） |
| **前置** | CW-020（PR #18 已合入）、CW-003/CW-001/CW-002/CW-004/CW-005/CW-053（W0 决策与既有增量均已合入） |

证据层级说明：全部结论来自本地自动化门禁与脚本级 mock 验证，**未过真实链路**，
不标 `STAGING_VERIFIED` / `REAL_CHAIN_VERIFIED` / `PRODUCTION_GO`。

## 开工查重与认领（排班 §3）

- `git fetch origin --prune` 后 `git ls-remote origin | grep cw021` 为空、无开放/近期 CW-021 PR、`git worktree list` 无 cw021 目录、`.git/codex-task-claims/` 无 CW-021 认领 → CW-021 独占，无重复在制。
- 原子认领：PowerShell `New-Item -ItemType Directory -ErrorAction Stop`（无 `-Force`）创建 `.git/codex-task-claims/CW-021/`，claim.json 登记任务/Owner/worktree/分支/基线/文件边界/测试资源。
- worktree 自 `origin/main@6390236` 创建：`git worktree add -b feat/customer-v3-cw021-remove-local-backend <路径> origin/main`。

## 变更范围（tracked 8 文件 + 3 文件删除）

| 文件 | 变更 |
| --- | --- |
| `client/src-tauri/src/lib.rs` | 删除 `#[cfg(feature = "local-sidecar")]` 全部启动链：`LOCAL_API_ADDR`("127.0.0.1:8000")、`BOOT_COMMAND_ENV`("VIDEO_REPLICA_BOOT_COMMAND")、`BackendProcess`、`local_api_ready` 端口探测、`default_boot_command`/`boot_command` 启动命令查找、`start_local_services`、setup 启动链、`RunEvent::Exit` 杀进程；凭据与下载 handler 原样保留 |
| `client/src-tauri/Cargo.toml` | 删除整个 `[features]` 表（`default = []` 与 `local-sidecar` feature）——任何构建（默认/opt-in）都无法再编译回本地后端；CW-020 注释中「CW-021 retires this feature」兑现 |
| `client/src-tauri/tauri.internal.conf.json` | **删除**（内部 opt-in overlay 随内部 edition 退役，桌面配置回归 base + customer overlay 双份） |
| `client/src-tauri/resources/start-backend.sh`、`start-backend.bat` | **删除**（打包启动器；客户安装包从此无启动脚本可携带） |
| `package.json` | 删除 `check:tauri:internal` / `tauri:build:internal` / `tauri:dev:internal`；`tauri:build`（唯一默认客户构建）与 `tauri:build:customer` 别名不变 |
| `.github/workflows/ci.yml` | Windows job 移除内部 check/build/record/archive/isolate 五步；「Verify customer installer excludes local launchers」扩大为「Verify customer installer excludes local backend distribution」（见下）；`LOCAL_ARTIFACT_ROOT` 引用 8→4、`SHA256SUMS.txt` 2→1 |
| `server/tests/test_build_contracts.py` | 删除 3 个 launcher 执行/内容测试；新增 `test_packaged_local_backend_launchers_are_removed`（启动器/内部 overlay/内部脚本/feature/lib.rs sidecar 标记「必须不存在」契约）；CI 合同测试改为「仅客户制品 + 扩大检测 + 启动器字样仅允许出现在制品门禁禁止名单」 |
| `server/tests/test_customer_ha_smoke.py` | `test_customer_desktop_build_is_the_sole_default_target` 内部断言翻转：internal overlay 必须不存在、`local-sidecar` feature 彻底不存在、package.json 无任何 `:internal` 脚本、CI 仅客户构建、frozen map 登记 CW-021 删除小节而非 overlay 文件 |
| `server/tests/test_desktop_artifact_no_pg_dsn.py` | 三配置布局改双配置布局；新增 `test_internal_edition_stays_withdrawn`；启动器「不存在」断言下沉到配置链路测试 |
| `README.md` | 对比表/架构 bullet/构建命令块同步「内部版已退役」；验证规模行「两种配置各 16」改「16（仅客户默认配置）」 |
| `docs/客户版代码开发清单-V3.md` | §4.6 收紧 + 新增 §4.7「删除桌面本地后端启动与管理资源（CW-021）」删除/修改登记 |
| `docs/客户版任务清单-V3.md` | 头部状态行 + §18 CW-021 行 |
| `docs/CUSTOMER-TASK-EVIDENCE-V3.md` | 证据登记（本文件） |

## RED → GREEN（承接 CW-011「先红后绿」）

RED（实现前，7 failed）：按「内部版必须退役」新契约先行改写三守卫测试，
`pytest test_build_contracts.py test_desktop_artifact_no_pg_dsn.py
test_customer_ha_smoke.py::test_customer_desktop_build_is_the_sole_default_target`
→ 6 failed（internal overlay 仍存在、start-backend 仍存在、ci.yml 仍有内部步骤、
LOCAL_ARTIFACT_ROOT=8、lib.rs 仍含 sidecar 标记等，失败点与 DoD「删除范围」逐项对应）
+ ha_smoke sole_default 1 failed。另 `test_local_start_commands...` 名下 launcher 断言
先行删除（文件已计划删除，无法 RED）。

GREEN（实现后）：同一命令 **15 passed**（含既有 8 个不变契约：PG DSN 隔离、
origin guard、构建命令、版本链等全部保持）。

## 制品检测扩大（CI 级验收载体）

「Verify customer installer excludes local backend distribution」检测四层：

1. 禁止文件名：`start-backend.bat`、`start-backend.sh`、`pyvenv.cfg`、`ffmpeg.exe`、`ffprobe.exe`。
2. 禁止扩展名：`.db` / `.sqlite` / `.sqlite3` / `.pyd`（业务 SQLite 库与 Python 扩展）。
3. 禁止目录：payload 内任何 `server/`、`.venv/`、`ffmpeg/` 路径段。
4. 二进制标记串（exe/dll，ASCII + UTF-16 双编码）：`start-backend`、`VIDEO_REPLICA_BOOT_COMMAND`、`127.0.0.1:8000`。

本地 PowerShell mock 验证（E:/tmp/cw021_psmock，CI PowerShell 语法同源）：
三类文件违规（`start-backend.bat`、`ffmpeg.exe`、`server\lib.db`）全命中；
ASCII 标记（`VIDEO_REPLICA_BOOT_COMMAND`）与 UTF-16LE 标记（`127.0.0.1:8000`）
全命中；合法 devUrl `127.0.0.1:5173` **不误报**。

## 验证记录

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| 秘密扫描 | `bash scripts/verify_no_secrets.sh` | EXIT=0「No hardcoded secrets detected」 |
| ruff | `uv run ruff check server` + `ruff format --check server` | All checks passed / 298 files already formatted |
| mypy | `uv run python -m mypy --config-file server/pyproject.toml server/app` | Success: no issues found in 104 source files |
| 守卫专项 | 三守卫文件 pytest（见上） | 15 passed |
| 全量 pytest | `uv run python -m pytest --rootdir server server/tests -q`，指向**本任务专属 PG 实例**（`PG_FIXTURE_NAME=customer-v3-pg-test-cw021`，端口 5443，卷独立；`TEST_POSTGRESQL_URL` 指向该实例）+ 仓库外 Windows fcntl shim（`.dev-env/pyshim`，沿 CW-055 先例，永不提交）+ 独立共享锁路径 | 按排班 §4「PG 资源按任务隔离」执行：共享 fixture(5433) 被其他会话在制占用，本任务起专属容器全量隔离串行跑（结果回填于「全量回归」） |
| client 门禁 | `npm run check --workspace client`（biome+tsc+vitest）+ `check:e2e` | biome/tsc 0 error、**80 文件 1296 passed**、e2e EXIT=0 |
| cargo fmt/check、cargo test | `npm run check:tauri` 等 | 本机无 Rust 工具链（沿 CW-019/CW-020 先例），以 push 后 CI「Linux quality gate」+「Windows Tauri and NSIS」为准 |

## 全量回归（隔离实例，39 分钟）

`uv run python -m pytest --rootdir server server/tests -q` → **28 failed, 2316 passed,
2 skipped, 38 errors in 2340.71s**。逐项甄别：

- 失败/错误**全部**落在 `test_simple_character.py`(6)、
  `test_cw033_pitr_drill_validation.py`(22)、`test_oral_domain.py`(38 errors)——
  主题分别为图片解码、子进程 CLI 校验、口播域 fixture，与本次改动面
  （构建契约/HA smoke/制品隔离/工作流）**零文件交集**；本任务的三个守卫测试
  文件在全量中全数通过。
- 与同机 CW-055 基线全量（`.dev-env/cw055-fullrun.log`：34 failed, 2181 passed,
  38 errors）比对：失败文件集为本基线的**真子集**（基线另含
  cw009_security_matrix_export / postgres_migrations / security_contracts 三个
  本机环境失败文件，本次未复现），38 个 oral_domain errors 完全一致——
  属本机 Windows 环境预存问题（fcntl shim/子进程/编码），非本任务回归。
- 权威全量门禁以 CI「Linux quality gate」（Linux 原生分片 pytest）为准。

## 边界与未测试项（诚实披露）

- **不触碰旧安装数据**：未动 `customer-installer-hooks.nsh` 的旧内部版卸载迁移钩子
  （升级路径归 CW-003 冻结命名空间 + CW-022 复验 + CW-046 实机）；未卸载/清理任何既有安装。
- **resources/ffmpeg/ 未物理删除**：客户默认 `bundle.resources: []` 不打包它，仓库内
  已无任何构建引用；物理清理按 CW-001 P1「物理删除延后」归 CW-040/CW-042。
- `docs/服务端分发与自动拉起方案.md` 等历史方案文档仍描述已删除的内部启动器
  （历史快照不改写；原断言其内容的测试随 launcher 删除一并移除）。
- CI Windows job 的解包检测为合同验证（staging.example.invalid 契约产物），
  真实 staging/release origin 注入与签名实机归 CW-024/CW-046/CW-050。
- cargo 编译与 NSIS 制品级四层检测的实际执行以 CI 三门禁为准（本机无 Rust/7-Zip 链）。

## 回退方式

PR squash 合并前：直接放弃本分支（revert 未合入代码）。合并后回退：对 squash
commit 做逆向提交并走同等 PR/门禁流程；删除的文件可自合并前分支 `6390236` 恢复，
无数据/迁移不可逆项（本任务无 DB 迁移、无运行时数据写入）。
