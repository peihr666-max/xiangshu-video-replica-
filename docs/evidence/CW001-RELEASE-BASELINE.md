# CW-001 — 整合候选、补丁来源与发布基线决议（草案，待集成负责人签认）

## 任务信息（§14 模板）

| 字段 | 值 |
| --- | --- |
| 任务/工作包 | CW-001 确定整合候选、补丁来源与发布基线 |
| Owner / Reviewer | Owner：ZCode 代理（hlong026 会话，2026-09-09）；Reviewer：独立复核子代理 + 待集成负责人签认 |
| 分支 / 基线 SHA | `feat/customer-v3-cw001-release-baseline` / 正式候选基线 `origin/main@df7020c` |
| 上游规格段落 | V3 清单 §4 CW-001（line 96-109）；§1 规则 5（分支比对到固定提交再整合）；`data-deploy-audit.md`（审计输入 bffc341，非最终基线） |
| 改动文件 | `docs/evidence/CW001-RELEASE-BASELINE.md`（新增） |
| 失败测试或回归锁定 | 不适用（准备与决策层；迁移链核实为静态核验） |
| 实现结果 | 见 §1–§6：发布基线冻结 df7020c；迁移单 head 080 无多父；8 分支补丁来源处置；回滚点；pre-GA 路线附件；2 待确认策略点 |
| 验证命令与通过数 | 静态核验：`git ls-tree`/`git grep` 迁移链单 head 计算（§2）；`git rev-list --count`+`git merge-base` 补丁来源与 fork 基线（§3）；`git diff b4b584e df7020c --stat` tree 逐字节比对（§1）；`git cat-file -e df7020c:<doc>` 核验 6 份草案目标文件 ABSENT（§3/§4 cherry-pick 零冲突依据） |
| 证据层级 | 决策与静态核验（签认前不得视为完成） |
| 安全与可观测性 | 不适用（本项不含运行时改动） |
| 迁移与回滚 | 纯文档新增，revert 即回退；发布基线 df7020c 的回滚点见 §4 |
| 外部授权记录 | 无 |
| 未测试项 | §6 两个待集成负责人确认的策略点；§7 签认字段 |
| Lore 提交 SHA | 本 PR squash 后回填 |

## 1. 发布基线冻结（整合候选）

正式候选 = **`df7020c`**（`Feat/customer v3 cw007 pg test foundation (#103)`），即当前 `origin/main`。

| 决议项 | 结论 | 依据 |
| --- | --- | --- |
| 应用源码基线 | `df7020c` | CW-007 已 squash merge（PR #103）；`git diff b4b584e df7020c --stat` 输出为空 → tree 与 CW-007 分支 b4b584e 逐字节一致，无夹带 |
| 迁移基线 | df7020c 内 `server/migrations/versions/` 单 head 080 | 见 §2 |
| 文档输入基线 | V3 清单（bf6aab8 定义）+ data-deploy-audit（bffc341 审计快照） | V3 line 3；audit 为审计输入，非最终候选 |
| 数据库规范 | 全环境 PG 唯一（承接 CW-002 §1） | `docs/PostgreSQL唯一数据库实施与验收规范.md` |

- 漂移说明：`data-deploy-audit.md` 的规模数字（103 顶层文件 / 76 迁移 / 92 测试文件）钉在 **bffc341** 审计快照，与 df7020c 存在漂移；本决议以 df7020c 实际树为准，audit 仅作裁剪边界输入（CW-053 已将 DB 语义清单重算到 df7020c 基线）。
- **`source-baseline.json` 处置（DoD line 104 文件对象）**：位于 `outputs/customer-cloud-convergence-analysis-2026-09-08/source-baseline.json`（df7020c 内 track；独立分析目录 `乡墅爆款短视频复刻-客户版收敛分析/outputs/...` 同名文件一致）。其 `source_base_sha=bffc3419f9d89bf76fd4ad1bdad65dd824a44553`、`captured_at_utc=2026-09-08T12:20:28`、`audit_branch=codex/customer-cloud-convergence-analysis-20260908`，记录的是**分析阶段快照**（当时 origin/main=2cacc920）。**决议：作为分析输入快照保留、不改写**（改写会破坏审计可追溯性）；发布基线以本决议 §1 的 df7020c 为准，二者分属不同层（bffc341=分析起点，df7020c=整合后正式候选）。bffc341→df7020c 的演进 = viral 收敛队列3（ce40db5，PR #100–102）+ CW-007（df7020c，PR #103），均为已合并 main 的正式提交，符合 DoD line 107"不能用分析分支代替最终集成版本"。

## 2. 迁移图核实（无多 head、无已发布 revision 改写）

在 df7020c 基线核实（CW-001 DoD 保留验收底线："复核迁移无多 head、无已发布 revision 改写"）：

| 核查项 | 结论 | 依据 |
| --- | --- | --- |
| 迁移文件总数 | 78 | `git ls-tree df7020c -r server/migrations/versions/ \| grep -c '\.py$'` |
| 唯一 head | `080_viral_link_resolution_receipts` | 悬空 head 计算（revision 集合 − down_revision 集合）仅输出 080 |
| 无多父 merge | 确认（纯线性链） | `git grep -E "^down_revision.*\(" df7020c` 输出空 → 无 down_revision 元组 |
| 链起点 | `001_core`（down_revision=None） | `git grep -l "down_revision.*None"` 仅命中 001_core.py |
| 编号缺号 | 缺 030、060；缺号处链连续 | 031 down=027、061 down=059 |
| 编号顺序 ≠ 拓扑顺序 | 031 在链上位于 027↔028 之间 | 027→031→028→029→032（历史编号错乱，拓扑仍单一线性） |
| 已发布 revision 未改写 | 025 硬红线起点在位，未篡改 | `025_postgres_runtime_compatibility` down=`024_wallet_backfill` 在位 |

**文档漂移登记（供 CW-044 文档收口更正）**：`AGENTS.md` 称"迁移文件名冻结 `025_postgres_runtime_compatibility … 030_user_fair_queue`"，但 df7020c 实际 030 缺号、`user_fair_queue` 为 **041**。该句是内部 P0 版历史描述，客户版 V3 迁移布局已重排；**发布基线以 df7020c 实际迁移图为准**。

## 3. 补丁来源清单（8 条本地分支处置决议）

相对 df7020c 逐分支核实（`git log --oneline df7020c..<branch>`）：

| 分支 | head | 领先 df7020c | 处置决议 | 依据 |
| --- | --- | --- | --- | --- |
| cw007-pg-test-foundation | b4b584e | 2（squash 前原始） | **已并入 df7020c，分支可废弃** | tree 与 df7020c 一致（§1） |
| cw009-security-matrix | b13d735 | 1 | **已 push origin，待 owner squash merge** | `origin/feat/customer-v3-cw009-security-matrix@b13d735` |
| cw010-pg-recovery-baselines | 0d79622 | 3（含旧 96c77b1/b955677） | **堆叠旧 CW-007/009，暂放**；未来 rebase --onto df7020c 后再评估 | 用户 2026-09-09 指令"放着不动" |
| cw02-platform-scope | 898afec | 1 草案 | **已签认，待 cherry-pick 到 df7020c** | owner 2026-09-09 接受全部 6 项 |
| cw03-compat-window | a08c778 | 1 草案 | **已签认，待 cherry-pick** | §4/§5 N/A pre-GA、§1/§2/§3/§6 保留 |
| cw04-deploy-metrics | 34e8b7b | 1 草案 | **已签认，待 cherry-pick** | 冻结设计主线+验收目标基线，数值/灰度 defer GA |
| cw05-data-disposition | 589ad04 | 1 草案 | **呈报待签认** | 框架冻结+内部 P0 数据归档不合入+GA 触发 |
| cw053-db-inventory | 3e67783 | 1 草案 | **呈报待签认** | 静态 DB 语义清单+精确历史例外 |

- **fork 基线与领先/落后披露（2026-09-09 复核修正）**：`git merge-base df7020c <branch>` + `git rev-list --count` 实测——
  - cw02/03/04/05/053 五条草案分支 merge-base=**b211095**（早于 6268bfb/247f263/ce40db5/df7020c 四个 mainline 提交），**ahead=1（文档 tip commit）/ behind=4**。故表中“领先 df7020c=1”仅指各自的 1 个文档 commit，分支本体相对 df7020c **落后 4 个提交**（`git diff df7020c..cw02 --stat`=329 文件 / −114059 行即缺失量）。
  - cw009-security-matrix merge-base=**df7020c**、ahead=1 / behind=0 → 已 rebase 到当前 main，**干净可直接 owner merge**（与草案分支陈旧基线不同）。
  - cw007 merge-base=ce40db5 / ahead=2 / behind=1（其 squash 即 df7020c）；cw010 merge-base=b211095 / ahead=3 / behind=4（堆叠旧 cw007/009，需 rebase --onto df7020c，用户指令暂放）；cw001（本分支）merge-base=df7020c / ahead=2 / behind=0。
- **W0 落地机制（据此更正 §4）**：签认后 **cherry-pick 各草案的 tip 文档 commit** 到 df7020c（cw002=898afec / cw003=a08c778 / cw004=34e8b7b / cw005=589ad04 / cw053=3e67783 各 1 commit；cw001=ff791d0+15f509e 共 2 commit）。每个 tip commit 均单文件纯新增、目标文件在 df7020c 经 `git cat-file -e` 核验为 **ABSENT** → cherry-pick 零冲突。**严禁 merge/rebase 整条草案分支**（会把 behind=4 的陈旧发散带入 df7020c）。
- CW-001 本文档为 W0 第 6 份，前置=无（V3 line 36），是其余 W0 与 W2–W7 的发布基线锚点。

## 4. 备份与回滚点（WIP 可恢复）

| 对象 | 回滚点 | 恢复方式 |
| --- | --- | --- |
| 发布基线 | `df7020c` | `git checkout df7020c` / `reset --hard df7020c` |
| CW-009 rebase 前 | `backup/cw009-prerebase@b955677` | 已建备份分支 |
| CW-010 原始堆叠 | `0d79622`（未动） | 分支保留，未 rebase |
| 各 W0 草案 | 898afec / a08c778 / 34e8b7b / 589ad04 / 3e67783 | 分支保留至 cherry-pick 落地 |
| 本决议文档 | 纯新增 | `git revert` 即回退 |

恢复抽查：df7020c、b955677、0d79622 均可 `git checkout` 找回；受保护原改动（CW-007 缺库硬门、CW-009 安全矩阵）已分别在 df7020c、b13d735 中，未丢失。

**已复用 / 已剔除范围、合并要求与回归先后（DoD line 108）**：

- 已复用：df7020c 已含 CW-007 缺库硬门与 PG 测试隔离成果（无需重建）；V3 清单（bf6aab8 定义）、data-deploy-audit（bffc341 审计）、source-baseline.json 与 v3/baseline.json（分析快照）作为输入复用，不重做全仓摸底。
- 已剔除：DoD line 102"重复做未指定边界的全仓摸底"——本决议复用已有 Git/迁移基线快照，不重新扫描全仓；"已有 Git 与迁移基线生成能力"不重建。
- 合并要求：已签认 W0 草案（CW-002/003/004）+ 本文档 + 待签认的 CW-005/053，签认后 **cherry-pick 各自 tip 文档 commit** 到 df7020c（机制见 §3 更正：草案分支 fork 自 b211095、behind=4，故只 cherry-pick tip commit，**不 merge/rebase 整分支**）。6 份目标文件（CW001/002/003/004/005/053-*.md）在 df7020c 均 ABSENT、各 tip commit 均单文件纯新增 → cherry-pick 已核验零冲突；owner 定 PR 策略（W0 合为 1 个批次 PR 或逐份 PR，受 AGENTS.md“一 PR 一任务”约束需 owner 裁量）后落地。
- 回归先后记录：CW-001 为决策与静态核验层，无代码回归；在其冻结的 df7020c 基线上，后续 W2–W7 代码/测试增量遵 V3 §1 规则 3"缺陷先红后绿、数据库断言真实 PG"，CW-007 已建立的缺库硬门（require_pg_or_explicit_skip）为回归基座。

## 5. pre-GA 执行路线（发布基线之上的路线决议附件）

> 依据 V3 line 5/7/18（57 项按执行时机分类、条件项有实际数据/范围证据才启用）+ 用户语境（pre-GA：无真实用户/数据、桌面与服务器锁步发布）。**非缩小目标**——57 项最终都做，GA 项在 GA 触发条件满足时执行。

### 5.1 三层归属

| 层 | 数量 | 项号 | 处置 |
| --- | --- | --- | --- |
| GA 触发·冻结 | 15 | W5 CW-033~039 + W7 CW-046~052 + CW-014 | 留框架/预案，GA 有真实数据·环境·客户·付费时触发（见 5.5） |
| pre-GA 已收口 | 9 | W0 CW-001~005/053 + W1 CW-007/009/010 | 见 §3 |
| pre-GA 核心开发 | 33 | W2×6 + W3×6 + W4×12 + CW-060 + W6×7 + CW-045 | 见 5.2 |

### 5.2 33 项核心开发：必须 30 / 可延后清理 3

| 批次 | 项号（剩余任务） | 必须/延后 |
| --- | --- | --- |
| W2 客户入口收敛 | 012 迁出共享类型·013 客户根入口/路由恢复·015 移除内部身份回退·016 两钱包入口+充值回归·017 退出/凭据清理·018 本地补丁与云端整合 | 必须 |
| W3 桌面制品唯一化 | 019 客户/管理员独立制品·020 客户配置唯一默认·021 删桌面本地后端·022 原生凭据/设备兼容·023 下载取消/失败·024 安全升级+唯一签名 | 必须 |
| W4 PG 全面覆盖+运行时 | 025 PG 扩全环境·026 退内部认证+fencing·027 后台权限差额·028 迁出共享设置·029 账务扣费/支付·030 Worker PG 调度/恢复·031 云端资产回退·032 可重建后端包·054 PG 批量/查询/异常·055 PG 事务/连接池·056 空/旧 PG 升级矩阵·057 维护/种子 CLI | 必须 |
| W5 | 060 隔离历史 SQLite 工具与兼容测试（= 关入口） | 必须 |
| W6 收口 | 043 独立核销全业务 PG·044 唯一客户 CI/命令/文档·058 内容资产真实 PG·059 账务与全任务真实 PG | 必须 |
| W7 | 045 最终候选全量 PG+制品门禁（= 锚点验收本身） | 必须 |
| 清理批次 | 040 退内部发行/运维入口·041 退内部身份入口·042 裁剪无消费者 SQLite 实现 | **可延后**（物理删除；"关入口"语义已被 015/021/026 覆盖，依 data-deploy-audit §6"先关入口，物理清理另起追加迁移"） |

### 5.3 pre-GA 可发布候选验收锚点（7 条硬标准）

早于 V3 的 GA 四级签收（CW-052），全部满足 = 可对外发内测/预发布候选：

| # | 锚点 | 判据（可核销） | 承载任务 |
| --- | --- | --- | --- |
| 1 | 客户路径唯一 | 桌面包解包无 server/.venv/Python/FFmpeg/SQLite 业务库/start-backend；客户 NSIS 为唯一默认构建 | CW-019/021/024/044 |
| 2 | PG 唯一硬门 | 业务测试全部真实 PG，缺库 fail-closed 不 skip；客户生产 SQLite/缺 URL 启动即失败 | CW-007✅/025/043/058/059 |
| 3 | 内部/SQLite/sidecar 入口 fail-closed | 客户 API 无内部身份回退、桌面不起本地后端、内部认证退出（关入口即可，物理删除延后） | CW-015/021/026 |
| 4 | 桌面唯一化+锁步可装机运行 | identifier/app_data_dir/凭据路径锁；干净 Windows 环境 装→启→登→传→预览→生成→下载→卸载 全通 | CW-020/022/023 |
| 5 | 可重建后端交付包+唯一签名发布 | 空白机可重建后端；唯一签名/升级链；客户 identifier 连续性 | CW-024/032/044 |
| 6 | 全业务 PG 覆盖独立核销 | 内容资产+账务+全任务测试真实 PG 覆盖，独立复核签字 | CW-043/058/059 |
| 7 | 最终候选全量门禁绿 | CW-045 在最终候选跑全量 PG+制品门（= CI Linux 门 + Windows NSIS 门） | CW-045 |

### 5.4 执行批次（1 阶段 1 分支 1 PR，遵 AGENTS.md"同一时间只开一个任务分支"）

```
批次0  W0 收尾   CW-001 本决议签认 + CW-005/053 签认落地 → 冻结发布基线
   ↓（W2 的 012/016 等依赖 CW-001~005/053 全部 W0）
批次1  W2       012→013→015→016→017→018   客户入口收敛（CW-014 冻结）
批次2  W3       019→020→021→022→023→024   桌面制品唯一化
批次3  W4       025→…→032 + 054~057       PG 全面覆盖 + 运行时收敛
批次4  W5+W6    060 + 043/044/058/059     关入口 + 全业务 PG 收口
批次5  W7       045                        最终候选全量门禁 = 锚点验收
清理批次(延后)  040/041/042                物理删除内部/SQLite/sidecar 残留
```

### 5.5 GA 触发 15 项冻结预案

| 项 | 冻结理由（pre-GA 缺什么） | GA 触发条件 | pre-GA 预留 |
| --- | --- | --- | --- |
| CW-033~039（W5 数据） | 无真实客户数据；内部 SQLite 行数/资产量/账务规模未核实（audit §9） | 真实数据盘点 + 处置路线选定（A/B/C） | CW-005 已冻结处置框架；导入器/对账工具保留可用 |
| CW-046~052（W7 现场） | 无真实签名包实机/多实例负载/激活·支付·COS·Provider 链路/真实客户 UAT/数据切换灰度 | 进入 staging→生产、有真实客户与付费授权 | CW-045 先出可发布候选；四级签收流程文档预留 |
| CW-014（游客门禁） | 无游客激活范围证据（V3 line18"有实际数据/范围证据才启用"） | 产品决定开放游客激活范围 | CW-013 客户根入口预留门禁挂载点 |

## 6. 待集成负责人确认的策略点

| # | 策略点 | 建议 | 依据/影响 |
| --- | --- | --- | --- |
| P1 | CW-044 依赖松绑 | pre-GA 仅要求 CW-040/041/042"入口 fail-closed"，物理删除延后为独立清理批次 | data-deploy-audit §6"先关入口，物理清理另起追加迁移"；松绑后 CW-044 可在功能收敛后收口唯一客户 CI，不必等物理删除 |
| P2 | 验收锚点是否含"内测实机跑通" | 建议 §5.3 的 7 条锚点为 pre-GA 完成定义；"内测客户实机跑通一轮"归 GA（CW-046/049） | 决定 pre-GA 与 GA 的边界；pre-GA 无真实客户，实机跑通需 GA 环境 |

## 7. 签认记录

| 角色 | 结论 | 日期 |
| --- | --- | --- |
| 集成负责人（发布基线/补丁来源/迁移图/pre-GA 路线/策略点 P1-P2） | 待签认 | — |

> 本文档为决议草案。所有"待签认/待确认"字段由集成负责人确认后，才可将 CW-001 在任务账本 §18 标记完成；签认前不得以本文档替代 W2–W7 的逐项验收行，也不得据 §5 路线跳过任何 GA 触发项的最终实施（GA 触发条件满足时 15 项仍须逐项执行）。
