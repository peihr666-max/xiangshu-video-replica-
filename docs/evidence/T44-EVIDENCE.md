# T44 — T43 后续安全收口证据

## 1. 当前结论

- 当前证据层级：`CODE_PRESENT`。
- 分支：`feat/customer-v3-t44-security-followup`，基线 `3799789588fd0278b8e18691329d60c7e75dfe23`。
- 实现提交：`0b36c61`；逐文件自评审未发现遗留 Critical/High/Medium 代码问题，真实 PG 执行边界仍保持开放。
- 所有已报告缺陷均已修改并建立回归锁；本机没有 PostgreSQL fixture，因此迁移 051 的真实 PG16 用例尚未执行，不提前标记 `AUTOMATED_VERIFIED`。
- 未连接或修改生产数据库、服务器、支付、COS、Provider，也未构建或发布桌面安装包。

## 2. 逐项修复结果

| 编号 | 修复结果 | 回归边界 |
| --- | --- | --- |
| B-1 | 新增 `051_identity_owner_backfill`：先从来源/授权素材、项目主人物及项目人物选择推导唯一项目 owner，再以仍存在的创建人兜底；多 owner 或无 owner 会中止迁移；最后将 `owner_user_id` 改为 `NOT NULL`、外键删除策略改为 `RESTRICT` | PG 用例覆盖项目 owner 优先、创建人兜底、NOT NULL、downgrade，以及冲突时事务回滚并停在 050 |
| F-1 | `/api/recharge-orders` 拒绝 customer 与 auditor；客户只能走带 session、幂等信封和客户定价的 `/api/customer/recharge-orders` | 断言 403 且不产生充值单 |
| F-2 | 无人值守恢复和显式激活恢复均不再匹配 `REVOKED` 设备 | 断言恢复统一失败且设备持续为 REVOKED |
| C-1 | legacy 项目主人物绑定复用 owner-aware `get_character` | 非 owner 即使知道人物 ID 也不能绑定 |
| F-3 | 人物缓存 URL 与普通下载 URL 使用相同的 auditor 写/导出门禁 | 断言 403，且不触发额外存储读取 |
| F-4 | 首帧任务在查询幂等重放记录前先执行角色和项目归属校验 | 其他账号猜中 project/key 仍返回 `PROJECT_FORBIDDEN` |
| F-5 | 本地对象键不再规范化 `..`、反斜杠、空段或 `.` 段，而是直接拒绝 | 覆盖跨租户穿越、Windows 反斜杠、双斜杠和点段 |
| P-1 | 按产品确认保留“无需管理员审核、直接生成发布”；自动批准记录的 reviewer 为空，comment 和发布快照明确标识 `SYSTEM_AUTO_PUBLISH` | 直接发布行为不变，但不再把客户 actor 伪装成人工审核员 |

## 3. 测试与检查

1. 实现前的六个运行时回归测试全部在旧代码上失败，覆盖 F-1、C-1、F-3、F-4、F-5 和 P-1。
2. 实现后同一专项：`6 passed`。
3. 迁移/schema/人物相关组合：`116 passed, 13 skipped`。
4. 受影响模块组合：`164 passed, 117 skipped`；跳过项主要为需要外部 PostgreSQL fixture 的用例。
5. 服务端全量：`924 passed, 499 skipped, 0 failed`，耗时 14 分 40 秒；跳过项为未配置的 PG/外部工具环境合同。
6. 静态检查：全服务端 Ruff 与 format check 通过；Mypy `74` 个模块通过；`git diff --check` 通过。

## 4. 上线前 No-Go

- 必须先在生产快照的隔离副本上执行 051；若报告 multiple owners 或 no deterministic owner，必须人工确认归属后再迁移，不允许删除人物、临时填 admin 或跳过 NOT NULL。
- 必须在 PostgreSQL 16 上执行新增的两个 T44 迁移测试，并验证 upgrade/downgrade 后外键行为。
- 生产迁移前必须完成可恢复备份；同一发布 SHA 下验证客户充值路由、撤销设备、跨账号 legacy 绑定、首帧重放和直接发布审计快照。
- 051 未在真实 PG16 通过前，不得宣称 `AUTOMATED_VERIFIED`、`STAGING_VERIFIED` 或 `PRODUCTION_GO`。
