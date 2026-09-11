# CW-044 前置盘点：CI / 命令 / 文档现状与收口蓝图

> **本文档定位**：CW-044「收口唯一客户 CI、命令与交付文档」的**前置盘点交付物**，不是收口实施本身。
>
> **范围声明**：本次开工（分支 `feat/customer-v3-cw044-ci-doc-inventory`）仅做**只读盘点**——梳理 `origin/main @ 1b78734` 上的 CI、npm scripts、Tauri 配置、脚本、部署模板、文档正本、SQLite/internal 残留与 TEST-* 分类现状，产出可被 CW-040~043 直接消费的收口点位清单与差异分析。**不修改任何 CI/命令/构建脚本/源码**；实际收口实施待前置 CW-040/041/042/043 全部合入 main 后另启会话。
>
> **消费方**：CW-040（退出内部发行/运维入口）、CW-041（退出内部身份）、CW-042（裁剪 SQLite 在线实现）、CW-043（PG 覆盖核销）、CW-044 收口实施会话、CW-045（最终候选全量门禁）。

## 元信息

| 项 | 值 |
|---|---|
| 任务 | CW-044 前置盘点（`scope=INVENTORY_ONLY`） |
| 分支 | `feat/customer-v3-cw044-ci-doc-inventory` |
| 基线 | `origin/main @ 38ae06c`（盘点起于 `1b78734` = CW-030 #29 后；push 前 main 三次前进 CW-032 #31 + CW-024 #32 + CW-058 #33，已两次 rebase 至 38ae06c 并按 §18 增量复核） |
| Worktree | `E:/众墅之家爆款短视频创作/.worktrees/CW-044-ci-doc-inventory` |
| Claim | `.git/codex-task-claims/CW-044/claim.json`（`lifecycle_state=ACTIVE`） |
| 盘点日期 | 2026-09-11 |
| Owner | Qoder session on behalf of honor.pei |
| 前置状态 | CW-019 ✅ 已合并；CW-040/041/042/043 ❌ NOT_STARTED（未认领，无 claim/分支/worktree） |
| 交付物 | 本文件（`docs/evidence/CW044-INVENTORY.md`） |

## 1. 执行摘要

### 1.1 盘点覆盖面

| 类别 | 已盘点 | 关键发现 |
|---|---|---|
| CI workflow | `.github/workflows/ci.yml`（417 行、5 job） | 单文件三门禁已就位；path-filter 三分（desktop/frontend/server）无 admin/internal/sqlite 维度 |
| Root npm scripts | `package.json`（**25** scripts） | 已按 CW-019/020/021 收敛为客户唯一构建；CW-024 新增 `release:customer`（唯一签名发布通道）；仍缺 PG preflight 统一入口 |
| Client npm scripts | `client/package.json`（9 scripts） | `build:admin` 保留（CW-019 双制品）；无内部命令残留 |
| Tauri 配置 | 双配置（base=customer foundation + customer overlay=installerHooks） | `tauri.internal.conf.json` 已被 CW-021 删除，格局已收敛 |
| `scripts/` | **23** 个 tracked（root 6 + `ci/` 3 + `ci/self-hosted-runner/` 5 + `ci/test-shards/` 4 + `ffmpeg-minimal/` 3 + `release/` 1 + `p0_acceptance_evidence.py`） | 客户 PG fixture 已就位；`ci/test-shards/` 陈旧造成 CI 漏跑（§18.2）；`ffmpeg-minimal/` 产物已无发行消费者（§18.4）；`p0_acceptance_evidence.py` 是内部 P0 遗留 |
| `deploy/` | **28** 个（含 14 systemd unit + CW-032 新增 `deploy/customer/` 3 个） | CW-032 交付可复建客户后端唯一默认交付包；`internal-p0.env.example` + `nginx/internal-p0.conf.example` + `video-replica-backup.{service,timer}` 仍是 CW-040 目标 |
| `packaging_tools/` | 10 个 tracked 文件 | **完整内部发行工具链**（build_release.py + install_skill.py + 4 平台安装脚本），CI 未引用但仓库保留，CW-040 目标 |
| `server/pyproject.toml` | description 仍为 "Internal API service..."；pytest markers 仅 `pg` | CW-041/044 需改 description；CW-044 需增 TEST-IMPORT/TEST-HISTORY marker |
| SQLite 残留（tests） | ≥ 7 文件 25+ 处直用 `BusinessConnection.sqlite` | viral 域是重灾区，CW-042/058/059 目标 |
| Internal 残留（源码/测试） | 2 app + 1 migration + 4 test + 1 client test + 2 deploy 模板 | CW-040/041 目标 |
| TEST-* 分类 | `pg_test_kit.py` 是 TEST-PG 契约中心；12+ 测试已标记 | 未在 `pyproject.toml` markers 层固化；CW-043/044 目标 |
| 文档正本 | 六份正本 + 部署手册 + 桌面升级与签名发布手册（CW-024 新）+ `deploy/customer/README.md`（CW-032 新）+ 内部 P0 双文档 + 历史快照；`docs/` 共 380 tracked | ⚠️ **索引 drift**：CW-024/CW-032 新增的两份交付文档未登记进 README §文档索引与 AGENTS §必读正本（§18.5） |

### 1.2 核心结论

> ⚠️ **最高优先发现（fail-open，可独立于全部前置立即修，证据见 §18.2）**：CI Linux 门的 server pytest 只执行 committed 分片清单内的 **99** 个测试文件，而仓库现有 **112** 个——**13 个近期 CW 任务的测试文件（含刚合入的 CW-024 `test_cw024_signed_release_upgrade_contracts.py`、CW-032 `test_cw032_delivery_package.py`，以及盘点进行中 main 又合入的 CW-058 `test_cw058_content_asset_pg_matrix.py`）在 CI 里从未执行过**。根因：`scripts/ci/run-pytest-shards.sh` 的 `resolve_manifests()`（L69-82）在 4 个 committed 清单齐全时直接采用、**不校验清单并集是否覆盖实际测试集**，而 ci.yml 无全量 pytest 兜底步骤（L214-216 注释明确 `check:static` = “former `npm run check` minus its trailing full pytest”）。属 CW-044「CI 门禁职责不缺失」范围，但**不依赖 CW-040/041/042/043**；建议单独开紧急修复任务，不等收口。

1. **CI/命令层的客户唯一化已 substantially 完成**（CW-019/020/021 成果）：`tauri:build` 唯一默认、admin bundle 独立、客户 NSIS 是唯一构建产物、内部 sidecar 启动链已从源码退役。
2. **收口缺口集中在四个方向**：
   - **A. 内部发行物理退出**（CW-040）：`packaging_tools/`、`deploy/internal-p0.*`、`deploy/nginx/internal-p0.conf.example`、`deploy/systemd/video-replica-backup.{service,timer}`、`scripts/p0_acceptance_evidence.py` 仍在仓库
   - **B. 内部身份入口退出**（CW-041）：`server/app/internal_{accounts,billing}.py`、`server/tests/test_internal_*.py`（4 文件）、`client/src/internalBillingApi.test.ts`、`server/pyproject.toml` description、迁移 `022_internal_billing.py`（已发布 revision，不可删）
   - **C. SQLite 在线实现裁剪**（CW-042）：至少 7 个测试文件直用 `BusinessConnection.sqlite`（viral/wallet 域）；`test_viral_refresh.py` 仍断言 `_run_sqlite_viral_refresh_step`；`server/app/generation_worker.py` 保留 `run_worker_once` SQLite 核心（生产不可达）
   - **D. PG 覆盖核销与分类门禁**（CW-043/044）：`pg_test_kit.py` 是 TEST-PG 契约中心但 `pyproject.toml` markers 只有 `pg`，缺 TEST-IMPORT/TEST-HISTORY 独立分类；缺 PG 时非 0 失败门禁未在 `check`/`test`/`test:e2e`/`pg-fixture test` 四个入口统一
3. **CW-044 收口点位**：全文共 **11 类 63 个编号点位**（`git grep` 实测：CI-1~8、NPM-1~6、SH-1~7、DEP-1~5、PKG-1~3、SQL-1~2、INT-1~5、CLASS-1~4、PG-1~4、TAURI-1~3、DOC-1~16），§13 收口蓝图按前置就绪顺序编排其中的关键路径；§18 增量复核新增 13 处（CI-7、CI-8、NPM-6、SH-5、SH-6、SH-7、DEP-4、DEP-5、TAURI-3、DOC-13~16）。前置全部就绪后估计 1 个 PR、3-5 天工作量（其中 CI-7/SH-5/SH-6 分片完整性守卫应提前单独修）。
4. **本次盘点已识别但暂不处置的未决问题 5 项**（详见 §15），需 owner 在 CW-044 收口实施前签认。
5. **本文件含三处对初稿计数的纪正**（root scripts 24→25、`scripts/` 10→23、§1.2 收口点位口径由「21→33」改以 `git grep` 实测 63 处/11 类为准），详见 §18.6；纪正后全文计数以 `git ls-files` / `git grep` 实测为准。

---

## 2. CI 门禁现状（`.github/workflows/ci.yml`）

### 2.1 Job 拓扑（5 job）

| Job | 触发条件 | Runner | Timeout | 核心步骤 |
|---|---|---|---|---|
| `changes` | 同仓 PR 或 push main | ubuntu-24.04 | 5 min | `dorny/paths-filter` 计算 desktop/frontend/server 三个布尔输出 |
| `select-runner` | 同上 | ubuntu-latest | 5 min | `actions/github-script` 探测 `video-replica` label 的 self-hosted runner，在线则用之，否则回退 ubuntu-24.04；`CI_FORCE_HOSTED` repo var 可强制 hosted |
| `secret-scan` | 同上 | ubuntu-24.04 | 5 min | checkout + setup-node@24 + `npm run check:security`（即 `bash scripts/verify_no_secrets.sh`） |
| `quality-linux` | 同上，`needs: [changes, select-runner]` | 由 select-runner 决定 | 60 min | 12 步：checkout → apt(Tauri+ffmpeg) → node24 → py3.12 → uv 0.12.0 → rust stable → `npm ci` → `uv sync --project server --locked --group dev` → `npm run check:static` → `bash scripts/ci/run-pytest-shards.sh`（4 分片各带独立 PG 容器）→ 条件性 `pg-fixture.sh start` + Playwright Chromium + `npm run test:customer-e2e`（frontend=true）→ 条件性 `cargo test`（desktop=true）→ 条件性 `npm run build` + `npm run build:admin` + `npm run verify:customer-bundle`（desktop=true）→ 条件性 `npm audit`（frontend=true）→ `pg-fixture.sh stop`（always） |
| `windows-nsis` | 同上，`needs: changes` | windows-2025 | 45 min | 10 步：desktop 检测（always green）→ 条件性 checkout/node/rust/npm ci（desktop=true）→ `npm run check:tauri` → `cargo test` → `npm run tauri:build:customer` → pwsh 验证 NSIS payload 不含 local backend（forbidden: start-backend.*/pyvenv.cfg/ffmpeg.exe/.db/.sqlite/.pyd/server|.venv|ffmpeg 路径；binary markers: start-backend/VIDEO_REPLICA_BOOT_COMMAND/127.0.0.1:8000）→ `Get-FileHash` SHA256 → 归档到 `runner.temp/video-replica-artifacts/<sha>/customer-cloud/` + `SHA256SUMS.txt` |

### 2.2 Path-filter 覆盖矩阵

| Filter | 覆盖路径 | 影响的 job 步骤 |
|---|---|---|
| `desktop` | `client/src-tauri/**`, `client/**`, `package.json`, `package-lock.json`, `packaging_tools/**`, `.github/workflows/ci.yml` | quality-linux: cargo test / build web / build admin / verify bundle；windows-nsis: 全步骤（除 always-green 检测外） |
| `frontend` | `client/**`, `package.json`, `package-lock.json` | quality-linux: pg-fixture start / playwright install / customer E2E / npm audit |
| `server` | `server/**`, `scripts/**`, `package.json` | 仅作为 changes job 输出（当前 CI 中未直接被任何 `if:` 消费；quality-linux 的 check:static 与 sharded pytest 恒执行） |

**盘点观察**：
- ⚠️ **`packaging_tools/**` 在 desktop filter 中**——如果 CW-040 物理退出 packaging_tools，需从 filter 中移除该路径
- ⚠️ **`scripts/verify_customer_bundle.mjs` 落在 server filter 而非 desktop filter**（CW-019 已登记为结构问题）——只改该脚本的 PR 上产物级断言被跳过，但源码级 `entryContract.test.ts` 仍会跑
- ⚠️ **无 `admin`/`internal`/`sqlite` 维度 filter**——CW-044 收口时若引入历史 TEST-IMPORT/TEST-HISTORY 独立报告，可能需要新增 filter 维度

### 2.3 门禁 → npm script 映射

| CI 步骤 | 调用的 npm script | 底层命令 |
|---|---|---|
| Secret scan | `check:security` | `bash scripts/verify_no_secrets.sh` |
| Linux static | `check:static` | secret + `client check`（biome/tsc/vitest）+ `check:e2e`（biome e2e）+ `check:tauri`（cargo fmt+check）+ ruff check + ruff format --check + mypy |
| Linux pytest | 直接调 `bash scripts/ci/run-pytest-shards.sh` | 4 分片，每片独立 PG 容器（端口 5433+i）；Docker 不可用回退顺序单跑 |
| Linux customer E2E | `test:customer-e2e` | `playwright test --config e2e/customer/playwright.config.mjs` |
| Linux Rust tests | 直接调 `cargo test` | `--manifest-path client/src-tauri/Cargo.toml --locked` |
| Linux build web | `build` | `npm run build --workspace client`（tsc -b + vite build） |
| Linux build admin | `build:admin` | `npm run build:admin --workspace client`（tsc -b + vite build --config vite.admin.config.ts） |
| Linux verify bundle | `verify:customer-bundle` | `node scripts/verify_customer_bundle.mjs`（24.6 KB 大脚本） |
| Linux npm audit | 直接调 `npm audit --audit-level=high` | 3 次重试，容忍 503/timeout |
| Windows check:tauri | `check:tauri` | `cargo fmt --check + cargo check --locked` |
| Windows NSIS build | `tauri:build:customer` | 别名指向 `tauri:build`：`require:customer-api-base` + `tauri build --config src-tauri/tauri.customer.conf.json --bundles nsis --no-sign --ci -- --no-default-features` |

### 2.4 CI 中已内嵌的历史任务成果（盘点时不可回退）

| 行号 | 内容 | 归属任务 |
|---|---|---|
| L244-247 | Build admin bundle 注释：admin console 是独立 artifact（`client/dist-admin`, base `/admin/`） | CW-019 |
| L254-262 | Build admin bundle + Verify customer bundle excludes admin and internal entries（门控 desktop=true） | CW-019 |
| L330-335 | Windows-only Rust credential/download tests（DPAPI/durable-identity/download-registry 在 Linux 编译排除） | CW-022 |
| L336-340 | Build unsigned customer cloud NSIS（内部版本已退役，只 build 客户云包） | CW-021 |
| L345-393 | Verify customer installer excludes local backend distribution（pwsh 脚本，forbidden names + binary markers 双检） | CW-021 |

### 2.5 CW-044 收口时需修改的 CI 点位（预期）

| # | 点位 | 修改类型 | 前置依赖 |
|---|---|---|---|
| CI-1 | `changes` job 的 `desktop` filter 移除 `packaging_tools/**` | 删除 | CW-040 物理退出 packaging_tools 后 |
| CI-2 | `quality-linux` 增加**统一 PG preflight 步骤**（在 check:static 之前 fail-closed 检测 PG 可达性） | 新增 | CW-043 完成 PG 覆盖核销后 |
| CI-3 | `quality-linux` 拆出 **TEST-IMPORT/TEST-HISTORY 独立报告步骤**（与 TEST-PG 分片并行） | 新增 | CW-042 裁剪 SQLite 在线实现后 |
| CI-4 | `quality-linux` 的 sharded pytest 步骤增加 **缺 PG 非 0 失败门禁**（当前 `pg_test_kit` 已在测试层 fail-closed，但 CI 层无显式门禁步骤） | 新增/强化 | CW-043 完成后可实施 |
| CI-5 | `windows-nsis` 的 forbidden 检测扩展：若 CW-042 裁剪后仓库无任何 `.sqlite*` 文件，可加入 payload 检测 | 强化 | CW-042 |
| CI-6 | 移除或保留 `scripts/p0_acceptance_evidence.py` 相关的 CI 引用（当前 CI 未直接引用，但需确认无间接依赖） | 核查 | CW-040 |
| CI-7 | `quality-linux` 增加**分片覆盖率断言步骤**（打印 discovered 112 vs manifest 99 的差额，不为空即失败）——与 SH-6 脚本层守卫互为双保险 | 新增 | 无（§18.2，**紧急、不依赖任何前置**） |
| CI-8 | `windows-nsis` 制品目录已改名 `customer-cloud-internal-test-unsigned` 并写 `RELEASE-CHANNEL.txt`（CW-024）→ 需把「CI 产物不可分发、唯一发布通道是 `release:customer`」写进交付文档正本 | 文档同步 | 无（DOC-16） |

---

## 3. npm scripts 现状

### 3.1 Root `package.json`（25 scripts）

| Script | 命令 | 分类 | CW-044 收口点位 |
|---|---|---|---|
| `build` | `npm run build --workspace client` | 客户构建 | 保留 |
| `build:admin` | `npm run build:admin --workspace client` | 管理构建（CW-019） | 保留 |
| `build:all` | `build && build:admin` | 双构建 | 保留 |
| `check` | secret + client check + e2e + tauri + ruff + ruff-format + mypy + **全量 pytest（顺序）** | 全仓门禁 | ⚠️ 需加 PG preflight |
| `check:e2e` | `biome check e2e` | E2E lint | 保留 |
| `check:security` | `bash scripts/verify_no_secrets.sh` | Secret 扫描 | ⚠️ 若 packaging_tools 退出，扫描范围需同步 |
| `check:sharded` | `check:static + run-pytest-shards.sh` | 全仓门禁（并行） | ⚠️ 需加 PG preflight |
| `check:static` | secret + client check + e2e + tauri + ruff + ruff-format + mypy | 静态门禁 | 保留 |
| `check:tauri` | `cargo fmt --check + cargo check --locked` | Tauri 静态 | 保留 |
| `dev:client` | `npm run dev --workspace client` | 开发（前端） | 保留 |
| `dev:server` | `bash scripts/dev-with-pg.sh ...bootstrap && ...uvicorn` | 开发（后端） | ✅ 已含 PG wrapper（CW-025） |
| `dev:worker` | `bash scripts/dev-with-pg.sh ...bootstrap && ...generation_worker` | 开发（Worker） | ✅ 已含 PG wrapper（CW-025） |
| `format` | client format + ruff format | 格式化 | 保留 |
| `generate:api` | `npm run generate:api --workspace client` | OpenAPI 生成 | 保留 |
| `release:customer` | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/release/build-customer-signed-release.ps1` | **唯一签名发布通道**（CW-024 新增）：fail-closed——缺 `VIDEO_REPLICA_RELEASE_SIGN_THUMBPRINT` 或缺 `VITE_API_BASE_URL` 即 throw；产出 installer + SHA256SUMS.txt + release-manifest.json；构建期复验 6 处版本冻结源（package.json / client/package.json / package-lock.json ×2 / Cargo.toml / server/pyproject.toml） | 保留；⚠️ CI 不跑（需签名材料），故其验证完全依赖 `test_cw024_signed_release_upgrade_contracts.py`——而该测试文件**不在分片清单内**（§18.2） |
| `require:customer-api-base` | `node scripts/require_customer_api_base.mjs` | 构建期守卫（CW-011/020） | 保留 |
| `tauri` | `npm run tauri --workspace client --` | Tauri 直通 | 保留 |
| `tauri:build` | `require:customer-api-base + tauri build --config src-tauri/tauri.customer.conf.json --bundles nsis --no-sign --ci -- --no-default-features` | **唯一默认客户构建**（CW-020） | 保留 |
| `tauri:build:customer` | 别名指向 `tauri:build` | 兼容别名 | ⚠️ CW-044 可考虑合并（保留一个） |
| `tauri:dev` | `npm run tauri --workspace client -- dev` | Tauri 开发 | 保留 |
| `test` | client test + 全量 pytest | 测试合集 | ⚠️ 需加 PG preflight |
| `test:e2e` | client e2e_contract.test.tsx + server test_e2e_fake_provider.py | E2E 合约 | ⚠️ 需加 PG preflight |
| `test:gate1` | `uv run python -m app.gate1_e2e` | 内部 FakeProvider 桌面纵向验收 | ⚠️ CW-021 后 harness 已退役（CW-057 备注），需确认是否删除 |
| `test:customer-e2e` | `playwright test --config e2e/customer/playwright.config.mjs` | 客户浏览器 E2E | ⚠️ 需加 PG preflight（当前 CI 里由独立 `pg-fixture.sh start` 步骤承担） |
| `verify:customer-bundle` | `node scripts/verify_customer_bundle.mjs` | 客户制品验证（CW-019） | 保留 |

### 3.2 `client/package.json`（9 scripts）

| Script | 命令 | 备注 |
|---|---|---|
| `build` | `tsc -b && vite build` | 客户构建（默认入口） |
| `build:admin` | `tsc -b && vite build --config vite.admin.config.ts` | 管理构建（CW-019，独立 vite 配置 + 独立 outDir `dist-admin`） |
| `check` | `biome check . && tsc -b && vitest run` | 前端门禁 |
| `dev` | `vite` | 前端开发 |
| `format` | `biome check --write .` | 前端格式化 |
| `generate:api` | `openapi-typescript http://127.0.0.1:8000/openapi.json -o src/generated/api.ts` | OpenAPI 类型生成 |
| `tauri` | `tauri` | Tauri CLI 直通 |
| `test` | `vitest run` | 前端单测 |
| `verify:customer-bundle` | `node ../scripts/verify_customer_bundle.mjs` | 客户制品验证（复用 root 脚本） |

**盘点观察**：client 层无内部命令残留（CW-019/021 已收敛）。

### 3.3 CW-044 收口时需统一/删除/新增的 script

| # | Script | 动作 | 前置 |
|---|---|---|---|
| NPM-1 | `check`, `check:sharded`, `test`, `test:e2e`, `test:customer-e2e`, `pg-fixture test` | **统一加入 PG preflight**（缺 PG 非 0 失败，不允许 skip） | CW-043 |
| NPM-2 | `tauri:build:customer` 与 `tauri:build` | 评估是否合并为单一入口（当前是别名，保留兼容） | 无（可独立决策） |
| NPM-3 | `test:gate1` | 确认是否删除（CW-021 已退役内部 sidecar，CW-057 备注 harness 已退役） | CW-040 |
| NPM-4 | 新增 `check:pg-preflight`（或类似）作为独立可调用门禁 | 新增 | CW-043 |
| NPM-5 | 新增 `test:history` / `test:import` 独立报告入口（TEST-IMPORT/TEST-HISTORY 分类） | 新增 | CW-042, CW-043 |

---

## 4. Tauri 配置现状（双配置格局）

### 4.1 `client/src-tauri/tauri.conf.json`（61 行，base = customer foundation）

关键字段（CW-020 翻转成果）：
- `productName`: "短视频复刻客户云工作台"
- `identifier`: `com.xiangshu.video-replica.customer`
- `version`: `0.1.16`
- `app.windows[0].url`: `customer`（不是 `index`）
- `app.windows[0].title`: `""`（空，由前端设置）
- `app.security.csp`: `default-src 'self'; connect-src ipc: http://ipc.localhost https:; ...`（**HTTPS-only**，无 loopback http）
- `bundle.resources`: `[]`（**空**，不再打包本地资源）
- `bundle.longDescription`: "连接客户云服务的短视频复刻 Windows 桌面端，**不包含本地 API 或 Worker 启动器**。"
- `bundle.targets`: `["nsis"]`
- `bundle.windows.nsis.installMode`: `currentUser`

### 4.2 `client/src-tauri/tauri.customer.conf.json`（11 行，overlay）

仅一个字段：`bundle.windows.nsis.installerHooks = "customer-installer-hooks.nsh"`

### 4.3 `client/src-tauri/tauri.internal.conf.json`（**MISSING**）

按 V3 任务清单 L505 CW-020 记录曾新建此文件（identifier `com.internal.video-replica`、CSP 含 loopback、resources `["resources/*"]`），但 worktree 中不存在——已被 CW-021「删除桌面本地后端启动与管理资源」物理删除。**格局已收敛为客户唯一**。

### 4.4 CW-044 收口时需确认的点

| # | 点位 | 动作 |
|---|---|---|
| TAURI-1 | 双配置是否合并为单配置（`tauri.conf.json` 直接内联 installerHooks） | 评估：合并可减少文件数，但会失去「base + overlay」的清晰分层；建议保留双配置 |
| TAURI-2 | `README.md` §架构与技术栈 L35 与 §仓库结构 L161 提到「内部版显式 opt-in」 | ⚠️ **文档 drift**：CW-021 已删除内部版，README 需同步删除该表述 |
| TAURI-3 | `customer-installer-hooks.nsh`（CW-024 +115 行） | 新增 legacy 世代处理（短视频复刻工作台 0.1.12 / 0.1.13 / 0.1.15 / 0.1.16 #92），旧版卸载以已验签归档为前提；CW-044 收口时需确认该 hook 与 CW-003 受支持版本清单、签名发布手册三处一致 |

---

## 5. `scripts/` 目录现状（23 个 tracked 文件）

> ⚠️ **初稿计数纪正**：本节初版写「10 个（7 root + 3 ci/）」，漏盘了 `ci/self-hosted-runner/`（5）、`ci/test-shards/`（4）、`ffmpeg-minimal/`（3）三个子目录与 CW-024 新增的 `release/`（1）。实测 `git ls-files scripts` = **23** 个；补盘见 §5.5-§5.8。

### 5.1 CI/构建守卫类（保留）

| 文件 | 大小 | 用途 | 归属 |
|---|---|---|---|
| `verify_no_secrets.sh` | 3.5 KB / 107 行 | 扫描 secrets（sk-/AKIA/PRIVATE KEY/api_key=... 等 4 类模式）+ runtime 特征串（激活码 XS-... / 预签名 URL）+ deploy 层 X-Control-Proxy-Token 检查 | 通用门禁 |
| `require_customer_api_base.mjs` | 1.9 KB / 58 行 | 构建期守卫：`VITE_API_BASE_URL` 必须是可路由 HTTPS 非 loopback origin（拒绝 127/0/169.254/192.0/198.18/224/240/::1/fe80/ff00 等 15 类非目的地地址 + localhost 后缀 + 用户名/密码/端口/路径/查询/哈希） | CW-011 建立，CW-020 沿用 |
| `verify_customer_bundle.mjs` | 24.6 KB | 客户制品验证（CW-019）：扫描 `client/dist` 是否含 admin/internal 文件名与特征串；阳性对照 6 条管理域字面量必须在 `dist-admin` 命中 | CW-019 |
| `ci/build-test-shards.py` | 10.1 KB | 生成 pytest 分片清单（按 test-durations.json 平衡） | CI |
| `ci/run-pytest-shards.sh` | 6.9 KB / 203 行 | 4 分片并行 pytest，每片独立 PG 容器（端口 5433+i），Docker 不可用回退顺序单跑 | CI |
| `ci/test-durations.json` | 4.7 KB | 测试文件时长记录（用于分片平衡）；⚠️ 含 4 个 `test_internal_*.py` 记录，CW-041 退出后需清理 | CI |

### 5.2 PG fixture 类（保留）

| 文件 | 大小 | 用途 |
|---|---|---|
| `pg-fixture.sh` | 4.9 KB / 136 行 | Docker PG16 fixture 管理：`start` / `stop` / `clean` / `status` / `test`；⚠️ `test` 子命令仅跑 `test_postgres_migrations.py` 单文件，CW-044 需扩展为统一 PG preflight 入口 |
| `dev-with-pg.sh` | 1.2 KB / 29 行 | 开发环境 PG wrapper（CW-025）：幂等拉起 pg-fixture，注入 `VIDEO_REPLICA_DATABASE_URL`，`exec "$@"` |

### 5.3 内部发行/运维类（CW-040 目标）

| 文件 | 大小 | 用途 | CW-040 处置建议 |
|---|---|---|---|
| `p0_acceptance_evidence.py` | 6.4 KB | 内部 P0 单机部署验收证据脚本 | **物理删除**（内部 P0 已收口） |
| `customer_release_preflight.py` | 4.9 KB / 144 行 | T45 客户生产发布 fail-closed 门禁（校验 env 文件的 `VIDEO_REPLICA_CUSTOMER_PRODUCTION=true` / `AUTH_MODE` 非 desktop|development / `ALLOW_DEV_IDENTITY_HEADER` 禁用 / `DESKTOP_USER_ID` 未设 / metrics token 文件权限） | **保留**（属客户线，README L119 明确要求发布前必跑） |

### 5.4 CW-044 收口时需修改的脚本

| # | 脚本 | 动作 | 前置 |
|---|---|---|---|
| SH-1 | `pg-fixture.sh` `test` 子命令 | 扩展为完整 PG preflight（不只跑 `test_postgres_migrations.py`） | CW-043 |
| SH-2 | `verify_no_secrets.sh` `scan_paths` / `runtime_secret_paths` | 若 `packaging_tools/` 退出，同步移除该路径 | CW-040 |
| SH-3 | `ci/test-durations.json` | 清理 `test_internal_*.py` 4 条记录 | CW-041 |
| SH-4 | `p0_acceptance_evidence.py` | 物理删除 | CW-040 |
| SH-5 | `ci/test-shards/shard-{0..3}.txt` | **重新生成**（`python3 scripts/ci/build-test-shards.py --shards 4`）以覆盖当前 112 个测试文件；同时用 `--from-log` 刷新 `test-durations.json` 基线 | 无（§18.2，紧急） |
| SH-6 | `ci/run-pytest-shards.sh` `resolve_manifests()` | **加 fail-closed 完整性守卫**：清单并集与实际 `rglob("test_*.py")` 集合不一致即 exit 非 0（或自动把余集追加到最短分片），杜绝静默漏跑复发 | 无（§18.2，紧急） |
| SH-7 | `ffmpeg-minimal/`（3 文件） | 产物落 `client/src-tauri/resources/ffmpeg/`，但 CW-021 已把 `bundle.resources` 置空、windows-nsis forbidden 名单含 `ffmpeg.exe` → 评估是否随 CW-040/042 退出，或在 README 明确其为服务端/开发用途 | CW-040 或独立决策 |

### 5.5 `ci/self-hosted-runner/`（5 文件，初稿漏盘）

| 文件 | 用途 |
|---|---|
| `setup-runner.sh` | 装 ci.yml `quality-linux` 所需同一套工具链（Node24/Python3.12/uv/Rust/ffmpeg/Tauri 依赖/Docker） |
| `register-runner.sh` | 注册 self-hosted runner（`RUNNER_TOKEN=`） |
| `runner-service.sh` | `start` / `status`（→ ONLINE）/ `install-systemd` |
| `provision-vm.md` | macOS 路线：OrbStack / Lima ubuntu:24.04 VM（arm64） |
| `provision-windows-wsl2.md` | Windows 路线：WSL2 Ubuntu 24.04（x64）；声明 `pg-fixture.sh` / `run-pytest-shards.sh` / `self-hosted-runner/*.sh` 在 WSL2 原样运行、零脚本改动 |

**与 CI 的关系**：ci.yml `select-runner` job 探测带 `video-replica` label 的 self-hosted runner，在线则用之、否则回退 ubuntu-24.04；AGENTS.md L66 据此定义「双路径豁免」（runner 在线时 PR CI 即本地跑，可不再单独跑第二遍本地全量）。

⚠️ **CW-044 收口点**：`select-runner` 的回退语义 + AGENTS §双路径豁免 + 本目录三份 provision 文档构成一条「命令与交付文档」链，收口时需三处一致（当前无自动化守卫）。

### 5.6 `ci/test-shards/`（4 文件，初稿漏盘）—— ⚠️ 陈旧导致 CI 漏跑

| 文件 | 测试文件数 |
|---|---|
| `shard-0.txt` | 24 |
| `shard-1.txt` | 23 |
| `shard-2.txt` | 26 |
| `shard-3.txt` | 26 |
| **并集（去重）** | **99** |
| 仓库实际 `server/tests/test_*.py` | **112** |
| **差额（CI 从不执行）** | **13** |

完整证据与名单见 §18.2（本盘点最高优先发现）。

### 5.7 `ffmpeg-minimal/`（3 文件，初稿漏盘）

`Dockerfile` + `build.sh` + `smoke.sh`：musl 交叉编译**精简 LGPL** ffmpeg/ffprobe 静态二进制（不含 x264/x265 等 GPL 组件），覆盖图片解码校验、抽音轨与探测时长；产物默认复制到 `client/src-tauri/resources/ffmpeg/`（该目录仅 `.gitignore` + `README.md` 入库，二进制不入库）。

⚠️ 与 CW-021 成果的关系：`tauri.conf.json` L32 `bundle.resources: []` 且 windows-nsis forbidden 名单含 `ffmpeg.exe` → 该产物**不进客户安装包**。处置见 SH-7。

### 5.8 `release/`（1 文件，CW-024 新增）

`build-customer-signed-release.ps1`（142 行）：客户云桌面安装包的**唯一签名发布通道**。fail-closed 设计——无签名材料 / 无获批云 origin / 产出 installer 未通过 Authenticode 验签，三者任一即中止且**不产出任何发布制品**。输出 `customer-cloud/<version>/{installer.exe, SHA256SUMS.txt, release-manifest.json}`。运行手册为 `docs/客户版桌面升级与签名发布手册.md`；实机升级验收归 CW-046、真实旧数据迁移归 CW-051。

---

## 6. `deploy/` 目录现状（28 个文件）

### 6.1 客户生产（保留）

| 文件 | 用途 |
|---|---|
| `customer-git-rollout.sh` | 客户站部署脚本（CW-019 M1 修：同 SHA 原子替换 + admin-site-before.tar.gz 备份/回滚 + `build:all` + verify 纳入发布链 + `curl /admin/` 真实探活；**CW-032 修**：`COMPOSE` 从主机未登记文件改为仓内 `deploy/customer/compose.yaml`（保留 `CUSTOMER_COMPOSE=` 兼容通道）+ 备份目录多写 `compose.sha256` 钉住本次发布的拓扑制品） |
| `customer.env.example` | 客户生产环境样例 |
| `nginx/customer.conf.example` | 客户 nginx 配置样例 |
| `postgres/migrate.sh` | PG 迁移脚本（CW-056 加升级后 head 读回校验） |
| `postgres/pitr-{backup,fetch-wal,preflight,restore-drill}.sh` | PG PITR 4 脚本 |
| `postgres/README.md` | PG 运维说明 |
| `operator/build_operator_package.py` | CW-060 建立的可复建 operator 制品构建器 |
| `customer/compose.yaml` | **CW-032 新增**：客户后端唯一默认交付拓扑（db + 一次性 migrate + api-1/api-2 + worker-1..4）；`migrate` 是唯一执行 schema DDL 的角色，api/worker 经 `depends_on: service_completed_successfully` 等待，多实例不竞争改 schema；db `max_connections=120` |
| `customer/bootstrap-base-image.sh` | **CW-032 新增**：空白环境首个应用镜像（干净基底 + 锁定依赖 + 与 rollout 相同的镜像内检查） |
| `customer/README.md` | **CW-032 新增**（95 行）：空白环境可重建手册——前置、重建步骤、first admin 开通、连接池预算（6×8=48+1+3=52 ≤ 120）、备份与恢复、健康检查与发布验证、制品哈希；⚠️ **未登记进 README §文档索引**（DOC-14） |
| `systemd/video-replica-{api,api@,worker,worker@}.service` | 客户 API + Worker systemd unit（含 template unit） |
| `systemd/video-replica-maintenance{,-alert}.{service,timer}` | 维护 timer + alert |
| `systemd/video-replica-ops-alerts.{service,timer}` | 运维告警 |
| `systemd/video-replica-pitr-backup.{service,timer}` | PITR 备份 |

### 6.2 内部 P0（CW-040 退出目标）

| 文件 | 用途 | CW-040 处置建议 |
|---|---|---|
| `internal-p0.env.example` | 内部 P0 单机部署环境样例 | **物理删除** |
| `nginx/internal-p0.conf.example` | 内部 P0 nginx 配置样例 | **物理删除** |
| `systemd/video-replica-backup.{service,timer}` | CW-057 备注：`app.backup + video-replica-backup.{service,timer}` 注册为 `historical-internal-p0`（模块分类横幅 + 隔离横幅守卫） | **物理删除**（CW-057 已注册隔离，CW-040 执行退出） |

### 6.3 CW-044 收口时需同步的部署文档/模板

| # | 点位 | 动作 | 前置 |
|---|---|---|---|
| DEP-1 | `docs/客户版部署与灰度手册.md` | 确认无 `internal-p0.*` 引用；若有则清理 | CW-040 |
| DEP-2 | `docs/Windows内测与运维手册.md` | README §文档索引 L151 标记为「历史快照，不得作为实施依据」；CW-044 收口时评估是否物理删除或明确归档 | 无（可独立决策） |
| DEP-3 | `docs/内部运营P0单机部署与验收记录.md` + `docs/内部运营与ZPay计费管理文档-P0.md` | README §文档索引 L151 引用为「内部 P0 运营」文档；CW-040 退出后需同步删除或明确归档 | CW-040 |
| DEP-4 | `deploy/customer/README.md`（CW-032） | 纳入交付文档正本体系（README §文档索引 + AGENTS §必读正本），并确认与 `docs/客户版部署与灰度手册.md` 无重叠矛盾 | 无（§18.5） |
| DEP-5 | `deploy/customer/compose.yaml` 连接池预算（52 ≤ 120） | 确认该预算与 CW-004 冻结的 PG 资源框架（min1/max8/ceiling64）一致，并由 `test_cw032_delivery_package.py` 契约测试钉住（⚠️ 该测试不在分片清单内，§18.2） | 无 |

---

## 7. `packaging_tools/` 现状（内部发行工具链）

### 7.1 文件清单（10 个 tracked）

```
packaging_tools/
├── __init__.py
├── build_release.py            # 内部发行构建脚本
├── install_skill.py            # 一键安装 skill 脚本
├── assets/
│   ├── CHANGELOG.md
│   ├── README-安装说明.md
│   ├── 安装-Linux.sh           # exec python3 install_skill.py
│   ├── 安装-Windows.bat
│   ├── 安装-Windows.ps1
│   └── 安装-macOS.command
└── tests/
    └── test_install_skill.py
```

### 7.2 引用现状

| 引用点 | 内容 | CW-040 处置 |
|---|---|---|
| `scripts/verify_no_secrets.sh` L12/L37 | `scan_paths` 与 `runtime_secret_paths` 均包含 `packaging_tools` | 同步移除 |
| `.github/workflows/ci.yml` L65 | `changes` job 的 `desktop` filter 包含 `packaging_tools/**` | 同步移除 |
| `outputs/branch-merge-audit-2026-09-08/inventory.json` L46 | 历史审计快照引用 `dist/Video_Reverse_SkillS_V0.6.4-OneClick/install_skill.py` | 历史归档，不动 |
| CI 各 job 步骤 | **未直接调用 packaging_tools 内任何脚本** | 无 CI 步骤需删 |

### 7.3 CW-044 收口点位

| # | 点位 | 动作 | 前置 |
|---|---|---|---|
| PKG-1 | `packaging_tools/` 整体 | 物理删除（10 个 tracked 文件） | CW-040 |
| PKG-2 | `verify_no_secrets.sh` scan_paths | 移除 `packaging_tools` | CW-040 |
| PKG-3 | `ci.yml` desktop filter | 移除 `packaging_tools/**` | CW-040 |

---

## 8. SQLite 残留盘点（映射 CW-042/058/059）

### 8.1 `server/tests/` 中直用 `BusinessConnection.sqlite` 的测试文件

Grep 结果（限 25 条，实际可能更多）：

| 文件 | 处数 | 归属任务 |
|---|---|---|
| `test_wallet_routes.py` | 2（L68/L98） | CW-059（账务域 PG 迁移） |
| `test_viral_refresh.py` | 1 + `_run_sqlite_viral_refresh_step` 断言（L16/L30/L81/L111/L127） | CW-058（内容域 PG 迁移）或 CW-042（若属在线实现） |
| `test_viral_routes.py` | 1（L123） | CW-058 |
| `test_viral_statistics.py` | 1（L30） | CW-058 |
| `test_viral_store.py` | 1（L45） | CW-058 |
| `test_viral_import.py` | 15+（L35/L91/L202/L222/L254/L298/L312/L341/L347/L395/L401/L433/L456/L485/L520） | CW-058 |
| `test_viral_link.py` | 4（L50/L428/L662/L664） | CW-058 |

**盘点观察**：viral 域是 SQLite 直用重灾区（6 文件 22+ 处）；wallet 域 1 文件 2 处。CW-058 与 CW-059 需分别承接。

### 8.2 `server/app/` 中的 SQLite 分支（CW-030 备注）

按 V3 任务清单 L515 CW-030 记录：
> 正式 Worker 仅剩 PG 入口——物理删除 generation_worker 的 `run_sqlite_worker_round`/`run_forever`（`--db-path` 此前已不在 argparse），保留防御性 RuntimeError，**SQLite 核心 `run_worker_once` 按 CW-042 分工保留（生产不可达）**

即 `server/app/generation_worker.py` 仍保留 `run_worker_once` 的 SQLite 核心逻辑，生产不可达但代码存在，CW-042 需裁剪。

### 8.3 文档中的 SQLite 表述（README + AGENTS）

| 文档 | 行号 | 表述 | CW-044 处置 |
|---|---|---|---|
| `README.md` | L5-7 | 头部声明「SQLite 仅限精确登记的离线历史输入、归档与兼容工具」 | 保留（与 CW-053 例外矩阵一致） |
| `README.md` | L23 | 双版本基线表格：内部 P0 数据真源 = SQLite | ⚠️ CW-040 退出内部 P0 后，整个表格需重构 |
| `README.md` | L63 | 「当前代码仍有非生产 SQLite fallback 和旧 dev 命令；缺 PG 拒绝启动、合法客户种子与统一命令由 CW-007/025/044 交付」 | ⚠️ **CW-044 直接交付点**：收口后此表述需改为「已交付」 |
| `README.md` | L130 | 红线：「禁止 SQLite/PG 双真源与双写」 | 保留 |
| `AGENTS.md` | L11-13 | 与 README 头部一致的 PG 统一声明 | 保留 |
| `AGENTS.md` | L52 | 红线：「禁止 SQLite/PG 双真源与双写」 | 保留 |
| `AGENTS.md` | L108-109 | 环境变量备忘：「SQLite/DB_PATH/缺 URL/不可达 PG 拒绝启动」+「旧 `VIDEO_REPLICA_DB_PATH`/内部固定身份仅作迁移识别」 | ⚠️ CW-042/041 完成后需同步 |

### 8.4 CW-044 收口时需从 CI 命令中删除的 SQLite 兼容

| # | 点位 | 动作 | 前置 |
|---|---|---|---|
| SQL-1 | `windows-nsis` job 的 forbidden 检测（L376）已含 `.db/.sqlite/.sqlite3` 扩展名 | 保留（客户包 payload 检测，与源码 SQLite 存在与否无关） | 无 |
| SQL-2 | `npm run check` / `test` 命令末尾的全量 pytest | 收口后应无 SQLite 直用测试；CW-044 无需改命令，但需确认 CW-042/058/059 已完成裁剪 | CW-042, CW-058, CW-059 |

---

## 9. Internal 身份/入口残留盘点（映射 CW-040/041）

### 9.1 `server/app/internal_*.py`（2 文件）

| 文件 | 用途 | CW-041 处置建议 |
|---|---|---|
| `server/app/internal_accounts.py` | 内部账号管理 | 评估：若已无消费者则物理删除；若有历史消费者需先解耦 |
| `server/app/internal_billing.py` | 内部计费（CW-029 备注：`test_payments` 仍在 SQLite 内部通道） | 评估：同上 |

### 9.2 `server/migrations/versions/022_internal_billing.py`（已发布 revision）

⚠️ **红线约束**：AGENTS.md L51「已发布 revision 只可追加修复，不得篡改」——**不可物理删除**。CW-041 处置建议：
- 保留迁移文件本体
- 若 `internal_billing` 表已无消费者，可新增后续 revision 标记为 deprecated 或 drop table（需评估数据保全）

### 9.3 `server/tests/test_internal_*.py`（4 文件）

| 文件 | 时长（`test-durations.json`） | CW-041 处置建议 |
|---|---|---|
| `test_internal_access_tokens.py` | 8.86s | 评估：若 CW-026 已退出内部认证，此测试可删或转为 TEST-HISTORY |
| `test_internal_admin.py` | 8.14s | 评估：若 CW-027 已收口管理端权限，此测试可删或转为 TEST-HISTORY |
| `test_internal_billing.py` | 7.98s | 评估：同 §9.1 |
| `test_internal_deployment.py` | 0.07s | 评估：若 CW-040 退出内部部署，此测试可删 |

### 9.4 `client/src/internalBillingApi.test.ts`

前端内部计费 API 测试。CW-041 处置建议：若 `internalBillingApi` 已从客户入口链路消失（CW-015 备注），此测试可删。

### 9.5 `deploy/internal-p0.*` 与 `nginx/internal-p0.*`

见 §6.2，CW-040 处置。

### 9.6 `server/pyproject.toml` description

⚠️ L4：`description = "Internal API service for the video replica desktop app"` —— **仍是 "Internal"**！CW-041/044 需改为客户云版描述（如 "Customer cloud API service for the video replica desktop app"）。

### 9.7 `scripts/verify_customer_bundle.mjs` 中的 internal 特征串

L18/L33/L141/L288：包含 `internalAccessToken` 等特征串——这是**阳性对照**用途（验证客户包**不含** internal），是**好的**，CW-044 保留。

### 9.8 CW-044 收口时需从命令与 CI 中移除的引用

| # | 点位 | 动作 | 前置 |
|---|---|---|---|
| INT-1 | `scripts/ci/test-durations.json` 4 条 `test_internal_*.py` 记录 | 清理 | CW-041 |
| INT-2 | `server/pyproject.toml` L4 description | 改为客户云版描述 | CW-041 |
| INT-3 | `README.md` §双版本基线表格（L21-27） | 内部 P0 列删除或改为「已退役」 | CW-040 |
| INT-4 | `README.md` §文档索引 L151「内部 P0 运营」引用 | 删除或改为归档说明 | CW-040 |
| INT-5 | `AGENTS.md` L21「两条线：内部 P0 单机版已完成收口...」 | 简化为「客户版 V3 唯一产品线」 | CW-040 |

---

## 10. TEST-* 分类现状（映射 CW-043）

### 10.1 TEST-PG 契约中心：`server/tests/pg_test_kit.py`

按文件头注释：
> Single home for the test-resource contract that every TEST-PG suite shares

即 `pg_test_kit.py` 是 TEST-PG 类测试的**唯一契约入口**（create/drop helper + allowlist 登记）。CW-007 建立，CW-010/029/030/054/055/056/057/058/059/060 均沿用。

### 10.2 已明确标记 TEST-PG 的测试文件（12+）

Grep 结果：

| 文件 | 标记位置 |
|---|---|
| `test_cw054_pg_portable_contract.py` | L3 docstring |
| `test_cw057_cli_pg_entry.py` | L14 docstring |
| `test_cw060_operator_isolation.py` | L16/L22 docstring（含 TEST-IMPORT/TEST-HISTORY 硬门登记） |
| `test_cw027_admin_permission_matrix.py` | L14/L333 docstring + 注释 |
| `test_cw029_billing_pg_matrix.py` | L1/L4/L264 docstring + 注释 |
| `test_cw026_converged_auth.py` | L586 docstring |
| `test_wallet_billing_service.py` | L3/L7/L11 docstring（含 SQLite→PG 迁移说明） |
| `test_oral_domain.py` | L3/L272 docstring + 注释 |
| `test_independent_creation.py` | L4 docstring |
| `test_gate1_bootstrap.py` | L3 docstring（含历史 SQLite 形式说明） |
| `test_db_portable.py` | L19 引用 |
| `pg_test_kit.py` | L3 契约中心自述 |

### 10.3 TEST-IMPORT / TEST-HISTORY 硬门（`test_cw060_operator_isolation.py` 登记）

按 L16/L22/L227：
- **TEST-IMPORT**：`test_sqlite_to_postgres`（真实 PG 硬门，`require_pg_or_explicit_skip`）
- **TEST-HISTORY**：`test_migration_dialect_contract`（纯静态 AST 分析，`LEGACY_EXEMPTIONS` 例外不得增长）

CW-060 已将两者登记为**独立报告**（不与 TEST-PG 混跑）。

### 10.4 分类缺口

⚠️ **`server/pyproject.toml` L32-34 pytest markers 只有 `pg` 一个**：
```toml
markers = [
    "pg: requires the isolated PostgreSQL integration fixture",
]
```

**缺 TEST-IMPORT / TEST-HISTORY 独立 marker**——当前分类仅在 docstring 与 `pg_test_kit.py` 契约层，未在 pytest marker 层固化。CW-044 收口时需新增：

```toml
markers = [
    "pg: requires the isolated PostgreSQL integration fixture (TEST-PG)",
    "test_import: TEST-IMPORT — historical import tooling, runs against real PG",
    "test_history: TEST-HISTORY — pure-static AST/contract checks, no DB required",
]
```

### 10.5 未标记但应属 TEST-PG 的测试（分类缺口）

需 CW-043 独立核销时补齐。本次盘点未做全量分类审计（超出 INVENTORY_ONLY 范围），仅识别已显式标记的 12+ 文件。

### 10.6 CW-044 收口时需在 conftest/pyproject 加入的分类门禁

| # | 点位 | 动作 | 前置 |
|---|---|---|---|
| CLASS-1 | `server/pyproject.toml` markers | 新增 `test_import` / `test_history` marker | CW-043 |
| CLASS-2 | `server/tests/conftest.py` | 新增分类门禁 fixture：TEST-PG 类缺 PG 非 0 失败（当前 `pg_test_kit` 已在测试层实现，但 conftest 层无统一门禁） | CW-043 |
| CLASS-3 | `npm run check` / `test` | 增加分类报告输出（TEST-PG / TEST-IMPORT / TEST-HISTORY 三独立计数） | CW-043 |
| CLASS-4 | CI `quality-linux` | 增加 TEST-IMPORT/TEST-HISTORY 独立步骤（与 TEST-PG 分片并行） | CW-042, CW-043 |

---

## 11. 文档正本现状

### 11.1 六份正本（README §文档索引 L140-146 + AGENTS §必读正本 L26-31）

| # | 文档 | 用途 | CW-044 收口点位 |
|---|---|---|---|
| 1 | `docs/客户版任务清单-V3.md` | 唯一任务状态账本（DoD、红线、§12 工作包、§14 证据模板） | §18 CW-044 行需追加「盘点已就绪」子状态 |
| 2 | `docs/客户版代码开发清单-V3.md` | 唯一文件映射（新文件名已冻结） | 若 CW-040~042 删除文件，需同步 |
| 3 | `docs/客户版开发计划-V3.md` | 里程碑与禁止并行项 | 收口后需更新里程碑 |
| 4 | `docs/客户版激活码完整开发文档-V3.md` | 激活码业务与架构正本 | 无 CW-044 直接点位 |
| 5 | `docs/客户版测试与验收规格-V3.md` | 测试与验收正本 | ⚠️ CW-044 收口时需同步 TEST-* 分类门禁规格 |
| 6 | `docs/CUSTOMER-TASK-EVIDENCE-V3.md` | 证据账本 | CW-044 收口时需登记 |

### 11.2 客户生产部署手册

- `docs/客户版部署与灰度手册.md`：README L120 明确为「操作正本」；CW-044 收口时需确认无内部 P0 引用

### 11.3 内部 P0 文档（CW-040 需退出）

- `docs/内部运营P0单机部署与验收记录.md`
- `docs/内部运营与ZPay计费管理文档-P0.md`
- README L151 引用为「内部 P0 运营」文档

### 11.4 历史快照（不得作为实施依据）

- `docs/剩余开发工作清单.md`
- `docs/Windows内测与运维手册.md`
- README L151 + AGENTS L35 明确标记

### 11.5 其他关键文档

| 文档 | 用途 |
|---|---|
| `docs/客户云版开发顺序排班与Worktree协作清单.md` | 排班、前置、并行、开工/提交/清理流程（AGENTS L3 引用） |
| `docs/客户云版任务认领登记.md` | 执行占用与交接记录（AGENTS L3 引用） |
| `docs/PostgreSQL唯一数据库实施与验收规范.md` | PG 唯一数据库规范（README L6 + AGENTS L12 引用） |
| `docs/ChatGPT网页端开发交接提示词-V3.md` | 完整协作流程与最新进度快照（AGENTS L16 引用） |
| `docs/evidence/CW044-INVENTORY.md` | **本文件**（新增） |

### 11.6 CW-044 收口时需同步的文档点位

| # | 文档 | 动作 | 前置 |
|---|---|---|---|
| DOC-1 | `README.md` L21-27 双版本基线表格 | 删除内部 P0 列或改为「已退役」 | CW-040 |
| DOC-2 | `README.md` L35 「内部版显式 opt-in」 | 删除（CW-021 已退役内部版） | 无（可立即修，属文档 drift） |
| DOC-3 | `README.md` L63 「CW-007/025/044 交付」 | 改为「已交付」 | CW-044 收口完成 |
| DOC-4 | `README.md` L111 「CW-021: 内部版与本地 sidecar 启动链已退役」 | 保留（历史说明） | 无 |
| DOC-5 | `README.md` L151 内部 P0 运营文档引用 | 删除或改为归档说明 | CW-040 |
| DOC-6 | `README.md` L161 仓库结构 「内部版显式 opt-in」 | 删除 | 无（可立即修） |
| DOC-7 | `AGENTS.md` L21 「两条线：内部 P0 单机版已完成收口...」 | 简化为「客户版 V3 唯一产品线」 | CW-040 |
| DOC-8 | `AGENTS.md` L108-109 环境变量备忘 | 同步 CW-042/041 完成后的实际约束 | CW-041, CW-042 |
| DOC-9 | `docs/客户版任务清单-V3.md` §18 CW-044 行 | 收口完成后从 `[ ]` 改为 `[~] AUTOMATED_VERIFIED` | CW-044 收口完成 |
| DOC-10 | `docs/CUSTOMER-TASK-EVIDENCE-V3.md` | 登记 CW-044 证据 | CW-044 收口完成 |
| DOC-11 | `docs/客户版测试与验收规格-V3.md` | 同步 TEST-* 分类门禁规格 | CW-043 |
| DOC-12 | `docs/客户版部署与灰度手册.md` | 确认无内部 P0 引用 | CW-040 |
| DOC-13 | `README.md` §文档索引（L138-149，10 行） | **增列 `docs/客户版桌面升级与签名发布手册.md`**（CW-024 新增正本，当前在 README/AGENTS 零命中） | 无（§18.5） |
| DOC-14 | `README.md` §文档索引 + `AGENTS.md` §必读正本 | **增列 `deploy/customer/README.md`**（CW-032 新增交付手册，当前零命中） | 无（§18.5） |
| DOC-15 | `README.md` §仓库结构（L155-166） | L158「migrations/ Alembic 迁移链（001 → 055）」已陈旧（实测 head = `081_oral_unit_price`，CW-001 §1a 已记录 080→081）；L163 `deploy/` 描述缺 `deploy/customer/` 与 `deploy/operator/`；L164 `scripts/` 描述缺 `scripts/ci/`（含 self-hosted-runner 与 test-shards）与 `scripts/release/` | 无 |
| DOC-16 | `README.md` L118-119 发布段 | 补「CI 产物 = `internal-test-unsigned`（带 `RELEASE-CHANNEL.txt`）不可分发，唯一签名发布通道 = `npm run release:customer`」；另 L162 e2e 描述「gate1：内部纵向验收」与 CW-021/057 已退役的 harness 不一致（关联 NPM-3） | 无 |

---

## 12. PG preflight 现状与统一收口点

### 12.1 现有 PG 相关命令

| 命令 | PG 处理方式 | 缺 PG 行为 |
|---|---|---|
| `npm run check` | 末尾跑全量 pytest；测试层由 `pg_test_kit` fail-closed | 测试层非 0 失败；命令层无显式 preflight |
| `npm run check:sharded` | `run-pytest-shards.sh` 每片独立 PG 容器；Docker 不可用回退顺序单跑 | 测试层非 0 失败；命令层无显式 preflight |
| `npm run test` | 同 `check` 末尾 pytest 段 | 同上 |
| `npm run test:e2e` | 跑 `test_e2e_fake_provider.py`（可能需 PG） | 未验证 |
| `npm run test:customer-e2e` | Playwright；CI 里由独立 `pg-fixture.sh start` 步骤承担 | 本地跑需手动起 fixture |
| `npm run dev:server` / `dev:worker` | 通过 `dev-with-pg.sh` wrapper 幂等起 fixture | ✅ 已含 PG preflight（CW-025） |
| `scripts/pg-fixture.sh test` | 仅跑 `test_postgres_migrations.py` 单文件 | 容器未起则 exit 1 |
| `scripts/pg-fixture.sh start` | Docker 起 PG16 容器 | 30 秒超时 exit 1 |

### 12.2 CW-044 需加入的统一 PG preflight

按收敛清单 L608：
> 对 check/test/业务 E2E 及 pg-fixture test 加入统一 PG preflight

**实施建议**：
1. 新增 `scripts/pg-preflight.sh`（或扩展 `pg-fixture.sh` 加 `preflight` 子命令）：检测 `TEST_POSTGRESQL_URL` 或默认 DSN 可达性，不可达则 exit 1 并打印明确错误
2. 在 `check`, `check:sharded`, `test`, `test:e2e`, `test:customer-e2e`, `pg-fixture test` 六个入口前置调用
3. CI `quality-linux` 在 `check:static` 之前增加独立 preflight 步骤（早失败早诊断）

### 12.3 缺 PG 非 0 失败门禁的实施点位

| # | 点位 | 动作 | 前置 |
|---|---|---|---|
| PG-1 | 新增 `scripts/pg-preflight.sh`（或 `pg-fixture.sh preflight`） | 新增 | CW-043 |
| PG-2 | `package.json` 6 个 script 前置调用 preflight | 修改 | CW-043 |
| PG-3 | CI `quality-linux` 增加独立 preflight 步骤 | 新增 | CW-043 |
| PG-4 | `server/tests/conftest.py` 增加分类门禁 fixture（TEST-PG 缺 PG 非 0 失败） | 新增/强化 | CW-043 |

---

## 13. CW-044 收口蓝图（前置就绪后的实施步骤）

### 13.0 阶段 A0：**紧急独立修复**（不依赖任何前置，建议不等收口）

- CI-7 + SH-5 + SH-6：分片清单陈旧导致 13 个测试文件在 CI Linux 门从不执行（§18.2）。该缺口处于 **fail-open** 状态且每新增一个测试文件就会隐式扩大——盘点进行中 main 合入的 CW-058（#33，`test_cw058_content_asset_pg_matrix.py`）即第 13 个，是缺口单向增长的现场实证；与 CW-040/041/042/043 无依赖关系，建议开一个独立小任务先行修复。
- DOC-13 ~ DOC-16：两份新交付文档未进索引 + README 仓库结构/迁移链/发布通道陈述陈旧，纯文档修正，同样无前置。

### 13.1 阶段 A：CI 唯一化（依赖 CW-040/041/042）

- CI-1：移除 `changes` job desktop filter 中的 `packaging_tools/**`
- CI-2：增加统一 PG preflight 步骤
- CI-3：拆出 TEST-IMPORT/TEST-HISTORY 独立报告步骤
- CI-4：sharded pytest 增加缺 PG 非 0 失败门禁
- CI-5：`windows-nsis` forbidden 检测扩展（可选）
- CI-6：核查 `p0_acceptance_evidence.py` 无间接 CI 依赖
- CI-8：把「CI 产物 = internal-test-unsigned、唯一发布通道 = `release:customer`」写进交付文档正本（CW-024）

### 13.2 阶段 B：npm scripts 统一（依赖 CW-040/043）

- NPM-1：6 个 script 统一加入 PG preflight
- NPM-2：评估 `tauri:build:customer` 与 `tauri:build` 合并
- NPM-3：确认 `test:gate1` 是否删除
- NPM-4：新增 `check:pg-preflight` 独立入口
- NPM-5：新增 `test:history` / `test:import` 独立报告入口

### 13.3 阶段 C：文档同步（依赖 CW-040/041/042/043）

- DOC-1 ~ DOC-12（见 §11.6）
- 六份正本逐份复核
- README + AGENTS 双入口一致性

### 13.4 阶段 D：PG preflight 与 TEST-* 分类门禁（依赖 CW-043）

- PG-1 ~ PG-4（见 §12.3）
- CLASS-1 ~ CLASS-4（见 §10.6）

### 13.5 阶段 E：证据产出与验收

- 新增 `docs/evidence/CW044-EVIDENCE.md`（收口实施证据，与本盘点文件独立）
- 更新 `docs/客户版任务清单-V3.md` §18 CW-044 行为 `[~] AUTOMATED_VERIFIED`
- 更新 `docs/CUSTOMER-TASK-EVIDENCE-V3.md` 登记
- CI 三门禁全绿（secret-scan / quality-linux / windows-nsis）
- 验收标准（收敛清单 L610）：
  - CI 无内部包 build/archive 残留
  - 客户包可追踪版本和 SHA
  - 前端/PG/Rust/E2E/构建/依赖审计职责不缺失
  - 文档按空环境可执行且不再声称客户包携带后端或成片强制 COS 归档
  - 断开 PG 后上述业务命令均非 0 失败
  - PG 可用时 TEST-PG 类 100% 执行、缺库 skip=0
  - TEST-IMPORT/TEST-HISTORY 独立结果仍须通过
  - 记录 server_version、起止 head、隔离 ID、执行/失败/skip 数

---

## 14. 与前置任务的映射矩阵

### 14.1 CW-019 → CW-044（已完成，作为基线）

| CW-019 成果 | CW-044 消费方式 |
|---|---|
| 客户/管理独立构建（`build:admin` + `vite.admin.config.ts` + `dist-admin`） | 保留，不改 |
| `verify_customer_bundle.mjs`（24.6 KB） | 保留，不改 |
| CI `Build admin bundle` + `Verify customer bundle` 步骤 | 保留，不改 |
| `deploy/customer-git-rollout.sh` M1 修（同 SHA 原子替换 + admin 备份/回滚） | 保留，不改 |

### 14.2 CW-040 → CW-044（内部发行退出后的收口点）

| CW-040 交付 | CW-044 收口点 |
|---|---|
| 物理删除 `packaging_tools/` | PKG-1/2/3, CI-1, SH-2 |
| 物理删除 `deploy/internal-p0.env.example` + `nginx/internal-p0.conf.example` | DEP-1, DOC-1, DOC-5 |
| 物理删除 `deploy/systemd/video-replica-backup.{service,timer}` | DEP-3 |
| 物理删除 `scripts/p0_acceptance_evidence.py` | SH-4, CI-6 |
| 归档或删除内部 P0 双文档 | DOC-5, DEP-3 |

### 14.3 CW-041 → CW-044（内部身份退出后的收口点）

| CW-041 交付 | CW-044 收口点 |
|---|---|
| 删除或归档 `server/app/internal_{accounts,billing}.py` | INT-1（间接） |
| 删除或转 TEST-HISTORY `server/tests/test_internal_*.py`（4 文件） | INT-1, SH-3 |
| 删除 `client/src/internalBillingApi.test.ts` | INT-1（间接） |
| 修改 `server/pyproject.toml` description | INT-2 |
| 处置迁移 `022_internal_billing.py`（不可删，可新增后续 revision） | 无 CW-044 直接点位 |

### 14.4 CW-042 → CW-044（SQLite 裁剪后的收口点）

| CW-042 交付 | CW-044 收口点 |
|---|---|
| 裁剪 `server/app/generation_worker.py` `run_worker_once` SQLite 核心 | SQL-2（间接） |
| 迁移或删除 7+ 测试文件的 SQLite 直用 | SQL-2, CLASS-3 |
| 文档同步（README/AGENTS SQLite 表述） | DOC-3, DOC-8 |

### 14.5 CW-043 → CW-044（PG 覆盖核销后的收口点）

| CW-043 交付 | CW-044 收口点 |
|---|---|
| 独立核销全业务 PG 测试覆盖 | CLASS-1/2/3/4, PG-1/2/3/4 |
| 补齐未标记但应属 TEST-PG 的测试分类 | CLASS-1 |
| 确认 TEST-IMPORT/TEST-HISTORY 独立报告机制 | CI-3, NPM-5 |

### 14.6 CW-044 → CW-045（本次盘点直接供最终门禁消费）

| CW-044 交付 | CW-045 消费方式 |
|---|---|
| 本盘点文件（`CW044-INVENTORY.md`） | 直接作为 CI/命令/文档现状基线，无需重新调研 |
| CW-044 收口实施证据（`CW044-EVIDENCE.md`，未来产出） | 作为最终候选门禁的输入 |
| 统一 PG preflight 与 TEST-* 分类门禁 | CW-045 全量门禁直接沿用 |

---

## 15. 未决问题与风险登记

### 15.1 `packaging_tools/` 是否整体退出还是保留部分

- **现状**：10 个 tracked 文件，CI 未直接调用，`verify_no_secrets.sh` 扫描覆盖
- **未决**：`install_skill.py` 是否被客户线复用？若否，整体删除；若是，需拆分
- **建议**：CW-040 开工前由 owner 确认

### 15.2 已发布迁移 `022_internal_billing.py` 的处置

- **现状**：红线约束不可篡改
- **未决**：`internal_billing` 表是否仍有数据？若有，drop table 需数据保全方案
- **建议**：CW-041 开工前由 owner + DBA 确认

### 15.3 `test_internal_*.py` 的处置（删测还是保留为 TEST-HISTORY）

- **现状**：4 文件，总时长 ~25s
- **未决**：若 CW-026/027 已完全退出内部认证与管理端，可删；若需保留历史契约验证，转 TEST-HISTORY
- **建议**：CW-041 开工前由 owner 确认

### 15.4 双 Tauri 配置是否合并为单配置

- **现状**：`tauri.conf.json`（61 行 base）+ `tauri.customer.conf.json`（11 行 overlay）
- **未决**：合并可减少文件数，但失去分层清晰性
- **建议**：保留双配置（分层清晰 > 文件数减少）

### 15.5 `sqlalchemy` 依赖是否违反「禁止 ORM」红线

- **现状**：`server/pyproject.toml` L13 `sqlalchemy>=2.0.52`；AGENTS.md L52 红线「禁止引入 ORM」
- **未决**：sqlalchemy 是否仅用于 Core（SQL 表达式语言）而非 ORM？需扫描 `server/app/` 实际用法
- **建议**：CW-044 收口实施时补充扫描（本次盘点未覆盖，见 §16）

---

## 16. 本次盘点未覆盖的范围（诚实登记）

按 `scope=INVENTORY_ONLY` 与 `forbidden_touch` 约束，以下明确**未盘点**，留待 CW-044 收口实施会话或相应前置任务：

| 未覆盖项 | 归属 | 备注 |
|---|---|---|
| `server/app/` 全域 SQLite 分支扫描（除 `generation_worker.py` 外） | CW-042 | 本次仅盘点 tests 层 |
| `server/app/` 全域 internal 消费者扫描 | CW-041 | 本次仅盘点文件存在性 |
| `sqlalchemy` 实际用法（ORM vs Core） | CW-044 收口实施 | 见 §15.5 |
| `client/src/` 全域 internal 引用扫描（除 `internalBillingApi.test.ts` 外） | CW-041 | 本次仅盘点单文件 |
| `e2e/` 目录结构与门禁覆盖 | CW-044 收口实施 | 本次未读 |
| `server/tests/conftest.py` 完整内容 | CW-043 | 本次未读 |
| `scripts/verify_customer_bundle.mjs` 24.6 KB 完整逻辑 | CW-044 收口实施 | 本次仅读头部注释 |
| `deploy/customer-git-rollout.sh` 完整逻辑 | CW-044 收口实施 | 本次未读 |
| `docs/` 376 文件逐份内容审计 | CW-044 收口实施 | 本次仅盘点顶层结构与六份正本 |
| CI 三门禁在最终候选 SHA 上的实际执行结果 | CW-045 | 本次盘点不涉及 CI 执行 |
| PG 覆盖核销（旧用例 → PG 用例映射矩阵） | CW-043 | 本次仅识别 TEST-PG 标记现状 |
| 内部 P0 数据保全与归档方案 | CW-040 | 本次仅识别退出目标 |

---

## 17. 盘点交付物验收

### 17.1 本文件自身的验收标准

- ✅ 覆盖 CI / npm scripts / Tauri / scripts / deploy / packaging_tools / pyproject / SQLite / internal / TEST-* / 文档正本 / PG preflight 共 12 个维度
- ✅ 每个维度均给出**具体文件路径 + 行号 + 引用来源**（可独立复核）
- ✅ 每个收口点位均标注**前置依赖**（CW-040/041/042/043/无）
- ✅ 与前置任务的映射矩阵（§14）覆盖 CW-019/040/041/042/043/045 六个方向
- ✅ 未决问题（§15）与未覆盖范围（§16）诚实登记

### 17.2 消费方使用指南

| 消费方 | 直接消费章节 |
|---|---|
| CW-040 开工会话 | §5.3, §6.2, §7, §9.5, §14.2 |
| CW-041 开工会话 | §9.1-9.4, §9.6, §14.3 |
| CW-042 开工会话 | §8.1-8.3, §14.4 |
| CW-043 开工会话 | §10, §12, §14.5 |
| CW-044 收口实施会话 | §13（蓝图）, §14（映射）, §15（未决）, §16（未覆盖） |
| CW-045 最终门禁会话 | §1.2（核心结论）, §13.5（阶段 E）, §14.6 |

### 17.3 更新机制

- 本文件是**基线盘点**，不随 main 前进自动更新
- **交付前已发生的三个合并**（CW-032 #31、CW-024 #32、CW-058 #33）已在本会话内两次 rebase 并完成增量复核，结果记在 **§18**（而非另开 EVIDENCE 文件，因为本文件尚未交付）
- 若前置任务在本文件交付之后、CW-044 收口实施之前合入 main，收口实施会话需先 rebase 到最新 main 并**增量复核**本文件相关章节
- 后续增量复核结果记入 `docs/evidence/CW044-EVIDENCE.md`（未来产出），§1-§17 保持本次交付时的基线不变

---

## 18. 增量复核（两次 rebase 至 `origin/main @ 38ae06c`）

### 18.1 基线变更

本次盘点起于 `1b78734`（CW-030 #29 后）。push 前 `git fetch` 发现 main 已前进三个合并：CW-032/CW-024 与本盘点对象（CI / 命令 / 部署 / 交付文档）**直接重叠**，CW-058 则新增一个 TEST-PG 测试文件、直接为 §18.2 缺口提供现场实证，故两次 rebase（先到 `b976976`、再到 `38ae06c`）后增量复核：

| 提交 | 任务 | PR | 对本盘点的影响面 |
|---|---|---|---|
| `db72705` | CW-032 可复建客户后端交付包 | #31 | `deploy/customer/`（3 新文件）、`deploy/customer-git-rollout.sh`、`package.json`、新测试 |
| `b976976` | CW-024 唯一签名发布流程 + 旧版卸载门 | #32 | `package.json`（+`release:customer`）、`scripts/release/`、`ci.yml` windows-nsis、`customer-installer-hooks.nsh`、新手册、新测试 |
| `38ae06c` | CW-058 内容/资产域矩阵重托管真实 PG（TEST-PG） | #33 | `server/tests/test_cw058_content_asset_pg_matrix.py`（新增 1534 行 / 20 用例）、`server/app/character_asset_review.py`（三处 SQLite rowid → 按 is_postgres 选 ctid/rowid）、`server/tests/pg_test_kit.py`、账本 CW-058 行、认领登记表 CW-058 行；**未触碰 `scripts/ci`、`test-shards`、`ci.yml`、`package.json`、`deploy/`** → root scripts 仍 25、scripts/ 仍 23、deploy/ 仍 28，唯一盘点相关增量是测试文件 111→112（§18.2 缺口 12→13） |

rebase 结果：第一次到 `b976976` **0 冲突**（CW-024 行 / CW-032 行与本任务 CW-044 行相距足够远，账本三方合并自动完成）；第二次到 `38ae06c` 时，CW-058 把账本 CW-058 行由 `[ ]` 改为 `[~] AUTOMATED_VERIFIED`，该行紧邻本任务 CW-044 行，触发**相邻行 content 冲突**——已用 `git checkout --ours` 取 main 版账本（保留 CW-058 `[~]` 行）后重挂 CW-044 子状态解决；认领登记表因本任务段落与 CW-058 表行分处不同区域，**自动合并成功**。最终 `git merge-base --is-ancestor origin/main HEAD` = true，分支仅 1 个提交、无外来提交。

### 18.2 【最高优先】分片清单陈旧 → CI Linux 门漏跑 13 个测试文件

#### 事实链（均可独立复核，行号为 rebase 后实测）

1. **CI 只有一个 server pytest 步骤**：`.github/workflows/ci.yml` L217-223 `Run sharded PostgreSQL pytest` → `bash scripts/ci/run-pytest-shards.sh`；L214-216 注释明确 `check:static` 是 “former `npm run check` minus its trailing full pytest”。**无全量 pytest 兜底步骤**。
2. **清单齐全即直接采用、不校验完整性**：`scripts/ci/run-pytest-shards.sh` L69-82 `resolve_manifests()` 只检查 `shard-0..(N-1).txt` 是否存在，存在则 `SHARD_SRC_DIR=committed` 并 `return 0`；**无任何将清单并集与实际测试集对比的代码**。
3. **pytest 只跑清单内文件**：L154-164 逐行读 manifest 拼成 `files` 后 `"${UV_PYTEST[@]}" ${files}`——不是跑 `server/tests` 目录。
4. **生成器本身是会包含新文件的**：`scripts/ci/build-test-shards.py` L71-74 `discover_test_files()` 用 `rglob("test_*.py")`，L48 还为「无基线时长的新测试」定义了 `DEFAULT_NEW_FILE_COST`。即：**不是设计缺陷，而是 committed 清单从未重新生成**。
5. **实测差额**：`git ls-tree -r origin/main -- server/tests` 中 `test_*.py` = **112**（rebase 前 `b976976` 为 111，CW-058 合入后 +1）；4 份 committed 清单并集（去重）= **99**；差额 **13**。反向核对：清单中**零幽灵条目**（manifest ⊂ repo），即 99 个全部存在。
6. **时长基线同样陈旧**：这 13 个文件在 `scripts/ci/test-durations.json` 中**全部无条目**（逐个 `MISSING` 实测，含 CW-058 的 `test_cw058_content_asset_pg_matrix.py`）——分片清单与时长基线是同一时间点冻结后一起陈旧的。

#### 差额名单（CI Linux 门从不执行的 13 个文件）

| 测试文件 | 归属任务（均已合入 main） |
|---|---|
| `test_cw024_signed_release_upgrade_contracts.py` | CW-024（#32，**第一次 rebase 刚合入**） |
| `test_cw032_delivery_package.py` | CW-032（#31，**第一次 rebase 刚合入**） |
| `test_cw058_content_asset_pg_matrix.py` | CW-058（#33，**盘点进行中第二次 rebase 刚合入；1534 行 / 20 用例 TEST-PG 矩阵，缺口单向增长的现场实证**） |
| `test_cw026_converged_auth.py` | CW-026（#20） |
| `test_cw027_admin_permission_matrix.py` | CW-027（#23） |
| `test_cw028_shared_settings_contract.py` | CW-028（#28） |
| `test_cw029_billing_pg_matrix.py` | CW-029（#24） |
| `test_cw030_worker_pg_matrix.py` | CW-030（#29） |
| `test_cw054_pg_portable_contract.py` | CW-054（#14） |
| `test_cw056_supported_head_matrix.py` | CW-056（#15） |
| `test_cw057_cli_pg_entry.py` | CW-057（#19） |
| `test_cw060_operator_isolation.py` | CW-060（#27） |
| `test_storage_cross_instance.py` | CW-031（#17） |

**不是全面漏跑**：早于清单最后一次生成的文件已覆盖（例如 CW-055 的 `test_db_pg.py` 在 `shard-0.txt` 内，账本记载的 “shard0 659 含 test_db_pg.py” 与此一致）。缺口是**单向增长**的：每新增一个测试文件就静默扩大一位——本次盘点期间即被现场验证：`b976976` 时差额 12，仅一个合并（CW-058 #33）之后 `38ae06c` 差额即变 13，且 CW-058 完全未触碰 `scripts/ci`（清单/时长基线原样），说明该缺口会随每一次 TEST-* 合入自动扩大，无需任何“出错”动作。

#### 影响面

- 上述 13 个任务（CW-024/026/027/028/029/030/031/032/054/056/057/058/060）账本行的「CI 三门禁全绿」与「Linux 分片全量 pytest NNNN passed」**均未包含其自身新增的测试文件**。这些计数本身是真实的（分片确实全绿），但**不等于全量 pytest 全绿**。尤其 CW-058 账本行自称「GREEN 20 passed」是在其**专属容器 vs-pg-cw058@5440 手工跑**得到的，CI Linux 门并不会复跑这 20 个用例。
- 其中多个文件是 **PG 专项/契约守卫**（CW-056 升级矩阵、CW-057 CLI PG 入口、CW-060 operator 隔离、CW-029 账务 PG 矩阵、CW-030 Worker PG 矩阵），也是 CW-043「独立核销全业务 PG 测试覆盖」的直接对象——**CW-043 开工前必须先修此缺口**，否则核销对象本身不在门禁内。
- `test_cw024_signed_release_upgrade_contracts.py` 是 `release:customer` 的**唯一自动化验证**（CI 不跑签名构建，需签名材料），它不在门禁内 = 唯一签名发布通道实质上无 CI 守卫。

#### 反直觉点（需写进交付文档）

L54-60 `run_sequential()` 传的是 `server/tests` 整个目录——即**本地无 Docker 时反而全覆盖**，而 CI（Docker 可用、N=4）只覆盖 99/112。开发者本地跑 `npm run check`（顺序全量）也是全覆盖，所以该缺口在本地**永不暴露**，只在 CI 生效。

#### 修复建议（均为本盘点建议，本分支不实施）

| 编号 | 动作 | 验收方式 |
|---|---|---|
| SH-5 | `python3 scripts/ci/build-test-shards.py --shards 4` 重生 committed 清单；再用 `--from-log` 刷新时长基线 | 并集 = 112、四片时长均衡 |
| SH-6 | `resolve_manifests()` 加 fail-closed 完整性守卫（余集非空即 exit 非 0，或自动追加到最短分片） | 删一个清单条目 → 脚本必须失败（变异测试） |
| CI-7 | `quality-linux` 增一个覆盖率断言步骤，与 SH-6 互为双保险 | 在 PR 日志里可读到 discovered/manifest 计数 |

### 18.3 CW-024（#32）对盘点面的增量

| 变更 | 内容 | 盘点归位 |
|---|---|---|
| `package.json` | +1 script `release:customer` → root 总数 **24→25** | §3.1（已补行）、NPM 分类新增「发布」类 |
| `scripts/release/build-customer-signed-release.ps1` | 新目录 + 新文件（142 行），fail-closed：无签名材料 / 无获批云 origin / 未通过 Authenticode 验签 → 不产出任何制品；构建期复验 **6 处版本冻结源** | §5.8；版本链一致性是 CW-044「客户包可追踪版本和 SHA」验收项的直接支撑 |
| `.github/workflows/ci.yml` | windows-nsis 制品目录 `customer-cloud` → `customer-cloud-internal-test-unsigned`；新增 `RELEASE-CHANNEL.txt` = `internal-test-unsigned` | §2.1 windows-nsis 行需以此为准；CI-8 |
| `client/src-tauri/customer-installer-hooks.nsh` | +115 行：legacy 世代（0.1.12 / 0.1.13 / 0.1.15 / 0.1.16 #92）旧版卸载以已验签归档为前提 | TAURI-3 |
| `docs/客户版桌面升级与签名发布手册.md` | 新增顶层正本（123 行） | DOC-13（**未进索引**） |
| `server/tests/test_cw024_signed_release_upgrade_contracts.py` | 新增 226 行契约测试 | §18.2 差额名单首位 |

### 18.4 CW-032（#31）对盘点面的增量

| 变更 | 内容 | 盘点归位 |
|---|---|---|
| `deploy/customer/compose.yaml` | 客户后端唯一默认交付拓扑（db + 一次性 migrate + api×2 + worker×4）；`migrate` 是唯一执行 DDL 的角色，api/worker 经 `service_completed_successfully` 等待 | §6.1（已补行）、DEP-5 |
| `deploy/customer/bootstrap-base-image.sh` | 空白环境首个应用镜像 | §6.1 |
| `deploy/customer/README.md` | 95 行重建手册（含连接池预算 6×8=48+1+3=52 ≤ `max_connections=120`） | §6.1、DEP-4、DOC-14 |
| `deploy/customer-git-rollout.sh` | `COMPOSE` 改为仓内制品（保留 `CUSTOMER_COMPOSE=` 兼容）+ 备份写 `compose.sha256` | §6.1 行已纪正 |
| `server/tests/test_cw032_delivery_package.py` | 新增 193 行契约测试 | §18.2 差额名单 |
| `deploy/` 总数 | **25→28** | §1.1、§6 标题已纪正 |

**连带发现（`ffmpeg-minimal/` 无发行消费者）**：`scripts/ffmpeg-minimal/build.sh` 默认把产物写到 `client/src-tauri/resources/ffmpeg/`，而 CW-021 已将 `tauri.conf.json` L32 `bundle.resources` 置空、windows-nsis forbidden 名单又包含 `ffmpeg.exe`——即该脚本的桌面产物目标**已不再随客户包发行**（tracked 仅 `.gitignore` + `README.md`）。处置见 SH-7；本盘点不判定它无用（服务端媒体校验仍可能依赖 ffmpeg），仅登记「产物目标与发行契约不一致」。

### 18.5 文档索引 drift（零命中证据）

对 `README.md`、`AGENTS.md`、`docs/客户版部署与灰度手册.md` 三份入口文档执行 `git grep -E "签名发布手册|deploy/customer/README|release:customer|build-customer-signed-release|RELEASE-CHANNEL"` → **exit 1（零命中）**；再用编辑器级 grep 复核 `README.md` §文档索引（L138-149，10 行）与 `AGENTS.md` §必读正本（L24-）亦无两份新文档。

后果：一个按「空环境可执行」读 README 的人，**找不到唯一签名发布通道与客户后端交付包的手册**——直接冲撞 CW-044 验收标准「文档按空环境可执行」。对应 DOC-13 / DOC-14 / DEP-4。

### 18.6 初稿计数纪正（本盘点自身缺陷）

| 项 | 初稿 | 实测（`git ls-files` / JSON 解析） | 原因 |
|---|---|---|---|
| root `package.json` scripts | 「23 scripts」（但 §3.1 表实际列了 24 行） | `1b78734` 时 **24**，`b976976` 时 **25** | 初稿标题计数手误，与自身表格不一致 |
| `scripts/` 文件数 | 「10 个（7 root + 3 ci/）」 | **23** | 漏盘 `ci/self-hosted-runner/`（5）、`ci/test-shards/`（4）、`ffmpeg-minimal/`（3），以及 CW-024 新增 `release/`（1） |
| §15 未决问题数 | §1.2 写「4 项」 | §15 实际 **5** 项（15.1-15.5） | 初稿交叉引用手误 |
| §1.2 收口点位总数 | 「21 处 → 叠加 12 处 = 33 处」（且列举的新增 ID 实为 13 个） | `git grep` 实测全文 **11 类 63 个编号点位**（CI-1~8/NPM-1~6/SH-1~7/DEP-1~5/PKG-1~3/SQL-1~2/INT-1~5/CLASS-1~4/PG-1~4/TAURI-1~3/DOC-1~16） | 「21 处」是 §13 蓝图子集口径、与全文编号总数不同分母；且 21+13≠33 有加法误差。已统一改以实测 63 处为准 |

三处计数缺陷均已在正文就地纪正（§3.1 / §5 标题与 §1.1 表 / §1.2 收口点位口径），并保留本表作为自查记录。其中 `scripts/` 漏盘**直接导致初稿没发现 §18.2 的门禁缺口**（`ci/test-shards/` 正是漏盘的 4 个文件），这是本次纪正中最重要的教训：**目录级计数必须用 `git ls-files` 实测、编号点位总数必须用 `git grep` 实测，不得凭顶层目录印象相加或凭蓝图子集口径外推**。

### 18.7 增量复核可复现命令

```powershell
# 1. rebase 与祖先关系
git fetch origin; git rebase origin/main
git merge-base --is-ancestor origin/main HEAD   # exit 0 = 已含最新 main

# 2. 三个合并的改动面
git log --oneline 1b78734..origin/main
git diff --name-status 1b78734 origin/main

# 3. 分片覆盖率差额（§18.2 核心证据）
$shards = Get-Content scripts/ci/test-shards/shard-*.txt | ? { $_ -ne '' } | Sort-Object -Unique
$actual = git ls-files 'server/tests/test_*.py' | Sort-Object -Unique
Compare-Object $actual $shards   # '<=' 即 CI 从不执行的文件

# 4. 目录级计数（§18.6 纪正依据）
git ls-files scripts | Measure-Object -Line
git ls-files deploy  | Measure-Object -Line
git ls-files docs    | Measure-Object -Line
(Get-Content package.json -Raw | ConvertFrom-Json).scripts.PSObject.Properties.Name.Count

# 5. 文档索引 drift（§18.5 证据）
git grep -n -E "签名发布手册|deploy/customer/README|release:customer|RELEASE-CHANNEL" -- README.md AGENTS.md
```

### 18.8 rebase 后重跑的验证（两次 rebase 至 `38ae06c` 后复跑；docs-only 改动，CW-058 仅动 server/tests 与账本，不影响下列读 docs 的测试）

| 验证 | 命令 | 结果 |
|---|---|---|
| 秘密扫描（含新增 docs，`--untracked`） | `bash scripts/verify_no_secrets.sh` | exit **0** |
| 实际读 `docs/` 的 5 份 server 测试 | `pytest tests/test_cw033_evidence_boundary.py tests/test_customer_ha_smoke.py tests/test_cw009_security_matrix_export.py tests/test_customer_pitr.py tests/test_internal_deployment.py -q` | **71 passed / 0 failed** |
| 其余 4 份匹配 "docs" 的测试 | `git grep -n docs -- <4 files>` | 仅 docstring 提及，**不读文件**，故不属受影响面 |
| 目录级断言风险 | `git grep -E "(iterdir\|glob\|rglob\|listdir)\(" -- server/tests/*.py` 筛 docs/evidence | **零命中** → 新增 evidence 文件不会破坏任何目录断言 |
| 账本锚点 | `\| [~] \| T39 \|`（test_customer_ha_smoke）与 CW-033 行正则（test_cw033_evidence_boundary） | 两处锚点均完好 |
| 本地环境声明 | 无 `uv`、无 worktree `.venv`；借用主仓库 `server/.venv`（Python 3.12.14 + pytest 9.1.1）只跑上述静态测试 | **未占用 PG**（与 claim `test_resources.pg_instance=N/A` 一致；当时本机在跑其他任务的 5 个 PG 容器，均未触碰） |
| 未跑的验证 | 全量 pytest / biome / tsc / cargo / 构建 / NSIS | docs-only 改动，**交 CI 三门禁裁决**，未记为已验证 |

---

**盘点结束**。本文件是 CW-044 前置盘点的唯一交付物，不修改任何 CI/命令/构建脚本/源码。实际收口实施待前置 CW-040/041/042/043 全部合入 main 后另启会话。

**但 §18.2 的门禁缺口不等收口**：它现在就处于 fail-open 状态，不依赖任何前置，且每合入一个新测试文件就静默扩大——本次盘点期间 main 合入的 CW-058（#33）已把差额从 12 现场推到 13，坐实了「单向增长」。建议 owner 读完 §18.2 后直接开一个独立修复任务（SH-5 + SH-6 + CI-7），且 CW-043 开工前必须先修。
