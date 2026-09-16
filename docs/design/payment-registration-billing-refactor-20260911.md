# 支付·注册·计费重构技术方案（CW-065 · 2026-09-12 修订）

> **来源**：所有者 2026-09-08 ~ 09-11 五轮口头需求（微信官方支付、设备解耦、注册+API Key、消耗折扣、全接口成本/售价+端点可换+成本版本号）。
> **蓝本**：现有 W8–W11 成本计费底座（迁移 056/057/058/059/081）、`docs/design/admin-redesign/requirements-cost-billing-and-features-20260904.md`（需求 2 / R5 / R10 直接延续）。
> **修订记录**：2026-09-12 根据 DOC-REVIEW-PAYMENT-20260911 评审报告修订——CW 编号顺延 +5（CW-060~064 已被占用）、迁移号顺延 +1（082 被 CW-062 预定）、补 admin_adjustment、补认证三轨×SES-04 会话围栏整合设计、补 P1 修正。
> **前提**：**无存量客户，全新开发**——可直接删除激活码模块、重构计费表，无数据迁移与灰度负担。
> **流程**：接续账本 CW 编号、从 main 切 worktree、测试先行（TDD 红→绿）、单任务单 PR、squash 合并。
> **关键事实依据**：`server/app/settings.py`（ProviderName 8 供应商、REQUIRED_PROVIDER_FIELDS）、`server/app/operation_costs.py`、迁移 056/059/081、`server/migrations/versions/`（**当前链头 = 081_oral_unit_price，074–081 已占用**）。

---

## 0. 背景、范围与全局红线

### 0.1 五大需求来源

| # | 需求 | 落地 Phase |
|---|---|---|
| 1 | 增加微信官方支付，后台可切换/并存 zpay 与微信 | Phase 1–2 |
| 2 | 取消「一个激活码绑两台机器」限制 | Phase 3 |
| 3 | 改为用户注册 → 用户中心 → 自动生成 API Key → 绑 Key 充值 | Phase 4 |
| 4 | 纯积分制、用多少充多少；视频生成成本可打折（消耗侧折扣） | Phase 5 |
| 5 | 每个涉及 API 调用的接口后台可配成本+售价、端点(base_url+api_key)可换、成本版本号、一条视频真实成本(admin)/售价(用户) | Phase 8 |
| — | 删除激活码模块（需求 3 的反面） | Phase 6 |
| — | 测试与上线 | Phase 7 |

### 0.2 无存量客户前提（已与所有者确认）

- 激活码模块**直接删除**，不保留只读兼容、不做 sunset 端点、不写迁移脚本。
- 计费/费率表可**重构而非兼容**（如 `recharge_orders.provider` CHECK 直接移除 `activation_code`）。
- 无需 feature flag 灰度切换。

### 0.3 全局红线（不可违背，贯穿所有 Phase）

- **R-A 成本泄露面**（延续 2026-09-04 R10）：真实成本 `cost_price_fen`、毛利、上游科目**只允许出现在管理端**（admin/auditor）；任何客户泳道 API **物理不返回**成本字段（不是前端隐藏）。客户侧费用预估只能用对外售价 `user_price_fen` 计算。
- **R-B 迁移不可篡改**：已发布迁移（≤081）冻结不动，放宽约束/改形状一律**新迁移追加**；SQLite 无 `ALTER CONSTRAINT`，内部 P0 通道走表重建；有按秒/按版本流水后 `downgrade` 必须 `RuntimeError` 拒绝（039 先例）。
- **R-C 管理写契约**：所有后台写操作走 `confirm + reason + Idempotency-Key + audit_logs`（T12 precedent），auditor 只读。
- **R-D 历史账目冻结**：任务下单时冻结费率/折扣/版本快照，事后改配置**不重算历史**（沿用 059 snapshot 机制）。
- **R-E 并发扣款**：PostgreSQL 行锁 + 原子 CAS（`UPDATE wallets ... WHERE available >= N`），**不引入 Redis**（已确认 PG 足够）。

---

## 1. 现状基线（已实现能力盘点）

### 1.1 支付与钱包 🟡

- **ZPay 聚合支付**：`zpay.py`（MD5 签名、`submit.php`/`mapi.php`/`api.php`）+ `payment_routes.py`（`GET /api/payments/zpay/notify|return`）+ `zpay_payments.py`（`confirm_recharge_payment` 九道校验入账，含 :93 `provider != "zpay"` 硬校验）。
- **钱包模型**：`wallets`（available_credits + reserved_credits）+ `wallet_transactions`（CHARGE/RESERVE/SETTLE/RELEASE，022 建、057 放宽形状 CHECK 支持按秒）。
- **充值下单**：`recharge_routes.py`（内部 `POST /api/recharge-orders`、客户 `POST /api/customer/recharge-orders` 走 T14 密封信封、`payment-code` 生成二维码、`DELETE` 关单）。

### 1.2 计费（双阶段 + 按秒）✅

- `internal_billing.py`：`reserve_internal_billing(seconds)` → `finalize_internal_billing(outcome)`；口播 `reserve_oral_billing`/`finalize_oral_billing`；悬挂清理 `reconcile_dangling_billing_reservations`。
- 幂等键：`reserve:{task_id}:{billing_round}`、`oral-{SETTLE|RELEASE}:{task_id}:{billing_round}`。
- **预扣→成功结算/失败退款已是现状**，需求 4 的扣费模型无需改核心逻辑。

### 1.3 成本/售价费率底座（W8–W11）🟡

- `operation_cost_rates`（056）：9 科目（7 上游成本 + 2 对外售价），PK=subject，`admin_rate_routes.py` 读写、`KNOWN_RATE_SUBJECTS` 硬编码。
- `operation_cost_records`（059）：追加式成本账本，`begin/complete_operation_cost`，冻结 `unit_price_fen` + `usage_amount` → `cost_fen`，状态 PENDING/ACTUAL/UNKNOWN。
- `generation_tasks` 快照列（059）：`cost_rate_subject_snapshot`/`cost_unit_price_fen_snapshot`/`external_unit_price_fen_snapshot`/`actual_output_seconds`/`cost_status`。
- `daily_external_prices`（058）：每日视频对外售价（利润总览收入口径）。
- `runtime_settings` 计费：`internal_base_unit_price_fen`/`charged_unit_price_fen`/`oral_unit_price_fen`(081)/`min_recharge_fen`/`recharge_step_fen`。
- **局限**：仅围绕「视频生成」单点；对外售价只覆盖视频生成；5 个接口成本未入账本；无「一条视频」聚合；无成本版本号。

### 1.4 供应商与外部 API 全景（Phase 8 的改造对象）🔴

**8 个注册供应商**（`settings.py` `ProviderName`），对应 **9 个可计费内容接口**：

| # | 功能 | 模块 | 供应商 | 硬编码 base_url | 计费单位 | 现状成本 | 现状售价 | 成本入账本 |
|---|---|---|---|---|---|---|---|---|
| 1 | 爆款视频提取 | `viral_tikhub.py` | tikhub | `api.tikhub.io` | 次 | ❌ | ❌ | ❌ |
| 2 | 链接提取(去水印) | `viral_link.py` | douyidou | `gateway.diadi.cn` | 次 | ❌ | ❌ | ❌ |
| 3 | 文案提取(ASR) | `asr.py` | dashscope | `dashscope.aliyuncs.com` | 秒/次 | ❌ | ❌ | ❌ |
| 4 | 文案改写 | `script_rewrite.py` | deepseek | 服务端固定 | 次/token | ❌ | ❌ | ❌ |
| 5 | 视频拆解 | `analysis.py` | apilio(Gemini) | `api.apilio.ai` | 秒 | ✅ `video_analysis_768p/2k` | ❌ | ✅ |
| 6 | 图像·首帧 | `first_frames.py` | apilio(Gemini) | `api.apilio.ai` | 张 | ✅ `first_frame_image` | ❌ | ✅ |
| 7 | 图像·角色 | `character_image_generation.py` | apilio(Gemini) | `api.apilio.ai` | 张 | ✅ `character_sheet_image` | ❌ | ✅ |
| 8 | 视频生成 | `generation.py` | metaso(MiniMax H3) | `metaso.cn` | 秒 | ✅ `video_generation_768p/2k`+`context_ir` | ✅ `external_price_768p/2k` | ✅ |
| 9 | 数字人口播 | `oral.py`/`hifly.py` | hifly | `hfw-api.hifly.cc` | 秒/条 | ❌ | ⚠️ 扁平 `oral_unit_price_fen` | ❌ |
| — | 对象存储 | `storage.py` | cos | 腾讯云 | GB/次 | ❌（**不计入**，所有者确认 COS 不纳入计费） | — | ❌ |

- **api_key 已可配**（加密 `provider_settings`）；**deepseek 与 dashscope 已支持从 provider_settings 配置 base_url**（`script_rewrite.py:378`、`asr.py:371-379`）；其余 **base_url 硬编码**（7 处常量），其中 metaso（`generation.py:6346` host 校验）与 douyidou（`viral_link.py:70` 域名白名单 `gateway.diadi.cn`）为换端点关键阻碍。
- 异形认证：douyidou=`app_id+app_secret`、cos=`access_key_id+secret_access_key+bucket+region`、apilio=无强制字段。
- **R5 输入侧成本科目**（延续 2026-09-04）：秘塔计费不止输出秒数——参考视频按输出分辨率同价计秒费、图片超 5 张 0.05 元/张、Context IR 0.05 元/次、768P→2K 再生成 0.06 元/秒。Phase 8 费率实体必须含输入侧科目，拆解任务需落「参考视频时长」用量。

---

## 2. 目标架构

### 2.1 支付网关抽象（PaymentProvider）

```
PaymentProvider (Protocol)
  ├─ create_order(order, amount, channel) -> ProviderOrder(code_url/pay_url/...)
  ├─ query_order(provider_trade_no) -> ProviderOrderStatus
  └─ handle_webhook(request) -> WebhookResult(verified, trade_no, amount)

registry: {"zpay": ZPayProvider, "wechat_native": WeChatNativeProvider}
```

- `recharge_orders.provider` 放开为 `zpay | wechat_native | admin_adjustment`（移除 `activation_code`，**保留 admin_adjustment**——管理端 AdjustmentsPage 免费赠额路径，见 026 migration §3.1 核对清单）。
- 全局并存，用户下单时选支付方式（决策：全局并存）。
- ZPay 现有逻辑迁入 `ZPayProvider`；微信新建 `WeChatNativeProvider`。

### 2.2 认证三轨

| 轨 | 主体 | 凭证 | 用途 |
|---|---|---|---|
| Admin session | 管理员/审计员 | 现有 session | 后台 |
| Customer password | 客户 | scrypt 密码 + Bearer session | 注册/登录/用户中心 |
| API Key | 客户程序 | `xsk_live_<8prefix>_<40 base62>`，HMAC-SHA256 digest 存储 | 充值/查询接口 |

- API Key 白名单端点：`POST /api/customer/recharge-orders`、`GET /api/customer/recharge-orders/*`、`GET /api/customer/wallet/*`、`GET /api/customer/pricing`（不含注册/登录/密钥管理自身）。
- API Key 明文只显示一次，库内只存 digest。

### 2.3 计费域全景

```
充值（zpay/微信）→ wallets.available_credits
                          ↓ reserve（预扣，按秒×对外价×折扣）
                       reserved_credits
                          ↓ finalize
              成功 SETTLE（实扣）/ 失败 RELEASE（退款）

成本侧（admin only）：每次外部 API 调用 → operation_cost_records（冻结 version+值）
                          ↓ 按 project_id 聚合
                    一条视频真实成本（后台报表）
```

- **折扣**（Phase 5）：消耗侧折扣，`reserve` 时 `ceil(billed_seconds × discount_rate)`；多折扣源互斥取优先级最高；任务提交冻结 `discount_rate_snapshot`。
- **全接口成本/售价**（Phase 8）：`interface_price_versions` 激活版决定 cost/price；端点可换驱动成本变化。

#### 四层价格叠加顺序

既有代码已存在三层定价 + 本次新增折扣，形成四层价格体系，叠加顺序定义如下：

```
充值阶段（recharge_orders）：
  customer_unit_prices（按客户定价，044 迁移已存在）→ 决定充值换算比
  若无 → runtime_settings.recharge_step_fen（全局兜底）

消耗阶段（reserve/finalize）：
  1. 取 interface_price_versions 激活版的 user_price_fen（接口版本价）
  2. 若该接口/客户有 customer_discounts（消耗侧折扣）
     billed_fen = ceil(seconds × unit_price × discount_rate)
  3. 冻结 discount_rate_snapshot（R-D）
```

**互斥规则**：
- `customer_unit_prices` 作用于充值换算（充 N 元得 X 积分），`customer_discounts` 作用于消耗扣减——两者不同阶段、不互斥
- 同一接口多个激活折扣源时：取优先级最高者（priority 值越小越高）
- 同 priority 多行时行为写入 CW-080 验收标准（建议取折扣率最大者）

**旧表处置**（CW-089/095）：
- `operation_cost_rates` 9 科目迁移到 `interface_price_versions`（回填成本与售价），旧表保留只读兼容一段时间后废弃
- `generation_tasks` 旧快照列（cost_rate_subject_snapshot 等 5 列）新增 `price_version` 引用，旧列保留不删（R-B）
- `daily_external_prices`（利润总览收入口径）切换到 `user_price_fen`，CW-091 补口径影响评估

### 2.4 可见性隔离（R-A 落地）

| 数据 | 后台 | 用户中心 |
|---|---|---|
| 每接口成本 `cost_price_fen` | ✅ | ❌ 物理不返回 |
| 每接口售价 `user_price_fen` | ✅ | ✅ 价目表 |
| 一条视频总成本 | ✅（project_id 聚合） | ❌ |
| 一条视频总价 | ✅ | ❌（所有者确认：用户中心仅价目表，不含总价） |

### 2.5 认证三轨与 SES-04 会话围栏整合设计（评审 P0-4 补章）

> **背景**：既有 `customer_fence.py` 的 `fenced_pg_transaction` / `BusinessDb.write()` 全链路以 `customer_session_state` 的 (user_id, **device_id**, session_id, epoch, lease) 元组为锚点（`customer_fence.py:86-101, 369-383`）。Phase 4 新增密码登录与 API Key 后形成三轨认证，必须回答每条轨如何与围栏接合。

#### A. 密码登录会话（Customer Password Session）

**决策**：密码登录时自动创建「虚拟设备」——每个用户一个系统生成的 `device_id`（格式 `"session-{uuid}"`），写入 `customer_session_state` 表，围栏比较正常运作。

- `customer_session_state.device_id` 列须确认可接受虚拟设备 ID（当前 schema 可能 NOT NULL 但无格式约束）。
- 登录成功后签发 session token（复用既有 `_token_digests` 机制，但密钥管理须先完成 §2.5.C 的围栏去激活码化）。
- 虚拟设备不可被用户管理（不是物理设备、不出现在设备列表），仅在会话围栏内部使用。
- **优势**：零新 code path——`customer_session_snapshot()` → `fenced_pg_transaction()` → `BusinessDb.write()` 全部复用；踢人/lease/并发锁语义一字不改。

#### B. API Key 认证（独立泳道）

**决策**：API Key 不经过会话围栏——新增 `ApiKeyUser` 依赖注入，从 `Authorization: Bearer xsk_live_...` 解析 → prefix 查 `customer_api_keys` → HMAC-SHA256 比对，走独立事务路径。

- API Key 白名单端点（充值/查询钱包/价目表）路由注入 `ApiKeyUser`，不走 `customer_session_snapshot`。
- `BusinessDb` 新增 `write_for_api_key(user: ApiKeyUser)` 方法——走独立 PG 事务（不调用 `fenced_pg_transaction`），保留行锁（`FOR UPDATE` 钱包行）。
- **安全论证**（须写入证据文档）：API Key 泳道接受以下风险——
  1. 无设备绑定（不能防止 key 泄露后的跨设备滥用——缓解：key 明文只显示一次 + 限速 + 可吊销）
  2. 无踢人语义（不能抢占 session——缓解：key 粒度独立，吊销即失效）
  3. 无 session lease 过期（key 本身可设 `expires_at` 或无限期，由客户管理）
- API Key 泳道安全配套：复用 `security_rate_limit.record_auth_failure` 做 key 尝试限速；响应 DTO 字段白名单与 R-A 对齐（严禁泄露 `cost_price_fen`）。

#### C. 围栏去激活码化（Phase 6 前置，CW-084 首批）

`customer_session_snapshot()` 当前依赖激活码服务（`customer_fence.py:42, 142`——`from app.activation_code_service import ActivationKeyError`；`_token_digests` 密钥管理挂在 `activation_code_service`）。

**在 CW-084 实施前不可删除激活码模块**。CW-084 须先完成：
1. `_token_digests()` 密钥管理独立化——移入 `customer_device_service` 自身或新模块 `session_keys.py`
2. `ActivationKeyError` 替换为会话域专用异常（`SessionKeyError`）
3. 围栏链路全部 17 个 app 文件 + 29 个测试文件（~46 文件引用面）逐一核验无残留 `activation_code_service` 导入

#### D. 注册用户首台设备初始化路径

注册（CW-076） → 登录（CW-077） → 虚拟设备自动创建。首台物理设备绑定路径：保留既有配对审批流（037/038 迁移 + PairingApprovalCard）——注册后首台设备免审批直绑（CW-073 明确），后续设备仍需审批。

---

## 3. 数据模型与迁移号分配（**修正撞号：083–096**）

### 3.1 迁移总表

> ⚠️ **重大修正（2026-09-11）**：旧任务清单写的 074–087 **全部与现有迁移撞号**（074–081 已被占用）。
> ⚠️ **二次修正（2026-09-12）**：082 已被 CW-062（publish-accounts，claim.json line 44 `082_publish_accounts.py`，down_revision=081_oral_unit_price）预定——支付域从 **083** 起步。CW-062 预计先合入，083 的 down_revision 指向 `082_publish_accounts`。
> 每 Phase 开工前须 `ls server/migrations/versions/ | sort` + 扫描 `.git/codex-task-claims` 核对实际链头与占号。

| 迁移 | Phase | 内容 |
|---|---|---|
| 083 | 1 | `recharge_orders.provider` 放开（zpay/wechat_native/**admin_adjustment**，移除 activation_code）+ 微信订单字段（prepay_id/code_url/transaction_id）；同步核对 026 复合约束（provider/status/pricing_scope 联动）与 054 金额约束在新枚举下的行为 |
| 084 | 1 | 支付通道配置（`payment_channels` 表或 provider_settings 增 wechat 段）+ 启用开关；若 wechat 走 provider_settings，须同步扩 `ck_provider_settings_supported_provider` 白名单（069 先例：056 漏 zpay 致支付配置保存被拒） |
| 085 | 2 | 微信支付商户配置（mchid/serial_no/api_v3_key/私钥路径，加密存储） |
| 086 | 3 | 移除 `MAX_DEVICE_SLOTS`：`customer_devices` 去 slot 唯一约束、增 per-user 上限列 |
| 087 | 3 | 设备上限可配置化（runtime_settings 或 per-customer） |
| 088 | 4 | 注册：`customer_password_credentials` 独立凭据表（沿 043 先例：scrypt + FK users.id + credential_version/password_changed_at）；`users` 增注册来源字段；注册复用 `users.username` 全局唯一列（客户与管理员共享命名空间，见 §2.5 认证设计决策） |
| 089 | 4 | `customer_api_keys` 表（key_prefix/key_digest/HMAC-SHA256/key_version/scopes/label/revoked_at） |
| 090 | 5 | `customer_discounts` 表（折扣率/优先级/有效期/适用接口范围） |
| 091 | 5 | `generation_tasks.discount_rate_snapshot` |
| 092 | 5 | `wallet_transactions.discount_rate`（ADD COLUMN 即可，不触碰 057 形状 CHECK——形状 CHECK 只约束 recharge_order_id/task_id/billing_round 组合；若需约束「仅 RESERVE/SETTLE 行非空」才走表重建） |
| 093 | 6 | 围栏去激活码化（独立化 `_token_digests` 密钥管理、抽离 `ActivationKeyError`）+ 删除激活码 5 张表 + 清理 `recharge_orders.provider` CHECK 残留 |
| 094 | 8 | `billable_interfaces` 目录 + `provider_settings` 增 `base_url`（加密 JSON 加键无需 schema 变更，需配套配置读写/校验逻辑） |
| 095 | 8 | `interface_price_versions`（成本版本号）；`operation_cost_rates` 9 科目处置方案（废弃/共存/回填到新表） |
| 096 | 8 | `operation_cost_records` 增 `project_id` + `price_version` |

### 3.2 关键 schema 要点

**billable_interfaces（094）**
```
interface_key   TEXT PK      -- 'video_generation'
display_name    TEXT         -- '视频生成'
provider        TEXT         -- 'metaso'（关联 provider_settings）
category        TEXT         -- extraction/analysis/generation/oral
unit            TEXT         -- second/image/call/token
enabled         BOOLEAN      -- 预留：注册但未启用的未来接口
sort_order      INT
updated_by_user_id / updated_at
```

**interface_price_versions（095）**
```
interface_key   TEXT FK
resolution      TEXT NULL    -- 768P/2K 或 NULL
version         INT          -- 成本版本号（自增）
cost_price_fen  INT          -- 成本（仅后台）
user_price_fen  INT          -- 售价（用户中心）
is_active       BOOLEAN      -- 同 (interface,resolution) 仅一个激活
effective_at / created_by / note / deleted_at（软删）
PK (interface_key, resolution, version)
```
- 编辑激活版 → 派生新 version（旧版留血缘）；草稿版就地改；删除=软删 `deleted_at`，被历史任务引用的版本永不硬删（R-D）。

**operation_cost_records 扩展（096）**
```
+ project_id     TEXT NULL   -- 一条视频聚合键（独立视频为 NULL，见 §7 协调点 3）
+ price_version  INT NULL    -- 用了第几版 interface_price_versions
```

**customer_api_keys（088）**
```
id / user_id / key_prefix(8) / key_digest(HMAC-SHA256) / key_version
scopes JSONB / label / created_at / last_used_at / revoked_at
```

---

## 4. Phase 分解

### Phase 1 · 支付网关抽象层（CW-066~068，迁移 083/084）🔴
- **CW-066**：抽出 `PaymentProvider` Protocol + registry；ZPay 逻辑迁入 `ZPayProvider`。
- **CW-067**：`recharge_orders` schema 演进（provider 放开 + 微信字段 + **保留 admin_adjustment**）。
- **CW-068**：管理后台多通道配置（启用/停用 zpay、wechat_native）。
- 依赖：无（起点）。

### Phase 2 · 微信支付 V3 Native（CW-069~072，迁移 085）🔴
- **CW-069**：微信 SDK 选型评估——`wechatpayv3` SDK 加密栈与 `cryptography==50.0.0` 的 pin 冲突风险；备选 V3 Native 自实现（SHA256-RSA 签名 + AES-256-GCM 解密，用既有 cryptography 全部可实现）；写入决策记录。封装 `POST /v3/pay/transactions/native` → `code_url`；SHA256-RSA 商户私钥签名；平台证书自动下载+内存缓存+定时轮换。
- **CW-070**：回调路由——APIv3 密钥验签 + AES-GCM 解密；应答 `{"code":"SUCCESS","message":"..."}`（非纯文本）；幂等入账**重构 `confirm_recharge_payment`**（:93 `provider != "zpay"` 硬校验改为参数化 provider——抽公共入账核 + 各 provider 前置校验）；回调 URL 需 HTTPS 且在商户平台预配置（联调前置风险）。
- **CW-071**：商户配置 UI（mchid/serial_no/api_v3_key/私钥）。
- **CW-072**：客户端支付方式选择（zpay / 微信扫码）。
- 依赖：Phase 1。阻塞：微信商户主体需已申请（联调前置）。

### Phase 3 · 设备槽位解耦（CW-073~075，迁移 086/087）🟡
- **CW-073**：移除 `MAX_DEVICE_SLOTS=2`（`customer_device_service.py:59`）；`list_device_slots` → `list_user_devices`；明确配对审批流（037/038 迁移 + PairingApprovalCard）去留——建议保留审批流，注册后首台设备免审批直绑。
- **CW-074**：设备上限可配置化（默认 NULL=无限）。
- **CW-075**：前端设备管理页改造（`CustomerProfilePanel.tsx:306` 去 `device_slots_total ?? 2`，改设备列表视图）。
- 依赖：无（可与 Phase 1 并行）。

### Phase 4 · 注册 + API Key + 认证三轨整合（CW-076~079，迁移 088/089）🔴
- **CW-076**：注册端点（用户名+密码，无邮箱/手机验证）；原子创建 users + wallets + customer_password_credentials（scrypt，沿 043 先例独立凭据表）；注册复用 `users.username` 全局唯一列（客户与管理员共享命名空间——见 §2.5 认证设计决策）。
- **CW-077**：登录端点 + 失败锁定 + 密码会话虚拟设备（自动创建 `device_id="session-{uuid}"`，写入 `customer_session_state`，复用既有围栏比较逻辑——见 §2.5）。
- **CW-078**：API Key 生成/管理/Bearer 认证（`Authorization: Bearer xsk_live_...` → prefix 查 `customer_api_keys` → HMAC-SHA256 比对 → 注入 `ApiKeyUser`，不经过会话围栏——见 §2.5）；API Key 泳道安全配套：复用 `security_rate_limit.record_auth_failure` 做 key 尝试限速；响应 DTO 字段白名单与 R-A 对齐。
- **CW-079**：用户中心页面（含 Phase 8 价目表板块，见 §7 协调点 1）。
- 依赖：无（可与 Phase 1 并行）。

### Phase 5 · 消耗折扣（CW-080~083，迁移 090/091/092）🔴
- **CW-080**：折扣数据模型（`customer_discounts` + 快照列）；折扣存储类型（int 千分比 vs numeric）、`ceil` 取整方向（对客户不利需所有者确认）、优先级平局规则（同 priority 多行时行为）写入验收标准。
- **CW-081**：折扣计算 + `reserve/finalize` 改造（`ceil(seconds × unit_price × discount_rate)`，互斥优先级，提交冻结快照）。
- **CW-082**：管理后台折扣配置 UI。
- **CW-083**：客户端折扣展示。
- 依赖：Phase 1（钱包/计费基线）。与 Phase 8 同属计费域，迁移链需协调（§7 协调点 2）。

### Phase 6 · 激活码清理（CW-084~085，迁移 093）🔴
- **CW-084**：围栏去激活码化（`customer_session_snapshot` 中 `_token_digests` 密钥管理独立化、抽离 `ActivationKeyError` 依赖；`customer_fence.py:42` 等 17 个 app 文件 + 29 个测试文件共 ~46 文件引用面全量扫描）+ 删除后端——`activation_code_routes.py`(1180) + `activation_code_service.py`(717) + `admin_activation_routes.py`(1171) ≈ 3068 行；drop 5 张表；移除 `recharge_orders.provider` 的 activation_code。
- **CW-085**：抽取 `CustomerAccessBrand` 为独立组件（`LoginPage.tsx:2`、`DevicePairingPage.tsx:3` 依赖）+ 删除前端激活码页面 + 路由 + API；清理 `CustomersManagementPage.tsx:70` AdminActivationSection 挂载。
- 依赖：Phase 4（注册路径就绪后才能删激活）。

### Phase 7 · 测试与上线（CW-086~087）🔴
- **CW-086**：单元测试 + PG 矩阵（含折扣、含全接口成本）；R-A 的 CI 成本字段泄露扫描纳入验收项。
- **CW-087**：E2E + 微信沙箱联调 + 上线。
- 依赖：Phase 1–6、8 全部。

### Phase 8 · 全接口成本/售价 + 端点可换 + 成本版本号（CW-088~093，迁移 094/095/096）🔴
- **CW-088**：`billable_interfaces` 目录 + `provider_settings` 增 `base_url`；7 处硬编码 base_url 迁配置（`HiflyClient`/`ViralSourceClient` 等构造函数已预留 base_url 参数，传配置值；常量降级为默认兜底）；**metaso**（`generation.py:515,595,6346` 含 host 校验）与 **douyidou**（`viral_link.py:70` 域名白名单 `gateway.diadi.cn`）需额外处理 host 校验逻辑；`REQUIRED_PROVIDER_FIELDS` 增可选 base_url；每供应商同一时刻仅一个激活 base_url（**单渠道可换**，非多渠道并存路由），换端点走写契约+审计（R-C）；异形认证保留各自字段形状（所有者确认，仅统一 base_url 可配 + 加密）。
- **CW-089**：`interface_price_versions` 成本版本号——派生/激活/软删语义；下单取激活版并冻结 version+值。
- **CW-090**：5 个未入账接口（tikhub/douyidou/dashscope/deepseek/hifly）接入 `begin/complete_operation_cost` + project_id；`operation_cost_records` 增 project_id/price_version。
- **CW-091**：后台费率管理页重构（接口目录 CRUD + enabled 预留 + 版本管理 + 端点配置 UI）；去 `KNOWN_RATE_SUBJECTS` 硬编码；补利润总览（`admin_profit_routes.py`）口径影响评估（`daily_external_prices` 收入口径与 `user_price_fen` 切换）。
- **CW-092**：用户中心价目表（`GET /api/customer/pricing` 只返回 `user_price_fen`，成本物理不下发——端点实测不存在，全新开发）。
- **CW-093**：一条视频实际成本聚合报表（后台按 project_id 聚合，admin only）。
- 依赖：CW-088 → CW-089 → CW-090 → CW-093；CW-088+089 → CW-091/092。

---

## 5. API 契约（新增/改造）

| 端点 | 方法 | 泳道 | 说明 |
|---|---|---|---|
| `/api/customer/register` | POST | 客户 | 注册（用户名+密码，scrypt 加密，独立凭据表） |
| `/api/customer/login` | POST | 客户 | 登录 + 失败锁定 |
| `/api/customer/api-keys` | GET/POST/DELETE | 客户 | API Key 管理（明文只返回一次） |
| `/api/customer/recharge-orders` | POST | 客户/API Key | 下单（选 zpay/wechat_native） |
| `/api/payments/wechat/notify` | POST | 公开 | 微信回调（验签+解密+幂等入账） |
| `/api/customer/pricing` | GET | 客户/API Key | 价目表（仅 user_price_fen，**无成本**） |
| `/api/control/settings/interfaces` | GET/PUT | 管理 | 接口目录 + 端点 + 版本（写契约+审计） |
| `/api/control/settings/rates` | GET/PUT | 管理 | 重构为版本化（取代 9 科目硬编码） |
| `/api/control/cost-reports/per-video` | GET | 管理 | 一条视频成本聚合（project_id） |

---

## 6. 依赖图与并行策略（worktree）

```
Phase 1 ──→ Phase 2 ──┐
   │                   │
   ├──→ Phase 5 ───────┤
   │                   ├──→ Phase 7（测试上线）
Phase 3（独立）─────────┤
Phase 4 ──→ Phase 6 ────┤
Phase 8（088→089→090→093；091/092 并行）─┘
```

- **可并行**：Phase 1 / Phase 3 / Phase 4 / Phase 8-CW088 四条线无 schema 冲突，可同时开 worktree。
- **必须串行**：Phase 2←Phase 1；Phase 6←Phase 4；Phase 5 与 Phase 8 迁移链需协调（同域）。
- 迁移号 083–096 按 landing 顺序 linearize，避免多头。

---

## 7. 跨阶段协调点（红线）

1. **CW-092 与 CW-079 同一页面**：用户中心价目表（CW-092）是「用户中心页面」(CW-079) 的板块，CW-092 依赖 CW-079 或合并落地，禁止两人各建用户中心。
2. **Phase 5 与 Phase 8 迁移相邻**：折扣（090–092）与全接口成本（094–096）同属计费域，`wallet_transactions`/`generation_tasks`/`operation_cost_records` 有交叉；并行开发时迁移链必须协调 rebase 顺序，避免 down_revision 撞车。
3. **`project_id` 对独立视频为 NULL**：复刻流有 project_id，独立视频流（T2V/I2V/R2V，`independent.py`）project_id 为 NULL。CW-090/093 的「一条视频成本聚合」需为独立视频准备兜底归集键（建议 `batch_id`），否则独立视频聚合不出成本。
4. **R5 输入侧成本科目**：Phase 8 费率实体必须含参考视频秒费、图片超 5 张、Context IR、768P→2K 再生成等输入侧科目，拆解任务落「参考视频时长」用量，否则利润表系统性虚高。

---

## 8. 风险登记

| ID | 风险 | 级别 | 缓解 |
|---|---|---|---|
| P1 | 微信支付商户主体未申请，阻塞 Phase 2 联调 | 高 | 前置确认主体状态；SDK 封装可先于联调完成 |
| P2 | 迁移撞号（已发现 074–081 占用、082 被 CW-062 预定） | 高 | 本文档已重分配 083–096；每 Phase 开工前核对实际链头与 claims；合并时 linearize |
| P3 | 成本泄露（R-A） | 高 | 客户泳道 DTO 白名单字段；CI 加成本字段泄露扫描 |
| P4 | 费率手误（0.15→15）全体客户 10 倍扣费 | 中高 | 写契约 + 数值边界 + >50% 二次确认 + 变更审计 + 上线试算 |
| P5 | 折扣与按秒计费形状 CHECK 冲突 | 低 | 092 迁移 ADD COLUMN 即可（形状 CHECK 不触碰 discount_rate）——P5 降级；若需约束「仅 RESERVE/SETTLE 行非空」才走表重建（R-B） |
| P6 | 独立视频 project_id NULL 聚合缺失 | 中 | 协调点 3：batch_id 兜底 |
| P7 | 换端点后历史成本被重算 | 中 | R-D 冻结快照 + 版本软删不硬删 |
| P8 | 删除激活码误伤在用代码路径 + 围栏依赖 | 高 | ~46 文件引用面（17 app + 29 tests）；CW-084 围栏去激活码化为前置；删前全库引用扫描 + 测试兜底 |

---

## 9. 任务清单索引（CW-065 ~ CW-093）

> ⚠️ 编号已从 CW-060~088 整体顺延 +5 至 CW-065~093——CW-060（CLEANED，SQLite 隔离工具 #27）、CW-061（REVIEW，CI 分片守卫 #36）、CW-062（ACTIVE，发布账号授权，占迁移 082）、CW-063（CLAIMED，h3 开关，预留 CW-064）、CW-064（被 CW-063 预留，缺口 5 快捷入口）均已被占用。

- **CW-065**：本技术方案文档（Phase 0）。
- **Phase 1**：CW-066 / 067 / 068
- **Phase 2**：CW-069 / 070 / 071 / 072
- **Phase 3**：CW-073 / 074 / 075
- **Phase 4**：CW-076 / 077 / 078 / 079
- **Phase 5**：CW-080 / 081 / 082 / 083
- **Phase 6**：CW-084 / 085
- **Phase 7**：CW-086 / 087
- **Phase 8**：CW-088 / 089 / 090 / 091 / 092 / 093

**总计 29 个任务**（含 CW-065）。工作量估算：串行 30–41 天，按 §6 并行压缩后 16–22 天（CW-084 围栏去激活码化 ×2 后可能上浮至 18–26 天）。

---

## 附：本文档取代的旧口径

- 旧任务清单迁移号 074–087 **作废**，以 §3.1 的 083–096 为准。
- 用户中心「一条视频总价」展示**取消**（所有者确认：仅每接口价目表）；一条视频成本/价格归后台 project_id 聚合。
- 激活码「保留兼容/灰度」**取消**（无存量客户，直接删除）。
