# 客户版收敛 · 集中问题清单（CW-ISSUES-BACKLOG）

> 用途：按用户指示（2026-09-09），收敛任务执行中发现的**非阻断**问题统一登记于此集中处理，
> 不逐项即时修复。缺陷类（测试假绿、行为错误、验收红线）不进本清单——当场修复；
> 本清单收录结构性差额、优化项、流程项与遗留清理。
> 每条含：发现任务、问题描述、影响、建议去向。处理完成后在"状态"列标记并注记处理位置。

| # | 发现于 | 问题 | 影响 | 建议去向 | 状态 |
| --- | --- | --- | --- | --- | --- |
| B-1 | CW-010 | **客户功能套件的身份语义差额**：independent（14 用例）与 oral（39 用例）套件基于 dev-header/override 替身构建；PG lane 的 fenced 写路径要求真实客户 session（`BusinessDb.write` 的 snapshot 分支），dev 身份仅存在于 SQLite desktop lane。忠实迁移需重构为"kit 种子激活码 → 真实 `/api/customer/activate` → Bearer session"身份流（可复用 CW-007 kit 种子扩展），属结构性改造而非机械替换 | CW-010 的"口播/独立生成逐类迁 TEST-PG"未完成（钱包类已完成）；图片/文案/ASR 类预计同受影响 | CW-026（内部认证退出）前完成，与 CW-058/059 全量迁移合并推进 | 待处理 |
| B-2 | CW-007 | 4 个历史测试库名缺 `_test` 后缀（t11_activation_code_service、t34_chain_e2e、t13c_customer_activation_concurrency、t22r_customer_recharge），无法进 kit allowlist；这些套件仍自管 CREATE/DROP | 套件建库/清理未统一到 kit；库名规范不一致 | 后续触碰这些文件时改名+收编 kit 助手（kit 内已有注释标注） | 待处理 |
| B-3 | CW-009 | Python 依赖审计缺失（仅 npm audit；无 pip-audit/uv audit） | S9 依赖审计门禁不完整 | CW-044（CI 收口）补门禁 | 待处理 |
| B-4 | CW-009 | 验收材料措辞约束（不得把客户端指纹宣称为绝对物理设备证明）无自动化守护 | 依赖 CW-046/049 验收材料人工复核 | CW-046/049 执行时复核 | 待处理 |
| B-5 | CW-053 | server/tests 仍有 40 个 TEST-SQLITE-CONN 债务文件 + 2 混合（钱包类已由 CW-010 迁出 1 个） | 全业务 PG 覆盖未闭合；CW-042 裁剪被阻塞 | CW-058/059 全量迁移（吸收 B-1 的身份重构方案） | 进行中 |
| B-6 | CW-053 | 28 个 app 文件的 sqlite3.Row/Error 仅类型引用债务 | 查询/类型债务未核销 | CW-054 逐调用者 RED→GREEN | 待处理 |
| B-7 | 分支治理 | cw009/cw010 分支叠放于 cw007（96c77b1）；CW-007 squash 合并 main 后，叠放分支需 rebase 到新 main 才能开独立 PR | PR 顺序约束：CW-007 先合并 | CW-007 合并后 rebase；期间 PR base 可暂设为 cw007 分支 | 待处理 |
| B-8 | CW-002/003/004/005 | 五项 W0 决议文档均为"待签认"草案（产品/架构/运维/数据/桌面/后端负责人字段） | 对应任务不能在账本 §18 标完成 | 用户签认（或明确委托代理代签的授权） | 待处理 |
| B-9 | CW-005 | `data-deploy-audit.md` 在 origin/main 缺失（存于收敛分析分支 outputs/）；实际数据批次盘点未执行（无生产访问） | CW-033—037 条件链无法启用 | 现场盘点 + 候选整合时恢复该文档 | 待处理 |
| B-10 | CW-010 | wallet 套件迁移中发现的锁语义教训：长事务持有 TRUNCATE 排他锁会饿死并发用例（statement_timeout 300s）——已按短事务模式修复；oral/independent 迁移时直接采用该模式 | 无（经验教训） | 无需行动，迁移模式参照 `tests/test_wallet_billing_service.py` | 已闭环 |
| B-11 | CW-004 | `deploy/postgres/migrate.sh` 仅单机 flock；多主机安全迁移锁（PG advisory lock）在正式部署主线的落地归 CW-032（现状：advisory lock 仅存在于 T07 割接脚本） | 多主机部署迁移锁 | CW-032 | 待处理 |
| B-12 | 全局 | 任务账本 §18（含 CW 状态表）在收敛分析分支上，origin/main 无此文件——CW 任务的状态更新暂由各任务证据文档承载 | 账本更新需要先整合账本文件（与 CW-001 候选整合同批） | CW-001 候选整合时并入账本并开始逐项更新 §18 | 待处理 |

## 记录纪律

- 新问题按序号追加；处理后移入对应任务 PR 描述并在状态列注明。
- 缺陷类（假绿/行为错误/红线违反）**不入本清单**，必须在发现它的任务内当场修复并记入该任务证据文档的"独立复核"节。
