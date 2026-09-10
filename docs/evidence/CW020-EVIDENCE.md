# CW-020 — 将现有客户配置提升为唯一默认

## 任务信息（§14 模板）

| 字段 | 值 |
| --- | --- |
| 任务/工作包 | CW-020（W3·代码与测试增量·桌面负责人）将现有客户配置提升为唯一默认；DoD（V3 line 370）：①唯一默认配置和命令合同通过；②**旧配置不再能意外生成内部发行包**；③文档与脚本一致。保留验收底线（line 369）：默认构建就得到客户包（不要求操作者记住 `:customer`）、无本地 API 地址回退、客户 identifier/版本链/窗口权限保持、客户 WebView 正确连接明确的 HTTPS 后端 |
| Owner / Reviewer | Owner：ZCode 代理（hlong026 会话，2026-09-11）；Reviewer：独立 CodeReview 子代理（结论见 §6，**无 Must-fix**；1 Should-fix 已修、4 Consider 逐条处置）+ PR review |
| 分支 / 基线 SHA | `feat/customer-v3-cw020-customer-config-sole-default`；基线 `origin/main@e829ad1`（初建 `0d08608`＝CW-019 PR#12 squash 后；开工后 main 前进 `0d08608→e829ad1`＝CW-054 #14 + CW-055 #13 纯 PG 任务，`git rebase origin/main` 快进零冲突，7 代码目标文件逐字节一致→设计有效）；独立 worktree `乡墅爆款短视频复刻-cw020`（按 COORD 协议：从 main 建独立 worktree + 尽早 push 分支） |
| 上游规格段落 | V3 剩余任务清单 §CW-020（line 358–372）；文件/对象（line 367）：`tauri.conf.json`/`tauri.customer.conf.json`/`Cargo.toml`/`package.json` 四核心；承接 CW-011（line 366）：改默认配置前按 CW-003 锁住已发客户 identifier/app_data_dir/凭据命名空间/版本链；账本 §18 CW-020 行（line 485）、§12.6 DESK-02 行（line 286） |
| 前置任务 | CW-019、CW-003、CW-001、CW-002、CW-004、CW-005、CW-053 —— 全部已合入 main（CW-019 PR#12@0d08608 为本任务直接基线前置） |
| 改动文件 | **13 文件（4 spec 核心 + 8 DoD 派生 + 1 收尾回归修复）+ 本证据文件；tracked 12 文件 +317/−164，另新增 1 文件 32 行**。核心：`client/src-tauri/tauri.conf.json`（base 翻为客户 foundation，+18）、`client/src-tauri/tauri.customer.conf.json`（瘦为仅 installerHooks，−25）、`client/src-tauri/Cargo.toml`（`default=[]`，+16）、`package.json`（脚本翻转，+8）。DoD 派生：`client/src-tauri/tauri.internal.conf.json`（**新建** 32 行，内部 opt-in overlay，用户决策 A）、`.github/workflows/ci.yml`（windows-nsis job 3 改，+8）、`server/tests/test_build_contracts.py`（+7）、`server/tests/test_customer_ha_smoke.py`（重写双发行合同→唯一默认 + 3 负向断言，+117）、`README.md`（+11）、`docs/客户版代码开发清单-V3.md`（冻结映射 §4.6 登记新文件，+26）、`docs/客户版部署与灰度手册.md`（§6 生产验收描述纪正，+16/−9）、`docs/客户版任务清单-V3.md`（§18 CW-020 行 + §12.6 DESK-02 脚注）、`server/tests/test_desktop_artifact_no_pg_dsn.py`（**收尾回归修复**：CW-025 守卫重指向 CW-020 三配置布局并强化，+143/−73，见 §3.1） |
| 重复开发核查（用户红线） | **六层核查全空 → CW-020 独占**（开工前 3 次 + re-anchor 兼作第 4 次）：DIM1 无其它 cw020 worktree；DIM2 本地+远端无其它 cw020 分支；DIM3 全 ref `--grep=CW-020` 零命中；DIM4 其余 worktree（main/c5-publish/cw015/人物IP口播/素材库）对全部目标文件**零未提交 WIP**；DIM5 无 claim；DIM6 无任何状态 CW-020 PR。re-anchor 后复核 CW-054/055 纯 PG 合入未碰 CW-020 代码目标（详见 §7） |
| 失败测试或回归锁定 | **RED→GREEN（承接 CW-011 先锁失败用例）**：先把 2 个目标合同测试重写为断言「客户版＝唯一默认」的新合同，对**旧配置**（内部为默认）跑出 **2 failed**——① `test_build_contracts.py:159` `assert "npm run check:tauri:internal" in workflow`（旧 ci.yml 仍是 `check:tauri:customer`）；② `test_customer_ha_smoke.py:624` `assert base_config["identifier"] == "com.xiangshu..."`（旧 base 是 `com.internal.video-replica`）。两失败精确对应 DoD ①②缺口。翻转配置后 **GREEN 2 passed**；CodeReview 后再加 3 负向断言仍 **9 passed**（1 目标 + 8 `test_build_contracts.py` 全量，无需 PG） |
| 实现结果 | §2 交付明细；§3 验证结果；§4 三配置合并矩阵 + 保留验收底线映射；§5 范围界定与 CW-021 边界 |
| 验证命令与通过数 | 全仓门禁 `npm run check`（Node 24.14.1 / cargo 1.94.1 / uv 0.11.6，PG fixture Docker PG16@5433）：secrets exit 0；client biome 202 files、`tsc -b` exit 0、**vitest 80 文件 1296 passed**；check:e2e biome 15 files；check:tauri `cargo fmt --check` + `cargo check --locked`（客户默认）exit 0；server ruff check All passed、ruff format 296 files already formatted、mypy **Success 104 source files**；**server 全量 pytest（诊断跑）3 failed / 2342 passed / 1 skipped in 900.77s——3 failed 全落在 CW-025 守卫 `test_desktop_artifact_no_pg_dsn.py`（本任务翻转造成的 drift，§3.1），修复后干净验收跑 **0 failed / 2345 passed / 1 skipped in 882.50s（EXIT_CODE=0）****。cargo 内部 edition（`--features local-sidecar`）单独复验 exit 0。详见 §3 |
| 证据层级 | AUTOMATED_VERIFIED（全仓门全绿 + RED→GREEN 两锁精确对应 DoD 缺口 + 收尾全量 pytest 抓到并修复 CW-025 守卫 drift（§3.1）+ 三配置合并矩阵与保留验收底线逐条映射 + CodeReview 无 Must-fix + cargo 双 edition 均 exit 0 + 重复开发六层独占；纯构建配置/合同/文档增量，无 staging/真实链路依赖）。**未过真实链路，不标 STAGING_VERIFIED/PRODUCTION_GO**：真实 Windows NSIS 构建/解包/签名/实机安装归 CI Windows 门禁与 DESK-03/04、CW-024/CW-046；`cargo test`/`npm audit`/客户浏览器 E2E/`npm run build` 只在 CI 三门禁执行 |
| 安全与可观测性 | 无密钥/激活码明文/设备或 session token 进代码、测试、日志、夹具或 PR；secrets 扫描 exit 0。客户版 base CSP 保持 HTTPS-only（无 `127.0.0.1:8000` loopback），origin guard（`require_customer_api_base.mjs`）强制可路由非 loopback HTTPS origin；`Cargo.toml default=[]` 保证任何未显式 `--features local-sidecar` 的构建都不会打进本地启动器（DoD ②的编译期硬保证） |
| 迁移与回滚 | 纯构建配置/命令合同/文档增量，**无数据库/迁移文件改动**，`server/app` 零触碰（仅动 `server/tests/` 2 个合同测试）。回滚 = revert 本分支（base 恢复为内部 foundation、`Cargo.toml default=["local-sidecar"]`、脚本恢复 `check:tauri:customer`、删除 `tauri.internal.conf.json`，即回到 CW-020 前状态） |
| 外部授权记录 | 无（不涉及真实 ZPay/付费 Provider/生产 COS/发码/灰度/公网发布；构建合同测试全程读本地配置文件，不发真实请求、不产真实安装包） |
| 未测试项 | 真实 Windows NSIS 构建/解包/拒绝本地启动脚本（`Verify customer installer excludes local launchers` 步骤属 CW-021 域，本地 macOS 跑不到）、`cargo test`、`npm audit`、客户浏览器 E2E（Playwright）、`npm run build`——均**只在 CI 三门禁执行**，以 push 后 CI 为准。签名/实机安装/升级/卸载归 DESK-03/04、CW-024/CW-046 |
| Lore 提交 SHA | 本 PR squash 后回填 |

## 2. 交付明细（对照 CW-020 DoD「仅做剩余」line 365）

| 规格要求（V3 line 365/368/370） | 交付 |
| --- | --- |
| 把现有客户配置和命令变成唯一默认 | `tauri.conf.json`（base）翻为客户 foundation：identifier `com.xiangshu.video-replica.customer`、productName `短视频复刻客户云工作台`、窗口 `url:"customer"`/`title:""`、`bundle.resources:[]`、publisher `Xiangshu Video Replica`、startMenuFolder `短视频复刻客户云工作台`、HTTPS-only CSP。`tauri.customer.conf.json` 瘦为**仅** `bundle.windows.nsis.installerHooks`（发行专属钩子）。`package.json`：`tauri:build` 直接产客户包（`--config tauri.customer.conf.json --no-default-features` + origin guard），`tauri:build:customer` 保留为别名，`check:tauri`/`tauri:dev` 默认即客户版 |
| 删除内部 default feature/config 对正式发行的影响 | `Cargo.toml` `default=["local-sidecar"]`→`default=[]`（保留 `local-sidecar=[]` feature 定义供内部 opt-in，CW-021 退役时删除）。内部版迁入**新建** `tauri.internal.conf.json` overlay（identifier `com.internal.video-replica`、productName `众墅之家`、CSP 含 `127.0.0.1:8000`、`resources:["resources/*"]`、窗口无 `url`），仅经 `npm run tauri:build:internal`（`--config tauri.internal.conf.json --features local-sidecar`）显式触发 |
| 默认 dev/build/check 统一 | `tauri:dev`（默认客户）/`tauri:build`（默认客户）/`check:tauri`（默认客户）三者统一为客户版；内部版对应 `tauri:dev:internal`/`tauri:build:internal`/`check:tauri:internal` 全部显式 opt-in。操作者无需记住 `:customer` 后缀即得客户包（保留验收底线①） |
| 联动地址失败合同 | `require:customer-api-base`（`scripts/require_customer_api_base.mjs`）仍是 `tauri:build` 前置门，缺 `VITE_API_BASE_URL` 或非纯 HTTPS/loopback/link-local/reserved origin 时构建 fail-closed；合同测试锁 origin guard 4 断言不变 |
| 联动 README | `README.md`：桌面构建表格行（客户＝`tauri:build` 唯一默认 / 内部＝`tauri:build:internal` opt-in）、架构段（`tauri.conf.json` 即客户 foundation、`tauri.customer.conf.json` 仅追加 installerHooks、内部版降级为 opt-in overlay）、构建与发布代码块（3 条 build 命令）全部纪正 |
| 新增默认构建和缺地址失败测试即可（line 368） | 复用既有 origin guard 与身份，不新增 vault/identifier 开发；仅重写 2 个构建合同测试断言唯一默认 + 加 3 负向断言（详见 §3/§4） |

**承接 CW-011（line 366）**：改默认配置前，客户 identifier（`com.xiangshu.video-replica.customer`，CW-003 锁）、app_data_dir/凭据命名空间（`customer_credentials.rs`，CW-020 零触碰）、版本链（`0.1.16`，7 处锁：base config + root/client package.json + package-lock ×3 + Cargo.lock + Cargo.toml + server pyproject + server main.py）全部沿用旧客户身份，未新增命名空间。

## 3. 验证结果（本地 macOS，Node 24.14.1 / cargo 1.94.1 / uv 0.11.6 对齐 CI；PG fixture Docker PG16@5433）

| 验证 | 命令/场景 | 结果 |
| --- | --- | --- |
| 基线（旧配置 + 旧测试） | `pytest test_customer_ha_smoke.py::<旧双发行测试> test_build_contracts.py` | 2 passed（旧合同成立） |
| **RED**（旧配置 + 重写为新合同） | 同上（测试已改断言唯一客户默认，配置未翻转） | **2 failed**：`test_build_contracts.py:159`（`check:tauri:internal` not in ci.yml）+ `test_customer_ha_smoke.py:624`（base identifier `com.internal.video-replica` ≠ `com.xiangshu...`），均干净 AssertionError 精确对应 DoD ①②缺口 |
| **GREEN**（翻转配置后） | `pytest test_customer_ha_smoke.py::test_customer_desktop_build_is_the_sole_default_target test_build_contracts.py` | **2 passed** → CodeReview 后加 3 负向断言复跑 **9 passed**（1 目标 + 8 全量 build_contracts），ruff format --check 2 files already formatted、ruff check All passed |
| cargo 客户 edition（默认） | `cargo check --manifest-path client/src-tauri/Cargo.toml --locked` | **exit 0**，Finished dev profile；2 warnings（`CREDENTIALS_FILE`:29 + `DPAPI_ENTROPY`:34，见下「warning 归因」） |
| cargo 内部 edition（opt-in） | `cargo check ... --features local-sidecar` | **exit 0**，Finished；同 2 warnings |
| client 单测门（全量·串行等价） | `npm run check --workspace client`（biome + tsc -b + vitest run） | biome 202 files No fixes；`tsc -b` exit 0；**vitest 80 文件 1296 passed**（含 `windowChrome.test.ts` 断言 `tauri.conf.json` base 窗口 `title==""` 仍绿） |
| check:e2e | `biome check e2e` | 15 files No fixes |
| check:tauri | `cargo fmt --check && cargo check --locked` | fmt 无 diff；check exit 0，"All checks passed!" |
| server 静态门 | `ruff check server` / `ruff format --check server` / `mypy server/app` | All checks passed! / 296 files already formatted / **Success: no issues found in 104 source files** |
| secrets 门 | `bash scripts/verify_no_secrets.sh` | exit 0，No hardcoded secrets detected in runtime contract surface |
| **server 全量 pytest（诊断跑）** | `pytest --rootdir server server/tests`（PG fixture up） | 3 failed / 2342 passed / 1 skipped in 900.77s；3 failed 全为 `test_desktop_artifact_no_pg_dsn.py`（CW-025 守卫 drift，见 §3.1）——本任务 12 文件变更集触发的**唯一**回归 |
| **收尾回归修复 GREEN** | `pytest server/tests/test_desktop_artifact_no_pg_dsn.py`（纯静态配置断言，无需 PG） | **8 passed in 0.03s** + ruff format --check / ruff check 双过（见 §3.1） |
| **server 全量 pytest（干净验收跑）** | `npm run check` 末段全量 pytest（修复后最终代码树，PG fixture up） | **0 failed / 2345 passed / 1 skipped in 882.50s（EXIT_CODE=0，npm run check 全绿；1 warning 为既存 StarletteDeprecationWarning 与本任务无关）** |

**warning 归因（2 条 cargo dead_code，非 CW-020 引入）**：`customer_credentials.rs:29 CREDENTIALS_FILE` 与 `:34 DPAPI_ENTROPY` 的使用点在 `#[cfg(windows)]` 门控块内（DPAPI 桥），本地 macOS 不编译 windows 门控代码→报 dead_code。CW-020 **零触碰** `customer_credentials.rs`（属 CW-022 域）；两常量在 Windows CI 上被使用→无 warning；`cargo check` 无 `-D warnings`，warning 不失败，两 edition 均 exit 0。此为 macOS 平台专属既存现象，非本任务引入。

## 3.1 收尾真回归（本任务造成，已修）

**现象**：收尾全量 `npm run check` 的 server pytest（诊断跑）在 49% 处报 `test_desktop_artifact_no_pg_dsn.py ..F.FF..`——8 用例中 3 失败（`test_customer_tauri_config_has_no_backend_resources` / `test_internal_tauri_config_is_separate_from_customer` / `test_package_json_customer_build_script_does_not_inject_pg_dsn`），最终 `3 failed / 2342 passed / 1 skipped in 900.77s`。这是本任务 12 文件变更集触发的**唯一**回归（其余 2342 全绿，含读账本的 `test_cw033_evidence_boundary` / `test_customer_ha_smoke`）。

**根因**：`test_desktop_artifact_no_pg_dsn.py` 是 CW-025 的安全守卫（"验证桌面制品不接收 PG DSN"）。CW-020 把客户 foundation 从 `tauri.customer.conf.json` 翻进 base `tauri.conf.json`、并把 `tauri:build:customer` 降为别名后，该守卫的**旧文件引用字面量失效**：① `longDescription`/`identifier`/`resources` 已迁入 base，而守卫仍读瘦 customer overlay（取值恒空）→ `assert "不包含本地 API" in long_description`、`assert "customer" in customer_id` 失败；② 守卫把 `tauri.conf.json` 当内部制品（现已翻为客户 base）；③ `tauri:build:customer` 现为别名 `npm run tauri:build`，字面不含 `tauri.customer.conf.json` → `assert "tauri.customer.conf.json" in customer_build` 失败。**安全意图仍完全有效**，只是文件布局变了。

**为何只有全量 pytest 抓到**：CodeReview 子代理评审的是变更集 diff（不含未改的 CW-025 守卫），定向合同测试（`test_build_contracts` / `test_customer_ha_smoke`）也不覆盖此文件——唯有收尾全量 pytest 扫描全部 2346 用例才暴露。印证 AGENTS.md「每任务收尾一次全量」的价值。

**处置（CW-019 M1 先例 + CW-011 指令）**：不回退必要的翻转，改修守卫 needle 并强化。授权依据——CW-011「将保护双发行目标的旧断言改成唯一客户默认目标」；CW-019 M1「必要 in-scope 改动使上游守卫旧字面量失效时，处置为修测试 needle（不回退必要改动）并新增锁」。具体：
- 保留 CW-025 不变量（桌面制品不接收 PG DSN）与**8 用例数**（与账本 §18 CW-025 行历史记录"test_desktop_artifact_no_pg_dsn 8 用例"一致，不篡改 CW-025 历史；不重命名函数以最小化爆炸半径）。
- 3 常量重指向 CW-020 三配置布局：`TAURI_BASE_CONF`=tauri.conf.json（客户 foundation）、`TAURI_CUSTOMER_OVERLAY_CONF`=tauri.customer.conf.json、`TAURI_INTERNAL_OVERLAY_CONF`=tauri.internal.conf.json。
- **强化**断言：三份桌面配置均无 PG DSN/DB_PATH（CW-025 不变量扩展到全部桌面制品）；base 即客户 foundation（identifier 含 customer、CSP 无 loopback、resources=[]、longDescription 明确不含本地启动器）；内部 overlay identifier 含 internal 且与客户隔离、客户 overlay 不重复承载 identifier（单一真源在 base）；`tauri:build` 唯一默认含 `tauri.customer.conf.json`+`--no-default-features`+origin guard 且无 PG DSN，`tauri:build:internal` 须显式 `local-sidecar`。
- **RED→GREEN**：诊断全量跑即 RED（3 failed）；修复后目标文件隔离跑 **8 passed in 0.03s**（纯静态配置断言，无需 PG）+ ruff format --check / ruff check 双过。
- 爆炸半径经 grep 确认仅此 1 文件（`test_customer_ha_smoke.py` / `test_build_contracts.py` 已在 GREEN 阶段处理且诊断跑中全 dots 通过）；无任何测试/CI/deselect 引用这些函数名（仅账本 §18 CW-025 行与 CW025-EVIDENCE.md 按语义描述"8 用例"，均保持一致）。

## 4. 三配置 Tauri 合并矩阵 + 保留验收底线映射

> Tauri 配置合并语义（实证 + CodeReview 确认为 JSON-merge-patch）：**对象按键深合并、数组整体 REPLACE、深合并只能加/覆盖不能删键**。故 `installerHooks` 必须留在 customer overlay（若入 base，internal overlay 无法删除→内部版会错误继承）；`windows`/`resources` 数组可被 overlay 完整 REPLACE。

| 键 | base `tauri.conf.json`（客户 foundation＝唯一默认） | customer overlay（瘦） | internal overlay（opt-in，新建） |
| --- | --- | --- | --- |
| identifier | `com.xiangshu.video-replica.customer` | 继承 | **覆盖** `com.internal.video-replica` |
| productName | `短视频复刻客户云工作台` | 继承 | **覆盖** `众墅之家` |
| version | `0.1.16`（唯一真源） | 继承 | 继承 |
| app.windows[0] | `{create:false,label:"main",title:"",url:"customer",1280×820}` | 继承 | **整数组 REPLACE**：无 `url`（加载 index.html）、`title:""` |
| app.security.csp | HTTPS-only（无 `127.0.0.1:8000`） | 继承 | **覆盖**：含 `127.0.0.1:8000` loopback |
| bundle.resources | `[]`（空） | 继承 | **覆盖** `["resources/*"]` |
| bundle.publisher | `Xiangshu Video Replica` | 继承 | **覆盖** `众墅之家` |
| bundle...nsis.startMenuFolder | `短视频复刻客户云工作台` | 继承 | **覆盖** `众墅之家` |
| bundle...nsis.installerHooks | **无**（关键：不入 base） | **追加** `customer-installer-hooks.nsh` | **无**（不继承 customer overlay 的钩子） |
| build/frontendDist | `../dist`（`beforeBuildCommand`/`devUrl` 等） | 继承 | 继承 |

**保留验收底线逐条映射（line 369）**：
1. **默认构建就得到客户包，不要求操作者记住 `:customer`** → `npm run tauri:build`（无后缀）＝客户包；`tauri:build:customer` 仅保留为别名。合同测试锁 `require:customer-api-base` + `--no-default-features` + `--config tauri.customer.conf.json` in `tauri:build`。
2. **无本地 API 地址回退** → base CSP `"127.0.0.1:8000" not in`；origin guard 强制非 loopback HTTPS；`Cargo default=[]` 使默认构建编译期不含 local-sidecar。
3. **客户 identifier、版本链及窗口权限保持** → identifier `com.xiangshu.video-replica.customer`（CW-003 锁）；version `0.1.16` 7 处链全钉（合同测试逐处断言）；窗口 `url:"customer"`/`title:""`（`windowChrome.test.ts` 断言 `title==""` 仍绿）。
4. **客户 WebView 正确连接明确的 HTTPS 后端** → base CSP `connect-src ipc: http://ipc.localhost https:`（HTTPS-only），构建期 `VITE_API_BASE_URL` 必须为可路由非 loopback HTTPS origin。

**DoD ②「旧配置不再能意外生成内部发行包」的三重硬保证**（CodeReview 确认）：① `Cargo default=[]`→裸 `cargo build`/`tauri build`/`tauri:build`/`tauri:dev` 不启用 local-sidecar；② base＝客户 foundation→默认产物 identifier/productName/CSP/resources 全是客户版；③ 内部版需**同时**显式 `--config tauri.internal.conf.json` **和** `--features local-sidecar` 才能产生，无任何隐式路径。3 负向断言进一步锁：内部 overlay 不含 `installerHooks`、`tauri:build:internal` 不含 `require:customer-api-base`、不含 `--no-default-features`。

## 5. 范围界定与 CW-021 边界

- **CW-020 触碰**：base/customer/internal 三 Tauri 配置、`Cargo.toml` `[features].default`、`package.json` 脚本、`ci.yml` windows-nsis job 的 3 处 check/build 命令、2 个构建合同测试、README、冻结映射 §4.6、部署手册 §6、账本。
- **CW-020 明确不碰（CW-021 域，line 374–388）**：`client/src-tauri/src/lib.rs`（BackendProcess/端口探测/BOOT_COMMAND/退出杀进程源码）、`resources/start-backend.sh|.bat`、`ci.yml` 的 `Verify customer installer excludes local launchers` 步骤（L375–401）。`local-sidecar` feature **定义保留**（仅从 `default` 移除），供 CW-021 退役内部版时整体删除。
- **冻结映射先例**：`docs/客户版代码开发清单-V3.md` §4.5（CW-019）确立「物理上必须新增入口文件，故在此追加登记，使本清单继续作为唯一文件映射真源」；CW-020 循此新增 §4.6 登记 `tauri.internal.conf.json`（内部 opt-in overlay 是用户决策 A 的物理必须新增文件），合规非违规。
- **Consider#3（lib.rs L15-19 注释已随默认翻转而过期）登记交 CW-021**：CW-020 红线禁动 lib.rs，该注释的纪正随 CW-021 删除 local-sidecar 源码时一并处理，本任务不越界。

## 6. 独立复核（CodeReview 子代理）

独立 CodeReview 子代理直接读代码核实，**结论：无 Critical / 无 Must-fix**。逐项确认：
- **安全判据（DoD ②）成立**：裸 `tauri build`/`tauri:build`/`tauri:dev` 不能产生内部包（`default=[]` + base＝客户 + 无隐式选 internal）。
- **合并推理成立**：internal overlay `windows[0]` 无 `url` 替换 base 数组；`installerHooks` 只在 customer overlay 不在 base→internal 不继承；internal 正确覆盖 identifier/productName/CSP(含 loopback)/resources/publisher/descriptions/startMenuFolder，version/build 继承 base。
- **CI plumbing 正确**：`--` 分隔符正确路由 cargo flags；`tauri:build:customer`→`tauri:build` 别名仍传 `VITE_API_BASE_URL`（npm-run 子进程继承 env）；artifact globbing `*.exe` 与 productName 无关；`Isolate customer NSIS output` 步骤仍先删内部产物。
- **scope discipline 尊重**：lib.rs/start-backend.*/Verify launchers 步骤未碰。
- **test 质量真实锁合同**：正/负向断言齐全，version 链全钉，`test_build_contracts` 正确翻转。

处置：
- **Should-fix（已修）**：`docs/客户版部署与灰度手册.md` §6（L320–329）T36 类生产验收描述过期——4 处与新合同不符（旧文称客户身份/空 resources 在 `tauri.customer.conf.json`、内部为默认构建保留 local-sidecar、CI 默认内部版门禁）。CW-020 DoD ③明确要求「文档与脚本一致」，已就地纪正为：客户身份/空 resources/HTTPS-only CSP 由 base `tauri.conf.json` 承载、`tauri.customer.conf.json` 只追加 installerHooks、内部版为 `tauri:build:internal`（`--features local-sidecar`）显式 opt-in、`Cargo default=[]` 保证无 sidecar、CI `check:tauri` 默认校验客户版。
- **Consider#1（已采纳）**：`test_customer_ha_smoke.py` 加 3 负向断言（`installerHooks not in internal_overlay.nsis`、`require:customer-api-base not in tauri:build:internal`、`--no-default-features not in tauri:build:internal`）→ 复跑 9 passed。
- **Consider#2（已采纳）**：账本 §12.6 DESK-02 行（L286）仍引用已删 `check:tauri:customer`，追加 CW-020 脚注说明翻转（`check:tauri:customer`→`check:tauri:internal`、客户身份迁入 base、内部改 opt-in），保留 T36 历史记录不篡改。
- **Consider#3（登记不改，交 CW-021）**：`lib.rs` L15-19 注释已随默认翻转而过期，但 CW-020 红线禁动 lib.rs（CW-021 域），登记随 CW-021 删除 local-sidecar 源码时纪正（见 §5）。
- **Consider#4（评估后不改）**：README 未列 `tauri:dev:internal`。核查 README 全文**从不记录 Tauri dev 命令**（`tauri:dev` 客户版同样未列，dev 只提 Vite 的 `npm run dev --workspace client` 与 `dev:client`），「构建与发布」块专列 build+release+test；只加内部 dev 变体而不加客户 dev 会造成不对称，且属把从未记录的 dev 工作流纳入文档的 scope creep，故不改。

## 7. 重复开发核查（用户红线，六层）

开工前共做 3 次新鲜六层核查 + re-anchor 兼作第 4 次，均确认 CW-020 独占：
- **DIM1 worktree**：`git worktree list` 仅本 cw020 worktree 在 `feat/customer-v3-cw020-*` 分支。
- **DIM2 branch**：本地 + 远端（`git ls-remote`）无其它 cw020 分支。
- **DIM3 commit**：全 ref `git log --all --grep=CW-020` 零命中（本任务提交前）。
- **DIM4 其它 worktree WIP**：main / c5-publish（陈旧发布特性）/ cw015 / 人物IP口播联调 / 素材库联调完成 对全部目标文件（3 配置 + Cargo.toml + package.json + ci.yml + 2 测试 + README + 3 docs）**零未提交 WIP**；部署手册/账本编辑前再次跨 worktree WIP 扫描确认无并发编辑者。
- **DIM5 claim / DIM6 PR**：无 CW-020 claim、无任何状态 CW-020 PR。
- **re-anchor 复核**：main `0d08608→e829ad1`（CW-054 #14 + CW-055 #13 纯 PG，改 `server/app/db_pg.py`/`db_portable.py`/tests + docs）未碰 CW-020 任一代码目标；`git rebase origin/main` 快进零冲突后 7 代码目标文件逐字节一致；2 docs 碰撞面（CW-054 在冻结映射顶部新 section vs 我 §4.6；CW-055 在账本 §18 CW-055 行 vs 我 CW-020 行）不同 section→3-way 干净。

## 8. 签认记录

- Owner：ZCode 代理（hlong026 会话）——按 V3 §14 模板填写本证据；全仓门全绿（client vitest 1296 passed、cargo 双 edition exit 0、ruff/mypy/secrets 全过、server 全量 pytest 见 §3）；重复开发六层核查 CW-020 独占；`server/app` 零触碰。
- Reviewer：独立 CodeReview 子代理——无 Must-fix；1 Should-fix 已修、Consider#1/#2 已采纳、#3 登记交 CW-021、#4 评估后不改。
- 认领生命周期（COORD）：CLAIMED→ACTIVE（本证据）→REVIEW（PR 提交后回填 PR URL/head SHA）→MERGED（squash 后回填 merge SHA）→CLEANED。
- 待办：PR squash 合并入 main 后回填 §18 账本 CW-020 行 Lore SHA，并释放本机认领锁、清理 worktree。
- **本条为单任务登记，不代表里程碑推进**：真实 Windows NSIS 构建/解包/签名/实机以 CI Windows 门禁与 DESK-03/04、CW-024/CW-046 为准；`cargo test`/`npm audit`/客户浏览器 E2E/`npm run build` 以 push 后三门禁为准；未过真实链路故证据层级停在 AUTOMATED_VERIFIED。当前状态仍以 §18 为唯一真源。
