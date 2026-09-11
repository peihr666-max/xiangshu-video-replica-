# CW-002 — 平台与条件业务范围决议（已签认，owner 2026-09-09）

## 任务信息（§14 模板）

| 字段 | 值 |
| --- | --- |
| 任务/工作包 | CW-002 补齐平台与条件业务范围决议 |
| Owner / Reviewer | Owner：ZCode 代理（hlong026 会话，2026-09-09）；Reviewer：独立复核子代理 + 待产品负责人/架构负责人签认 |
| 分支 / 基线 SHA | `feat/customer-v3-cw02-platform-scope`（draft 钉 b211095）→ W0 批次 cherry-pick 到发布基线 `origin/main@df7020c`；2026-09-09 核实平台/范围/公平各项**决策**对 df7020c 仍成立，唯 client studio 三文件（types.ts/ContentPages.tsx/MainPages.tsx）与 test_customer_queue_fairness.py 经 b211095→df7020c 漂移，§3/§6 相关行号已按 df7020c 校正（generation.py:4491/4600/4644 与 oral_worker.py 未变动、行号仍准） |
| 上游规格段落 | V3 清单 §4 CW-002；§5 客户业务验收矩阵；§8 可量化阈值 |
| 改动文件 | `docs/evidence/CW002-SCOPE-DECISIONS.md`（新增） |
| 失败测试或回归锁定 | 不适用（决策与静态核验层） |
| 实现结果 | 见下文范围表 |
| 验证命令与通过数 | 静态核对：`grep`/文件行号逐项核对（见各表"依据"列） |
| 证据层级 | 决策与静态核验（签认前不得视为完成） |
| 安全与可观测性 | 不适用 |
| 迁移与回滚 | 纯文档，可整体回退 |
| 外部授权记录 | 无 |
| 未测试项 | 签认字段 |
| Lore 提交 SHA | 本 PR squash 后回填 |

## 1. 已确认边界（沿用既有决策，本项不重选型）

- 产品形态：客户桌面端（Tauri）+ 云端后端服务；不再维护独立内部产品线（V3 清单 §1 规则 1）。
- 数据库：全环境 PostgreSQL（开发/测试/CI/staging/生产），历史 SQLite 仅按精确例外用于独立 operator 与受保护输入。已由用户确认，本项仅承接。
- 数据库行为测试一律真实 PG；UI、纯逻辑及外部服务可受控替代（V3 清单 §1 规则 3）。

## 2. 支持平台决议（建议值，待签认）

| 平台 | 决议 | 依据 |
| --- | --- | --- |
| 客户桌面 — Windows 10/11 x64 | **保留（唯一支持桌面平台）** | CI 唯一桌面构建门禁为 `windows-2025` NSIS（`.github/workflows/ci.yml:146-149`）；客户包配置 `tauri.customer.conf.json` 仅含 Windows NSIS bundler 与 `customer-installer-hooks.nsh` |
| 客户桌面 — macOS | **不支持（本轮）** | 无 macOS 构建/签名/公证流水；Tauri 客户配置无 dmg/targets 声明。如需支持须按 CW-002 追加决议并登记 CW-022/023/046 平台差额 |
| 客户桌面 — Linux | **不支持（本轮）** | 同上，无 AppImage/deb 目标 |
| 后端服务 — Linux x86-64 | **保留** | `deploy/systemd/`、`deploy/customer-git-rollout.sh`、`deploy/postgres/` 全部以 Linux systemd/容器为目标 |
| 管理网页 — 现代浏览器（Chromium/Firefox/Evergreen） | **保留** | `client/src/admin/` 独立 React 页面，随服务器静态部署（CW-019 拆分后归属后端部署） |
| 移动端 | **不支持** | 无任何移动构建目标或适配工作包 |

## 3. 保留功能范围 — F01–F12 映射（CW-018 自动化与 CW-049 UAT 共同最小覆盖）

页面枚举依据 `client/src/studio/types.ts:8-29`（`StudioPage` 21 个页面值；df7020c 校正，draft 钉 b211095 时为 :3-24，types.ts +36/-3 漂移后移位，21 值不变）。

| ID | 业务 | 保留页面/入口 | 当前状态 | 范围结论 |
| --- | --- | --- | --- | --- |
| F01 | 激活、设备、会话和资料 | 客户状态机（`client/src/customer/`：激活/登录/冲突/失效/撤销/配对）+ `profile` | 已实现，整屏激活门禁 | 保留 |
| F02 | 工作台和项目 | `workbench` + 项目列表/详情 | 已实现（live.ts 接真实项目 API） | 保留 |
| F03 | 项目型视频复刻 | `replica`、`reference`（源帧/首帧/Prompt/批次） | 已实现 | 保留 |
| F04 | 独立视频创作 | `video` | 已实现（独立生成三模式） | 保留 |
| F05 | 人物、场景和首帧 | `people`、`person-ip`、`person-photos`、`person-avatars`、`person-voices`、`replacement` | 已实现 | 保留 |
| F06 | 口播与音频 | `oral`（文本）、`oral-audio`（音频） | 已实现 | 保留 |
| F07 | 文案提取与改写 | `copy` | 已实现 | 保留 |
| F08 | 素材库 | `materials` | 已实现 | 保留 |
| F09 | 爆款与收藏 | `viral`、`viral-detail` | 已实现（TikHub 真实数据） | 保留 |
| F10 | 任务和结果 | `tasks`、`task-detail` | 已实现 | 保留 |
| F11 | 钱包与充值 | `profile` 内客户钱包两个入口 | **已知缺陷**（两入口上下文不一致，CW-016 修复） | 保留（先红后绿） |
| F12 | 管理和经营看板 | `analytics`（客户仅本人）+ `client/src/admin/`（管理员） | 已实现 | 保留 |
| — | 发布管理（`publishing`） | `publishing` 页 | **未接通**：按钮为诚实提示"正式发布（接口未接通）"（`client/src/studio/ContentPages.tsx:2653-2657`；df7020c 校正，draft b211095 时为 :1764-1768，+1055/-166 漂移后移位，字符串不变）、"尚未连接发布账号 / 平台账号授权接口尚未接入"（`client/src/studio/MainPages.tsx:1782-1783`；df7020c 校正，draft b211095 时为 :1220 的"发布账号服务尚未接入"，+736/-61 漂移后移位且提示文案改写为 Empty 组件 title/description） | **09-09 原结论（不改写）**：不纳入本轮完工口径，保留诚实提示或按确认范围隐藏（V3 §5 发布管理条款）；若纳入须先补专用验收矩阵。<br>**2026-09-11 范围变更**：按 owner 决策改为**纳入，分两阶段**——第一阶段（CW-068）仅账号授权（抖音/视频号连接、密文落库、登录态探测、前端「发布账号」tab），第二阶段另立任务交付正式发布链路（records/worker publish round/封面/定时/published_total）。专用验收矩阵已按 §3 原要求补于本文 §8，CW-068 的 DoD 以 §8 第一阶段行为准。`publishing` 页与首页「累计已发布」指标属第二阶段，第一阶段保持诚实降级不变 |

## 4. 游客浏览门禁决议（CW-014 条件依据）

- **决议建议：不启用游客浏览，CW-014 登记为 N/A。**
- 依据：当前客户产品为整屏激活门禁——未激活/会话失效时仅渲染客户状态机（激活/配对/冲突/失效壳），身份建立成功后才挂载工作台；公开游客壳及"目标动作续接"从未实现；V3 清单 CW-014 明确"DEV ReviewWorkspace 不等同正式游客产品"。
- 影响：`publishing` 等未接通入口对未激活用户同样不可达，无需公开壳。
- 签认：待产品负责人确认。若改判启用，CW-014 转为开发项并补公开壳/私有动作门禁/一次续接全部用例。

## 5. 条件任务启用依据登记

| 条件任务 | 启用条件 | 当前事实 | 决议状态 |
| --- | --- | --- | --- |
| CW-014 游客激活门禁 | CW-002 明确保留游客浏览 | 整屏激活，无游客壳 | 建议 N/A（待签认，见 §4） |
| CW-034 保留客户PG（路线A） | 数据批次裁决选 A | 待 CW-005 真实数据盘点 | 保持 conditional |
| CW-035 空PG导入（路线B） | 数据批次裁决选 B | 待 CW-005；导入工具已存在（T07） | 保持 conditional |
| CW-036 选择性合并（路线C） | 数据批次裁决选 C | 待 CW-005；合并能力未开发 | 保持 conditional |
| CW-037 local 资产迁移 | 任一待保留数据存在 local/非共享持久对象 | 待 CW-031 收口后全量扫描 | 保持 conditional |
| CW-030 新增跨口播完整轮转 | CW-002 范围决定 | 现状：公平队列覆盖 H3/独立视频与口播（见 §6） | 本轮不新增公平能力，按现有限制验收（诚实登记限制） |
| 发布管理纳入 | CW-002 追加专用验收矩阵 | 未接通，诚实提示 | **09-09 原决议（不改写）**：不纳入（见 §3）。<br>**2026-09-11 变更**：条件已满足——专用验收矩阵见本文 §8，故改为**纳入，分两阶段**：第一阶段账号授权由 CW-068 交付，第二阶段正式发布链路另立任务；小红书第一阶段暂缓（三平台中唯一无自有实现） |

## 6. 跨任务公平范围

当前代码实际覆盖（CW-030 按此范围逐类验证，未覆盖类别如实登记限制）：

- **H3/独立视频队列**：每用户 running≤1（`server/app/generation.py:4600,4644` 调度条件 `running_tasks_count = 0`，超限时 `LEAST(...,1)` 收敛；generation.py 该二行 b211095→df7020c 未变动、仍准）、全局并发上限 `max_concurrent_h3_tasks=100`（runtime seed，`server/tests/test_customer_queue_fairness.py:138`；df7020c 校正，draft b211095 时为 :148，+2/-12 漂移后移位）、公平轮转 cursor（`server/app/generation.py:4491` 附近 = `_FAIR_QUEUE_MAX_ROUNDS = 8`@4492，未变动仍准；轮次上限测试见 `test_customer_queue_fairness.py:534`，df7020c 校正，draft b211095 时为 :544）。
- **口播队列**：`server/app/oral_worker.py:178,306,940` 复用同一 `user_queue_cursors` 轮转与 running≤1 模式。
- **未纳入公平队列的类别**：图片生成（character_image_generation）、分析/文案/ASR（analysis、script_rewrite、script_from_audio）当前无公平队列租约/轮转代码——本轮不扩展，CW-030 验收时逐类登记"无公平机制"的现状限制，不得以 H3 覆盖冒充。
- V3 §8/CW-047 的"A=1000/B=100/C=10"为 staging 负载验收的**建议基线数值**（未在代码中固化为常量），与本节代码现状机制分属两层，不得混写。

## 7. 签认记录

| 角色 | 结论 | 日期 |
| --- | --- | --- |
| 产品负责人（平台/游客/发布范围） | 已签认（owner phlong026 代签）：客户桌面仅 Windows 10/11 x64（macOS/Linux/移动端本轮不支持）；游客浏览门禁不启用、CW-014 登记 N/A；publishing 不纳入本轮完工口径（保留“接口未接通”诚实提示） | 2026-09-09 |
| 架构负责人（PG 范围/公平范围） | 已签认（owner phlong026 代签）：全环境 PG 唯一（遵 PG-01—12）；公平范围限 H3/独立视频+口播（已有队列），图片/分析/文案/ASR 无公平机制、本轮不扩展、如实登记限制不以 H3 冒充 | 2026-09-09 |
| 产品负责人（发布管理范围变更） | **追加签认（owner 决策，2026-09-11；上两行 09-09 原签认原文保留不改写）**：发布管理由「不纳入本轮完工口径」变更为「纳入，分两阶段」。第一阶段＝账号授权（CW-068）：抖音/视频号手工粘贴 Cookie 连接、Fernet 密文落库、异步登录态探测、前端「发布账号」tab 接线；正式发布链路（records/worker publish round/封面/定时/published_total）与 `publishing` 页留第二阶段另立任务；小红书暂缓。按 §3 原要求同步补齐 §8 发布管理专用验收矩阵，CW-068 DoD 以 §8 第一阶段行为准。真实平台发布/探测链路不在本次签认范围，需真实凭据人工授权，证据层级上限 AUTOMATED_VERIFIED | 2026-09-11 |

> 本文档决议已签认（owner phlong026，2026-09-09）；原草案约定：所有"待签认"字段由对应责任人确认后才可将 CW-002 在任务账本 §18 标记完成；签认前不得以本表替代 CW-018/CW-049 的逐项验收行。

> 2026-09-11 追加：§3/§5/§7 的发布管理范围变更由 owner 决策，原 09-09 签认原文逐字保留于上表，未改写。按 §3「若纳入须先补专用验收矩阵」的要求，专用矩阵见 §8；CW-068 的 DoD 以 §8.1 为准。

## 8. 发布管理专用验收矩阵（2026-09-11 追加）

发布管理分两阶段：**第一阶段＝账号授权（CW-068，本节验收）**，第二阶段＝正式发布链路（另立任务，见 §8.3）。后端用例全部落在 `server/tests/test_publish_accounts.py` 的**真实 PG lane**（CW-002 §1「数据库行为测试一律真实 PG」），前端用例落在 `client/src/studio/MainPages.test.tsx` 的 `describe("CW-068 发布账号管理（正式模式）")`（前缀对齐同文件既有的 `describe("CW-016 …")` 惯例）。

### 8.1 第一阶段验收行（CW-068）

| # | 验收项 | 契约要求 | 测试用例 |
| --- | --- | --- | --- |
| A1 | 账号连接（抖音） | 抖音必须同时提供 `cookie` 与 `security_sdk`；缺 `security_sdk` 返回 422 且 `detail.code == "PUBLISH_SECURITY_SDK_REQUIRED"` | `test_create_douyin_account_requires_security_sdk` |
| A2 | 账号连接（视频号） | `wechat_channels` 只需 `cookie`，响应 `security_sdk_required` 为 `False` | `test_channel_account_omits_security_sdk` |
| A3 | 连接成功回显 | 响应含 `platform`/`display_name`/`status == "connected"`；`GET /accounts` 能列出该账号 | `test_create_account_roundtrip_and_credential_never_returned` |
| A4 | **凭据不回传** | 任何 accounts 端点的响应体（含 `repr()` 全文）不得出现 cookie / security_sdk 明文，且不得存在 `cookie`、`security_sdk` 字段 | `test_create_account_roundtrip_and_credential_never_returned` |
| A5 | **密文落库** | `cookie_enc` 为 Fernet 密文（`gAAAAA` 前缀）且 ≠ 明文；`security_sdk_enc` ≠ 明文；明文不出现在库中任何位置 | `test_cookie_is_encrypted_at_rest` |
| A6 | **用户隔离（读）** | `GET /accounts` 只返回本人账号，他人账号不可见 | `test_accounts_are_user_scoped` |
| A7 | **用户隔离 + 解绑** | 他人 `DELETE /accounts/{id}` 返回 404（不泄露存在性）；本人返回 200 且 `deleted == True`；解绑后列表为空 | `test_delete_account_is_owner_scoped` |
| A8 | **探测发起 + 用户隔离** | 本人 `POST /accounts/{id}/verify` 返回 200 且 `submitted == True`、`verify_requested` 落 1；他人同一请求返回 404 | `test_verify_request_marks_account` |
| A9 | 探测租约与回写 | `claim_account_verify_work` 返回 `kind == "account_verify"` 租约；同一请求二次 claim 返回 `None`；`finalize_account_verify(ok=False)` 后 `status == "invalid"`、`verify_requested == 0`、`error_message` 落库 | `test_account_verify_claim_and_finalize` |
| A10 | **探测并发抢占（PG 专有）** | 两条独立 PG 连接并发 claim 同一 verify 请求时，`FOR UPDATE SKIP LOCKED` 语义下只有一个 worker 拿到租约，另一个返回 `None`（SQLite lane 因翻译层移除 `FOR UPDATE [SKIP LOCKED]` 无法覆盖，此项为迁 PG 的收益） | `test_verify_claim_skip_locked_across_concurrent_connections` |
| A11 | worker 轮次闭环 | `run_publish_round` 走完 claim → `_dispatch_probe` → finalize；`processed == 1`；probe 收到解密后的真实 cookie 与正确 platform；账号转 `invalid` 且 `error_message` 落库 | `test_worker_round_verifies_invalid_account` |
| A12 | **范围切分锁** | verify claim 在**只有 `publish_accounts`、没有 `publish_records`** 的库上正常工作，证明 `_quarantine_expired_verifies()` 已与 records 解耦（原 `_quarantine_expired_publishes()` 同时 UPDATE 两表，会在本阶段范围下崩） | `test_claim_verify_does_not_touch_publish_records` |
| A13 | 迁移链 | `082_publish_accounts` 为唯一 head、`down_revision == "081_oral_unit_price"`；只建 `publish_accounts`（含 lease 三件套与 `idx_publish_accounts_user_created`），不建 `publish_records`；`platform IN ('douyin','wechat_channels')`、`status IN ('connected','invalid')`、`verify_requested IN (0,1)` 三条 CHECK 生效；`downgrade()` 只 drop `publish_accounts` | 10 个测试文件的 head 断言（`test_db.py` 4 处 / `test_activation_code_schema.py` / `test_character_domain.py` / `test_characters.py` / `test_customer_devices.py` / `test_internal_billing.py` / `test_postgres_migrations.py` / `test_recharge_orders.py` / `test_settings.py` / `test_cw056_supported_head_matrix.py`）。其中 `test_cw056_supported_head_matrix.py` **不是纯机械替换**：除 `HEAD_REVISION` 外还须同步 CW-056 冻结矩阵——`HEAD_SCHEMA_COUNTS`（tables/primary_keys 76→77、columns 894→909、check_constraints 221→224、foreign_keys 145→146；`partial_indexes` 25 与 `triggers` 18 不变，因 082 两个索引均非 partial、未加触发器）、`HEAD_TABLE_NAMES` +`publish_accounts`、`HEAD_SCHEMA_DIGEST` 于真实 PG 16-alpine 重算为 `a23fa2756885009a3faa9af9d73472c21667bbce057283cdbf3d64dd456bf071`、`LATE_TABLES_AFTER_PUBLISHED_HEAD` +`publish_accounts`（链尾迁移建表，是「失败不留半结构」的最强哨兵）。CW-056 `test_published_migration_chain_bytes_are_frozen` **零回归**：`PUBLISHED_HEAD_REVISION` 仍为 `055_customer_batch_visibility` 未动，已发布链 bytes 冻结不受追加 082 影响（链总长刻意不冻结） |
| A14 | **前端接线** | `profile` 页「发布账号」tab 移除「平台账号授权接口尚未接入，暂不可添加账号。」与「发布账号服务尚未接入」占位；平台选择 / Cookie 粘贴（抖音额外 security_sdk）/ 连接提交 / 账号列表（昵称·平台·状态·最后校验时间）/ 发起校验 / 解绑六个动作全部接 `live.ts` 真实调用 | `连接发布账号：填写 Cookie 后提交并回显列表`、`抖音未填 security_sdk 时给出明确提示`、`未接通占位提示已移除`、`发起校验与解绑走真实接口并刷新列表` |
| A15 | **前端凭据不回显** | 提交后的 DOM（含账号列表行与表单残值）不得出现已提交的 cookie / security_sdk 明文 | `凭据明文不出现在 DOM` |
| A16 | 供应商静态门口径 | `app/publishers/vendor/**` 排除出 ruff check / ruff format / mypy（第三方源码不参与本仓口径）；secret 扫描仍覆盖该目录，且沿用分支已主动排除含 PEM 模板的 `ucenter_ticket.umd.js` 的裁剪结果，不重新引入 | `uv run ruff check .` / `ruff format --check .` / `mypy app` 全绿 + CI secret 扫描门 |

### 8.2 第一阶段明确不验收（诚实登记，不得冒充）

- **正式发布链路全部留第二阶段**：`publish_records` 表、records 6 个端点、worker publish round（`_PUBLISH_CANDIDATE_SQL`/`claim_publish_work`/`prepare_publish_work`/`finalize_publish_work`/`_dispatch_publish`/`perform_publish_delivery`）、封面资产、定时发布、平台 item id / 短链回写、`published_total`、`publishing` 页。
- **首页「累计已发布」指标保持 `review ? "156" : "—"` 诚实降级不变**——`published_total` 属 records 范围；本阶段仅在该处补注释说明待第二阶段。
- **小红书暂缓**：三平台中唯一无自有实现，另立后续任务；`platform` CHECK 约束只含 `douyin`/`wechat_channels`。
- **真实平台探测/发布链路未测**：按硬红线需真实凭据人工授权。本阶段全部用例使用合成凭据（`sessionid=douyin-test-cookie-value; ttwid=1` + `"0"*32`），`_dispatch_probe` 在测试中被 monkeypatch 替换，**不触网**。证据层级上限 **AUTOMATED_VERIFIED**，不得标 PRODUCTION_GO。
- **`publish_to_douyin` / `publish_to_channels` 为 CODE_PRESENT 未验证**：随 `publishers/` 内聚单元一并搬入（探测经 `_load_publisher()` 内联 import vendor，无法只留 `base.py`），但本轮无调用方、不由任何测试覆盖。
- **服务端运行前置**：抖音签名依赖外部 **Node.js ≥ 18**（`_require_node()` 用 `shutil.which("node")` fail-fast，缺失时返回可读中文提示）。属部署前置条件，不由本矩阵用例覆盖。

### 8.3 第二阶段追加要求

第二阶段任务开工时须在 §8.1 之后追加验收行并重新取得产品负责人签认，届时至少覆盖：records 草稿持久化与生命周期（draft→queued→publishing→published/failed/cancelled）、资产与封面归属校验、定时与状态 claim 条件、同账号发布串行化而其他账号可并行、发布成功回写平台 item id/短链、发布失败可置账号 invalid、`published_total` 真实计数、`publishing` 页正式动作解锁，以及 §3 表中 `publishing` 行结论的再次更新。不得以本阶段矩阵冒充第二阶段验收。

