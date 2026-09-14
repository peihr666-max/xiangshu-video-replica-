# FIX-R02-DELIVERY-20260914 — 支付回调原子性主线交付

来源：2026-09-12 上线前评估 R-02；本次按 2026-09-14 worktree 整理指令，将仍有价值的资金修复迁到当前主线。基线 `origin/main@281a82848cf9a3255054082939da228f7c92c7c6`；分支 `fix/r02-payment-atomicity-delivery-20260914`。旧分支 `fix/r02-payment-atomicity-20260912@b7e66fe` 仅作只读来源，未直接合并旧文档或过期基线。

修改范围：`server/app/payment_routes.py`、`server/app/zpay_payments.py`、`server/tests/test_wechat_native_callback_pg.py`。共享支付结算在 PostgreSQL 请求事务内使用真实保存点，先锁定订单再写订单、账本和钱包；异常在路由转换响应前完整回滚。微信异步回调把同步数据库结算放入线程池并等待结果，避免订单锁等待阻塞事件循环。没有修改共享连接的提交权，没有新增迁移。

主线兼容修复：`BusinessConnection.execute()` 会把 PG 约束异常转换为 `IntegrityConstraintError`。初次迁入仍捕获旧类型，账本唯一键冲突红灯为 ZPay/微信各 1 项未处理异常；改为只将 SQLSTATE `23505` 映射为 `*_SETTLEMENT_CONFLICT`，其余约束错误继续抛出。当前主线的 CHARGE 触发器会创建 `billing_credit_lots`，测试修复冲突夹具时先删除该派生批次，再删除人工注入的账本行。修复后失败回滚矩阵 6 passed。

验证：隔离 PostgreSQL 16 上的支付、充值、微信/ZPay Provider、账务矩阵专项 **129 passed**。全仓静态门通过：秘密扫描、Biome、TypeScript、前端 **1418 passed**、e2e lint、Tauri fmt/check、Ruff 335 文件、mypy 146 模块。后端官方清单覆盖 93 个测试文件，四个专属空库分片分别为 540、604、501、393 passed，合计 **2038 passed / 1 skipped**，退出码全部为 0。

第一轮全量误用了联调候选数据库，其中保留的 `20260914T0000_local_joint_merge` 迁移头不属于 R02 分支，导致两个无关分片 setup error。该运行保留为失败证据；换成 4 个 R02 专属空库后完整重跑通过，没有跳过或把污染运行计作成功。

独立评审结论 PASS。复审确认保存点不提前提交、订单锁串行化同订单回调、两渠道复用同一资金路径、`auth_source='internal'` 保留，以及非唯一约束异常不会被误报为结算冲突。没有执行真实支付、生产账本修改、历史自动补账或生产部署。

回退：撤回本交付分支的代码与测试提交；无 schema 变更。任何既有生产资金记录都不应随代码回退自动修改，后续对账需单独授权。

状态：本地 AUTOMATED_VERIFIED + INDEPENDENT_REVIEW_PASS。用户已明确授权向公开 GitHub 仓库推送本交付分支及内部任务证据；最终 PR、CI 与合并状态以 GitHub 记录为准。
