# FIX-WALLETSTATUS-20260912 — 钱包提示竞态前置修复

任务/工作包：独立 CI 前置，修复钱包状态轮询覆盖用户操作错误。

Owner / Reviewer：Codex（01a094e2-9d59-73e3-8b2d-280723c19e7e）/ review_w13（独立只读评审 PASS）。

分支 / 基线 SHA：fix/wallet-status-error-race-20260912；origin/main@8ae7305471d9c6a10ceacbd2c0f2c5c1ce4004bf。新 worktree 从该最新主干创建，未从功能分支派生。

上游规格段落：PR #80 Linux job 103558670916 的既有 CustomerWalletPanel 测试失败；初始流水完成后错误提示被轮询清除。本项独立于 W12 售价修改，也不重做 UC 账号、钱包或充值规则。

改动文件：client/src/customer/CustomerWalletPanel.tsx、同目录 CustomerWalletPanel.test.tsx；本任务四个共享账本及证据。

失败测试或回归锁定：两条受控 Promise 测试在旧代码稳定失败（2 failed、9 passed），失败点为删除失败提示被较晚的成功/失败查询覆盖；流水以实际渲染 +37 秒确认消费完成。先纠正新测试的显示单位匹配后记录有效 RED，不把夹具错误算生产回归。

实现结果：独立 pollingError，仅查询更新或清理它；用户操作 error 展示优先；订单切换/停止轮询清除旧查询错误；保留已有支付查询和交易行为。新增轮询失败后恢复成功清除自身错误的回归，不延长等待、不禁用轮询、不跳过测试。

验证命令与通过数：node node_modules/vitest/vitest.mjs run --root client src/customer/CustomerWalletPanel.test.tsx，11 passed；Biome 两文件通过；完整 Linux 质量门待完成。

证据层级：CODE_PRESENT，专项及独立评审通过；全量门禁、PR 和合并待完成。

安全与可观测性：仅使用模拟会话和受控 fetch；无真实支付、凭据、外部请求及部署操作。

迁移与回滚：无迁移或依赖变化；通过正常 PR revert 回滚组件及测试，保留业务数据。

外部授权记录：用户已授权独立 worktree、开发修复、独立只读子代理评审、提交 PR 和合并；人工联合调试归第二部分由用户团队执行。

未测试项：真实浏览器充值、支付回调、跨设备和生产体验均留第二部分，本次组件回归不冒充联合调试。

Lore 提交 SHA：不适用；最终候选与 PR、squash SHA 后续登记。
