# WORKSPACE-CLEANUP-20260914：已合并工作区清理证据

本任务仅处理本地工作区整理与历史成果保全，未修改业务实现。用户已授权按工作区盘点建议执行。

Owner：Codex / 01a09d06-e504-7a63-8099-b0f9b028ce68。Reviewer：执行者自检及本维护 PR 门禁；未声称独立人工评审。基线 `origin/main@11c3de13422f2bab009a052a9f2074bf8c13e12c`。

## 已执行结果

- 33 个已合并任务 worktree 已由 Git 移除，目录与注册项均已复核不存在；全部本地/远程分支保留。
- 原盘点有 45 个 worktree。原清理候选为 32 个已合并目录加 1 个审查基线；本次保留无独立 PR 的 AUDIT-FRONTEND，另外归档 W6 三份日志后将其加入清理，实际仍为 33 个。
- 43 个原工作区已建立保全记录；183 个文件共 1,035,019,682 字节，按原字节归档并验证 SHA-256。包含旧代码草稿、支付三份稿件、审查探针、CI 日志和 UC 验收材料。
- `stash@{0}` 原始提交 `e967e70` 及其 4 个文件另行导出，Git 中的 stash 保留。
- 全部 Git 引用已打包为完整 `repository-refs.bundle`，259,743,682 字节；`git bundle verify` 通过，SHA-256 为 `1f2f81f0b7d81f2a02f21f1e330c8e845e8c7227b108ba82f961485b06cec72f`。
- 未检出的本地 main 已使用带旧 SHA 校验的 `update-ref` 从 `a093f61` 快进到 `11c3de1`，消除原有 55 个提交的落后。原主检出目录仍保留原功能分支及未提交方案。
- 共享 claim 仅在工作区路径精确匹配时回填 CLEANED；已被其他阶段复用的同编号 claim 不覆盖。逐目录独立清理记录统一保存在本任务 claim 下。

## 合并、进程与路径验证

所有下表 PR 均有 merged_at、最终 PR head 和 squash SHA；逐项验证本地 head 包含于该 PR head、squash SHA 是上述远程 main 的祖先。使用 squash 证据，未以原分支是否为 main 祖先替代。

main [CI run 34778309914](https://github.com/peihr666-max/xiangshu-video-replica-/actions/runs/34778309914) 的 Secret scan、Linux quality gate、Windows Tauri and NSIS 均成功。原 main 门禁仅作为这些既有任务清理依据，本维护 PR 自身状态另以当前检查为准。

清理前读取 Windows 进程真实工作目录与运行容器挂载。相关在用进程均属于 LOCAL-JOINT，保留其服务、数据库卷、存储和依赖。逐目录复查 HEAD、未跟踪文件、ignored 文件及归档哈希；所有目标先解析绝对路径并确认位于约定的 .worktrees 根内、属于 Git 登记项且不是主检出目录或公共 Git 目录。

移除前仅解除依赖目录联接，保留共享目标；使用 `git worktree remove`，没有 force 或递归删除回退。CW-068 的 Git 命令返回 0 且已注销，但残留一个此前已失效的 npm 联接；核对目标后非递归删除该联接及三个空目录。没有移除其指向的其他任务目录。

## 已清理清单

下表归档子目录均位于工作区根 `.worktree-archives/WORKSPACE-CLEANUP-20260914/`；原始压缩包与运行材料只存本机，不纳入 PR。

| Worktree | PR | Squash SHA | 保全文件 | 状态 |
|---|---|---|---:|---|
| ADMIN-R01-20260913 | [#96](https://github.com/peihr666-max/xiangshu-video-replica-/pull/96) | `f401a0b48b4d336154e42574db302e2b6787e515` | 0 | CLEANED |
| COORD-STATUS-AUTO-R10-20260912 | [#76](https://github.com/peihr666-max/xiangshu-video-replica-/pull/76) | `55220f7e5a84b06e748f98324bfed141f2e6fb94` | 0 | CLEANED |
| CW-031-LEDGER-BACKFILL | [#42](https://github.com/peihr666-max/xiangshu-video-replica-/pull/42) | `fd90a94b0a4a7fdc22cfad4708170aad67360cd9` | 0 | CLEANED |
| CW-042-scope-inventory | [#71](https://github.com/peihr666-max/xiangshu-video-replica-/pull/71) | `3ae6d5dd6d12fc6de7b2fc3b123493c38e595390` | 0 | CLEANED |
| CW-043-audit-implementation | [#46](https://github.com/peihr666-max/xiangshu-video-replica-/pull/46) | `2be7c3dcb80e81a6d7261d63cacfb35cac8cf49c` | 0 | CLEANED |
| CW-043-pg-coverage-audit | [#43](https://github.com/peihr666-max/xiangshu-video-replica-/pull/43) | `1389f98e58914ab9f4a735867c1f0b18f9ebb047` | 0 | CLEANED |
| CW-061-ci-shard-coverage-guard | [#36](https://github.com/peihr666-max/xiangshu-video-replica-/pull/36) | `a093f61f7efb73e989c79eda17ae649c519a6e28` | 0 | CLEANED |
| CW-063-h3-extended-modes-toggle | [#48](https://github.com/peihr666-max/xiangshu-video-replica-/pull/48) | `f98b86833a850916409a7284ab4d95a516785e4c` | 0 | CLEANED |
| CW-066-payment-provider | [#56](https://github.com/peihr666-max/xiangshu-video-replica-/pull/56) | `f2754e68c2e376cf5ebddb38074cdc756d9a203e` | 0 | CLEANED |
| CW-068-publish-accounts | [#60](https://github.com/peihr666-max/xiangshu-video-replica-/pull/60) | `40111825c47e14a0674570edb93aa259e56fcac7` | 0 | CLEANED |
| CW-078-api-keys | [#64](https://github.com/peihr666-max/xiangshu-video-replica-/pull/64) | `d091557c0e37200e436cd35eb1539b5bdd273298` | 0 | CLEANED |
| CW-W6-PHYS-EXIT-20260912 | [#91](https://github.com/peihr666-max/xiangshu-video-replica-/pull/91) | `3492bc37b0a8291163436979ca183754cb94046d` | 3 | CLEANED |
| FE-CHARACTER-SCENES-20260913 | [#98](https://github.com/peihr666-max/xiangshu-video-replica-/pull/98) | `b3f7e5cc3772d01ebc553eade19e2a2650a70ff3` | 0 | CLEANED |
| FE-PRELAUNCH-20260913 | [#93](https://github.com/peihr666-max/xiangshu-video-replica-/pull/93) | `c28fb7c42f43a2b1eedbe97cdc317027e37644fd` | 0 | CLEANED |
| FE-VIDEO-PREVIEW-20260913 | [#95](https://github.com/peihr666-max/xiangshu-video-replica-/pull/95) | `400bbaa3af7fd1290fad7e949b328df349ec8203` | 0 | CLEANED |
| FIX-ADM02-20260912 | [#80](https://github.com/peihr666-max/xiangshu-video-replica-/pull/80) | `47c9ffb1d3cb14f7d282a1681db06377ef82a4b2` | 0 | CLEANED |
| FIX-TESTBASE-20260912 | [#78](https://github.com/peihr666-max/xiangshu-video-replica-/pull/78) | `8ae7305471d9c6a10ceacbd2c0f2c5c1ce4004bf` | 0 | CLEANED |
| FIX-TESTREADY-20260912 | [#88](https://github.com/peihr666-max/xiangshu-video-replica-/pull/88) | `820c3d84025cfc9f390fed398c490a6950e6402f` | 0 | CLEANED |
| FIX-VIDEO-LINK-20260913 | [#97](https://github.com/peihr666-max/xiangshu-video-replica-/pull/97) | `84b4d712ed55438ff7d00b9e348bef12ec1a6354` | 0 | CLEANED |
| FIX-W13-20260912 | [#84](https://github.com/peihr666-max/xiangshu-video-replica-/pull/84) | `cd8bccf007c736e92239a35a4bc9d480f228fd36` | 0 | CLEANED |
| FIX-W15-20260912 | [#85](https://github.com/peihr666-max/xiangshu-video-replica-/pull/85) | `75ce0c690bf6f5e65c46612e6729abc35de3c294` | 0 | CLEANED |
| FIX-W18-20260912 | [#82](https://github.com/peihr666-max/xiangshu-video-replica-/pull/82) | `4c7da0f2fab24765f78d2faf0a9c4a6744dcb730` | 0 | CLEANED |
| FIX-W19-20260912 | [#87](https://github.com/peihr666-max/xiangshu-video-replica-/pull/87) | `e8445c4c24f4b321aa08a0b8de50818358b7fa51` | 0 | CLEANED |
| FIX-W20-20260912 | [#83](https://github.com/peihr666-max/xiangshu-video-replica-/pull/83) | `9bfe593754179da340f829fd46b7061b17554646` | 0 | CLEANED |
| FIX-WALLETSTATUS-20260912 | [#81](https://github.com/peihr666-max/xiangshu-video-replica-/pull/81) | `4d2e59876245e12dea94c53fb80074613d4d38d1` | 0 | CLEANED |
| JT2-20260913 | [#89](https://github.com/peihr666-max/xiangshu-video-replica-/pull/89) | `1b12737ca74d735237b975830cabc1f45ef92168` | 0 | CLEANED |
| UC-BATCH-01-account-access | [#79](https://github.com/peihr666-max/xiangshu-video-replica-/pull/79) | `37a263390b3ca03cbc1713e1f61ff9e7f165166e` | 44 | CLEANED |
| UC-BATCH-02-personal-center | [#86](https://github.com/peihr666-max/xiangshu-video-replica-/pull/86) | `791fd6646288c59a84dbed1f1ec26528e862a06d` | 21 | CLEANED |
| UC-BATCH-03-points-pricing | [#90](https://github.com/peihr666-max/xiangshu-video-replica-/pull/90) | `40e261c0d936df044023b03be0eae5afd73135ae` | 22 | CLEANED |
| UC-BATCH-04-account-operations | [#92](https://github.com/peihr666-max/xiangshu-video-replica-/pull/92) | `abc96b7b093f92f54acdbfc4d5cd167eac5fa3e5` | 63 | CLEANED |
| CW-014-ledger-backfill | [#39](https://github.com/peihr666-max/xiangshu-video-replica-/pull/39) | `c9c0609739817ff00aff7a3a0148e17e1017b9ee` | 0 | CLEANED |
| CW-067-recharge-schema | [#57](https://github.com/peihr666-max/xiangshu-video-replica-/pull/57) | `cd959ff58b3eb03ab15c2300202921a882d93004` | 0 | CLEANED |
| CW-073-device-slots | [#58](https://github.com/peihr666-max/xiangshu-video-replica-/pull/58) | `76ee840a9811352aba1ff4ee29c45945ef43f09c` | 0 | CLEANED |

## 保留成果与增量判定

### LOCAL-JOINT

原运行目录和 SYNC 验证目录均保留。同期任务已将两者更新到本地合并提交 `db2209fa30e727c31045cffa4707ee17416d8152`，包含 main `11c3de1` 和原 6 个本地提交，工作区冲突已解决。该整合仍未推送或形成新 PR。

根据同期 `outputs/local-joint-sync-20260914/本地环境更新验收.md`：5173/5174/8000 及 Worker 已同步运行；配置字节、17 项业务表摘要及 41 个存储文件保留。其原始全量结果为后端 2037 passed / 4 failed / 1 skip，修复后相关三文件 35 passed；这些是同期任务证据，不记作本清理任务重新运行的测试。历史缓存转入新发布集合尚未验收，未自动开启付费采集。

### FIX-R02：仍有独立差额，保留为待交付

本地 `b7e66fe4427c6fdfb888a05249f8a54f28d39ec1` 未包含于任何现存远程分支，未找到 PR。对当前 main 源码比对：

| 检查点 | 当前 main | 原 R02 补丁及处理结论 |
|---|---|---|
| 支付结算异常原子性 | `zpay_payments.py` 仍调用 BEGIN IMMEDIATE 与适配层 commit/rollback；PG 路径由外层事务管理 | 补丁新增真实 PG transaction/savepoint。仍需迁入和重新验收，不能声明已由主线覆盖 |
| 同订单并发重放 | 结算读取没有 FOR UPDATE | 补丁包含订单行锁；保留该独立改动 |
| 微信异步回调 | 直接执行同步结算 | 补丁使用线程池，避免等待行锁阻塞事件循环事务收尾 |
| 回归覆盖 | 专属证据与新增矩阵未原样进入 main | 原 PG 故障恢复、并发与外层回滚用例随原分支和 bundle 保留 |

原证据的 62 passed 为旧基线结果。本次完成静态增量判定，未把旧测试当作最新 main 的通过结果。处理决定：保留原 worktree/claim/提交，后续从届时最新 main 单独迁入 R02 行为与测试；不把旧共享账本或后续业务重构整体覆盖回去。

### FIX-R04：部分主线已有，重试意图仍有差额

本地 `e8f79889f17cdbda02da2676561c834e60aec626` 未包含于现存远程分支，未找到 PR。当前 `CustomersPage.tsx` 已有相同请求指纹复用幂等键、发放成功后 onChanged 刷新，不应重复重做。

仍有源码差额：当前未冻结整份待确认业务意图；异常后可修改输入/来源类型，确认对话框重开会清空原因，改动指纹会生成新键；客户列表请求缺少原 R04 的代次防覆盖。原补丁包含冻结意图、同步提交锁、未知结果保留、确定拒绝释放、余额及详情刷新、新增 `CustomersPage.free-grant.test.tsx`。这些专属实现和测试未完整进入 main。

处理决定：保留原 worktree/claim/提交，后续从最新 main 迁入最小差额，并兼容主线新增来源类型及 LOCAL-JOINT 的客户页布局。旧补丁直接覆盖会回退后续 UI。此次为静态判定，未重新运行旧证据中 16/168 项测试，不声明业务验收完成。

### 旧稿与其他保留目录

- CW-044 选择归档历史盘点；987 行盘点文档、分支、原 worktree 保留。它已推送到任务分支，但无合并 PR；不把归档称作 CW-044 收敛实施或交付完成。
- 支付原稿、评审稿、修订稿统一归档，保留原目录。DOC-FIX 的 `644e493` 本地提交完整保存；三份文档用途及版本不同，不合并成未经复核的新规范。
- CW-077 旧稿与 UC-BATCH-01 / PR #79 存在迁移关系，但并非逐字相同；旧稿仍含单在线、注册后回登录等过期要求。24 个改动文件与二进制 diff 已归档，保留原目录；未将其作为新功能重新提交。
- 两个 AUDIT-ADMIN 探针记录旧失败行为，实际管理请求修复已随 PR #96 合并。探针已归档，保留原目录，不把旧故障断言变成正式回归契约。
- AUDIT-FRONTEND 只是审查基线，无独立合并 PR，保守保留。
- 执行期间新增 NOTIFICATION-DESIGN-20260914，不属于原扫描清理清单，保留其目录和提交。

## 恢复与验证

已清理任务可以从保留分支重新执行 `git worktree add <新目录> <分支>`；PR squash SHA 也可从远程恢复。工作文件从该任务 `local-materials.zip` 按 `manifest.json` 的原路径恢复，先核对哈希；stash 仍可正常查看，暂不套用旧横幅或旧迁移 head。

仓库外原始记录：`outputs/workspace-cleanup-20260914/cleanup-results.json`、`archives.json`、`process-cwds.json`、`docker-mounts.json`、`local-main-sync.json`。原 45 项审计快照保留为历史快照；最新目录数量以新的执行清单为准。

本维护提交仅更新认领登记及本证据。执行 Git 差异/空白检查、记录与目录一致性校验、文档本地链接校验及仓库秘密扫描；业务全量不重复本地运行，按 AGENTS 纯文档维护规则交本 PR CI。业务证据等级、生产发布状态均未提升。

## 后续交付与二次清理（2026-09-14）

首次清理后的待交付项已按最新主线串行处理：

| 交付 | PR head | Squash SHA | CI | 二次清理 |
|---|---|---|---|---|
| LOCAL-JOINT delivery | `9b23e5fb1305f0fd705cca62e8d88350703eb346` | [PR #102](https://github.com/peihr666-max/xiangshu-video-replica-/pull/102) / `281a82848cf9a3255054082939da228f7c92c7c6` | 5/5 success | 交付 worktree 已移除，分支保留 |
| FIX-R02 delivery | `ad43276223497b6bf35232bf131f19f36a0f2dc0` | [PR #103](https://github.com/peihr666-max/xiangshu-video-replica-/pull/103) / `29ce20d2698a4e4a9e46926caccdf40a69827eb6` | 5/5 success | 交付 worktree 已移除，分支保留 |
| Notification design | `41e4a8bebcc65114694928d704a943edb7ec8d03` | [PR #104](https://github.com/peihr666-max/xiangshu-video-replica-/pull/104) / `50059bc1adc4ef92d68e749ecb0305bafef3d1eb` | 5/5 success | 设计 worktree 已移除，分支保留 |

每次合并后均先 `fetch origin --prune`，只在远程主线为本地主线快进时用旧 SHA 保护更新 `refs/heads/main`。二次清理前再次确认本地 `main == origin/main == 50059bc1adc4ef92d68e749ecb0305bafef3d1eb`，并逐项验证目标绝对路径位于 `E:/众墅之家爆款短视频创作/.worktrees/`、worktree 已登记且干净、PR head 树与 squash 树相同、squash 是主线祖先；未使用 force，未删除任何分支。登记 worktree 数量由 10 个降为 7 个。

以下对象继续保留：主 worktree 为用户明确在制的 CW-056；`IMAGE-CONSENT-20260914` 有新的未提交源码、测试和 CLAIMED 记录；LOCAL-JOINT 源/同步目录仍承载本地联调；旧 R02 源分支与正式交付树存在适配差异；R04 仍需从最新主线迁入最小有效差额；本维护 worktree 需待本 PR 合并后再按相同规则移除。
