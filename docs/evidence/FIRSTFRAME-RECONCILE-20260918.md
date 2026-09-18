# FIRSTFRAME-RECONCILE-20260918 · 首帧待核对任务收尾三件套

## 背景

#144 已把置换首帧改为单张流并合入 main（消除"数量不符"事故类别），本任务收尾遗留的三项运维/鲁棒性缺口：事故归因无任务级日志、管理员无核对工具、确定性供应商失败仍占用"待核对"终态。

## 本次修改清单

| 修改项 | 修改后的行为 | 主要文件 |
| --- | --- | --- |
| 任务级异常日志 | worker 图片任务（first_frame / character_sheet，同步与 PG 共四条 lane）的 except 块留下带表名/任务 ID/尝试次数/异常类型的 ERROR 日志；消息与堆栈均为供应商中性文本，不含密钥、提示词或用户内容 | `server/app/image_tasks.py`（`log_image_task_failure`）、`server/app/generation_worker.py` |
| 管理端核对接口 | 新增 `POST /api/control/first-frame-tasks/{task_id}/reconcile`（AdminWriter 门禁）：事务内校验 SUBMISSION_UNCERTAIN 并解析回执 → 事务外凭回执轮询供应商真实状态 → 事务内围栏改状态+结算+审计。供应商任务在跑/已完成 → 重排队 PENDING 凭回执续轮询（不二次付费）；供应商侧失败/无回执/账户指纹变化 → FAILED 并释放预扣；供应商不可达/不可解读 → 503/409 且状态不动，稍后可重试。重复提交天然幂等（撞状态围栏 409）。非 Apilio 配置直接判"配置已变化" | `server/app/admin_first_frame_routes.py`（新增）、`server/app/image_tasks.py`（prepare/decision/apply 三函数）、`server/app/main.py` |
| 确定性失败归类 | `fail_image_task`：非传输层的 `ImageProviderFailed`（数量不符/响应不可读/拒不给图）与 HTTP 502 `FIRST_FRAME_PROVIDER_RESPONSE_INVALID` 归类为已知失败 → FAILED + retryable=1，用户重新生成即可；`RetryableImageProviderFailed`（超时/429/5xx）保持"结果未知"语义不变 | `server/app/image_tasks.py` |

## 关键设计约束（零改动面）

- 确认（confirm）与 H3 生成对最新候选版本的围栏不动；
- 钱包结算沿用 `finish_source` 原有路径（核对判死按 0 张结算释放预扣，续跑不动预扣）；
- 无数据库迁移、无新依赖；RESUME 后若再次失败，任务按归类规则落 FAILED 或待核对，不会无限循环（每次核对至多多跑一轮）。

## 验证结果

- 新增 PG 集成测试 17 项（归类 3、worker 日志 1、reconcile 核心 7、路由 6），先红后绿；`test_cw030_worker_pg_matrix.py` + `test_admin_first_frame_reconcile.py` 合跑 104 项通过。
- 静态门 `npm run check:static` 全绿（secret / Biome / tsc / tauri / ruff / ruff-format / mypy=161 文件无问题）。
- 分片并行 pytest：四片全绿 841+568+584+649 = **2642 通过 / 1 既有跳过**（分片清单已随新测试文件再生成并随本 PR 提交；独立命名容器 ff-reconcile-pg@5570、分片 5571-5574 物理隔离，避开并行会话的标准 fixture 容器）。

## §14 任务证据

- 任务 / 工作包：FIRSTFRAME-RECONCILE-20260918（生产事故收尾：日志 / 管理端核对 / 失败归类）。
- Owner：ZCode 会话（GLM-5.3-Flash）代 honor.pei，sess_ca8cb3a2；Reviewer：执行者自检 + PR 门禁，独立评审待分配。
- 分支 / main 基线：`fix/firstframe-reconcile-20260918` / `68969a7f1f1cfee6b9007d91e5f5a66fe0d1b26a`（含 #144、#145）。
- worktree：`/Users/honor.pei/Documents/订单项目/.worktrees/FIRSTFRAME-RECONCILE-20260918`；共享 claim 已登记于 Git common directory `codex-task-claims/FIRSTFRAME-RECONCILE-20260918/claim.json`。
- 开工查重：fetch 后 origin/main=68969a7f；开放 PR 仅 #146/#147（material-perf C/D，文件无交集）；#144 已合并（dd2fb186），其 worktree 按合并即删规则清理。
- 文件边界：`server/app/image_tasks.py`、`server/app/generation_worker.py`、`server/app/admin_first_frame_routes.py`（新）、`server/app/main.py`（注册一行）、`server/tests/test_cw030_worker_pg_matrix.py`、`server/tests/test_admin_first_frame_reconcile.py`（新）、`server/tests/pg_test_kit.py`（测试库allowlist一行）、登记表与本证据。无迁移、无新依赖、无真实付费调用、无生产部署。
- 测试资源：独立容器 ff-reconcile-pg@5570；分片 5571-5574（`CI_SHARD_BASE_PORT`），日志目录预建。

## 边界与后续

- 未合并、未部署；合并以 PR 当前 head 的 Secret / Linux / Windows 三门禁为准。
- 管理端 UI 按钮、把待核对任务聚合进现有图像生成记录页的批量操作：后续按需另立任务（当前接口可直接 curl）。
