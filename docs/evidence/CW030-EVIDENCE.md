# CW-030 证据 — 收敛各类 Worker 的 PG 调度与恢复差额

> 状态：`AUTOMATED_VERIFIED`（本机 Windows 原生 + Docker Linux 容器（python:3.12-slim + PG 16.15 vs-pg-cw028，独立网络 vs-cw028-net，与 CI Linux 质量门同环境）执行）。
> 分支 `feat/customer-v3-cw030-worker-pg-convergence`，基线 `origin/main@8ab85c7`（CW-057 #19；前置 CW-010、CW-002、CW-025、CW-029 #24、CW-054 #14、CW-055 #13 均已入 main）。
> 按 CW-002 签认范围：本轮不新增公平能力；跨口播完整轮转维持 CW-002 §6 决议（不实现、按现有限制验收），A=1000/B=100/C=10 生产负载压测归 CW-047。

## 1. 任务与范围

- 任务/工作包：CW-030 / W4 代码与测试增量（Worker 负责人）。
- 上游规格：V3 收敛清单 §CW-030；任务账本 §18；排班清单 §2.2 批次5、§3—§7；CW-002-SCOPE-DECISIONS §6/§7；AGENTS.md 标准工作流。
- 查重（2026-09-11 fetch 后）：无 cw030 本地/远程分支、无 PR/Draft、认领登记无 CW-030 行；同仓原子认领目录 + 独立 worktree 新建成功。与并行在制的 CW-028（PR #28）文件边界不相交。
- 差额一（正式可达 SQLite Worker 路径）：`generation_worker.py` 仍保留 `run_sqlite_worker_round`/`run_forever` SQLite 轮询入口（CW-025 后不可达但代码在），SQLite 版 `--db-path` 已不在 argparse。
- 差额二（逐类 PG 验证缺口，全仓 grep+测试矩阵核查）：H3 与口播已有全场景 PG 覆盖（test_worker_crash_recovery/test_customer_queue_fairness/test_oral_domain）；独立任务无专属调度/恢复用例；首帧/联系表（image_tasks 状态机）无并发同抢与真 PG 用例；人物图全套仅 SQLite 且无 UNCERTAIN 语义登记；源帧无 PG 用例；文案改写/ASR 全套仅 SQLite，ASR 无 Provider 超时与 UNCERTAIN 用例。
- 剔除（按规格）：跨口播完整轮转由 CW-002 决策（本轮不新增）；生产负载归 CW-047；历史 SQLite 业务测试套件不整体重写（CW-059 账务/任务全量 PG 覆盖承接），仅移除/移植直接引用被删入口的用例。

## 2. 生产代码改动（两处，均在任务文件清单内）

1. **移除 SQLite Worker 入口**（generation_worker.py）：删除 `run_sqlite_worker_round`、`run_forever` 及 `from app.db import connect_database`/`from pathlib import Path` 孤儿导入；`main()` 在 PG 模式后保留防御性 RuntimeError（resolve_database_config 回退分支），注释更新为「CW-030 已移除」。`run_worker_once`（SQLite 业务核心）按 CW-042 分工保留（测试可达、生产不可达）。
2. **mark_task_submission_uncertain 迟到标记守卫**（generation.py）：原实现对任意状态的任务都会转为 UNCERTAIN 并无条件释放用户 slot——同一任务的迟到重复信号会把**替代任务正在使用的 slot** 重复释放（每用户 running≤1 被击穿为 2）。现 UPDATE 增加 `WHERE status IN ('SUBMITTING','RUNNING')` + `RETURNING batch_id`，仅当真实发生在飞态转换时才释放 slot（mark 侧补齐 P1-5 reconcile 已有的同型守卫）。crash_recovery 全套回归验证 live/sweep 路径行为不变。

## 3. 逐类 PG 矩阵（新增 tests/test_cw030_worker_pg_matrix.py，29 用例全绿）

专用库 `cw030_worker_matrix_test`（pg_test_kit allowlist 已登记），所有用例以生产 Worker 同款领取/完成/失败函数在 `pg_transaction` 围栏内驱动，迁移链升至 head：

| 类别 | 覆盖场景（用例） |
| --- | --- |
| 独立任务（generation 机制，creation_kind=independent） | 2 Worker 同抢互斥+slot=1；过期租约→UNCERTAIN+slot 释放且不盲重提；**迟到重复 uncertainty 不再重复释放替代任务 slot（守卫回归）**；Worker 结算精确一次（预置 RESERVE→SETTLE，账本=[RESERVE,SETTLE]、reserved 回零）；crash 后 claim 持久 SUBMITTING→重启不盲重提 |
| 首帧（image_tasks 状态机） | 同抢互斥；attempt≥3 过期→UNCERTAIN(IMAGE_TASK_LEASE_EXPIRED)；可恢复 checkpoint 过期→恢复重领（attempt 1→2 换主）；**陈旧租约 fail 不覆盖已恢复状态**；提交围栏：submission_started=True→UNCERTAIN / False→FAILED retryable |
| 联系表（character_sheet_tasks） | 同抢互斥；过期→UNCERTAIN(IMAGE_TASK_LEASE_EXPIRED) |
| 人物图（character_generation_tasks） | SKIP LOCKED 同抢互斥；剩余 attempts 过期回收换主；attempts 耗尽→FAILED(CHARACTER_LEASE_EXPIRED) 闭环 |
| 源帧（source_frame_tasks） | 同抢互斥；过期→FAILED(SOURCE_FRAME_TASK_RECOVERY_REQUIRED) 仅人工恢复；**质检配置缺失降级轮询（run_pg_worker_round）真 PG 出片**（移植自被删 SQLite 入口的同名行为） |
| 文案改写（script_rewrite_tasks） | 领取互斥；过期提交→UNCERTAIN 且不重调 Provider；504 超时→UNCERTAIN 不自动重试；**陈旧租约 complete 抛 lease lost、迟到结果不覆盖**；Worker 真 PG 结算（仅 _request_deepseek 造假，Settings 途经真实解析接缝） |
| ASR（script_from_audio_tasks） | 领取互斥；提交前过期→回 PENDING 安全重领（attempt 0→1）；提交后在飞过期→UNCERTAIN(SCRIPT_FROM_AUDIO_SUBMISSION_UNCERTAIN)；Provider 失败终结不盲重提；audio_object_key 回执跨重试存活 |
| 混合队列/两设备 | H3+独立混合 3 用户在 `_FAIR_QUEUE_MAX_ROUNDS=8` 轮转界内全部获服务、每用户 slot 归零；同用户第二设备提交不得把 running slot 从 1 变 2 |

## 4. 已按 CW-002 登记的现状限制（不冒充、不扩展）

- **公平队列覆盖面**：H3/独立视频与口播（oral_worker.py:178,306,940 复用 user_queue_cursors 轮转与 running≤1）；**图片（首帧/联系表/人物图/源帧）、文案改写、ASR 无公平队列机制**——按 CW-002 §7 本轮不扩展，矩阵按各类真实机制验收，未以 H3 覆盖冒充。
- **跨口播完整轮转**：未实现（CW-002 §6 决议）；口播侧共享并发槽语义由 test_oral_domain 既有用例承载，本任务不新增能力。
- **SUBMISSION_UNCERTAIN 语义边界**：人物图与源帧机制无该状态（人物图以 attempts 耗尽 fail-closed 闭环；源帧以 SOURCE_FRAME_TASK_RECOVERY_REQUIRED 人工恢复闭环），ASR 仅提交后在飞窗口存在（SCRIPT_FROM_AUDIO_SUBMISSION_UNCERTAIN）——矩阵按各机制真实语义断言。
- **口播 Provider 超时**：既有覆盖以 HiflyError 传输中断形态（@1049/@1586/@2230），无独立 timeout 类型用例——维持既有口径登记。
- **混合队列等待阈值**：CW-004 冻结表为「建议基线」（目标机定标前无数值 SLA），矩阵以轮转界（≤8 轮）+slot 归零断言推进性，数值阈值定标归 CW-045/047。

## 5. 验证命令与通过数

| 验证 | 环境 | 结果 |
| --- | --- | --- |
| `pytest tests/test_cw030_worker_pg_matrix.py` | Docker Linux + PG16.15 | **29 passed / 0 fail / 0 skip** |
| `pytest tests/test_worker_crash_recovery.py tests/test_customer_queue_fairness.py tests/test_wallet_billing_service.py tests/test_db_pg.py`（mark 守卫+入口移除回归） | 同上 | **130 passed / 0 fail** |
| `pytest tests/test_independent_creation.py tests/test_cw029_billing_pg_matrix.py tests/test_customer_fencing.py` | 同上 | **85 passed / 0 fail** |
| `pytest tests/test_oral_domain.py` | 同上（无 ffmpeg） | 47 passed + 38 errors 全部为 `MediaToolUnavailable`（ffmpeg 缺失，CW-031/055/056 证据同口径，CI Linux 分片有 ffmpeg 全过）；uncertain/过期/结算专项可跑部分 5 passed |
| `pytest tests/test_source_frames.py` | 本机 Windows（SQLite 历史套件） | 21 passed / 1 skipped（ffmpeg 既有 skip）；被删入口用例已移植矩阵 §3 源帧行 |
| `pytest tests/test_generation.py::test_video_worker_round_does_not_load_image_quality_credentials` | 本机 Windows | 1 passed（run_sqlite_worker_round 调用改为 run_worker_once 直驱，行为断言不变） |
| `ruff check app tests` / `ruff format --check` | 本机 | All checks passed / 213 files already formatted |
| `mypy app`（strict） | 本机 | Success: no issues found in 104 source files |
| `bash scripts/verify_no_secrets.sh` | 本机 | exit 0 |
| main 全量门（check:sharded + 三门禁） | CI | PR 承载，结果以 PR CI 为准 |

## 6. Section 14 Ledger Record

```text
任务/工作包：CW-030 / W4 代码与测试增量（收敛各类Worker的PG调度与恢复差额）
Owner / Reviewer：ZCode 全链路代理（用户 2026-09-11 指令「开始28和30的开发」授权开发与提交）/ 待 PR 独立评审 + CI 三门禁
分支 / 基线 SHA：feat/customer-v3-cw030-worker-pg-convergence / origin/main@8ab85c7（CW-057 合并提交）
上游规格段落：V3 收敛清单 CW-030 行；任务账本 §18；排班清单 §2.2 批次5、§3—§7；CW-002 §6/§7 范围决议；AGENTS.md 标准工作流
改动文件：server/app/generation_worker.py（删 run_sqlite_worker_round/run_forever+孤儿导入）；server/app/generation.py（mark_task_submission_uncertain 增加 SUBMITTING/RUNNING 状态守卫+条件释放）；server/tests/test_cw030_worker_pg_matrix.py（新增 29 用例）；server/tests/pg_test_kit.py（allowlist 登记 cw030_worker_matrix_test）；server/tests/test_generation.py（被删入口调用改 run_worker_once 直驱）；server/tests/test_source_frames.py（删被删入口用例，行为移交矩阵）；server/tests/test_db_pg.py（SQLite 入口改为不存在断言）；docs/evidence/CW030-EVIDENCE.md；docs/CUSTOMER-TASK-EVIDENCE-V3.md；docs/客户版任务清单-V3.md §18+头部；docs/客户版代码开发清单-V3.md（新文件登记）
失败测试或回归锁定：矩阵先行红（种子/断言按真实机制逐步锁定）；mark 守卫以「迟到重复信号不改变替代任务 slot」红→绿；crash 后 SUBMITTING 持久性、过期→UNCERTAIN 不盲重提、settle 账本=[RESERVE,SETTLE] 精确值、陈旧租约完成必抛 lease lost 且结果零覆盖——均为静态可重跑红灯
实现结果：正式 Worker 仅剩 PG 入口（run_pg_worker_round/run_forever_pg），SQLite 轮询入口物理删除；逐类（独立/首帧/联系表/人物图/源帧/文案改写/ASR/混合/两设备）领取、租约、迟到结果、Provider 超时、UNCERTAIN、重启恢复、计费边界共 29 用例真 PG 全绿；mark 侧迟到信号不再击穿 running≤1
验证命令与通过数：见 §5（矩阵 29；回归 130+85；静态门全绿；oral 套件 ffmpeg 环境缺陷与既有口径一致）
证据层级：AUTOMATED_VERIFIED（真实 PG16 容器；真实 Provider/付费链路归 CW-050，生产负载归 CW-047，不提升 STAGING）
安全与可观测性：无真实 secret 入代码/日志/夹具；mark 守卫强化「每用户 running≤1」并发不变量；过期/不确定路径的审计写入未改动（crash_recovery 审计断言回归通过）
迁移与回滚：无 DB 迁移；回滚 = revert 本分支提交（mark 守卫回到无条件释放，SQLite 入口恢复——均不涉及 schema）
外部授权记录：用户指令授权本任务开发；PR squash 合并由用户执行；未触碰真实 ZPay/付费 Provider/生产 COS
未测试项：cargo test / npm audit / 客户浏览器 E2E / npm run build（仅 CI 三门禁）；oral 全套 ffmpeg 依赖（CI Linux 承载）；A=1000/B=100/C=10 生产负载与 EXPLAIN 证据（CW-047/CW-059）；跨口播完整轮转（CW-002 决议不实现）；真实 Provider 超时类型注入（CW-050）
Lore 提交 SHA：见 claim.json 与 PR 登记
```
