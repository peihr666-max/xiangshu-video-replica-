# 管理后台改版实现证据（2026-09-05）

## 证据边界

本页记录 W3–W17 的代码实现、专项与最终全仓门禁。后台 12 页及客户端 3 个组件已完成浏览器对照，详见 [浏览器验收](browser-qa.md)；真实支付、真实 Provider、对外发码和生产迁移未执行。最终 `npm.cmd run check` 退出 0：前端 746 项通过，后端 1633 项通过、1 项因本机缺少 ffmpeg 跳过；源码指纹 133 个文件全部一致。

产品行为以最新用户需求和最终业务裁决为准。AI 参考图用于布局、层级、密度和视觉语言对比；其中的示例金额、批次/发放流程、设备归属列或没有真实入口的点击暗示不覆盖产品与审计约束。

## W3–W17 实现状态

| 工作包 | 当前实现 | 尚待证明 |
| --- | --- | --- |
| W3 客户列表 | 状态/日期/余额筛选、钱包与设备槽位汇总、CSV、秒数口径与详情入口已接入 | 本地自动化及浏览器复核已通过；生产未验证 |
| W4 激活码 | 创建即签发、有效期、派生过期状态、明确确认的初始免费秒数、原因与审计已接入 | 对外发码与生产验证未执行 |
| W5 设备与会话 | 用户/平台/状态筛选、在线与汇总、会话卡片及管理员结束会话已接入 | 本地自动化及浏览器复核已通过；生产未验证 |
| W6 客户详情 | 账户、价格、设备、会话、订单、流水和调账已聚合到客户详情 | 本地自动化及浏览器复核已通过；生产未验证 |
| W7 资金流水 | 充值订单与钱包流水筛选、分页、关联项及可证明的余额前后值已接入 | 真实支付未验证 |
| W8 利润总览 | 每日外部售价、标准收入、成本、毛利、利润率、日表与 CSV 已接入 | 生产数据口径复核 |
| W9 成本明细 | 提交费率快照、真实用量成本、UNKNOWN、日/科目明细与 CSV 已接入 | 真实 Provider 用量未验证 |
| W10 费率管理 | 7 个上游科目与 2 个售价档、审计历史、边界与大幅调价确认已接入 | 生产调价未执行 |
| W11 按秒计费 | 客户按提交档位秒数预留/结算；真实输出秒数只进入成本和统计 | 生产账本迁移未执行 |
| W12 生成参数 | 7 档比例、数量 1/2/4、逐任务生成与报价接口已接入 | 真实 Provider 对比例支持待授权验证 |
| W13 提示词 | 编辑、个人另存、列表与应用已接入，按项目访问和作者隔离 | 本地自动化及浏览器复核已通过；生产未验证 |
| W14 客户端秒数化 | 钱包、充值、流水、生成器和提交报价统一为秒数/元每秒 | 真实支付未验证 |
| W15 总览 | KPI、成本/成功趋势、待办、槽位与快捷入口使用真实聚合端点 | 本地自动化及浏览器复核已通过；生产未验证 |
| W16 审计中心 | 用户名筛选、全局调账、中文事件、单价 old→new 安全字段与历史未知态已接入 | 本地自动化及浏览器复核已通过；生产未验证 |
| W17 生成记录 | 用户/状态/类型/日期筛选下推并统一分页；按裁决不增加设备归属 | 本地自动化及浏览器复核已通过；生产未验证 |

## 迁移链

- [`059_operation_cost_records.py`](../../../server/migrations/versions/059_operation_cost_records.py)：为生成任务增加成本科目、成本单价、对外售价和实际输出秒数快照；新增追加式 `operation_cost_records`，状态限定为 `PENDING / ACTUAL / UNKNOWN`。缺失实际用量保持 `UNKNOWN`。
- [`061_saved_prompt_metadata.py`](../../../server/migrations/versions/061_saved_prompt_metadata.py)：复用 `versions`，增加 `scope/source/author_user_id`、所有权约束和查询索引，避免第二套提示词存储。
- [`062_activation_initial_free_seconds.py`](../../../server/migrations/versions/062_activation_initial_free_seconds.py)：允许零面值激活批次携带经明确授权的初始免费秒数；存在此类数据时 downgrade 拒绝，防止丢失授权和账本历史。
- [`063_wallet_ledger_sequence.py`](../../../server/migrations/versions/063_wallet_ledger_sequence.py)：为新钱包流水分配不可变序号，支持并发写入后的确定性余额重建；历史秒级时间戳无法证明顺序，因此不伪造序号。

迁移链为 `058_daily_external_prices → 059_operation_cost_records → 061_saved_prompt_metadata → 062_activation_initial_free_seconds → 063_wallet_ledger_sequence`。预留的 060 没有创建。

## 公共 API 变化

- 审计：[`admin_audit_routes.py`](../../../server/app/admin_audit_routes.py) 的 `GET /api/control/audit-log` 增加 actor/target 用户名筛选以及 `change_subject`、`old_unit_price_fen`、`new_unit_price_fen`。字段只从费率和客户单价事件白名单提取，完整 metadata 不返回；历史缺旧值为 `null`。
- 会话：[`admin_session_routes.py`](../../../server/app/admin_session_routes.py) 新增 `POST /api/control/customer-sessions/{session_id}/revoke`。请求必须带写契约、幂等键和观察到的 `session_epoch`；事务内锁行并执行 CAS，epoch 已变化返回冲突，同一幂等键安全重放原结果。
- 提示词：[`generation_routes.py`](../../../server/app/generation_routes.py) 新增项目级 saved prompt 创建、列表与应用端点；服务层同时校验项目访问、作者和 `kind/scope`，防止跨用户套用。
- 报价：`GET /api/generation/price-quote` 按分辨率、4/15 秒和数量 1/2/4 返回预计秒数及售价，不暴露内部成本。
- 经营：[`admin_profit_routes.py`](../../../server/app/admin_profit_routes.py) 提供每日售价、利润总览、成本明细和两类 CSV；[`admin_dashboard_routes.py`](../../../server/app/admin_dashboard_routes.py) 提供总览聚合。上海自然日计算覆盖完整首日。
- 成本未知态：[`operation_costs.py`](../../../server/app/operation_costs.py) 在调用前建立费率快照，完成时仅用实际返回量结算成本；无用量或旧在途任务无快照时记录 `UNKNOWN`，前端和 CSV 均明确展示待核对。
- 管理查询：客户、设备、资金、调账和生成记录接口增加页面所需的筛选、汇总及分页字段；前端公共类型集中在 [`api.admin.ts`](../../../client/src/api.admin.ts)。

## 开发期专项验证

| 验证 | 结果 |
| --- | --- |
| `tests/test_admin_audit_routes.py -q` | 14 passed；包含 fake `api_key` 不泄露与历史缺旧值回归 |
| `AuditEventsPage.test.tsx` | 8 passed；包含点号事件精确筛选、old→new、长 ID title 和重置 |
| `tests/test_admin_dashboard_routes.py -q` | 4 passed；包含上海首日 00:10 成本边界 |
| `OverviewPage.test.tsx` | 2 passed；包含真实聚合显示与导航目标 |
| Ruff | 相关 Python 文件通过 |
| Mypy | 78 个源文件通过 |
| Biome | 相关前端文件通过 |
| `tsc -b` | 通过 |
| `git diff --check` | 通过 |

早期专项曾报告缓存目录不可写；最终门禁使用独立、可写的临时与缓存目录，禁止其他任务并行运行 pytest 或清理目录。汇总专项包括管理端后端 402 项、导入和客户链路 40 项、钱包 5 项，均已读取最终退出码 0。

## 兼容与自审收尾

1. 总览和利润图改为连续三次曲线、圆滑描边；相邻点之间不产生越界峰谷。客户详情旧分支已删除，筛选栏与过小字体已修正。
2. SQLite 导入显式识别 PG 专属成本表，费率仅允许完整且未修改的迁移默认值。导入历史流水时仅在同一事务内暂时关闭序号分配触发器，保持其他约束，重新启用并复核；真实 PG 测试覆盖导入中途异常后的触发器恢复、全事务回滚和再次导入。
3. 客户链路夹具保留迁移默认费率，使用客户支持的 4 秒档位，验证预留与结算均为 4 秒。历史账本的未知顺序不伪造补齐。
4. 报价与个人提示词列表失败复用现有错误展示，不把空库或充值换算值冒充请求成功。
5. 首帧成本按实际 Provider 返回量逐调用持久化，记录发生在存储和质检之前；断点恢复不会把文件复用计为新调用。供应商重试分别记录，未知用量不补 0。解析和人物图本地发布失败后仍保留已返回的已知用量。
6. 真实 ZPay、真实 Provider、生产迁移、安装包与公网发布未验证。PostgreSQL 人物图 worker 仍沿用既有外层事务包裹 Provider 与存储 I/O，长事务及连接占用风险保留。

## Section 14 Ledger Record

```text
任务/工作包：管理后台改版 W3–W17
Owner / Reviewer：Codex 实现与主线程整合；专项交叉复核及最终自审
分支 / 基线 SHA：feat/customer-v3-admin-revamp / 67cf008
上游规格段落：docs/design/admin-redesign/work-plan.md v2、requirements-cost-billing-and-features-20260904.md、2026-09-05 最终业务裁决
改动文件：server/app 管理与生成计费模块；server/migrations/versions 059/061/062/063；server/scripts 导入对账；client/src 管理后台及生成/提示词/钱包；相关测试与本目录证据
失败测试或回归锁定：成本快照、按秒结算、会话 CAS、跨用户提示词拒绝、余额序号、导入拒绝与异常回滚、报价错误、曲线和页面筛选均有回归
实现结果：W3–W17 已实现；后台 12 页与客户端 3 个组件经过参考图和实际截图成对比较；保留最新业务裁决及真实数据差异
验证命令与通过数：最终 npm.cmd run check 退出 0；前端 746 通过，后端 1633 通过/1 跳过；管理专项 402、导入及客户链路 40、首帧及成本 50、钱包 5 通过
证据层级：AUTOMATED_VERIFIED；本地浏览器对照完成，真实外部链路和生产未验证
安全与可观测性：沿用 session/CSRF/幂等/fencing；费率与赠送保留审计；未知用量不伪造；密钥扫描进入全仓门禁
迁移与回滚：058→059→061→062→063；新迁移可降级，062 有初始免费秒数授权记录时拒绝降级以保护历史；生产库未迁移
外部授权记录：仅本地实施、自动化和浏览器对照；未授权真实支付、付费 Provider、对外发码或生产发布；浏览器赠送测试写入被自动审批拒绝，未绕过
未测试项：真实供应商、真实支付、生产环境、正式安装包与 CI；本机缺少 ffmpeg 的单项真实提帧测试跳过
Lore 提交 SHA：迁移与导入 f744bbb；后端实现 e440695；界面与曲线 3511dbc；文档记录独立提交
```
