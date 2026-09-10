# CW-018 — 整合保留业务的本地补丁与云端交互缺口

## 任务信息（§14 模板）

| 字段 | 值 |
| --- | --- |
| 任务/工作包 | CW-018（W2）整合保留业务的本地补丁与云端交互缺口；DoD：按 F01–F12 复验真实客户场景与关联链；**修正 API 仍提示"检查本地服务"的云端错误**；将未接视频链接解析/口播音频上传/分页·刷新·迟到请求逐条与本地候选对照、**只整合确认有效差额**；发布功能继续诚实未接通；每格标当前实现/复验结果/候选整合/剩余缺口，源未接能力不伪装成功，避免一项笼统重做全部前端 |
| Owner / Reviewer | Owner：ZCode 代理（hlong026 会话，2026-09-10）；Reviewer：独立 CodeReview 子代理（结论见 §6，**无 Must-fix / 无 Should-fix**，2 条 Nit：Nit-1 已采纳、Nit-2 登记不改）+ PR review |
| 分支 / 基线 SHA | `feat/customer-v3-cw018-retained-business-cloud-gaps`；基线 `origin/main@e06b13c`（CW-017 PR#9 squash 合并后）；独立 worktree `乡墅爆款短视频复刻-cw018`（按 COORD PR#10 协议：从 main 建独立 worktree + `codex-task-claims/CW-018/claim.json` 原子认领锁 + 尽早 push 分支） |
| 上游规格段落 | V3 清单 §18 CW-018 行（line 479）；V3 剩余任务清单行 326–340（仅做剩余 line 333）；§5 客户业务验收矩阵 F01–F12（line 964–983，CW-018 自动化 + CW-049 真实角色 UAT 的共同最小覆盖） |
| 改动文件 | **3 文件 +31/−5，client 增量，server 零触碰**：`client/src/api.ts`（+2/−2：`generationRequestError`@4232 与 `analysisRequestError`@4265 两处 TypeError 传输失败映射器文案 `请检查本地服务`→`请检查网络后重试`）、`client/src/api.test.ts`（+28/−2：generation 网络失败用例改精确云端文案 + catch 双断言护栏；新增 `startVideoAnalysis` TypeError 分支 CW-018 专项用例）、`client/src/GenerationComposer.test.tsx`（+1/−1：mock reject 字符串同步为新文案，属一致性维护，断言用 `/网络连接失败/` 正则不变） |
| 重复开发核查（用户红线） | **六层核查全空 → CW-018 独占**：DIM1 无 cw018 worktree（11 worktree）；DIM2 本地+远端无 cw018 分支；DIM3 全 ref `--grep=CW-018` 零命中；认领登记（COORD PR#10）CW-018 未认领；`codex-task-claims/CW-018` 目录不存在（本次原子创建）；无任何状态 CW-018 PR（仅 PR#10 COORD 草案）。DIM4 其余 10 worktree 对 CW-018 目标（studio/整目录+5页面）**零未提交 WIP**；3 个 studio 未合并分支（c5-publish/character-ip-oral/material-library）经甄别为**独立陈旧特性分支**（49–84 落后 main、无 PR、末次提交 2026-09-07），非 CW-018 同步开发（详见 §5） |
| 失败测试或回归锁定 | **RED→GREEN 证据（承接 CW-008 先锁失败用例）**：修复前 `vitest run src/api.test.ts` = **2 failed \| 97 passed（99）**——① generation `createScriptVersion` TypeError 分支 `expected …请检查网络后重试 but got …请检查本地服务`（api.ts:4232）；② 新增 analysis `startVideoAnalysis` TypeError 用例 `expected 启动视频拆解失败：…请检查网络后重试 but got …请检查本地服务`（api.ts:4265）。两失败精确对应 line 333「API 仍提示检查本地服务的云端错误」缺口。修复后 **99 passed GREEN** |
| 实现结果 | §2 交付明细；§3 验证结果；§4 F01–F12 复验矩阵；§5 候选对照结论 |
| 验证命令与通过数 | client 门（Node 24.14.1）：`biome check` 0 error exit 0；`tsc -b` exit 0；`vitest run --no-file-parallelism`（串行）79 文件 **1288 passed**（基线 1287 + 本任务净 +1 = 新增 analysis TypeError 用例）；`verify_no_secrets.sh` exit 0；server 零触碰。详见 §3 |
| 证据层级 | AUTOMATED_VERIFIED（client 门全绿 + RED→GREEN 两锁精确对应云端错误缺口 + F01–F12 逐格映射到 1288 现有自动化用例真断言 + 候选分支 merge-base 对照实证已超越/属独立任务 + 发布诚实未接通经代码核实；纯前端契约/文案增量，无 staging/真实链路依赖；真实角色 UAT 归 CW-049、真机凭据 vault 归 CW-022） |
| 安全与可观测性 | 无密钥/凭据/token 进代码、测试、日志、Web Storage 或前端制品；secrets 扫描 exit 0；**消除客户云端传输失败时"请检查本地服务"的误导**（客户版无本地服务：CW-015 fail-closed base、CW-021 删本地后端），改为与服务端云端措辞一致的"请检查网络后重试"（对齐 api.ts:5026 `customerTransportError` 及服务端 `ANALYSIS_PROVIDER_UNREACHABLE`="…请检查网络后重试。"） |
| 迁移与回滚 | 纯前端 client 文案/测试增量，`server/` 零触碰、无数据库/迁移改动；回滚 = revert 本分支（恢复 generation/analysis 网络失败文案为"请检查本地服务"，即回到 CW-018 前状态） |
| 外部授权记录 | 无（不涉及真实 ZPay/付费 Provider/生产 COS/发码/灰度/公网发布；网络失败用例全程 mock fetch TypeError，不发真实请求） |
| 未测试项 | server 全量 pytest、`npm run check:tauri`（cargo）、`npm run build`、`npm audit`、客户浏览器 E2E（Playwright）—— 均**只在 CI 三门禁执行**；本任务 server 零触碰，故 server 回归交 CI（同 CW-013/015/016/017 模式）。真实角色逐模块 UAT 归 CW-049、真机原生凭据 vault 归 CW-022 |
| Lore 提交 SHA | 本 PR squash 后回填 |

## 2. 交付明细（对照 CW-018「仅做剩余」line 333）

| 规格要求（V3 line 333） | 交付 |
| --- | --- |
| 修正 API 仍提示检查本地服务的云端错误 | `api.ts` `generationRequestError`@4232（视频生成 F03/F04/F06）与 `analysisRequestError`@4265（视频拆解 F03/F07）两处 TypeError（fetch 网络失败）分支文案 `请检查本地服务`→`请检查网络后重试`，保留 `网络连接失败` 前缀（兼容 GenerationComposer.test.tsx:1092、TaskRecordsPanel.test.tsx:900/923 的 `/网络连接失败/` 正则）。**范围界定**：其余"本地服务"出现均非客户路径，故意不改——`App.tsx:797/801`（CW-013 已从客户路由收敛、无生产 import，仅 3 测试引用）、`api.ts:702 getHealth`/`api.ts:1208 getCurrentUser`（仅被孤立 App.tsx:214/:55 调用，客户不调 /api/auth/me）、`SettingsPanel.tsx:135`（admin，CW-027）。客户路径（studio/+customer/+5 页面）grep `本地服务\|本地后端\|检查本地` 现为**空** |
| 按 F01–F12 复验真实客户场景与关联链 | §4 矩阵：F01–F12 逐格映射到 79 文件 / 1288 现有自动化用例（customer/17 + studio/13 + admin/20 + 顶层组件 21 + api/契约），全量串行 **1288 passed** 为复验绿基线；验收执行≠重新开发，已实现路径只复验 |
| 逐条与本地候选对照，只整合确认有效差额 | §5：3 候选分支经 merge-base 对照——c5-publish（发布=CW-002/C5 范围，CW-018 保持发布诚实未接通）、character-ip-oral（净删除 +29/−37、落后 84，main 已「收编人物库收口线」超越）、material-library（+701/−158、落后 83，需 rebase+重验=独立整合任务）。**无一可作为「确认有效差额」安全整合入 CW-018**（强整合陈旧分支会回退 main），符合 line 338「候选缺口明确进入独立任务」+ line 983「不以候选分支存在代替整合和验收」 |
| 发布功能继续诚实未接通 | **代码核实已满足**（非本任务新增）：`MainPages.tsx:706`「C5 发布能力暂缓：没有真实发布数据源，保持 "—" 不伪造」、`:1604`「进入发布管理仅创建发布草稿，不会自动发布」、`:1778-1779`「平台账号授权接口尚未接入，暂不可添加账号」；`StudioWorkspace.tsx:876/1394/1409`「该模式需要完成供应商核对后开放，敬请期待」、`:1907`「此独立创作接口尚未接入」。未接通能力不伪装成功 |

## 3. 验证结果（本地，Node 24.14.1 对齐 CI；client 门不碰 PG）

| 验证 | 命令/场景 | 结果 |
| --- | --- | --- |
| RED（修复前锁失败用例） | `vitest run src/api.test.ts`（2 云端文案锁 + 未改 api.ts） | **2 failed \| 97 passed（99）**：generation `createScriptVersion` 与 analysis `startVideoAnalysis` TypeError 分支均 `got …请检查本地服务`≠`…请检查网络后重试` |
| GREEN（api.ts 修复后） | `vitest run src/api.test.ts src/GenerationComposer.test.tsx src/TaskRecordsPanel.test.tsx` | **169 passed（99+28+42）**：两 RED 转绿 + 依赖 `/网络连接失败/` 正则的下游断言无回归 |
| 类型门 | `tsc -b` | **exit 0**（新增测试 `as Error` 转换、catch 双断言均类型正确） |
| Lint/格式门 | `biome check`（3 改动文件） | **0 error，exit 0**（"No fixes applied"） |
| 单测门（全量·串行） | `vitest run --no-file-parallelism` | **79 文件 / 1288 passed**（基线 e06b13c 为 1287；本任务净 +1 = 新增 analysis TypeError 用例；零回归），耗时 124s |
| secrets 门 | `bash scripts/verify_no_secrets.sh` | **exit 0**，No hardcoded secrets detected in runtime contract surface |
| server 零触碰 | `git diff --stat origin/main -- server/` | **空** → 生产后端零改动，server pytest/ruff/mypy/tauri/build 交 CI |

**并行 flake 说明（沿用 CW-015/016/017 结论）**：以串行 `--no-file-parallelism` 全绿 1288/1288 为确定性证据。

## 4. F01–F12 客户业务验收矩阵（V3 §5 line 964–983 → 当前实现/复验结果/候选整合/剩余缺口）

> 每格证据 = 现有自动化用例（1288 passed 全量串行）；真实角色逐模块 UAT 归 CW-049，本表为 CW-018 自动化栏取证。

| ID | 业务 | 覆盖自动化证据（测试文件） | 当前实现 | 复验 | 候选整合 | 剩余缺口 |
| --- | --- | --- | --- | --- | --- | --- |
| F01 | 激活/设备/会话/资料 | customer/{ActivationPage,useCustomerSession,CustomerPairingFlow,DeviceManagementPage,DevicePairingPage,HeartbeatStatus,LeaseCountdown,LoginPage,PairingApprovalCard,SessionConflictDialog,SessionDisplacedNotice,customer-state,CustomerProfilePanel}.test + RootApp.test + api/customerApi.test | 激活→工作台→改资料→重启恢复→配对→切换→退出全接通（CW-001/003/013/015/017） | PASS | — | 无（真机凭据 vault 归 CW-022） |
| F02 | 工作台和项目 | studio/{StudioWorkspace,MainPages,state,live}.test + ProjectsPage.test + WorkspaceTabs.test + useWorkspaceReadiness.test + customer/CustomerWorkspace.test | 首页真实数据→项目列表/查找→详情→跨刷新恢复；迟到请求隔离广泛（studio 非测试 75 处 abort/operation/requestId 标记） | PASS | 无（候选落后） | **项目列表后端分页**：live.ts:341 `(await listProjects()).slice(0,24)` 前端冻结容量截断，`listProjects()` 无分页参数、后端无分页项目端点 → 真后端分页需 server 改动=独立任务（CW-018 client 零触碰 server）。人物/生成/口播列表已用后端 cursor 分页（listSimpleCharacterLibraryPage/listGenerationBatches/listOralTasksPage + loadMore*） |
| F03 | 项目型视频复刻 | ProjectDetailFlow.test + studio/CreationPages.test + {SourceFrameSelection,FirstFrameSelection,CharacterReferenceSelection,ScriptEditor,PromptMarkdown,GenerationComposer,GenerationLauncher}.test + api.test（analysis/generation）+ studio/cloudDraftQueue.test | 上传→拆解/分镜→源帧→人物/参考→首帧→Prompt 编译/锁定→批次→结果/下载全接通 | PASS | — | 无；**CW-018 修复** generation/analysis 网络失败云端文案（RED→GREEN） |
| F04 | 独立视频创作 | AnalysisWorkspace.test + studio/CreationPages.test + GenerationComposer/GenerationLauncher/VideoResultStage.test | 能力参数→文生/图生/参考→报价→提交→任务→结果接通；未接模式诚实提示（StudioWorkspace.tsx:1907「此独立创作接口尚未接入」） | PASS | — | 部分独立创作模式待供应商核对后开放（诚实标注「敬请期待」，非伪装） |
| F05 | 人物/场景/首帧 | CharacterLibrary.test + CharacterSelection.test + studio/PeoplePages.test + FirstFrameSelection/CharacterReferenceSelection.test | 人物建档/选择→场景/图片→首帧确认→交接；后端 cursor 分页 | PASS | character-ip-oral 候选落后 84、main 已「收编人物库收口线」→已超越，不整合 | 无 |
| F06 | 口播与音频 | studio/CreationPages.test（音频上传）+ api.test（oral tasks）+ studio/live.test（loadOralTasks/listOralTasksPage） | 选择人物/音色→文本或音频输入→提交→任务→下载；**口播音频上传已接通带迟到请求隔离**（CreationPages.tsx:2983-3075 AbortController + `audioUploadOperationRef` `if(operation!==current)return` + 取消「口播音频上传已取消」） | PASS | character-ip-oral（口播）候选净删除 +29/−37、落后 84→main 已超越，强整合会回退，不整合 | 无（口播单价计费字段属 server/generated，非 CW-018 client） |
| F07 | 文案提取与改写 | studio/scriptRewrite.test + studio/ContentPages.test + ScriptEditor.test | 上传/导入来源→提取→保存文案→改写→交接接通 | PASS | — | 无 |
| F08 | 素材库 | studio/ContentPages.test（素材）+ api.test（assets）+ videoDownload.test | 上传→确认→分组/筛选→预览→选作输入→下载/隐藏接通 | PASS | material-library 候选 +701/−158、落后 83→需 rebase+重验=独立整合任务，非 CW-018 强合并 | material-library 隔离候选整合登记为独立任务 |
| F09 | 爆款与收藏 | studio/viralImport.test + studio/viralState.test + studio/ContentPages.test | 列表/筛选→详情→预览→收藏/取消→导入复刻或提取文案；viralImport.ts 幂等键管理（sessionStorage+内存兜底+轮询超时+重复点击安全） | PASS | main 已「收编 viral 收敛线」→已超越 | 无（无独立「外部链接解析」未接功能伪装；viralImport 是幂等键管理，导入 API 在 live.ts/ContentPages） |
| F10 | 任务和结果 | TaskRecordsPanel.test + VideoResultStage.test + studio/live.test（tasks）+ api.test（batches）+ videoDownload.test | 创建→排队→运行→成功/失败→结果→下载/下一步；后端 cursor 分页（listGenerationBatches limit 20）；TaskRecordsPanel 网络错误处理 | PASS | — | 无（关桌面继续云任务/新设备读同任务属 server+E2E，CI/CW-049） |
| F11 | 钱包与充值 | customer/{CustomerWalletPanel,CustomerRechargeDialog}.test + studio/LiveWorkspacePanel.test（CW-016 两入口）+ WalletPanel.test（内部兜底）+ internalBillingApi.test | 两入口（使用记录 tab + 查看使用记录 button）均客户组件；充值走 `POST /api/customer/recharge-orders`；内部费率对客户隐藏 | PASS（CW-016 AUTOMATED_VERIFIED） | — | 无 |
| F12 | 管理和经营看板 | admin/*.test（20 文件：Accounts/ActivationCodes/Adjustments/AuditEvents/CostDetails/Customers*/Devices/GenerationRecords/Orders/Overview/Profit/QueueMode/Rates/Sessions/ViralRuntime/ui）+ AdminApp.test + api.admin.test | 管理登录→客户/码/设备/费率/配置→订单/成本/利润/审计；客户看板仅看本人 | PASS（admin 全绿） | — | 权限差额收口归 CW-027（复用管理后台并收口权限差额）；customer 不能管理写由 CW-013/026 结构保证 |

**发布管理（跨 F09/F12）**：诚实未接通（§2 已核）；正式发布/平台联动归 CW-002/C5，若纳入范围须追加专用验收矩阵（V3 line 983），CW-018 不计作已完工客户功能。

## 5. 本地候选分支对照结论（line 333「逐条与本地候选对照，只整合确认有效差额」）

| 候选分支 | 独有 studio delta（vs merge-base） | ahead/behind main | 性质 | CW-018 处置 |
| --- | --- | --- | --- | --- |
| `feat/c5-publish-module` | +1202/−145（ContentPages.tsx +482、MainPages.tsx +319、live.ts +181、types.ts +46） | ahead 6 / behind 49 | **发布功能**（C5） | 发布=CW-002/C5 范围；CW-018 DoD 明确「发布继续诚实未接通」→**不整合**（整合会违反 DoD），登记独立任务 |
| `codex/character-ip-oral-completion` | **+29/−37（净删除）**（live.ts/MainPages.tsx/types.ts 为主） | ahead 4 / behind 84 | 口播/人物同步（tip=同步 generated/api.ts 口播单价字段） | main 已 `26044a4`「收编人物库收口线」超越；整合陈旧净删除会**回退 main**→不整合，登记 dormant |
| `fix/material-library-isolation-and-completion` | +701/−158（ContentPages.tsx +262、ContentPages.test +293、CreationPages.tsx +72、state.ts） | ahead 9 / behind 83 | 素材库用户隔离 | 落后 83，需 rebase-onto-main + 重验 = **独立整合任务**（line 338），非 CW-018 强合并；隔离候选登记为独立任务 |

**关键实证**：main 自候选分叉（2026-09-06/07）后有 **18 个 studio/ 提交**，含 `247f263`「收编 fp 前端修复全链——**16 分支超集**」、`ce40db5`「收编 viral 收敛线」、`26044a4`「收编人物库收口线」、`6268bfb`「收编前端收尾线」——main 已是吸收前端候选工作的**超集**。3 候选均 dormant（末次提交 2026-09-07、无 PR）。结论：**无「确认有效差额」可安全整合入 CW-018**；每个候选的真实整合需各自 rebase+重验，属独立任务，不以架构收敛掩盖（line 338），不以候选存在代替整合验收（line 983）。

## 6. 独立复核

独立 CodeReview 子代理直接读代码核实 5 维（正确性/完整性/测试充分性/回归风险/安全），**结论「无 Must-fix / 无 Should-fix」**，AUTOMATED_VERIFIED 层级达成。逐项确认：两处映射器文案准确且保留 `网络连接失败` 前缀（下游 `/网络连接失败/` 正则全匹配）；与服务端 `ANALYSIS_PROVIDER_UNREACHABLE`「…请检查网络后重试。」及 api.ts:5026 `customerTransportError` 云端措辞对齐；客户路径 grep「本地服务/本地后端/检查本地」0 命中，范围界定（App/getHealth/getCurrentUser/SettingsPanel 不改）经代码核实成立（main.tsx 只 import RootApp、App 仅 3 测试引用、getHealth/getCurrentUser 仅 App:214/:55 调用）；`generationRequestError`/`analysisRequestError` 全库仅 2 处调用（api.ts:2732/4202）影响面收敛；GenerationComposer mock 改动安全（`vi.mocked` 桩化不经真实 mapper）；3 文件 diff 无密钥。评审另佐证 `FirstFrameSelection.test.tsx:383` 已有 `queryByText(/本地服务未关闭/)).toBeNull()` 负向护栏（既有 CW-018 同类护栏）。

Nit 处置：
- **Nit-1（已采纳）**：generation 侧缺对称 `not.toMatch(/本地服务/)` 护栏 → 将 api.test.ts generation 网络失败用例改为 catch 手法 + 双断言（`toBe(精确云端文案)` + `not.toMatch(/本地服务/)`），与 analysis 侧对称，硬化 RED 锁（防未来宽松正则化静默失效）；不增加 fetch 调用、不耗尽 mock。复验 api.test.ts 99 passed。
- **Nit-2（登记不改）**：api.ts:5026 `customerTransportError` 尾句为「请检查网络」（无「后重试」），与本任务两处「请检查网络后重试」细微差。评审明确本任务不动（超 CW-018 DoD），且新文案与服务端严格对齐属**更优**；若后续统一 copy pass 可全库对齐。

## 7. 签认记录

- Owner：ZCode 代理（hlong026 会话）——按 V3 §14 模板填写本证据，client 门全绿 1288 passed，server 零触碰，重复开发六层核查 CW-018 独占。
- Reviewer：独立 CodeReview 子代理——无 Must/Should-fix，Nit-1 已采纳、Nit-2 登记。
- 认领生命周期（COORD PR#10）：CLAIMED→ACTIVE（本证据）→REVIEW（PR 提交后回填 PR URL/head SHA）→MERGED（squash 后回填 merge SHA）→CLEANED。
- 待办：PR squash 合并入 main 后回填 §18 账本 CW-018 行 Lore SHA，并释放本机认领锁。
