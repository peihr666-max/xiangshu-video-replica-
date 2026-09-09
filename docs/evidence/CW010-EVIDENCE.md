# CW-010 — 各任务类别真实 PG 恢复基线（部分完成：钱包类已迁，其余登记集中处理）

## 任务信息（§14 模板）

| 字段 | 值 |
| --- | --- |
| 任务/工作包 | CW-010 补齐各任务类别的真实 PG 恢复基线 |
| Owner / Reviewer | Owner：ZCode 代理（hlong026 会话，2026-09-09）；Reviewer：独立复核子代理 + PR review |
| 分支 / 基线 SHA | `feat/customer-v3-cw010-pg-recovery-baselines`，叠放于 CW-007@96c77b1 |
| 上游规格段落 | V3 清单 §4 CW-010 |
| 改动文件 | 重写 `server/tests/test_wallet_billing_service.py`（SQLite→真实 PG，16 用例）；`server/tests/pg_test_kit.py` allowlist 登记 3 个 CW-010 库名；新增 `docs/evidence/CW-ISSUES-BACKLOG.md`、本证据文档；文件映射登记 |
| 失败测试或回归锁定 | 迁移保留原全部断言（16 用例逐一对应）；迁移中新增语义断言："拒绝调用后无部分写"以独立事务复核（PG 提交权语义） |
| 实现结果 | **钱包类（W11 RESERVE/SETTLE/RELEASE/悬挂清扫）已完成真实 PG 多连接基线**；口播/独立生成类迁移被结构性身份差额阻塞（B-1，登记集中处理）；H3 崩溃恢复与公平队列本已为 TEST-PG（复用） |
| 验证命令与通过数 | wallet 套件 16/16 绿（PG16 fixture，5.8s）；全量门禁见 PR |
| 证据层级 | AUTOMATED_VERIFIED（**钱包类范围**）；整项不标完成 |
| 安全与可观测性 | 不适用（测试基线） |
| 迁移与回滚 | revert 本分支即回滚（纯测试变更） |
| 外部授权记录 | 无 |
| 未测试项 | 口播/图片/分析改写/ASR/独立生成类（B-1 阻塞，见集中问题清单） |
| Lore 提交 SHA | 本 PR squash 后回填 |

## 1. 钱包类迁移明细（本轮交付）

| CW-010 验收要求 | 落实 |
| --- | --- |
| 真实 PG、多连接 | 每测试独立池事务（`pg_transaction`）；拒绝路径与断言路径使用独立连接（`_fresh_conn`）；并发用例双线程双事务 |
| 同一幂等键重放新增收费=0 | `test_reserve_moves_one_credit_and_is_idempotent`（replay_round==1，仅 1 条 RESERVE） |
| 成功结算次数=1 | `test_finalize_success_settles_only_an_archived_result`（replay SETTLE 不重复）+ `test_dangling_reservation_sweep_settles_only_archived_success` |
| 确认失败释放次数=1 | `test_finalize_failure_or_cancellation_releases_credit_once`（failed/cancelled 参数化，replay RELEASE 唯一）+ `test_dangling_reservation_sweep_releases_terminal_failure_once` |
| 未知/部分写保护 | 三个 rejects 用例均以**回滚后新事务**断言 0 账务行（PG 提交权语义的忠实化） |
| 崩溃恢复 | `test_dangling_reservation_sweep_isolates_poisoned_candidate`（毒化候选隔离：released==failed==1，互不污染） |
| 提交边界 | 并发超支：`test_concurrent_task_reservations_cannot_overspend`（双线程双事务，恰好一个 reserved） |

迁移语义记录：`with conn:`（SQLite 的块级提交）在 PG 上是 no-op（提交权在外层事务）——因此原"with 块内异常→块回滚→块外断言"重写为"独立被测事务回滚→新事务断言"，这是 PG lane 的真实行为而非翻译。

## 2. 未完成部分与原因（诚实边界）

- **独立生成（independent，14 用例）与口播（oral，39 用例）未迁移**：二者通过 dev-header（`X-Dev-User-Id`）或 `get_business_db` override 替身驱动 fenced 写路径；PG lane 的 `BusinessDb.write` 分支要求真实客户 session——**该身份流在 PG lane 不存在**，机械替换会产生假基线。忠实迁移必须重构为真实激活流（kit 种子 + `/api/customer/activate`），并连带把测试的用户模型从 employee 改为客户。登记为集中问题清单 **B-1**，建议与 CW-026/CW-058/059 合并推进。
- 图片/分析/改写/ASR 类：预计同受 B-1 影响，待其迁移时按同方案处理。
- H3 崩溃恢复（`test_worker_crash_recovery.py`）与客户公平队列（`test_customer_queue_fairness.py`）**原本即为真实 PG 多连接基线**（复用，符合 CW-010"复用现有"），本轮已核验其仍绿。

## 3. CW-010 任务类别×基线现状矩阵

| 任务类别 | 基线套件 | 现状 |
| --- | --- | --- |
| 钱包（W11 账务核心） | test_wallet_billing_service.py | ✅ TEST-PG（本轮迁移，16 用例） |
| H3/独立视频 Worker 崩溃恢复与租约 | test_worker_crash_recovery.py | ✅ 原有 TEST-PG（多连接、双领、释放专项） |
| 客户公平队列 | test_customer_queue_fairness.py | ✅ 原有 TEST-PG（轮转/并发/租约） |
| 独立生成业务流 | test_independent_creation.py | ⏸ B-1（身份语义重构待集中处理） |
| 口播业务流 | test_oral_domain.py | ⏸ B-1 |
| 图片/分析/改写/ASR | 各自套件 | ⏸ B-1 + B-5 |

## 4. 独立复核

独立评审结论随 PR 记录；本轮评审聚焦钱包迁移的语义忠实性（事务边界重排是否削弱原断言）。

## 5. 签认记录

| 角色 | 结论 | 日期 |
| --- | --- | --- |
| 后端测试负责人 | 待签认（整项在 B-1/B-5 闭合前不得标完成） | — |
