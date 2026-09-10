# COORD-SCHEDULE 文档维护证据

## 范围与来源

2026-09-10用户要求建立开发顺序、前置与并行清单，开工查重，每任务独立worktree，完成后提交远程，合并核验后清理；追加所有新分支从main创建。

仅维护8份协作文档：AGENTS、交接提示词、开发计划入口、任务账本入口、文件映射，以及新建排班清单、认领登记和本证据。不改变业务完成状态、代码、数据库或CI，不新增CW编号。

正式依赖来源：outputs/customer-cloud-convergence-analysis-2026-09-08/v3/客户版收敛剩余任务清单-V3.csv（57项）。pre-GA范围来源为CW-001签认，游客N/A来源为CW-002签认。实况来自fetch、本地worktree/状态和远程PR；用户已说明在制的任务缺提交仍保护占用。

## 分支与隔离

- 基线：d8f3352fbad938f23b5ed2990ef3be033a24bb4c。
- 维护ID：COORD-SCHEDULE；分支：docs/customer-v3-schedule-worktree-policy。
- worktree：E:/众墅之家爆款短视频创作/.worktrees/COORD-SCHEDULE。
- 创建命令：git worktree add -b docs/customer-v3-schedule-worktree-policy E:/众墅之家爆款短视频创作/.worktrees/COORD-SCHEDULE origin/main。
- Owner：Codex / 01a08add-2977-7b60-a307-af86f90445dd；本机共享claim已创建。
- 原CW-055 WIP未搬移、切分支、暂存或提交；未接管017/019/031/033/055/056及CI PR #8。

## 本地校验

2026-09-10在本任务worktree执行Python文档核对脚本、Git检查及仓库秘密扫描，结果如下；这些是文档校验，不是业务测试通过数。

- [x] 8文件范围符合登记；git diff --check通过，未修改业务或CI文件。
- [x] 25项候选无重复，8个批次一致；25项正式前置与原CSV逐项、按序相同。
- [x] 另17项数据/清理/实机任务前置及原执行条件与CSV一致，共42项完整依赖核对；分组覆盖57项且无遗漏/重复。
- [x] 按签认的pre-GA适用范围处理044/045后，正式依赖加024/028/032汇合与资源避让边无环，25项均汇入045。
- [x] 本次新增的20个相对链接全部存在；AGENTS/交接/排班入口均明确origin/main来源，旧“从未合并前序分支创建”许可已移除。
- [x] git merge-base HEAD origin/main与创建基线一致；本任务创建时未带其他任务提交。
- [x] C:/Program Files/Git/bin/bash.exe scripts/verify_no_secrets.sh退出0，秘密扫描通过。

文档核对时PowerShell默认编码导致第一次Python读取Git文件列表失败，显式UTF-8后完整重跑通过；未将失败运行计为通过。

## 远程提交与验收边界

本地检查后推送分支并创建Draft PR。提交后的PR URL、head SHA和检查以GitHub及共享claim记录为准，不预写未来commit/merge SHA。

本次不跑本地业务全量pytest，不宣称业务AUTOMATED_VERIFIED；当前main所需CI三门禁仍由PR执行。取得实际成功结果前，CI、独立评审与合并均待完成。PR未合并时保留worktree。

回退通过新的main来源分支和PR撤回本次文档变化，不回滚其他任务代码。无生产变更、数据迁移、发码或外部付费调用。
