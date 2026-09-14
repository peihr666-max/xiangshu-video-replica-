# FIX-R04-DELIVERY-20260914 — 赠送积分未知结果安全重试

来源：2026-09-12 上线前评估 R-04；本次按 worktree 风险评估结论，从旧分支 `fix/r04-free-grant-retry-20260912@e8f7988` 只读迁入仍有价值的行为。交付分支 `fix/r04-free-grant-retry-delivery-20260914` 直接创建于 `origin/main@50059bc1adc4ef92d68e749ecb0305bafef3d1eb`，没有合并或覆盖旧客户页。

本地交付提交完成后再次 `fetch --prune`，确认本地 `main == origin/main == 06a53331501c6f70cece78ccd67c979ea7c8503f`，并将分支变基到该主线；共享登记文档同时保留 PR #105 工作区清理记录与本 R04 记录。

主线已经具备客户列表请求代次保护、自动生成来源单号、同一确认弹窗内复用幂等键，以及成功后的列表重载。本次只补剩余缺口：请求出现超时、网络中断、网关错误等未知结果时，冻结积分来源、数量、事由、来源单号和幂等键；即使关闭确认框、返回列表或卸载后重新进入页面，输入仍保持锁定，后续只能原样重放。待确认意图在 POST 前按管理员 ID 与客户 ID 写入当前浏览器会话，不在不同管理员之间共享；浏览器存储写入失败会阻止发送。每次尝试有独立 attempt ID，迟到响应只能条件清理对应意图。首次请求得到明确的 4xx 拒绝时释放意图，允许管理员修正输入；一旦此前出现未知结果，之后的 4xx 只能证明本次重试失败，仍保留最初意图，直到观察到成功。408、409、429 及 5xx 始终按未知结果处理。

成功响应先用 `wallet_balance_after` 更新当前客户可用余额，再后台重载客户列表和相关详情；若重载失败，详情页显示错误，同时保留服务端已经返回的余额。已经卸载的旧发放组件只处理自己的持久记录，不再回写父页面，避免迟到成功覆盖后续发放余额。同步提交锁避免快速重复点击发出并发写请求。免费发放仍走既有审计调账 API，不改变服务端账务、来源类型或数据库 schema。

修改范围：`client/src/AdminApp.tsx`、`client/src/admin/CustomersManagementPage.tsx`、`client/src/admin/CustomersPage.tsx`、`client/src/admin/CustomersPage.test.tsx`。回归覆盖关闭未知结果弹窗后的字段锁定、返回列表与整页卸载后的意图恢复、请求仍在途时重建页面、不同管理员隔离、未知结果后再遇 403 仍原样重试、各次请求体与幂等键完全相同、持久存储失败时零请求、迟到成功不得覆盖后续新发放余额、成功余额刷新，以及首次明确 422 拒绝后恢复编辑。

本地验证：

- `biome check client/src/admin/CustomersPage.tsx client/src/admin/CustomersPage.test.tsx`：通过。
- `vitest run client/src/admin/CustomersPage.test.tsx`：18 passed。
- `npm run check --workspace client`：Biome、TypeScript、99 个测试文件、1424 项测试通过；仅输出主线已有的 CSS specificity 警告。
- `npm run check:e2e`：15 个文件通过。

本次未修改后端或迁移，未执行真实赠送、真实支付、生产账本修改或部署。全仓 Linux、Windows、秘密扫描与构建门禁留待正式 PR CI；未运行的门禁不记为通过。

回退：撤回本交付提交即可；无 schema 或数据回退。若线上已经产生赠送记录，不得随代码回退自动冲销，任何资金修正需单独授权和审计。

独立 Reviewer `/root/review_joint_delivery` 经三轮只读复审最终 PASS：发送前持久化、存储失败 fail-closed、未知后 403 保留、key + attempt ID 条件清理、卸载后迟到响应隔离均已闭合，无剩余阻断项。

状态：本地前端 AUTOMATED_VERIFIED，独立复审 PASS；远程交付待授权。
