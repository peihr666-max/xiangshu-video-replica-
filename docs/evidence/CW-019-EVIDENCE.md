# CW-019 — 拆出客户与管理员独立构建制品（W3）

## Task Information

| Field | Value |
| --- | --- |
| **Task ID** | CW-019 / W3「分离客户与管理员前端构建制品」 |
| **Owner** | 前端构建（Agent 执行） |
| **Reviewer** | CodeReview 子代理（push 前自检，M/m/n 分级）+ owner（PR 评审） |
| **Branch / Base SHA** | `feat/customer-v3-cw019-split-build-artifacts` / 开工基线 `5e9d2d7`；收尾**两次** rebase：`d8f3352`（CW-016 #6 / CW-025 #7 / CW-033 #3）→ `e06b13c`（CI 重构 #8 / CW-017 #9）。两次均 0 冲突，但第二次需手工修 ci.yml 门控语义（见 Critical Findings 8）。全仓门禁跑于树 `485541f`（本文档纪正编辑前的提交树）；`485541f` → PR head 的差集为 **docs-only**（`git diff --stat` 只含 `docs/`，无任何被测代码或构建输入变更） |
| **PR** | **#12**（base `main`）。push 后核对 PR 的 Commits 列表：`git log origin/main..HEAD` 只含本任务提交（实现提交 + 本行 PR 号回填的 docs 提交），**无外来提交**；受保护 main 仅接受 owner 账号 squash merge，本任务**不自行合并** |
| **Date** | 2026-09-10 |
| **Evidence Level** | `AUTOMATED_VERIFIED` |
| **上游规格** | `docs/开发交接提示词-CW019-拆双构建制品-2026-09-10.md` §5/§6/§7/§9/§10 |

证据层级说明：本任务全部结论来自本地自动化门禁与产物字节级扫描，**未过真实链路**，
故不标 `STAGING_VERIFIED` / `REAL_CHAIN_VERIFIED` / `PRODUCTION_GO`。服务器实际发布
（`deploy/customer-git-rollout.sh` 在目标机执行、nginx 重载、`/admin` 真实探活）未执行。

## Exit-Gate Verification

CW-019 验收底线：*客户所有 chunk 不得含内部/管理入口，且不是靠懒加载隐藏；管理站点
全部保留页面独立可用*。两条都由**双层断言**承载，而非人工检查：

| 层 | 载体 | 时机 | 断言内容 |
| --- | --- | --- | --- |
| 源码级 | `client/src/entryContract.test.ts`（7 用例） | 每次 vitest，秒级，无需 build | 客户入口不认识管理域/内部域的**模块引用语法**与 JSX 使用形态；`SettingsPanel` 不静态引用控制面 API |
| 产物级 | `scripts/verify_customer_bundle.mjs` | 构建后，CI 独立 step | 扫 `client/dist` 全量文件的禁止文件名 + 禁止特征串；对 `client/dist-admin` 做**阳性对照**；输出两份 SHA-256 清单 |

双层缺一不可，原因见「Critical Findings」第 2 条：标识符形状的特征串在 `minify: "oxc"`
压缩产物里**恒不命中**，产物层单独无法守住内部域；而源码层看不到真实产物字节。

## Critical Findings（本任务实测发现，非推测）

### 1. Rolldown 完全忽略 tree-shake 配置 —— 「靠配置排除管理代码」这条路不存在

Vite 8.2.1 / Rolldown 1.2.4 下实测三种写法：`build.rollupOptions.treeshake` 的
`sideEffects` hint、`moduleSideEffects` 函数式、全局 `false`。**三者产物哈希字节级相同**，
即该配置被完全忽略。

推论（决定了本任务的实现路径）：`CustomerWorkspace → StudioWorkspace → SettingsPanel`
链上原有的 `source === "control" ? getControlSettings() : getSettings()` 运行时三元分支，
打包器**不可能**消除其中一侧，`/api/control/` 必然串进客户制品。构建层补救无效，
只能在源码层切断静态可达链 → 改为依赖注入：`SettingsPanel` 导出 `SettingsBackend` 类型，
工作台面后端 `workspaceBackend` 内置为模块级常量，控制面后端由管理端调用方以
`controlBackend` prop 注入（`App.tsx`、`StudioWorkspace.tsx`、`SystemSettingsPage.tsx`
三个调用方均传模块级常量，不传内联对象，故 `useEffect([backend])` 引用稳定）。

同时清理了此前基于错误假设加入的无效配置：`vite.config.ts` 的 treeshake 块、
`client/package.json` 的 `sideEffects` 字段（二者已证零效果，留着会误导后续维护者）。

### 2. 排除断言曾处于「静默失效」状态 —— 阳性对照是本次补上的关键缺口

CodeReview 指出的 m2：原 `verify_customer_bundle.mjs` 只断言「客户制品 0 命中」。
但 `minify: "oxc"` 会 mangle 局部标识符，导致 §5.5 item 3/4 里的标识符形状特征串
（`AdminApp`、`api.admin`、`exchangeAdminSession`、`fetchAdminSession`、
`loginAdminWithPassword`、`getDevelopmentUserId`、`internalAccessToken`）在压缩产物中
**根本不存在**。此时「断言静默失效」与「制品真的干净」在输出上**完全同形**，
门禁报 ✅ 却毫无检测力 —— 这是最危险的一类伪绿。

修复：新增**阳性对照（positive control）**。6 条确认能在压缩产物中存活的字符串字面量
（`/api/control/`、`激活码批次`、`审计中心`、`强制下线`、`运营管理后台`、`ASX1.`）
必须在 `client/dist-admin` 中各命中 ≥1 个文件；任一命中 0 → 打印腐烂清单与处理指引 →
`process.exit(1)`。管理制品缺失同样 exit 1（没有阳性样本就无法证明 assay 有效）。
阳性对照在 `main()` 中**先于**排除断言执行，让失效最早暴露，而不是附在一份无效报告末尾。

处置口径：§5.5 item 3 的 10 条管理域特征串与 item 4 的 3 条内部域特征串**逐字保留、
零放宽**（含 `internalAccessToken`——实测在客户制品 0 命中，无需按 item 4 的但书调整）；
只**追加** 2 条（`运营管理后台` = `AdminApp.tsx:346` h1 文案、`ASX1.` = `AdminApp.tsx:406`
placeholder），用于扩大阳性对照覆盖面。内部域那 3 条改由源码层守：`client/src/App.tsx`
只被测试引用、不进任何生产制品，产物层拿不到阳性对照样本，硬留在产物层只会制造
一条永远为真、永远无法证伪的断言。

### 3. 部署脚本会「SUCCESS 地」把 `/admin` 部署成 500（CodeReview M1，阻塞项）

`deploy/customer-git-rollout.sh` 是仓库里**唯一**的客户站部署可执行路径，原先只构建、
只部署 `client/dist`。而本 PR 的 nginx example 与部署手册已要求 `location ^~ /admin/`
alias 到管理制品目录 —— 合并后首次发布，脚本会照常打印 SUCCESS，`/admin` 则静默 500。
更糟的是原脚本连**备份**都不会做管理站点，回滚无从恢复。

该文件不在 §7 越界清单内（清单列的是 Tauri feature/conf、BackendProcess、installer hooks、
`api.ts`、`MainPages.tsx`、`CustomerWorkspace.tsx`、`useCustomerSession.ts`），属本任务
「nginx example 的管理路径落地 + 部署手册的制品归属说明」的必要闭环，故修：

- `ADMIN_SITE="${SITE}-admin"` 与 `STAGE_ADMIN_SITE`，与客户站同 SHA **同轮**原子替换，
  两个制品永不出自不同 release SHA
- 构建段由 `npm run build` 改为 `npm run build:all && npm run verify:customer-bundle`，
  把 CW-019 排除证据纳入发布链（断言不过则不发布）
- 双侧结构断言：`[[ -s index.html && -d assets ]]` + 从 index.html 提取 `EXPECTED_ASSET` /
  `EXPECTED_ADMIN_ASSET`
- 备份新增 `admin-site-before.tar.gz`（+ 记入 `BACKUP-SHA256SUMS`）；`rollback()` 只在
  该归档存在时恢复管理站——首个引入 dist-admin 的发布本就没有前一版管理站，
  「无归档」= 无可回滚目标，而非静默跳过
- `precheck` 加入 `STAGE_ADMIN_SITE` 残留检查
- VERIFY 段新增 `curl -fsS "$PUBLIC_ORIGIN/admin/?release=$SHORT_SHA"` 真实探活并校验
  返回 HTML 含 `EXPECTED_ADMIN_ASSET`
- 最终 printf 增加 `ADMIN_SITE=` / `ADMIN_ASSET=`

`bash -n` 语法校验通过（本机无 shellcheck）。脚本**未在目标机执行**。

### 4. 25MB 客户专用素材被隐式搬进管理制品（CodeReview m4）

`build.copyPublicDir` 默认 `true`，`client/dist-admin` 曾达 **27MB**——把 `client/public/studio/`
下 13 张客户工作台专用 PNG（约 25MB）无评审、无断言地复制进了管理制品。这是一条
隐式的跨制品耦合通道：客户素材一改，管理制品体积与哈希就跟着变。

修复：`copyPublicDir: false` + 在 `vite.admin.config.ts` 的 `writeBundle` 钩子里显式单文件
拷贝 `public/favicon.svg`（`admin.html` 引用它），源文件缺失即抛错。
实测 `client/dist-admin` 由 **27MB 降到 388KB**，`studio/` 消失，
`index.html` 内 `/admin/favicon.svg`、`/admin/assets/admin-*.js`、`/admin/assets/admin-*.css`
前缀全部正确。

### 5. rename 插件曾吞掉一切 ENOENT（CodeReview m3）

Vite MPA 输出保留源文件 basename（`admin.html`），需重命名为 `index.html` 以匹配
nginx SPA fallback。原实现对 `renameSync` 的 `ENOENT` 一律静默 return（为幂等），
代价是「管理入口 HTML 根本没产出」也会静默通过。

修复：只在 **`ENOENT` 且目标已存在**时容忍（这才是真正的幂等重入），否则抛出带原始
错误消息的 Error。`emptyOutDir` 每次清空目录、`writeBundle` 每个 output 只触发一次，
走到 ENOENT 而目标又不在，只可能是入口没产出。

注：未使用 `new Error(msg, { cause })`——`client/tsconfig.node.json` 无 `target`/`lib`，
默认 ES5 lib 不含 `ErrorOptions`，会把原始错误拼进消息文本。

### 6. nginx 样例注释与事实不符（CodeReview m1）

`deploy/nginx/customer.conf.example` 原注释声称「`/api/control/` 在此完全不被代理」。
核实 `location ^~ /api/` 是**前缀匹配**，它确实会把 `/api/control/*` 转发到同一 upstream。
客户生产的真实防线不是「缺令牌 fail-close」：`server/app/control_auth.py` 的
`get_control_route_user` 在 `_is_customer_production()` 为真时走 per-operator
`admin_session` cookie（ASX1 exchange），**不看** `X-Control-Proxy-Token`；
`get_control_user` 在客户生产直接 403 `LEGACY_CONTROL_IDENTITY_FORBIDDEN`。

修复：注释改写为事实正确版本（明确该 location 确实转发 `/api/control/*`、客户生产由
`admin_session` cookie 鉴权、外壳会向未认证客户端披露完整管理 API 面），并在
`location ^~ /api/` 内补 `proxy_set_header X-Control-Proxy-Token "";`，与
`internal-p0.conf.example` 的每个 proxy 块一致——对
`VIDEO_REPLICA_CUSTOMER_PRODUCTION` 配置错误的主机形成纵深防御。

### 7. 链式门禁 + 已知 flake = server 真回归被完全掩盖（收尾期实测）

M1 修复把发布链构建命令从 `npm run build --workspace client` 改成
`npm run build:all && npm run verify:customer-bundle`，而**上游守卫测试
`server/tests/test_customer_git_rollout.py` 断言的是旧命令的字面量**：

```text
FAILED server/tests/test_customer_git_rollout.py::
       test_customer_git_rollout_builds_web_and_preserves_database_rollback_evidence
>       assert "npm run build --workspace client" in script
E       assert 'npm run build --workspace client' in '#!/usr/bin/env bash\n...'
1 failed, 3 passed, 1 warning in 1.83s      ← 隔离复跑，100% 确定性
```

该测试是纯静态文本断言（读脚本 + `in` 判断，无 DB、无时序），因此失败是**确定性**的，
不是 flake。

**掩盖机制（值得单独记录，属流程性教训）**：根 `package.json` 的 `check` 脚本用 `&&`
把 8 个阶段串成一条链，且 **client 阶段排在 server pytest 之前**。M1 修复之后我跑的
每一次全仓门禁都在 client vitest 阶段被时序 flake 打断（详见「本地时序 flake 的取证」），
`&&` 短路 → **server pytest 一次都没执行到** → 这个真回归在三轮「看似只差 flake」的
门禁里完全隐形。若当时按「flake 与本 diff 无关」的结论直接 push，就会把一个确定性
失败推给 CI。

处置：改为**分段执行**、每段独立记退出码（`.cw019-worklog/seg-status.log`：
`SEG_A_client=0 / SEG_B_e2e=0 / SEG_C_tauri=0 / SEG_D_mypy=0 / SEG_E_pytest`），
使任一段失败都不会屏蔽后续段的信号。分段后 client 段**一次通过（80 文件 / 1292 用例）**，
server 段则暴露出本条回归。

修复取向：M1 的脚本改动是必要的（不改就会「打印 SUCCESS 而 `/admin` 静默 500」），
因此修的是**测试的 needle**而非回退脚本；同时新增
`test_customer_git_rollout_ships_admin_artifact_in_the_same_release_run`，把 M1 的六项
行为（同 SHA 同轮命名、`dist-admin` 产物校验、`admin-site-before.tar.gz` 备份与条件
回滚、客户站先于管理站替换的**顺序**、`curl /admin/?release=` 真实探活、`precheck`
暂存残留拒绝）写成断言——否则 M1 修复自身没有任何回归保护。现该文件 `4 passed`，
`ruff check` / `ruff format --check` 双通过。

### 8. rebase「0 冲突」不等于语义正确 —— ci.yml 的自动合并结果是坏的（收尾期实测）

第二次 rebase（`d8f3352` → `e06b13c`）带入 PR #8
`2751200 chore(ci): path-filtered gates, sharded pytest, dual-path self-hosted runner`，
它给 `.github/workflows/ci.yml` 的 `Build web client` step 加了
`if: needs.changes.outputs.desktop == 'true'`（+173/-24）。本任务新增的两个 step
（`Build admin bundle` / `Verify customer bundle excludes admin and internal entries`）
是针对**旧** ci.yml 写的、**没有任何 `if:` 门控**。

`git rebase` 报 **0 冲突**——两侧 hunk 不重叠，git 自动合并成功。但合并结果语义破损：

```text
只改 server/** 的 PR  →  changes.desktop == false
                     →  Build web client 被跳过  →  client/dist 不存在
                     →  本任务的 verify step 无门控、照常执行
                     →  按设计把「制品目录缺失」当硬错误  →  exit 1  →  CI 必红
```

「缺制品必须失败」是 verify 脚本的正确设计（否则「没构建」会被当成「干净」），
所以坏的不是脚本，是 step 缺门控。**教训**：rebase 后不能只看冲突数与 diff 统计，
必须逐文件核对**上游对同一文件新增的语义前提**（此处是 `if:` 门控体系）。

修复：两个 step 补与 `Build web client` **逐字相同**的门控
`if: needs.changes.outputs.desktop == 'true'`，并加注释说明取舍——不用 `frontend`
（会让 desktop-only 改动跳过构建却仍跑断言）、不能不加（缺制品必须失败）。

修后核实：

- `python3 -c "import yaml; …"` 解析成功；三个 step 的 `if` 逐字一致；`quality-linux`
  19 steps；jobs = `['changes','select-runner','secret-scan','quality-linux','windows-nsis']`
- 逐条比对 PR #8 新增的 `server/tests/test_build_contracts.py` **严格计数断言**
  （`persist-credentials: false` == 4、`if: {fork_pr_guard}` == 5、
  `runs-on: ubuntu-24.04` == 2、`LOCAL_ARTIFACT_ROOT` == 8、`SHA256SUMS.txt` == 2、
  `checkout@` == 4、`setup-node@` == 3），确认本任务插入的 step **不改变任何一项计数**
- 守卫测试隔离复跑：`test_build_contracts` + `test_customer_git_rollout` +
  `test_internal_deployment` → **23 passed**；client 静态门 `TSC_EXIT=0`、
  `BIOME_EXIT=0`（202 files）
- 根 `package.json` 9 个脚本共存（`check`/`check:sharded`/`check:static`/`build`/
  `build:admin`/`build:all`/`verify:customer-bundle`/`dev:server`/`dev:worker`），
  `node -e JSON.parse` 通过；账本 §18 的 CW-016/017/019/025/033 五行各 2 行齐全；
  本任务 diff **无任何文件 mode change**
- PR #8 引入的 `scripts/ci/test-shards/shard-{0..3}.txt` 是**文件级静态列表**
  （24/23/26/26 = 99 文件），`server/tests/test_customer_git_rollout.py` 已在 shard-0，
  故 Critical Finding 7 新增的测试函数**无需登记分片**

### 9. 两项上游结构问题（本任务不修，主动披露）

1. **`scripts/verify_customer_bundle.mjs` 不在 `desktop` filter 内。** PR #8 的三个
   filter 实测为：`desktop` = `client/src-tauri/**`、`client/**`、`package.json`、
   `package-lock.json`、`packaging_tools/**`、`.github/workflows/ci.yml`；
   `frontend` = `client/**`、`package.json`、`package-lock.json`；
   `server` = `server/**`、`scripts/**`、`package.json`。故**只改这个断言脚本**的 PR 上
   `desktop == false`，本任务的两个 step 被跳过——最该行使产物级断言的场景不行使它。
   缓解事实（已核实）：`Run static quality checks`（`npm run check:static`）**无 `if:`
   门控、恒执行**且含 `npm run check --workspace client`，故**源码级**那一层
   （`entryContract.test.ts`）仍会跑。不修的理由：把 `scripts/**` 加进 `desktop` 会让
   任何脚本改动都触发约 13 分钟的 Windows Tauri/NSIS 构建；且 filter 覆盖范围属 #8
   的设计问题，应由独立任务统一决定，本任务不越界改上游 CI 结构。
2. **`scripts/pg-fixture.sh` 仓库内 mode 仍为 `100644`。** #8 只改内容未改可执行位，
   而 AGENTS.md 与本任务交接文档写的是直接调用形式（`./scripts/pg-fixture.sh start`），
   在 fresh checkout 上会 `permission denied`。实际无碍：`run-pytest-shards.sh` 内部用
   `bash "${PG_FIXTURE}"` 调用（line 105/142-143），CI 不受影响；本任务全程统一用
   `bash scripts/pg-fixture.sh <子命令>`。不修的理由：改文件 mode 属仓库级变更，且本
   任务 diff 目前零 mode change，不在前端构建任务里夹带权限位改动。

## 本地时序 flake 的取证与处置（如实披露）

rebase **前**的三次 client 全量套件运行各命中一次**不同**的时序失败，互不复现：

| 轮次 | 模式 | 失败用例 | 耗时 |
| --- | --- | --- | --- |
| 1 | 并行 | `StudioWorkspace.test.tsx`「旧口播请求的 finally 不会解锁角色往返后的新提交」 | 3027ms（超时边界） |
| 2 | 串行 `--no-file-parallelism` | `AnalysisWorkspace.test.tsx`「建批 5xx 后恢复记录保留…（P0-04-02）」 | 3103ms（超时边界） |
| 3 | 并行 | `CustomerWalletPanel.test.tsx`「does not clear a newer order-action error…」+ `StudioWorkspace.test.tsx` 另一用例 | 190ms / 3036ms |

判定**与本 diff 无关**的取证：

1. 三个文件 mtime 均为 worktree 检出时间（15:30:52），`git diff --name-only` 命中数 **0**
   ——本任务从未改动它们。
2. `CustomerWalletPanel.tsx` 与 `AnalysisWorkspace.tsx` 对本任务改过的任何模块**零 import**
   （`SettingsPanel`/`RootApp`/`main` 各 0 命中）→ 结构上不可能受影响。唯一有依赖链的
   `StudioWorkspace.tsx` 引用 `SettingsPanel`，但隔离跑 **82/82 通过**。
3. 隔离复跑全部通过：`StudioWorkspace` 82/82、`AnalysisWorkspace` 32/32、
   `CustomerWalletPanel` 9/9。
4. 环境争用实测：`load averages 7.11 / 8.76 / 8.33`（本机 6 个性能核），同期常驻 dev
   `uvicorn --reload`（已运行 1 天 5 小时，41.7% CPU）、`generation_worker`（6 天）、
   Docker 虚拟化进程与 IDE 渲染进程各占 50–100% CPU。`waitFor` 的 1000ms/3000ms 超时
   在此争用下属边缘性抖动。
5. **上游已修其一**：rebase 带进来的 `3b32418 ci(client): stabilize CustomerWalletPanel
   delete-order error assertion` 正是第 3 轮失败的用例。
6. **分段重跑后 client 段一次通过**（80 文件 / 1292 用例 / EXIT=0，load 7.68），
   进一步支持「争用致抖」而非「diff 致错」。

**未修改任何测试文件去「压平」上述 flake**——`CustomerWalletPanel` 属 CW-016 域，
越界。处置沿用 CW-015 账本先例：隔离复证 + 依赖链排查 + 环境取证 + 如实记录。

### 自曝：收尾期本任务自己制造了并发 pytest 争用

上述三轮之后，19:19 起了一个全仓门禁重试循环，19:33 又起了第二个。杀第一个循环时
**只杀了子进程、没杀循环体所在 shell**，循环随即自动起下一轮，于是 **19:34–19:40 期间
有两套全量 server pytest 同时打同一个 5433 fixture**——正是本仓库明令禁止的做法。
已连循环体一并杀掉，重跑改为分段、串行、单实例（重跑前已核实 5433 上只有本任务的
`customer-v3-pg-test` 一个容器、无并发 backend）。

时间线上这与三轮 client flake **无因果关系**（那三轮在 19:03/19:09/19:12，早于 19:19
的第一个循环），但必须记录：它一度破坏了取证结论所依赖的环境前提，且第 5 条
「PG fixture 上没有第二个全量 pytest」的原结论只对那三个时间窗成立。

## Build Artifact Manifests（来自 `npm run verify:customer-bundle` stdout）

### 客户制品 `client/dist`（17 文件）

清单取自**最终提交树**（rebase 到 `origin/main@e06b13c` 之后）。CW-017（PR #9）改动了
`client/src/api.ts`、`client/src/customer/CustomerWorkspace.tsx`、`useCustomerSession.ts`
并新增 `client/src/workspace-shell.ts`——这些都是**客户包输入**，故客户 JS 的内容哈希与
体积相对 rebase 前发生变化（`index-Be-n1pTZ.js` 747.04 kB → `index-DhDiBhwK.js`
746.75 kB）；`index.html` 因引用该文件名而哈希同步变化。**管理制品 4 个文件的哈希全部
未变**（CW-017 未触碰管理域），这本身就是「两制品已物理隔离」的一条旁证。

```
# sha256                                                            bytes  path
ceddddcba0932a8f075d813cfceb8409c50c785b3213979824d7b9dde8c8aec0    74164  assets/index-Da_qFTmv.css
c9ae2465832b409f49bd4e73b6da4d5b9286edf488f98fd0ecd4944143aaf05f   746753  assets/index-DhDiBhwK.js
ad22e0e59e148a15ac8cc4585eea51648a6bc469dee58c6581a040c5131b8a29      397  favicon.svg
ba8038aeee3c242de80ac2064af2e6d361955e50f819900933298fd65debaaa1      477  index.html
fff7f3252ea627e87a4d817032aa50dcecc2b82104bd0303eda465e2e805d2fe      786  studio/README.md
275efbf794ea5e485bf49111d8681170dc3b07e3d858e07fb32be9d7aeaabe5a    19269  studio/brand.png
c14dfd7dff3b7dff24c1371b7addd14216af71bc3e46c8f76f59a7479d345bea  1853463  studio/construction.png
1796fdc0188c399a6fda56a6a5280194db90c779b07005774d3f27d9f16870dd  2083876  studio/five-views.png
6285793caf6ec8b678dbe87bd1754d74e32fb665bcd367b552291290806f7d43  1872681  studio/li.png
271390b26fe683b2c22a99ba0accbc789d74687f09ec0a8e728172d062063d6b  2552264  studio/villa-bungalow.png
e438e7b20a34026ef3e8b7551b6e5935287e945a12e442461022444f146d6d40  2897209  studio/villa-courtyard.png
8387ea629229af14a3fdbcfd3e00c887d5704070791a9c8eb2a6dfd9990b2231  2641971  studio/villa-modern.png
e1ccb5e41e1254bab5ba4419e1f7cf9f4b0f51402cc2a06c8f1baf4144c01e88  2519993  studio/villa-white.png
412e363d2950fb0856ba47376cef6e3008fcb9db62d8eefd8fca380209fe90c2  2918576  studio/villa.png
f754fabb54564ea16a89730ca8502e4ab8f765d8e6c77acf514c19b6974d2ef2  1791101  studio/wang.png
9cf9216ebd16b0c54602d0c45655265f03fe58dbf1df4f19ee45725cd022e8f4  2045068  studio/zhang-courtyard.png
86c9c02e67e6fe8f83c6afd4fdc9a70f2970c6be64582b4cb51b393d65a3b74e  2023905  studio/zhang-studio.png
# total files: 17
```

### 管理制品 `client/dist-admin`（4 文件，阳性对照样本）

```
# sha256                                                            bytes  path
7a2e506f9f6398a9af5d4ca5b46fce5e27fe98a31e1cfe290776466002dfa99d    16577  assets/admin-Cvvbd8II.css
05a32dce1289b891c86f788e61e358a13eb6177c293ba8e721f592af33ae9d74   365449  assets/admin-Dp4WSijI.js
ad22e0e59e148a15ac8cc4585eea51648a6bc469dee58c6581a040c5131b8a29      397  favicon.svg
0c5f5fbf38f2813565630cf69e8f6a3a5d7926bb1f2a01d6a95fac3db5e84f84      502  index.html
# total files: 4
```

### 排除断言与阳性对照结果

```
[verify_customer_bundle] ✅ 客户构建制品通过管理/内部代码排除断言。
[verify_customer_bundle] 扫描文件数：17；禁止文件名命中：0；禁止特征串命中：0。
[verify_customer_bundle] 阳性对照：6/6 条管理域特征串在 client/dist-admin 中命中 ≥1 文件，
                         排除断言的有效性已自证。
退出码：0
```

阳性对照逐条命中文件数：`/api/control/` 1、`激活码批次` 1、`审计中心` 1、
`强制下线` 1、`运营管理后台` 1、`ASX1.` 1。

### 构建体积（`npm run build:all`）

| 制品 | 入口 | JS | CSS |
| --- | --- | --- | --- |
| 客户 `client/dist` | `index.html` → `/src/main.tsx` | `assets/index-DhDiBhwK.js` 746.75 kB（gzip 220.03） | `assets/index-Da_qFTmv.css` 74.16 kB（gzip 14.52） |
| 管理 `client/dist-admin` | `admin.html` → `/src/admin-main.tsx`，`base: "/admin/"` | `assets/admin-Dp4WSijI.js` 365.44 kB（gzip 105.98） | `assets/admin-Cvvbd8II.css` 16.57 kB（gzip 3.75） |

## Red → Green Evidence（§6.1 / §6.2 严格按序）

### 红 1：源码级合同测试必须失败

拆分前 `client/src/RootApp.tsx` 仍 `lazy(() => import("./AdminApp"))` 并有 `/admin` 分支：

```
⎯⎯ Failed Tests 4 ⎯⎯
FAIL src/entryContract.test.ts > 客户唯一入口 RootApp.tsx 不再引用 AdminApp 标识符
  AssertionError: expected 'import { lazy, Suspense, useMemo, use…' not to match /\bAdminApp\b/
FAIL src/entryContract.test.ts > 客户唯一入口 RootApp.tsx 不再分支到 /admin 路径
  AssertionError: … not to match /path\s*===\s*["']\/admin["']/
FAIL src/entryContract.test.ts > 管理端独立挂载文件 admin-main.tsx 存在且只挂载 AdminApp
FAIL src/entryContract.test.ts > 管理端独立入口 HTML admin.html 存在且引用 admin-main.tsx

Test Files  1 failed (1)
     Tests  4 failed | 1 passed (5)
```

### 红 2：产物级断言必须在旧单入口产物上失败

`npm run build`（旧单入口）产出单个 901.67 kB chunk，管理代码就在里面：

```
dist/index.html                   0.47 kB │ gzip:   0.33 kB
dist/assets/index-DkEmBiGV.css   90.74 kB │ gzip:  17.63 kB
dist/assets/index-tZ-6tmrX.js   901.67 kB │ gzip: 258.53 kB

[verify_customer_bundle] ❌ 客户构建制品未通过管理/内部代码排除断言：
── 禁止内容特征串命中 ──
  assets/index-tZ-6tmrX.js:
    [admin] "/api/control/"
    [admin] "激活码批次"
    [admin] "审计中心"
    [admin] "强制下线"
[verify_customer_bundle] 客户所有 chunk 不得含内部/管理入口（CW-019 验收底线）；
命中即证明物理分离未生效，禁止用懒加载隐藏代替排除。
```

注意这 4 条命中**全部是字符串字面量**，一条标识符形状的都没有——这正是
「Critical Findings 第 2 条」的现场证据：`AdminApp`、`exchangeAdminSession` 等
在同一个 chunk 里其实一行都没命中，因为它们已被 mangle。红 2 之所以还能红，
只是因为文案字符串救不了标识符串。

### 绿：双入口落地后

- 客户 JS 由 901.67 kB → **747.04 kB**（-154.63 kB，管理代码物理移出）。
  注：此为拆分当时的数值；收尾 rebase 到 `origin/main@e06b13c` 后，CW-017（PR #9）
  改动了客户包输入，最终树上客户 JS 为 **746.75 kB**（`index-DhDiBhwK.js`）。
  红→绿对比的**基线是同一棵树上的旧单入口 901.67 kB**，故结论不受上游改动影响。
- 管理 JS 独立产出 **365.44 kB**（rebase 前后哈希未变）
- `verify:customer-bundle` 由 ❌ 4 条命中 → ✅ **0 命中，退出码 0**
- `entryContract.test.ts` 由 4 failed / 1 passed → **7 passed**（用例数增加见下）

## Reproducibility（§6.6 两次构建比对）

连续两次 `npm run build:all`，对 `client/dist` + `client/dist-admin` 全量文件做
SHA-256 清单比对：

```
BUILD_A_EXIT=0   FILES_A=21
BUILD_B_EXIT=0   FILES_B=21
REPRO=IDENTICAL      # diff -u 输出为空
```

21 文件 = 客户 17 + 管理 4。两次产物**字节级完全相同**（含内容哈希文件名
`index-DhDiBhwK.js` / `admin-Dp4WSijI.js`），可复现结论有据，无需按 §6.6 但书说明不稳定原因。

该比对在三个不同树上各做过一次，结论均为 IDENTICAL：拆分完成时（16:45/16:51/16:55 三轮）、
CodeReview 修复后（19:01）、第一次 rebase 后（19:32–19:33，且与 rebase 前**字节级相同**）、
第二次 rebase 到 `e06b13c` 后（20:35，客户 JS 因 CW-017 改动而变，管理 JS 仍逐字节相同）。

## Admin Surface Regression（§6.4：管理页面全部保留、独立可用）

`AdminApp.tsx` 组件本体**零改动**（`git diff --stat 5e9d2d7 HEAD -- client/src/AdminApp.tsx`
输出为空），挂载入口从 `RootApp` 的 `/admin` 分支迁到独立的 `admin-main.tsx`。

**纪正一处本任务自己写错的表述**：早先版本称「`client/src/admin/**` 全部页面零改动」，
不实。`git diff --name-status 5e9d2d7 HEAD -- client/src/admin` 的**唯一**输出是
`M client/src/admin/SystemSettingsPage.tsx` —— 该页是控制面后端注入的必然调用点
（新增 `controlBackend: SettingsBackend` 模块级常量并以 prop 传给 `SettingsPanel`），
属 Critical Findings §1 的实现组成部分。除此之外 `src/admin/**` 的其余页面与**全部
管理域测试文件**零增删改（同一 `git diff` 已核实）。

| 范围 | 文件数 | 用例数 | 结果 |
| --- | --- | --- | --- |
| `src/admin/**`（含 `ui/` 3 文件：`TabBar.test.tsx` 2、`ui.test.tsx` 11、`vocabulary.test.ts` 6） | 20 | 119 | 全绿 |
| `src/AdminApp.test.tsx` | 1 | 19 | 全绿 |
| `src/api.admin.test.ts` | 1 | 14 | 全绿 |
| **管理域合计** | **22** | **152** | **全绿** |

**纪正第二处（计数错误，非回归）**：早先版本记为「`src/admin/**` 18 文件 117、合计
20 文件 150」。以 vitest `--reporter=json` 逐文件核算，正确值为上表的 20/119 与 22/152；
差额恰为 `CostDetails.test.tsx`（1 用例）与 `CustomersManagementPage.test.tsx`（1 用例）
两个单用例文件，说明早先那次的文件过滤漏掉了它们。已用
`git cat-file -e 5e9d2d7:<path>` 核实这两个文件在**开工基线上即存在**，且基线→HEAD
之间管理域无任何测试文件增删，故 **152 这一数字对整个任务期成立，早先的 150 属本任务
证据里的误计，不是上游改动、也不是回归**。

客户壳回归（§6.5）：`src/RootApp.test.tsx` **24** 用例全绿，其中原「`/admin` → 渲染 AdminApp」
用例已按 §5.5 改写为「`/admin` 与 `/admin/xxx` 不渲染任何管理内容、落入客户壳」。
`src/customer/**` 全绿。专项四文件（`entryContract` 7 + `RootApp` 24 + `AdminApp` 19 +
`SettingsPanel` 17）= **67 passed**，最终树上复跑一致。

## Reused / Removed Scope 与 CW-011 承接

**已复用（不重做）**：
- CW-011 既有客户构建合同与 `scripts/require_customer_api_base.mjs` 构建期守卫（未触碰）
- `client/dist` 目录名（被 `client/src-tauri/tauri.conf.json` 的
  `build.frontendDist: "../dist"` 依赖，`tauri.customer.conf.json` 无 `build` 键而继承同一值）
- `AdminApp.tsx` 组件本体与 `src/admin/**` 全部页面（唯一改动是 `SystemSettingsPage.tsx`
  注入 `controlBackend`，见「Admin Surface Regression」节的纪正）
- nginx `internal-p0.conf.example` 的 `allow` 内网三段 + `deny all` + `auth_basic`
  全部既有管控（§5.4 红线，未削弱）

**已剔除**：
- `RootApp.tsx` 的 `lazy(() => import("./AdminApp"))` 与 `/admin` 路径分支
- `vite.config.ts` 的 `build.rollupOptions.treeshake` 块、`client/package.json` 的
  `sideEffects` 字段（实测对 Rolldown 零效果，留着会误导）
- `SettingsPanel.tsx` 内的控制面 API 静态引用（改注入式）

**§5.6 归属拆分（CW-011 承接的第二半）**：本 PR 不动 CI 的
`Verify customer installer excludes local launchers` step、不动 Cargo feature、
不动 tauri conf，只新增前端产物层断言。Tauri 双包合同的制品检测扩大归 **CW-021**，
feature/config 唯一默认归 **CW-020**，installer hooks 与签名发布归 **CW-024**，本 PR 不触碰。

**回归先后记录**：严格按 §6 顺序执行——红 1（源码级）→ 红 2（产物级）→ 绿（双入口落地）
→ 管理端回归 → 客户壳回归 → 两次构建可复现 → 管理制品独立可用（`base` 前缀检查）。
红 1 与红 2 均在**任何**实现改动之前先跑出失败输出，符合测试先行要求。

## §7 边界遵守

未触碰越界项：`tauri.conf.json`、`tauri.customer.conf.json`、`Cargo.toml` feature/默认值、
`BackendProcess`、端口探测、`BOOT_COMMAND`、`start-backend.sh/.bat`、
`customer-installer-hooks.nsh`、`video_downloads.rs`、`customer_credentials.rs`、
`client/src/App.tsx` 本体（只保证它不进客户产物）、`api.ts`、`MainPages.tsx`、
`CustomerWorkspace.tsx`、`useCustomerSession.ts`。

`deploy/customer-git-rollout.sh` 与 `deploy/nginx/*.conf.example` 不在 §7 越界表内，
属 §7「CW-019 做」明列的「nginx example 的管理路径落地、部署手册的制品归属说明」范围。

## CodeReview 自检处置（§10.2：M/m 必须修完才能 push）

子代理评审结论：**1 M + 4 m + 4 n**，「不建议直接 push」。逐条处置：

| 级别 | 问题 | 处置 |
| --- | --- | --- |
| **M1** | `customer-git-rollout.sh` 不产出/不部署/不备份 `dist-admin`，合并后 `/admin` 静默 500 而脚本仍报 SUCCESS | **已修**（见 Critical Findings 3），`bash -n` 通过 |
| **m1** | `customer.conf.example` 注释与事实不符 + 缺 `X-Control-Proxy-Token` 清洗 | **已修**（见 Critical Findings 6） |
| **m2** | 排除断言无阳性对照，标识符形状 needle 在压缩产物恒不命中 → 静默失效与制品干净同形 | **已修**（见 Critical Findings 2），阳性对照 6/6 |
| **m3** | rename 插件吞掉一切 ENOENT，入口未产出也静默通过 | **已修**（见 Critical Findings 5） |
| **m4** | `copyPublicDir` 默认 true，25MB 客户专用素材隐式搬进管理制品 | **已修**（见 Critical Findings 4），27MB → 388KB |
| **n2** | `entryContract` 的 RootApp 用例含零增量断言 `/import[^;]*\bAdminApp\b/` | **已修**：收窄为「模块引用语法 + JSX 使用形态」两类正则常量，删掉重复覆盖 |
| **n3** | `main.tsx` / `admin-main.tsx` 断言用裸标识符，易被合法注释误伤 | **已修**：同上，改用 `*_MODULE_REF` / `*_JSX` 常量 |
| **n4** | `statSync` 跟随符号链接，`client/dist` 本身是软链时可绕过前置校验 | **已修**：改 `lstatSync` 且 `isSymbolicLink()` 直接 exit 1 |
| **n1** | `internal-p0.conf.example` 的 `location ^~ /admin`（无尾斜杠）与客户样例风格分叉，且会匹配 `/administrator`、`/admin-x` | **登记 follow-up，本 PR 不修**。理由：该块受 §5.4 红线保护（必须原样保留 `allow` 内网三段 + `deny all` + `auth_basic`），改匹配形态会触碰安全管控块；且现有 `deny all` + Basic Auth 已兜底，无实际越权路径 |
| **n4 附带** | `biome.json` 的 `files.includes` = `["client/src/**/*", "client/*.ts", "e2e/**/*"]`，**不覆盖 `scripts/**`**，故 `verify_customer_bundle.mjs` 不在任何 lint/format 门禁内 | **登记 follow-up，本 PR 不修**。理由：属仓库级 lint 配置变更，影响面超出 CW-019 范围，应由独立任务统一决定 `scripts/` 的门禁归属 |

子代理同时确认设计决策「`SettingsPanel` 控制面 API 改注入式」无问题：两个 backend
都是模块级常量，`useEffect([backend])` 引用稳定；三个调用方（`App.tsx:358`、
`StudioWorkspace.tsx:2094`、`SystemSettingsPage.tsx:65`）均无内联对象。

### 修复后的额外加固（超出 CodeReview 要求）

- `assertCustomerArtifactShape()`：只断言「不含管理代码」不够——一个只含 `favicon.svg`
  的空壳 dist 会通过全部排除断言并报 ✅。故要求 `index.html` 存在且非空、`assets/` 下
  至少一个 `.js`，与 rollout.sh 的 `[[ -s ... && -d ... ]]` 同规格。
- `readArtifactText()` 读不了即 exit 1，不静默跳过（跳过一个文件 = 该文件免检）。
- `printManifest()` 表头由写死的 "customer bundle manifest" 改为
  "build artifact manifest (${label})"：同一函数同时为客户与管理制品打印清单，
  label 才是制品身份的唯一来源；账本 §14 要求两份清单都进 stdout。
- `runPositiveControl()` 补 `client/dist-admin` 空目录硬门（原先只查「无文本产物」）。
- `entryContract.test.ts` 追加 2 个用例（共 7 个）：客户入口不引用内部壳 `./App`；
  `SettingsPanel` 不静态引用控制面 API 且必须以 prop 形态出现 `controlBackend`。

### 断言有效性的变异测试（防止「剔注释」把断言掏空）

n3 的修复方式是「匹配前剔除整行注释」，这天然有把断言弱化成空断言的风险。
故做了一次变异测试取证：向 `client/src/RootApp.tsx` 追加
`import App from "./App";` + `export const __mutation_probe = <App />;`，
`entryContract.test.ts` 立即失败退出 1（`AssertionError: ./RootApp.tsx 不得引用内部壳 ./App`），
随后从备份还原并确认零残留（`__mutation_probe` 与 `from "./App"` 各 0 命中、
文件行数与 diff 统计复原、7 用例重新全绿）。断言有牙，非空断言。

## Full-Repo Gate（`npm run check`）

`npm run check` 链：`verify_no_secrets.sh` → `check --workspace client`
（`biome check . && tsc -b && vitest run`）→ `check:e2e` → `check:tauri` →
`ruff check` → `ruff format --check` → `mypy` → 服务端全量 `pytest`。

> **上游变更**：收尾期 rebase 带入的 PR #8（`2751200 chore(ci): path-filtered gates,
> sharded pytest, dual-path self-hosted runner`）把 CI 的 Linux 质量门从单条
> `npm run check` 拆成 `npm run check:static` + `bash scripts/ci/run-pytest-shards.sh`
> （4 片并行，**每片一个独立 PG 容器**，端口 5433+i），并在 AGENTS.md §4 把「push 前
> 本地跑绿 Linux 质量门」从建议升级为**强制**，同时明确 `npm run check`（顺序全量）
> 仍是等价回退。本任务两条路径都跑了，结果见下。

### 路径 B（CI 实际命令）：`npm run check:sharded` —— 树 `485541f`，EXIT=0

跑前已 `bash scripts/pg-fixture.sh stop`（AGENTS.md 明示：默认 fixture 占 5433 会与
shard-0 撞端口；分片脚本自管 PG）。

| 阶段 | 命令 | 结果 |
| --- | --- | --- |
| Secret 扫描 | `bash scripts/verify_no_secrets.sh` | `No hardcoded secrets detected in runtime contract surface.` |
| 前端 lint | `biome check .`（client） | `Checked 202 files`，0 问题 |
| 前端类型 | `tsc -b` | 0 |
| 前端单测 | `vitest run` | **Test Files 80 passed (80) / Tests 1295 passed (1295)**，24.96s |
| E2E lint | `biome check e2e` | `Checked 15 files`，0 问题 |
| Tauri | `cargo fmt --check` + `cargo check --locked` | `Finished dev profile`，0 |
| 后端 lint | `ruff check server` | `All checks passed!` |
| 后端格式 | `ruff format --check server` | `295 files already formatted` |
| 后端类型 | `mypy server/app` | `Success: no issues found in 104 source files` |
| 后端全量 | `run-pytest-shards.sh`（4 片，99 个测试文件） | shard 0 **645 passed** / shard 1 **529 passed** / shard 2 **511 passed, 1 skipped** / shard 3 **558 passed** → `All 4 shards passed.` |

合计服务端 **2243 passed / 1 skipped / 0 failed**，4 片墙钟 419–434s，整条
`check:sharded` 7m56s（21:00:54 → 21:08:50），`SHARDED_EXIT=0`。

同一命令在前一轮树 `bc8bca2` 上也跑过一次并同样 `EXIT=0`（20:24:06 → 20:33:38，9m32s；
client 1295 用例 31.93s；**4 片用例数与上表逐一相同**）。`bc8bca2` → `485541f` 为
docs-only（3 文件 +142/−17），`485541f` → push 树亦为 docs-only（本轮两处纪正）。

> **docs 也是被测面**：仓库有 9 个 server 测试文件会读取 `docs/` 下的账本与证据
> （`test_build_contracts.py`、`test_customer_git_rollout.py`、`test_internal_admin.py`、
> `test_internal_deployment.py`、`test_customer_ha_smoke.py`、`test_customer_pitr.py`、
> `test_cw009_security_matrix_export.py`、`test_cw033_evidence_boundary.py`、
> `test_cw033_pitr_drill_validation.py`）。每轮 docs 编辑后都单独复跑这 9 个文件
> （**128 passed** = 7 文件 101 + 2 文件 27）并重扫 secrets（EXIT=0），再 amend。

### 最终树上的专项复跑

| 范围 | 结果 |
| --- | --- |
| 专项四文件（`entryContract` + `RootApp` + `AdminApp` + `SettingsPanel`） | 4 files / **67 passed** |
| 管理域（`src/admin/**` + `AdminApp.test.tsx` + `api.admin.test.ts`） | 22 files / **152 passed** |

### 路径 A（顺序全量，等价回退）：分段执行的 `npm run check` 全集 —— EXIT 全 0

在第一次 rebase（`d8f3352`）后的树上执行。**刻意分段**而非用 `&&` 串跑，每段独立记
退出码（原因见 Critical Findings §7：链式短路会让 client 段的 flake 屏蔽 server 段的
真失败）：

```
SEG_A_client  EXIT=0   Test Files 80 passed (80) / Tests 1292 passed (1292)
SEG_B_e2e     EXIT=0
SEG_C_tauri   EXIT=0
SEG_D_mypy    EXIT=0
SEG_E_pytest  EXIT=0   2243 passed, 1 skipped, 1 warning in 1280.98s (0:21:20)
```

（`ruff check` / `ruff format --check` 单独复跑，均 EXIT=0。）

两次运行的服务端用例数**逐一相同**（2243 passed / 1 skipped），与 #8 在 AGENTS.md 中
声称的「分片与顺序全量逐一致」相符；client 用例数由 1292 → 1295 的差值来自第二次
rebase 带入的 CW-017（PR #9）新增的 3 个前端用例，与本任务无关。

### 本地跑不到的四项（以 CI 为准）

按 §8.7：`cargo test`、`npm audit`、`npm run test:customer-e2e` 的 CI 侧完整链路、
Windows Tauri/NSIS 门禁。本地 `npm run check` 不含这四项，Rust/构建/依赖类问题
以 push 后的三门禁（Secret scan / Linux quality gate / Windows Tauri and NSIS）结果为准。

## Files Changed

| File | Change |
| --- | --- |
| `client/admin.html` | **新增**：管理端独立入口 HTML（`#root` + `/src/admin-main.tsx`） |
| `client/src/admin-main.tsx` | **新增**：管理端独立挂载文件（只挂载 `AdminApp`，挂载点缺失即抛错） |
| `client/vite.admin.config.ts` | **新增**：`base: "/admin/"`、`outDir: dist-admin`、`emptyOutDir: true`、`copyPublicDir: false`、`writeBundle` 重命名 `admin.html`→`index.html` + favicon 单文件拷贝 |
| `client/src/entryContract.test.ts` | **新增**：源码级入口合同测试 7 用例（双层断言第一层） |
| `scripts/verify_customer_bundle.mjs` | **新增**：产物级排除断言 + 阳性对照 + 两份 SHA-256 清单（双层断言第二层） |
| `client/vite.config.ts` | `rollupOptions.input` 显式钉住 `index.html`（防后来者加 html 被卷进客户包）、`outDir`/`emptyOutDir`、admin dev 期 rewrite 插件；剔除无效 treeshake 块 |
| `client/src/RootApp.tsx` | 删 `AdminApp` lazy import 与 `/admin` 分支，docblock 更新 |
| `client/src/RootApp.test.tsx` | 原 `/admin` → AdminApp 用例改写为「不渲染任何管理内容、落入客户壳」 |
| `client/src/SettingsPanel.tsx` | 导出 `SettingsBackend` 类型 + 判别联合 props，控制面后端改注入式（切断 `/api/control/` 静态可达链） |
| `client/src/SettingsPanel.test.tsx` | 适配注入式契约 |
| `client/src/admin/SystemSettingsPage.tsx` | 以 `controlBackend` 注入控制面后端 |
| `client/src/main.tsx` | docblock 说明双入口边界 |
| `client/tsconfig.node.json` | `include` 追加 `vite.admin.config.ts`（否则 `tsc -b` 静默不检查） |
| `client/package.json` | 新增 `build:admin`；剔除已证无效的 `sideEffects` |
| `package.json` | 新增 `build:all`、`verify:customer-bundle` |
| `.github/workflows/ci.yml` | Linux quality gate 新增 `Build admin bundle` + `Verify customer bundle excludes admin and internal entries` 两个 step；二者与上游 `Build web client` 同样门控于 `if: needs.changes.outputs.desktop == 'true'`（第二次 rebase 后手工补齐，见 Critical Findings §8） |
| `.gitignore` | 新增 `dist-admin/` |
| `deploy/nginx/customer.conf.example` | `location ^~ /admin/` alias 到管理制品 + SPA fallback；`location ^~ /api/` 补 `X-Control-Proxy-Token ""`；访问控制注释纪正 |
| `deploy/nginx/internal-p0.conf.example` | `/admin` 指向 dist-admin；`allow` 内网三段 + `deny all` + `auth_basic` 全部保留 |
| `deploy/customer-git-rollout.sh` | `dist-admin` 产出/备份/同 SHA 原子替换/回滚/`curl` 探活（M1） |
| `server/tests/test_customer_git_rollout.py` | 守卫 needle 由 `npm run build --workspace client` 更新为 `build:all` + `verify:customer-bundle`；新增 `test_customer_git_rollout_ships_admin_artifact_in_the_same_release_run` 锁住 M1 的六项行为（见 Critical Findings §7） |
| `docs/客户版部署与灰度手册.md` | 制品归属说明 |
| `docs/客户版代码开发清单-V3.md` | 追加 §4.5「构建入口与制品（CW-019）」登记 5 个新文件 |
| `docs/客户版任务清单-V3.md` | §18 CW-019 行 + 头部状态行 |
| `docs/CUSTOMER-TASK-EVIDENCE-V3.md` | 登记一行 |

## Section 14 Ledger Record

```text
任务/工作包：CW-019 / W3「分离客户与管理员前端构建制品」
Owner / Reviewer：前端构建（Agent 执行）/ CodeReview 子代理（push 前自检）+ owner（PR 评审）
分支 / 基线 SHA：feat/customer-v3-cw019-split-build-artifacts / 开工基线 origin/main@5e9d2d7，收尾两次 rebase：先到 origin/main@d8f3352（CW-016 #6 / CW-025 #7 / CW-033 #3 已合入；package.json 与 docs/客户版任务清单-V3.md 两处交集均自动合并、0 冲突；rebase 后两次 build:all 的 21 文件 SHA-256 清单与 rebase 前字节级相同），再到 origin/main@e06b13c（CI 重构 #8 + CW-017 #9；同为 0 冲突，但 ci.yml 的自动合并结果语义破损，已手工补 if 门控，详见 Critical Findings §8；客户制品因 CW-017 改动客户包输入而哈希变化，管理制品 4 文件哈希未变）。全仓门禁跑于树 485541f（本文档纪正编辑前的提交树），485541f 与 PR head 的差集为 docs-only（git diff --stat 只含 docs/），git log origin/main..HEAD 只含本任务提交、无外来提交
PR：#12（base main）；push 后核对 PR Commits 列表确认无外来提交；受保护 main 仅接受 owner 账号 squash merge，本任务不自行合并
上游规格段落：docs/客户版任务清单-V3.md §17 CW-019 行、§18 CW-019 行；docs/开发交接提示词-CW019-拆双构建制品-2026-09-10.md §5/§6/§7/§9/§10；docs/客户版代码开发清单-V3.md §4.5
改动文件：新增 client/admin.html、client/src/admin-main.tsx、client/vite.admin.config.ts、client/src/entryContract.test.ts、scripts/verify_customer_bundle.mjs；修改 client/vite.config.ts、client/src/RootApp.tsx、client/src/RootApp.test.tsx、client/src/SettingsPanel.tsx、client/src/SettingsPanel.test.tsx、client/src/admin/SystemSettingsPage.tsx、client/src/main.tsx、client/tsconfig.node.json、client/package.json、package.json、.github/workflows/ci.yml、.gitignore、deploy/nginx/customer.conf.example、deploy/nginx/internal-p0.conf.example、deploy/customer-git-rollout.sh、server/tests/test_customer_git_rollout.py、docs/客户版部署与灰度手册.md、docs/客户版代码开发清单-V3.md、docs/客户版任务清单-V3.md、docs/CUSTOMER-TASK-EVIDENCE-V3.md
失败测试或回归锁定：红1 entryContract.test.ts 4 failed/1 passed（RootApp 仍 lazy import AdminApp + /admin 分支）；红2 旧单入口 901.67 kB chunk 被 verify 判 ❌ 命中 /api/control/、激活码批次、审计中心、强制下线 4 条 → 双入口落地后转绿；变异测试锁定断言有效性（注入 import App from "./App" + <App/> → exit 1，还原后 7/7 绿）；n3「剔注释」弱化风险已用变异测试证伪；收尾期抓到并修复一处本 PR 造成的确定性真回归——上游守卫 test_customer_git_rollout.py 断言旧构建命令字面量 "npm run build --workspace client"（M1 已改为 build:all + verify:customer-bundle），隔离复跑 1 failed/3 passed 100% 可复现；该失败此前被 client vitest 时序 flake 掩盖（check 脚本以 && 串联且 client 段在 pytest 之前，flake 短路使 pytest 一次都没执行到），改分段执行后暴露，处置详见 Critical Findings §7
实现结果：Vite MPA 双入口 + 双 outDir 物理分离；客户 JS 901.67→747.04 kB（最终树 746.75 kB，差值来自第二次 rebase 带入的 CW-017），管理 JS 独立 365.44 kB；client/dist 17 文件禁止文件名 0 命中、禁止特征串 0 命中、退出码 0；client/dist-admin 4 文件、base /admin/、资源前缀 /admin/assets/ 正确；阳性对照 6/6 各命中 1 文件；实测 Rolldown 忽略全部 treeshake 配置（三种写法产物哈希字节级相同）→ 改依赖注入切断 /api/control/ 静态可达链；dist-admin 27MB→388KB（copyPublicDir:false 断开 25MB 客户素材隐式搬运）
验证命令与通过数：npm run build:all 两次 BUILD_EXIT=0 且 21 文件 SHA-256 清单 diff 为空（REPRO=IDENTICAL）；npm run verify:customer-bundle → 17+4 文件清单、0 命中、阳性对照 6/6、VERIFY_EXIT=0；npx vitest run src/entryContract.test.ts src/RootApp.test.tsx src/AdminApp.test.tsx src/SettingsPanel.test.tsx → 4 文件 67 passed；管理域 src/admin/** 20 文件 119 + AdminApp.test.tsx 19 + api.admin.test.ts 14 = 22 文件 152 全绿（早先版本记为「src/admin/** 18 文件 117、合计 150」，属本任务证据的**计数误计而非回归**：差额恰为 CostDetails.test.tsx 与 CustomersManagementPage.test.tsx 两个单用例文件，git cat-file -e 5e9d2d7:<path> 核实二者在开工基线即存在，且基线→HEAD 之间管理域无任何测试文件增删，故 152 对整个任务期成立，详见「Admin Surface Regression」节）；client npx tsc -b → 0；npx biome check . → 0；bash -n deploy/customer-git-rollout.sh → 通过；python3 -c "import yaml" 解析 ci.yml 通过、三个构建/断言 step 的 if 逐字一致；守卫测试 test_build_contracts + test_customer_git_rollout + test_internal_deployment → 23 passed；全仓门禁两条路径均绿（树 485541f，push 树与其仅差 docs-only 编辑）——路径 B（CI 实际命令）npm run check:sharded → SHARDED_EXIT=0（21:00:54→21:08:50，7m56s），client 80 文件 1295 用例 24.96s、4 片 pytest 645+529+511(+1 skipped)+558 = 2243 passed / 1 skipped / 0 failed，biome client 202 files、biome e2e 15 files、ruff All checks passed、ruff format 295 files already formatted、mypy 104 source files、cargo Finished dev profile、secrets 0；同一命令在前一轮树 bc8bca2 上亦 EXIT=0（9m32s，4 片用例数逐一相同）；docs 编辑后单独复跑 9 个读 docs 的 server 测试文件 = 128 passed + verify_no_secrets.sh EXIT=0；路径 A（顺序全量等价回退）分段执行的 npm run check 全集 → SEG_A_client/B_e2e/C_tauri/D_mypy/E_pytest 全 EXIT=0，pytest 2243 passed / 1 skipped in 1280.98s；两次运行服务端用例数逐一相同，详见「Full-Repo Gate」节
证据层级：AUTOMATED_VERIFIED（本地自动化门禁 + 产物字节级扫描 + 阳性对照自证；未过真实链路，不标 STAGING_VERIFIED/REAL_CHAIN_VERIFIED/PRODUCTION_GO）
安全与可观测性：客户制品零管理/内部特征串（双层断言 + 阳性对照防静默失效）；customer.conf.example 的 location ^~ /api/ 补 X-Control-Proxy-Token "" 与 internal-p0 一致（纵深防御，客户生产实际由 admin_session cookie 鉴权，非缺令牌 fail-close）；internal-p0.conf.example 的 allow 内网三段 + deny all + auth_basic 全部保留未削弱；SettingsPanel 控制面 API 改注入式，客户包不再静态可达 /api/control/
迁移与回滚：无数据库迁移。构建产物回退 = 回退本 PR 后重跑 npm run build（dist-admin 不再产出，需同步回退 nginx 的 location ^~ /admin/ 块）。部署回滚：customer-git-rollout.sh 的 rollback() 恢复 site-before.tar.gz，并仅在 admin-site-before.tar.gz 存在时恢复管理站（首个引入 dist-admin 的发布无前一版管理站，无归档=无可回滚目标而非静默跳过）
外部授权记录：无（本任务不含真实支付/Provider/生产发布动作）
未测试项：deploy/customer-git-rollout.sh 未在目标机执行（仅 bash -n 语法校验，本机无 shellcheck）；nginx 未真实 reload、/admin 未真实浏览器探活；cargo test、npm audit、npm run test:customer-e2e 的 CI 侧完整链路、Windows Tauri/NSIS 门禁本地跑不到（§8.7，以 push 后三门禁为准）；follow-up 两项（n1 internal-p0 的 location ^~ /admin 无尾斜杠风格分叉；biome.json 的 files.includes 不覆盖 scripts/**）；另主动披露两项上游结构问题且本任务不修（scripts/verify_customer_bundle.mjs 不在 desktop filter 内 → 只改该脚本的 PR 上产物级断言被跳过，源码级仍恒执行；scripts/pg-fixture.sh 仓库内 mode 仍为 100644 而文档写直接调用形式），详见 Critical Findings §9
Lore 提交 SHA：见 PR squash 合并 SHA
```
