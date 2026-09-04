# 管理后台改版工作任务清单（2026-09-03）

> 约束：**不改样式**——沿用 client/src/admin/ui/ 现有组件（vocabulary 徽章、ConfirmDialog、表格）与 styles.css，只改内容（字段/筛选/数据口径）与布局（导航分组/页面组织/跨页跳转）。效果图仅表达信息结构，不表达视觉。
> 流程：每个任务按仓库标准走——从 main 切 `feat/customer-v3-tXX-描述` 分支、测试先行、单任务单 PR、同步更新任务清单账本与证据。编号 ADM-xx 仅为本文引用，入账时接续账本现有 T 编号。
> 依据：`backend-gap-analysis.md`（字段级排查）、12 页效果图（docs/design/admin-redesign/01-12）、2026-09-03 后台分析报告问题清单。

## 前置决策（开工前需拍板，仅 1 项）

- **DEC-1**：生成记录是否落设备归属（generation_batches/tasks 加 device_id，fenced 提交时写入；历史不可回填，仅新任务生效）。影响 ADM-16、ADM-22。不做则 09 页"设备"列与筛选取消。
- 已按建议定案（无需再议）：EXPIRED 用查询派生（不动状态机）；balance_after 加列+回填；生成即发放用现有 auto_issue。

## 阶段一 · 纯前端，零后端改动（P0 快赢）

**ADM-01 导航与页面骨架重组**
AdminApp.tsx tab 重新分组（运营概览：总览/客户与钱包/充值订单/账务流水；客户运营：客户详情/激活码/发码中心/设备/生成记录/会话；系统治理：调账/审计/支付/服务），新页面先落骨架占位。验收：三组导航、现 10 页功能无回归（全量测试过）。

**ADM-02 充值订单页补内容**
OrdersPage 补列：渠道、第三方单号、下单时间、支付时间（接口已返回）；查单同步保留 reason 确认。验收：4 列展示、空值兜底。

**ADM-03 账务流水页补内容与跳转**
AccountsPage 流水表补列：时间、关联订单/任务（可点击跳对应页并带筛选）。验收：列齐全，点击跳转落点正确。

**ADM-04 激活码页补内容**
ActivationCodesPage 补列：批次、发放时间（issued_at）；保留展开设备/待批配对。验收：列展示；"已过期"筛选选项待 ADM-10 后端就绪再上（本期不做）。

**ADM-05 设备页断链修复（纯前端部分）**
DevicesPage 补列 slot_no/user_id/activation_code_id；启用 API 已有的按客户/激活码/状态筛选表单；客户详情"查看设备"跳转带 userId 并自动应用。验收：从客户页一键看到该客户设备。

**ADM-06 会话页补内容**
SessionsPage 补列：最近心跳、会话纪元、租约到期（已有数据）。验收：列展示。

**ADM-07 生成记录页前端部分**
GenerationRecordsPage：状态中文徽章（vocabulary）、耗时列（completed_at-created_at）、错误码红色展示。验收：状态全类型有映射，耗时空值兜底。

**ADM-08 客户列表口径与内容**
CustomersPage：列名"注册时间"改"激活时间"；补 user_id 列（供审计/会话页检索）；"需要处理"统计与状态筛选口径修正（前端过滤→服务端参数或明确标注当前页）；CSV 导出口径与页面一致。

**ADM-09 发码流程改造（前端）**
快速发码表单：有效期改为输入项（不再硬编码一年）、初始条数/批次名可填、操作原因必填输入（去自动原因）；接入 auto_issue=true（生成即发放）；DeliveriesPage 独立发放表单降级为"补发放"入口；复制明文码改真实 reason 输入。验收：新流程一次表单完成生成+发放；两类高危动作均有真实 reason 落审计。

**ADM-10 统计口径标注**
DevicesPage/CustomersPage 概览卡标注统计范围（当前页/全量），避免误读。

## 阶段二 · 后端接口扩展 + 对应前端（P0/P1）

**ADM-11 客户查询扩展**（B1）
GET /customers：+status/注册时间/余额区间参数；响应 +display_name、钱包可用/冻结（join wallets）、设备槽位占用（BOUND 子查询）。注意：credits_spent 是 SETTLE 笔数，文档标注。前端接余额/槽位列与筛选。

**ADM-12 设备查询扩展**（B2）
GET /devices：响应 +username（join users）、masked_code（join activation_codes）、在线状态（join customer_session_state lease_until）；+platform 筛选参数。口径：在线以会话租约为准，last_active_at 语义=最后绑定时间（文档标注）。前端补列替换裸 ID。

**ADM-13 激活码有效期与过期派生**（B3）
GET /activation-codes：+expires_at（join 批次 activation_expires_at）+派生"已过期"标志（expires_at<now AND status IN GENERATED/ISSUED）；前端有效期列（过期红标）+筛选加"已过期"。不动状态机。

**ADM-14 订单/流水时间筛选**（B4/B5）
GET /recharge-orders +channel、created_from/created_to；GET /wallet-transactions +时间范围。前端接筛选与渠道列筛选。

**ADM-15 审计与调账查询扩展**（B7/B8）
GET /audit-log：+target_username 反解；支持 actor_username/target_username 检索参数。GET /customers/{id}/adjustments：+admin_username。前端审计页目标列显示用户名、筛选改用户名输入；调账列表显示操作人。

**ADM-16 生成记录过滤**（B6；若 DEC-1 通过含设备维度）
GET /generation-records：+user_id/status/record_type/时间范围；分页实现从 5 表内存合并改为过滤下推+各表 COUNT。前端筛选栏（账号/类型/状态/时间；设备项待 DEC-1）。注意：图像/源帧类 charged_credits 恒 0。

**ADM-17 generate auto_issue 渠道参数**（B9）
POST generate 的 auto_issue 支持 channel/external_order_ref/recipient_ref（现固定 admin_console）；发码表单带渠道字段。写契约不变。

## 阶段三 · 新端点 + 新页面（P1）

**ADM-18 总览仪表盘**（C1）
新端点 GET /api/control/dashboard/summary：今日生成/成功率/环比、近7日趋势（成功/失败双线）、活跃客户、今日充值合计、待办四项（待批配对 PENDING+未过期、失败任务、对账不一致复用 reconciliation、即将过期码）、槽位占用。AdminReader 权限。前端总览页（KPI 卡+趋势+待办，复用现有卡片样式），对账指标可点击跳订单页。

**ADM-19 发码中心页**（C2/C3）
新端点 GET /activation-code-batches（批次列表：创建人 username、数量、已发放/已激活计数、面值/额度/有效期、OPEN/CLOSED）+ GET /activation-code-deliveries（发放记录：码掩码、渠道、外部单号、收件人、发放人、时间）。前端发码中心页两 tab（批次与发码记录 / 快速发码）。

**ADM-20 全局待批配对**（C4）
新端点 GET /device-pairings/pending（PENDING+expires_at>now()）；前端会话页右侧待办栏 + 仪表盘待办联动。

**ADM-21 客户详情 360° 页**（新页面）
前端拼装：customers（码+统计）+ devices?user_id= + orders?user_id= + adjustments + sessions + unit-price + ADM-18 趋势（或轻量按客户聚合）。头卡操作按钮复用现有写流程（加款/免费发放/改价，保持 reason+来源单契约）。客户列表行点击进入。

**ADM-22 调账独立页**（C-）
GET 扩展：全局调账列表（操作人/目标客户/来源单类型/时间筛选）。前端"系统治理/调账记录"独立 tab；前后余额列待 ADM-23。

**ADM-23（可选）仅踢会话端点**（C5）
POST /customer-sessions/{user_id}/kick 复用 revoke_session（不动设备绑定）；会话页"强制下线"按钮接此端点，写契约+审计。

## 阶段四 · 数据层（P2，决策后）

**ADM-24 余额快照落库**
迁移：wallet_transactions +balance_after（写入路径 RETURNING 落库）+ 按零差额不变量回填历史；admin_adjustments +balance_before/balance_after（创建响应值落库；append-only 触发器不挡加列）。前端流水/调账页补"变动后余额/前后余额"列。

**ADM-25 生成记录设备归属**（依赖 DEC-1 通过）
迁移：generation_batches（或 tasks）+device_id/session_epoch，fenced 提交事务写入（上下文现成）；前端生成记录设备列+筛选；标注仅新任务生效。

**ADM-26 审计变更明细**
UNION SQL 扩取已有键（改单价 old/new、调账金额条数）；新写入点（设置变更等）补 before/after 到 metadata_json；前端审计页"变更明细"列（旧值→新值）。历史事件无 before/after 的显示动作描述，不虚构。

## 依赖与顺序

- ADM-01 先行（骨架）；阶段一其余任务可并行。
- ADM-21 依赖 ADM-11/12/18；ADM-22 依赖 ADM-15；ADM-13 独立。
- ADM-16 设备维度、ADM-25 依赖 DEC-1。
- 全程不改 styles.css 与 ui 组件视觉；新增页面复用现有表格/徽章/卡片结构。
