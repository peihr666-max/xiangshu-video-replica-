# 管理后台改版后端支撑排查报告（2026-09-03）

对照 12 页效果图逐项核查现有接口（参数+返回字段）与数据层（表结构+写入路径）。
分级：✅ 后端已就绪（纯前端改动）｜⚠️ 数据在但接口缺参数/字段（接口扩展）｜🆕 需新增端点｜🗄️ 需数据层改动（迁移/写入路径）。

## 一、总体结论

- 约 40% 的改版内容**后端已就绪**，纯前端就能做（包括几处此前 UI 浪费掉的现成能力：设备按客户/激活码过滤参数、订单时间/渠道字段、生成即发放 auto_issue）。
- 接口层缺口集中在：**汇总统计（仪表盘）、批次/发放列表、跨实体 join 字段（username/掩码/余额/有效期）、筛选参数（时间范围/状态）**——全部可在现有表上实现，无需大迁移。
- 数据层真正的硬缺口只有三处：**生成记录无设备归属**、**流水/调账无变动后余额**、**EXPIRED 状态从不落库**。前两处需迁移或查询期计算，第三处建议查询派生（不动状态机）。

## 二、逐页核查

### 01 总览仪表盘 🆕
| 内容 | 状态 | 说明 |
|---|---|---|
| 对账 5 指标 | ✅ | billing-reconciliation 已有（control_routes.py:904） |
| 在线设备数 | ✅ | customer-sessions/live 的 total 即在线会话=在线设备（单会话模型） |
| 今日生成/成功率/环比、7日趋势 | 🆕 | 无统计端点；generation_tasks.created_at_utc 有索引（042），按天聚合直接可行 |
| 活跃客户、今日充值合计 | 🆕 | recharge_orders.paid_at+amount 聚合；活跃口径需产品定义 |
| 待办（待批配对/失败任务/即将过期） | 🆕 | 均可从现有表直接 count（配对须带 expires_at>now() 懒过期条件） |
| 槽位占用 | 🆕 | customer_devices BOUND 计数 / 客户数×2 |

### 02 客户与钱包
| 内容 | 状态 | 说明 |
|---|---|---|
| 用户名筛选 | ✅ | username ILIKE（admin_customer_routes.py:723） |
| 现有列（码/状态/生成统计/credits_spent） | ✅ | 全在（:792-807） |
| 状态筛选 | ⚠️ | API 不支持（CSV 导出反而支持，口径不一致） |
| 注册时间/余额区间筛选 | ⚠️ | 需加参数 |
| 钱包可用/冻结余额列 | ⚠️ | wallets 表有数据，列表 SQL 不 join |
| 设备占用列 | ⚠️ | BOUND 计数子查询可算 |
| display_name 列 | ⚠️ | users 表有，接口不返回 |

### 03 充值订单
| 内容 | 状态 | 说明 |
|---|---|---|
| 时间/渠道/第三方单号列 | ✅ | channel/provider_trade_no/created_at/paid_at 接口全部返回（control_routes.py:91-105），仅 UI 未显示 |
| 状态/账号筛选 | ✅ | status+user_id 参数已有 |
| 渠道、时间范围筛选 | ⚠️ | 需加参数 |
| 对账卡下钻 | ⚠️ | 5 个数已有；"已支付未入账"下钻需按该口径的订单过滤查询 |

### 04 账务流水
| 内容 | 状态 | 说明 |
|---|---|---|
| 时间/类型/账号/关联订单/任务列 | ✅ | 接口全部返回（control_routes.py:117-129） |
| 类型/账号筛选 | ✅ | user_id+type 参数已有 |
| 时间范围筛选 | ⚠️ | 需加参数 |
| 变动后余额列 | 🗄️ | 表无 balance_after 列。方案 a：加列+写入时落+窗口函数回填（零差额不变量保证可回填）；方案 b：查询期窗口函数现算 |
| 备注列 | 🗄️/⚠️ | 无 remark 列；可从关联订单/任务推导，或加列 |

### 05 客户详情 360° 🆕
| 内容 | 状态 | 说明 |
|---|---|---|
| 聚合详情端点 | 🆕 | 不存在；可前端拼装：customers（码+统计）、devices?user_id=（✅参数已支持）、orders?user_id= ✅、adjustments ✅、sessions ✅、unit-price ✅ |
| 余额四指标 | ⚠️ | 同 02 |
| 设备心跳/在线 | ⚠️ | 应取会话表 lease_until/last_heartbeat_at（✅ live 接口有）；devices.last_active_at 语义是"最后绑定时间"不可当心跳 |
| 生成趋势迷你图 | 🆕 | 无聚合端点 |
| 激活码有效期 | ⚠️ | 同 06（需 join 批次） |

### 06 激活码列表
| 内容 | 状态 | 说明 |
|---|---|---|
| search/status/batch_id/归档筛选 | ✅ | 参数全支持（admin_activation_routes.py:1020-1023） |
| batch_id/issued_at/掩码/绑定用户名/设备（含 last_active_at）/待批配对列 | ✅ | 全部返回（:1129-1143），此前 UI 未显示 |
| 有效期至列 | ⚠️ | 接口不 join 批次表；需加 expires_at（源自 batches.activation_expires_at） |
| 已过期筛选/标红 | ⚠️+🗄️ | **EXPIRED 状态从不落库**（过期码兑换时懒拒绝，status 停在 GENERATED/ISSUED，activation_code_routes.py:610-614）。建议接口层派生：JOIN 批次 WHERE activation_expires_at<now AND status IN (GENERATED,ISSUED)。不动状态机 |

### 07 发码中心
| 内容 | 状态 | 说明 |
|---|---|---|
| 生成即发放 | ✅ | **generate 已支持 auto_issue=true**（同事务 delivery+ISSUED+DELIVERED 事件，admin_activation_routes.py:325-351），仅前端未用；渠道要自定义需扩展参数（现固定 admin_console） |
| 有效期可配置 | ✅ | 批次创建 API 本就接受 activation_expires_at，前端硬编码一年 |
| 批次列表 | 🆕 | 无 GET batches 端点；表数据齐全（name/created_by/quantity/面值/额度/有效期/OPEN-CLOSED/creation_reason，027+033）；已发放/已激活计数需按码表聚合 |
| 发放记录列表 | 🆕 | 无 GET deliveries 端点；表有 channel/external_order_ref/recipient_ref/delivered_by_user_id/delivered_at/note（027:259-294） |

### 08 设备管理
| 内容 | 状态 | 说明 |
|---|---|---|
| 按客户/激活码/状态筛选 | ✅ | 参数全支持（admin_device_routes.py:95-99），此前 UI 未用 |
| slot_no/platform/bound_at/状态列 | ✅ | 已返回 |
| 所属客户用户名列 | ⚠️ | 接口单表查询不 join users（只给 user_id） |
| 激活码掩码列 | ⚠️ | 不 join activation_codes（只给 id） |
| 最近心跳列/在线徽章 | ⚠️ | devices 接口不查 last_active_at；且该列语义=最后绑定时间。真实在线/心跳应 join customer_session_state（lease_until/last_heartbeat_at） |
| platform 筛选 | ⚠️ | 需加参数 |
| 全量汇总卡 | 🆕 | 总数（接口 total 有）、在线（会话聚合）、强退/解绑计数需统计 |

### 09 生成记录
| 内容 | 状态 | 说明 |
|---|---|---|
| 现有字段（账号/项目/类型/模型/状态/错误码/成本/扣费） | ✅ | 接口返回（control_routes.py:141-163） |
| 耗时列 | ✅ | created_at/completed_at 都在，前端可算 |
| 任何筛选参数 | ⚠️ | 接口仅 limit/offset；且实现是 5 表各取一页内存合并——加过滤需重构为过滤下推+各表 COUNT |
| **设备/激活码维度** | 🗄️ | **任务表无 device_id/session_epoch/activation_code_id**；fence 证据只有不可逆 subject_digest（042:218-249）。要支持需在 fenced 提交事务落 device_id（上下文已有），历史不可回填，仅新数据生效 |
| 失败统计条 | 🆕 | 需聚合端点（可与仪表盘合并） |

### 10 会话管理
| 内容 | 状态 | 说明 |
|---|---|---|
| live/单客户会话全部列（心跳/epoch/租约/设备/槽位） | ✅ | 全部返回（admin_session_routes.py:78-94），此前 UI 未显示部分列 |
| 待批配对侧栏（全局列表） | 🆕 | 无独立端点（只能从激活码列表内嵌拼） |
| 强制下线按钮 | ⚠️ | 现有手段是吊销设备凭据/解绑（副作用大）；如需"仅踢会话不动设备"需新端点（revoke_session 服务函数已存在，复用即可） |

### 11 调账记录（独立页）
| 内容 | 状态 | 说明 |
|---|---|---|
| 金额/条数/来源单/状态/时间列 | ✅ | 列表已 join recharge_orders 取回（admin_customer_routes.py:649-662, 674-690） |
| 全局列表+筛选（操作人/来源单类型/时间） | ⚠️ | 现仅按客户+分页；需新全局查询参数 |
| 操作人用户名 | ⚠️ | 只返回 admin_user_id，需 join users |
| 调整前/后余额 | 🗄️ | **从未持久化**（wallet_balance_after 只在创建响应里）。admin_adjustments 加两列即可（append-only 触发器不挡 ALTER ADD COLUMN），写入时响应值直接落库 |

### 12 审计日志
| 内容 | 状态 | 说明 |
|---|---|---|
| 操作人用户名反解 | ✅ | actor_username 已返回（五源 UNION 都 join users） |
| 时间范围筛选 | ✅ | created_from/created_to 已有 |
| 目标客户用户名 | ⚠️ | target 只给裸 user_id，需加 join/反解 |
| 操作人/目标按用户名检索 | ⚠️ | 参数是 user_id；需支持 username（服务端解析） |
| 事件类型下拉 | ✅ | 参数是自由文本，类型集合已知，前端改下拉即可 |
| **变更明细（旧值→新值）** | 🗄️ | 源头没存：改单价有 old/new（metadata，admin_customer_routes.py:361-368）但 UNION SQL 不取；调账金额条数可从关联对象取；设备/激活码/设置事件无 before/after（表结构没有）。补法：新写入点统一把变更明细落 metadata/事件表（历史不可回填）；UNION SQL 先扩取已有键 |

## 三、后端补充工作清单（按改动层次）

### A. 零后端改动（前端直接做）
订单时间/渠道列、流水时间/关联列、激活码批次/发放时间列、设备筛选与 slot/user/code 列、会话心跳列、调账金额列、耗时列、审计 actor 列、发码有效期输入框、auto_issue 勾选（生成即发放）、快速发码真实 reason。

### B. 接口扩展（改现有 GET）
1. /customers：+status/注册时间/余额筛选；+display_name、钱包余额、设备槽位占用
2. /devices：+username、masked_code、在线状态（join 会话）；+platform 参数；+汇总计数
3. /activation-codes：+expires_at（join 批次）+派生"已过期"
4. /recharge-orders：+channel、时间范围参数
5. /wallet-transactions：+时间范围参数
6. /generation-records：+账号/状态/类型/时间过滤（含分页实现重构）
7. /audit-log：+target_username；+username 检索参数
8. /customers/{id}/adjustments：+admin_username
9. generate auto_issue：+channel/external_order_ref/recipient_ref 参数

### C. 新增端点
1. GET /dashboard/summary（今日生成+成功率+环比、7日趋势、活跃客户、今日充值、待办四项、槽位占用）——AdminReader 权限
2. GET /activation-code-batches（批次列表+创建人+已发放/已激活计数）
3. GET /activation-code-deliveries（发放记录列表）
4. GET /device-pairings/pending（全局待批配对）
5. （可选）POST /customer-sessions/{user_id}/kick（仅踢会话，复用 revoke_session）

### D. 数据层改动（需迁移或写入路径变更）
1. **生成记录设备归属**：generation_batches/tasks 加 device_id（fenced 提交时落），历史不可回填 → 决策项：09 页"设备"列是否必须
2. **balance_after**：wallet_transactions 加列+回填（推荐），或查询期窗口函数
3. **admin_adjustments 加 balance_before/after**
4. （可选）wallet_transactions 备注；设置变更写 old/new

## 四、口径修正与陷阱（实现时必须注意）

1. customers.created_at = 激活时间（aca.activated_at），非 users 注册时间——效果图"注册时间"语义上等价（激活即建档），展示名建议"激活时间"
2. credits_spent = SETTLE 流水笔数（COUNT），不是积分金额
3. customer_devices.last_active_at = 最后（重）绑定时间，登录/心跳不刷新——"最近心跳"一律以会话表为准
4. 设备"在线"唯一真源 = customer_session_state.lease_until > now()；status=BOUND ≠ 在线
5. EXPIRED 从不落库，过期判定必须 JOIN 批次 activation_expires_at 派生
6. 图像/源帧类任务 charged_credits 恒 0（仅视频走计费）
7. 新统计/列表端点一律 AdminReader（admin/auditor 可读），写扩展维持写契约（reason/confirm/Idempotency-Key）
