# FIRSTFRAME-SINGLE-SHOT-20260917 · 置换首帧改为每次生成一张

## 背景与根因（生产事故驱动）

2026-09-17 生产客户端首帧置换报"任务执行结果需要核对，已停止自动重试，请联系管理员。"根因链已用供应商侧任务 JSON 铁证锁定：

- worker 以 n=3 向图像网关发起一次异步生成；网关受理并按 3 张计费（0.180 = 3 × 单张 0.06），40 秒后返回 SUCCESS，但 `data` 数组只含 1 张图。
- 服务端响应解析对数量做严格校验（`len(data) != output_count` 即失败），在下载已生成图片之前抛出供应商异常；因发生在付费提交之后且无归档检查点，任务经两轮自动重排（重轮询同一供应商任务，同样 1≠3）后落入 `SUBMISSION_UNCERTAIN` 终态。
- 该类任务重置重跑无效（重跑仍 1≠3）；同参重提被"已有图像任务等待供应商结果核对"409 拦截，用户被卡死，只能管理员手工处置。

## 产品决策（用户拍板）

置换首帧改为**每次生成 1 张，不满意由用户手动再次生成**（用户触发的重新生成 = 新一次计费，维持"人工挑选即质检、质检不触发付费重生成"的现行契约）。n=1 让"数量不符"这一故障类别整体消失：单张请求要么恰好交付 1 张、要么干净失败（FAILED，可直接重试）。

## 本次修改清单

| 修改项 | 修改后的行为 | 主要文件 |
| --- | --- | --- |
| 候选池携带式合并 | 每个任务仍各自发布新候选版本，但同输入绑定（源画面选择/人物版本/参考图/模型/画幅/场景设置/提示词/外观指纹一致）时，新版本携带上一池全部候选并追加新图（上限 6 张，保留最新）。输入绑定变化则从空池开始，杜绝旧输入图片混入 | `server/app/first_frames.py`（`_first_frame_pool_binding` + `complete_first_frame_generation` 合并段） |
| 客户端单张语义 | 候选数量固定为 1；按钮"生成1张首帧/再生成1张"；说明改为"每次生成1张，不满意可再次生成"；计费文案改按次表述 | `client/src/FirstFrameSelection.tsx` |
| 预选最新候选 | 生成完成后自动预选最新（最后）一张候选，确认仍为显式单击 | `client/src/FirstFrameSelection.tsx` |

**零改动面（关键设计约束）**：`confirm_first_frame` 的"仅最新候选版本内可选"校验、H3 生成对 `first_frame_candidates_version_id` 必须等于最新候选版本的围栏、钱包按任务实际张数的计费结算，全部不动——携带式合并保证最新版本始终包含本输入绑定下所有仍可选的图。

## 验证结果

- 服务端：新增 2 项 PG 集成测试（同绑定累积 + 池上限 6 保留最新；绑定变化不混池），先红后绿；`test_cw030_worker_pg_matrix.py` 全量 87 项通过。
- 客户端：改写 FirstFrameSelection 相关断言（单张按钮/文案/quantity/预选最新），全量 107 文件 / 1728 项通过。
- 静态门：`npm run check:static` 全绿（secret 扫描 / Biome / tsc / tauri / ruff / ruff-format / mypy）。
- 分片并行 pytest：4 片全绿——624 + 833 + 628 + 532 = **2617 通过 / 1 既有跳过**（本机独立 fixture 端口 5570、分片端口 5571-5574，与他任务物理隔离；分片容器已自动清理）。

## §14 任务证据

- 任务 / 工作包：FIRSTFRAME-SINGLE-SHOT-20260917（生产事故修复 + 用户指定的产品行为变更）。
- Owner：ZCode 会话（GLM-5.3-Flash）代 honor.pei，sess_ca8cb3a2；Reviewer：执行者自检 + PR 门禁，独立评审待分配。
- 分支 / main 基线：`fix/firstframe-single-shot-20260917` / `07de759ed5b855e751d8785abe4c68392c7621d8`（含 #143）。
- worktree：`/Users/honor.pei/Documents/订单项目/.worktrees/FIRSTFRAME-SINGLE-SHOT-20260917`；共享 claim 已登记于 Git common directory `codex-task-claims/FIRSTFRAME-SINGLE-SHOT-20260917/claim.json`。
- 开工查重：`git fetch origin --prune` 后 origin/main=07de759e；开放 PR 为空、无同题分支/认领/worktree；REPLICA-FINAL-PROMPT（首帧三图人工选择）已作为 #130 合入，本任务在其之上改变产品形态。
- 文件边界：`server/app/first_frames.py`、`server/tests/test_cw030_worker_pg_matrix.py`、`client/src/FirstFrameSelection.tsx`、`client/src/FirstFrameSelection.test.tsx`、`client/src/ProjectDetailFlow.test.tsx`、登记表回填与本证据。无迁移、无新依赖、无真实付费调用、无生产部署。
- 测试资源：独立 PG fixture 5570；分片 5571-5574（`CI_SHARD_BASE_PORT`），日志目录预建。

## 边界与后续

- 未合并、未部署；合并以 PR 当前 head 的 Secret / Linux / Windows 三门禁为准。
- 生产现存 SUBMISSION_UNCERTAIN 任务的处置 runbook、worker 任务级异常日志、管理端首帧 reconcile 端点：另立任务，不混入本 PR。
- 网关"n=3 只回 1 张"的多扣费用申诉材料已在会话外整理，由用户向网关发起。
