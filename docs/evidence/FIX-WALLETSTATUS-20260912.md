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

## 最终完整门禁复验

完整本地质量门通过：服务端 2845 passed、1 原有 TLS 场景跳过；前端 1348 passed；secret、Biome、TypeScript、e2e lint、Tauri fmt/check、ruff、format、mypy 均通过。服务端四个独占 PG16 分片分别为 794、616、674、761 passed，各退出码 0，覆盖清单检查通过。最终日志为 `WALLETSTATUS-shard-0.log` 至 `-3.log` 与 `WALLETSTATUS-final-static.log`，保存在工作区 `outputs/remediation-20260912/`。PG 使用临时内存盘，默认同步与事务配置保持开启，不是生产容量或持久性验收。

先前中断、环境或旧夹具失败记录保留，不记为通过；当前证据层级为 AUTOMATED_VERIFIED（本地）。独立评审通过，PR 当前 SHA 的 CI 和正常 squash 合并仍待完成；所有人工联合调试留第二部分。

验证基线说明：服务端完整分片在主干 8ae7305 加本任务修复上执行，本任务未修改服务端。随后同步账号 PR #79 已合入的 main@37a2633；独立评审确认钱包及充值 API 合同未变化，当前合并代码的完整静态门（含 83 文件、1348 项前端测试）通过；主干 37a2633 的 CI run 34696348524 三门禁亦全部成功。未将旧基线后端计数冒充新主干重新执行的计数。

完整前端的前两轮分别遇到既有 StudioWorkspace 对话框、AnalysisWorkspace 草稿时序失败；记录为失败，不声明由钱包代码修复。降低本地并发并复测后，包含上述两文件的完整套件全部通过。测试计时器 DOM/Node 类型差异已改用 fake timers 解决，独立只读复审 PASS。
