# CW-010 — 补齐各任务类别的真实 PG 恢复基线

## 1. 任务信息（§14 模板）

| 字段 | 值 |
| --- | --- |
| 任务/工作包 | CW-010（W1）补齐各任务类别的真实 PG 恢复基线；DoD：所有保留异步任务类别均在 TEST-PG 多连接门禁通过，0 fail / 0 skip，数据库基线不得由 SQLite、mock 持久化或缺 PG 跳过充当 |
| Owner / Reviewer | Owner：ZCode 代理（hlong026 会话，2026-09-09）；Reviewer：独立 CodeReview 子代理（结论见 §7，无 Blocker，M1/M2/M3 + m1/m2/m3 + n1/n2/n3 全部落实）+ PR review |
| 分支 / 基线 SHA | `feat/customer-v3-cw010-pg-recovery-baseline`；基线 `origin/main@9a70918`（CW-009 #108 合并后） |
| 上游规格段落 | V3 清单 §18 CW-010 行；《客户版收敛剩余任务清单与验收完工标准-V3》CW-010（行 216–229）：仅做剩余（行 223）、5 命名文件（行 224）、增量验收四条计数（行 225）、保留验收底线（行 226）、完工标准（行 227）、必交证据（行 228） |
| 改动文件 | 4 文件 +2326/−2013：迁移 3 个仍以 `tmp_path` SQLite 建库的命名文件至各自专属 TEST-PG 库——`test_wallet_billing_service.py`（16 用例）、`test_oral_domain.py`（61 用例）、`test_independent_creation.py`（17 用例）；`pg_test_kit.py` +6（登记 3 个 CW-010 专属库名入 `RECORDED_TEST_DATABASES`）。另 2 命名文件 `test_worker_crash_recovery.py`（18）、`test_customer_queue_fairness.py`（12）为**已复用**（前序 CW 已真实 PG，本任务零触碰） |
| 失败测试或回归锁定 | 5 命名文件 124 用例即本项回归锁；缺 PG 硬门（`require_pg_or_explicit_skip`）在死端口下 123 errors + 退出码 1 + 0 skip 锁定"不得缺 PG 跳过"底线 |
| 实现结果 | §2 交付明细；§3 验证结果；§4 类别×状态×账务矩阵 |
| 验证命令与通过数 | 5 命名文件 **124 passed, 0 skipped**（34.42s）；`ruff check .` All passed；`ruff format --check .` 291 files formatted；`mypy app` Success 104 files；缺 PG fail-closed 退出码 1 / 0 skip。详见 §3 |
| 证据层级 | AUTOMATED_VERIFIED（真实 PG16 fixture `localhost:5433`，每用例独立多连接 `pg_transaction`；无 staging / 真实付费 Provider 依赖） |
| 安全与可观测性 | 无密钥/激活码明文/token 进入代码、日志或测试夹具；`RECORDED_TEST_DATABASES` allowlist + `assert_safe_test_database` 现覆盖 CW-010 三库的 `DROP … WITH (FORCE)`（n1）；拒绝审计（`security.role_denied`）在 PG 上持久化并被断言（m2） |
| 迁移与回滚 | 纯测试基建（server/app 生产代码零触碰）；回滚 = revert 本分支，不影响生产行为 |
| 外部授权记录 | 无（不涉及真实 ZPay / 付费 Provider / 生产 COS / 发码 / 灰度 / 公网发布；Provider 均为受控替身，真实付费属 CW-050） |
| 未测试项 | server 全量 pytest、`npm run check:tauri`（cargo）、`npm run build`、`npm audit`、客户浏览器 E2E —— 均**只在 CI 三门禁执行**；本任务 server/app 零触碰，全量回归交 CI（同 CW-009/CW-012 模式，且规避 dev server 占用共享 `customer_v3_test` 的并发互踩红线） |
| Lore 提交 SHA | 本 PR squash 后回填 |

## 2. 交付明细（对照 CW-010 仅做剩余 · 行 223）

| 验收要求（行 223 / 227） | 实现 |
| --- | --- |
| 钱包类别迁为 TEST-PG 独立多连接基线 | `test_wallet_billing_service.py` 迁至专属库 `cw010_wallet_billing_test`；RESERVE/SETTLE/RELEASE 差额、提交/回滚隔离、悬挂预留清扫全部走真实 PG，每逻辑块独立 `pg_transaction`（独立连接） |
| 口播类别迁为 TEST-PG 独立多连接基线 | `test_oral_domain.py`（61 用例）迁至 `cw010_oral_test`；consent/avatar/voice/task 生命周期、克隆 worker、租约过期释放、SUBMISSION_UNCERTAIN 保留、人工对账、`run_pg_worker_once` 生产 worker 环、路由契约全部真实 PG |
| 独立生成类别迁为 TEST-PG 独立多连接基线 | `test_independent_creation.py`（17 用例）迁至 `cw010_independent_test`；i2v/t2v/r2v 模式矩阵、幂等重放、钱包 RESERVE、PG worker、能力/保存提示词/video-tasks 路由全部真实 PG |
| 不能以 H3 覆盖替代其他类别 | 每类别有**专属命名文件 + 专属用例**（§4 矩阵）；H3 崩溃恢复（worker_crash_recovery）与公平队列（queue_fairness）为独立复用文件，不替代钱包/口播/独立生成 |
| 补齐每类提交/领取/崩溃/超时/SUBMISSION_UNCERTAIN/回写 + 状态/账务差额断言 | 见 §4 矩阵逐格；账务差额以 `wallet_transactions` 的 RESERVE/SETTLE/RELEASE 序列 + 钱包 (available, frozen) 双计数断言 |
| 缺 PG 必须非零失败且 0 skip | `require_pg_or_explicit_skip()` 硬门：死端口 59999 下 123 errors、退出码 1、0 skipped（§3） |
| 未把 Provider 成本记录等同钱包流水 | 账务断言只针对 `wallet_transactions` 钱包流水；Provider 侧 `provider_charge_state`（UNKNOWN/CHARGED/NOT_CHARGED）独立断言，二者不混同（如 SUBMISSION_UNCERTAIN 保留 `provider_charge_state=UNKNOWN` 同时钱包流水仍 `["RESERVE"]`） |
| 数据库基线不得由 SQLite/mock 持久化/缺 PG 跳过充当 | 三文件已删尽 `tmp_path` SQLite 建库路径；残留 `sqlite` 字样均为**迁移说明性 docstring/注释**（对比新旧行为），非功能性回退；`oral_test_media` 的 `tmp_path_factory` 仅生成 ffmpeg 媒体字节喂 `FakeSourceStorage` 替身（存储替身，行 222 允许），数据库始终真实 PG |

## 3. 验证结果（本地 PG16 fixture `postgresql://…@localhost:5433`，Node 无关；server 专项）

| 验证 | 命令/场景 | 结果 |
| --- | --- | --- |
| 5 命名文件（PG 就绪） | `pytest test_worker_crash_recovery.py test_wallet_billing_service.py test_oral_domain.py test_independent_creation.py test_customer_queue_fairness.py -q -rs` | **124 passed, 0 skipped**（34.42s；18+16+61+17+12） |
| 静态门 · lint | `ruff check .` | **All checks passed!** |
| 静态门 · 格式 | `ruff format --check .` | **291 files already formatted** |
| 静态门 · 类型 | `mypy app` | **Success: no issues found in 104 source files** |
| 缺 PG 硬门（行 223/227 底线） | `TEST_POSTGRESQL_URL=…@localhost:59999/customer_v3_test pytest <5 files>`（未设 `ALLOW_PG_SKIP`） | **退出码 1；1 passed（PG 无关的 openapi 契约用例）+ 123 errors；skipped 计数 = 0** |
| 硬门错误信息 | fixture 内 `pytest.fail` | `PostgreSQL test fixture is not reachable at …:59999/…; start it via scripts/pg-fixture.sh start` |

### 3.1 增量验收四条计数（行 225，逐条落到真实 PG 用例）

| 增量验收条 | 断言 | 代表用例（真实 PG） |
| --- | --- | --- |
| 同一幂等键重放新增收费任务 = 0 | 重放后 `RESERVE` 计数仍为 1、批次 id 不变、钱包差额不变 | independent `test_video_task_route_creates_batch_through_fenced_write_on_pg`（重放同 payload → 201 同 id，`_ledger_count("RESERVE")==1`，`_wallet==(990,10)`）；independent i2v 重放（m3：`_ledger_count("RESERVE")==1`，`_wallet==(992,8)`）；oral `idem-key-0001` 重放 |
| 成功结算次数 = 1 | 成功后恰一笔 `SETTLE`，冻结归零 | oral `test_generation_worker_completes_oral_task_and_settles_once`；wallet finalize 结算路径 |
| 确认失败释放次数 = 1 | 确认失败/取消后恰一笔 `RELEASE`，不重复释放 | wallet `test_finalize_failure_or_cancellation_releases_credit_once`（同事务 `RESERVE→RELEASE`，ledger_sequence 因果序）；wallet `test_released_task_can_reserve_a_new_billing_round`（`RESERVE1→RELEASE1→RESERVE2`） |
| 未知提交重提次数 = 0 | SUBMISSION_UNCERTAIN 不盲重提；retry 路由已移除（404），预留轮冻结不动 | oral `test_oral_task_retry_route_is_removed_and_keeps_uncertain_reservation`（retry → 404，`_ledger==["RESERVE"]`，`_wallet==(19,1)`）；oral `test_oral_task_retry_route_is_absent_for_all_states`；`test_openapi_does_not_advertise_uncertain_oral_resubmit` |

## 4. 任务类别 × 状态 × 账务矩阵（行 225 核心交付）

每格标注：**真实 PG 连接模型** = 每逻辑块独立 `pg_transaction`（独立池连接，多连接基线）；**Provider 替身边界** = 受控替身（行 222 允许），数据库从不 mock。

| 任务类别（命名文件） | 提交 submit | 领取 claim | 崩溃 crash | 超时 timeout | SUBMISSION_UNCERTAIN | 回写 writeback | 账务差额（wallet_transactions） |
| --- | --- | --- | --- | --- | --- | --- | --- |
| H3 视频生成崩溃恢复 `test_worker_crash_recovery.py`（18，**已复用**·真实 PG） | ✓ | ✓ 双领互斥 | ✓ 崩溃后租约回收 | ✓ 租约过期 | ✓ 保留核验 | ✓ | RESERVE→(SETTLE\|RELEASE) 由恢复路径决定 |
| 客户公平队列 `test_customer_queue_fairness.py`（12，**已复用**·真实 PG） | ✓ | ✓ 游标轮转 | ✓ | ✓ | — | ✓ | 队列 cursor 公平性（非计费） |
| 钱包计费 `test_wallet_billing_service.py`（16，**本任务迁移**） | ✓ RESERVE | — | — | ✓ 悬挂预留清扫 | — | ✓ 提交/回滚隔离 | RESERVE / SETTLE / RELEASE 差额 + (available, frozen) 双计数；ledger_sequence 因果序 |
| 口播/数字人 `test_oral_domain.py`（61，**本任务迁移**） | ✓ | ✓ `claim_oral_work` 租约 | ✓ `discard_uncommitted_oral_asset` | ✓ `test_expired_oral_submission_releases_queue_slot_once` | ✓ retry 移除 + 保留预留 | ✓ `run_pg_worker_once` | RESERVE→SETTLE（成功一次）/ RESERVE→RELEASE（取消一次）；`provider_charge_state` 独立断言 |
| 独立创作生成 `test_independent_creation.py`（17，**本任务迁移**） | ✓ i2v/t2v/r2v 矩阵 | — | — | — | — | ✓ PG worker | 幂等重放 RESERVE=1；wallet (990,10)/(992,8) 差额 |

Provider 替身清单（行 222 受控替身，真实付费属 CW-050）：oral = `ScriptedVendorTransport`（Hifly 脚本化响应，含 `SUBMISSION_UNCERTAIN` 连接中断剧本）+ `FakeSourceStorage`（媒体字节）；independent = `FakeStorageAdapter`；worker_crash/queue_fairness = 各自既有替身（已复用）。**替身只替 Provider/存储 I/O，数据库一律真实 PG。**

## 5. RED→GREEN 与迁移发现记录（行 226/227：缺陷场景保存失败日志，同一可验证增量转绿）

- **迁移发现 · 账本排序（SQLite→PG，M3）**：SQLite lane 以 `type` 字母序 tiebreak，把 `RELEASE` 排在 `RESERVE` 前（错误因果序）；PG 迁用 `ledger_sequence`（迁移 063 触发器：`wallets` 行 `FOR UPDATE` 锁下 `nextval` 赋值，权威且不可变）后，`test_finalize_failure_or_cancellation_releases_credit_once`（wallet:377）与 `test_released_task_can_reserve_a_new_billing_round`（wallet:511）的期望序列**翻转**为真实因果序 `RESERVE→RELEASE(→RESERVE)`。与生产 `control_routes.py` / `test_customer_chain_e2e.py` / `test_internal_admin.py` 的 `ledger_sequence` 口径一致。
- **迁移发现 · 布尔列**：`runtime_settings.h3_extended_modes_enabled` 在 PG 为真实布尔列，SQLite 的 `SET … = 1` 改为 `SET … = true`（independent `ENABLED_UPDATE`）。
- **迁移发现 · FK CASCADE**：`operation_cost_rates` FK 引用 `users`（ON DELETE SET NULL），`TRUNCATE users CASCADE` 会清掉迁移种子费率；seed 先捕获后以 `ON CONFLICT DO NOTHING` 复原，保证每任务冻结真实成本快照。
- **RED（开发期捕获）· 唯一键冲突**：M1 保存提示词路由用例初版把坏 JSON 行 `sp-bad` 与 `sp-1` 同插 `(project_a, saved_prompt, version_number=1)`，触发 `UniqueViolation`（`versions_project_id_kind_version_number_key`）→ 1 failed；改为独立 `pg.execute` 用 `version_number=2` → 17 passed GREEN。
- **RED（开发期捕获）· E731**：M2c 的 `_override_business_db` 初版用 `lambda` 赋值触发 `ruff E731` → 改为内嵌 `def override()` → ruff clean。

## 6. 已复用 / 已剔除范围 + 合并与回归先后（行 228 必交）

- **已复用（零触碰）**：`test_worker_crash_recovery.py`（18）、`test_customer_queue_fairness.py`（12）——行 221 明确"H3 崩溃恢复与客户公平队列已有真实 PG、多 Worker、租约、双领和释放专项"，本任务直接纳入 5 文件门禁复跑（124 含此 30），不重复开发。
- **已剔除（属他项）**：真实付费 Provider 调用 = **CW-050**（本项仅受控替身）；容量规模与类生产拓扑 = **CW-047**；图片 / 分析·改写 / ASR 类别的**专属收敛** = **CW-030 下游**（这些类别各有专属文件 `test_analysis.py`/`test_script_rewrite.py`/`test_asr_provider.py`/`test_apilio_image_provider.py`/`test_character_image_generation.py`/`test_studio_analytics.py`，均不在 CW-010 行 224 的 5 命名文件清单内；CW-010 只锁定行 224 的 5 个异步任务恢复/计费基线文件）。
- **合并要求**：受保护 `main` 仅接受 squash merge（owner phlong026）；三门禁 CI 全绿（secret 扫描 / Linux 质量门 / Windows NSIS）后合并。
- **回归先后**：CW-010 前置 = CW-007（PG 测试基建/硬门，已合并）、CW-002；本任务 server/app 生产代码零触碰，故与在途 CW 无生产代码冲突面；全量回归由 CI Linux 质量门（含唯一一次 server 全量 pytest）承载。

## 7. 独立复核（CodeReview 子代理）

独立 CodeReview 子代理对 3 个改动测试文件做评审，结论**有条件通过 → 全部落实后无未决项**：无 Blocker；3 Major（M1/M2 阻塞、M3 强烈建议）+ 3 Minor（m1/m2/m3）+ 3 Nit（n1/n2/n3），逐条实质修复：

| 编号 | 评审意见 | 落实 |
| --- | --- | --- |
| M1 | independent `GET /api/studio/saved-prompts` 读路由零覆盖（原为伪测试） | 改为 `TestClient` + dev-header 路由驱动（零 override）：author 过滤、`limit` 钳制（0/999→50）、坏 JSON 跳过、越权隔离（employee_2 仅见 sp-2）——17 GREEN |
| M2a | independent docstring 假 cross-reference + 身份声明自相矛盾 | 删除假引用；重写为诚实陈述恢复的路由边界；并修正 para1"dev-header 仅 SQLite lane"的过宽声明——正确限定为**fenced 写路径**拒绝（401），**unfenced 读路径**在 development 模式下于 PG 认证 dev-header |
| M2b | `GET /api/independent/capabilities` 路由零覆盖 | 新增 `test_capabilities_route_serves_http_contract_on_pg`：默认能力 + 开启扩展模式后 i2v/t2v/r2v/last_frame 全真 |
| M2c | `POST /api/independent/video-tasks`（fenced 写）路由零覆盖 | 新增 `test_video_task_route_creates_batch_through_fenced_write_on_pg`：`_PgBusinessDb` double 走真实 `pg_transaction`（镜像生产 `BusinessDb.write()` 的 `AuditedSecurityDenial` catch→persist→re-raise），201 + `BatchResult` 序列化 + RESERVE + 重放同 id |
| M3 | 三文件账本排序用 `created_at,type` 字母序（RELEASE 误排 RESERVE 前），未用 PG 权威 `ledger_sequence` | wallet/oral 全部 `wallet_transactions` 排序改 `ORDER BY ledger_sequence`；wallet:377/:511 期望序列翻转为因果序 + 注释；docstring 重写说明 063 触发器机制 |
| m1 | oral `_pg_database_override` 是生产 `get_database` PG 分支的逐行副本，遮蔽被测代码 | 删除该 override + 3 处 `dependency_overrides[get_database]` + import；读路由改跑**真实** `get_database`（与 independent 零 override 一致）——61 GREEN |
| m2 | oral auditor 拒绝用例未断言持久化拒绝审计 | 补 `audit_logs` 断言：`actor_user_id='employee_1'` 戴 auditor 角色的 4 个 `attempted_action` 集合（consent/avatar/voice create + voice confirm） |
| m3 | independent 重放用例未断言账本计数 | 重放后 + 冲突后各补 `_ledger_count("RESERVE")==1` + `_wallet` 差额 |
| n1 | CW-010 三专属库名未登记 `RECORDED_TEST_DATABASES`，raw admin CREATE/DROP 绕过 allowlist 守卫 | 登记 `cw010_wallet_billing_test`/`cw010_independent_test`/`cw010_oral_test`；三 fixture 改用 kit `create_test_database`/`drop_test_database`（`assert_safe_test_database` 现守卫 `DROP … WITH (FORCE)`） |
| n2 | oral `lease_expires_at` 时区格式不统一（`2000-01-01 00:00:00` vs `…T00:00:00+00:00`） | :2720 统一为 `2000-01-01T00:00:00+00:00`（与 :2413/:2478 一致；TEXT 列，显式 UTC 消除会话时区歧义） |
| n3 | DSN 拼接健壮性（`rsplit("/",1)` 丢弃 query 参数） | 通过 n1 采用 kit helper 后，三文件删除自研 `_pg_dsn`/`_admin_dsn`/`_X_dsn` 拼接，委托 kit `resolve_test_dsn`/`admin_dsn_of`；残留 query-param 健壮性属 CW-007 kit 既有代码、当前 fixture DSN 无 query 串（潜在非活动），不在 CW-010 范围 |

复核其余结论：账务差额断言与钱包流水/Provider 成本分离正确；多连接基线（每块独立 `pg_transaction`）满足行 223；无 SQLite/mock 持久化/缺 PG 跳过充当数据库基线；无密钥入代码/日志/夹具。

## 8. 签认记录

| 角色 | 结论 | 日期 |
| --- | --- | --- |
| 后端测试负责人 | 待签认 | — |
| 后端负责人 | 待签认 | — |
| 集成负责人 | 待签认 | — |
