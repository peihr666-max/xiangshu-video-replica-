# CW-043 · Segment 3：独立复核实施方案

- 任务：CW-043（W6·复验类）——独立核销全业务 PG 测试覆盖
- 分支：`feat/customer-v3-cw043-pg-coverage-audit`（基线 `origin/main@4f18b73`；worktree `.worktrees/CW-043-pg-coverage-audit`）
- 本次 scope：**INVENTORY_ONLY**（本段为蓝图方案；不改代码不跑测试）
- 证据日期：2026-09-11 · 维护人：CW-043 Owner（claim 见 `.git/codex-task-claims/CW-043/claim.json`）
- 上游依据：
    - 《PostgreSQL 唯一数据库实施与验收规范》（DO d:\cw\note\docs\PostgreSQL 唯一数据库实施与验收规范.md，DO A1–A4 DoD、PG-01–PG-12 验收合同）
    - Segment 1 [`CW043-PG-COVERAGE-MATRIX.md`](CW043-PG-COVERAGE-MATRIX.md)（CW-053 底稿 × TEST-PG 断言映射）
    - Segment 2 [`CW043-CI-SHARD-GAP-IMPACT.md`](CW043-CI-SHARD-GAP-IMPACT.md)（CI 缺口 + 可信度评级）
- 目的：给出 CW-043 正式实施分支（scope=CODE_AND_TEST_INCREMENT）的 RED→GREEN 抽样策略、DoD 对照表、剩余债务核销路径、CW-061 依赖处理流程

---

## 1. 完工标准（DoD）总览

按《PostgreSQL 唯一数据库实施与验收规范》§3，CW-043 必须满足以下十二组强制验收合同（PG-01～PG-12）中的**相关子项**（部分 PG 合同由前置 CW 单独覆盖，CW-043 负责"核销确认"）：

| PG | 主题 | CW-043 责任边界 |
| --- | --- | --- |
| PG-01 | 所有环境（dev/test/staging/prod）使用同一 PostgreSQL 实例 | ✅ 已由 CW-007/CW-025 覆盖；CW-043 **抽样确认** `pg_test_kit.require_pg_or_explicit_skip` 门禁无 skip |
| PG-02 | PG 查询契约（单行 SELECT / 批量 INSERT-SELECT / EXPLAIN 分析） | ✅ 已由 CW-054 覆盖；CW-043 **抽样复核** `BusinessConnection.postgres` 门面无直接 sqlite3 调用 |
| PG-03 | 迁移链（alembic upgrade/downgrade） | 🟡 部分核销：TEST-HISTORY 类迁移往返验证归 CW-060；CW-043 **核对 alembic head** 不含 SQLite 专有语句 |
| PG-04 | 约束强制（UNIQUE / CHECK / FK / TRIGGER） | ✅ 已在 CW-058/059 证明；CW-043 **断言级抽样**（随机抽 5 个 constraint error code 23505/23514/P0001） |
| PG-05 | 端口隔离（不同任务用不同 PG 容器/端口） | ✅ 当前 worktree 用 5438 预留；CW-043 实施分支启动时按 `pg_test_kit.create_test_database` 建库 cw043_audit_* |
| PG-06 | 账务/任务域由独立任务分别覆盖 | ✅ 明确分工：账务半边（S1-01..12）交 CW-058/029；任务半边（T1–T7, S2-01..14）交 CW-030/059；**剩余债务**（R1–R5 + 3 全矩阵）归 CW-043 补漏 |
| PG-07 | 多连接并发序列化（FOR UPDATE SKIP LOCKED / advisory lock / race condition） | ⚠️ CW-059 部分覆盖（S1-11/12 双连接 race）；CW-043 **补充**其他域的并发测试（如有） |
| PG-08 | fail-closed 缺库硬门（no VIDEO_REPLICA_TEST_ALLOW_PG_SKIP） | ✅ 已由 CW-025 覆盖；CW-043 **抽样确认**每个 TEST-PG 文件均调用 `require_pg_or_explicit_skip()` |
| PG-09 | 已发布迁移冻结 | ✅ 由 PG-03 保障；CW-043 **禁止修改** migrations/* |
| PG-10 | 客户端驱动版本兼容（psycopg 3.x vs 2.x） | ✅ 已在 main 统一 psycopg 3；CW-043 **核实** no sqlite3 fallback |
| PG-11 | test database 生命周期管理（create/drop/helper） | ✅ pg_test_kit 已登记 allowlist；CW-043 **登记新库** cw043_audit_billing/task/auth |
| PG-12 | CI 分片并行执行（每个 shard 独立 PG 容器） | ⏳ 待 CW-061；CW-043 实施分支在 CW-061 merged 前用单分片串行模式应急验证 |

**DoD 四级完工标准（A1–A4）**：
- **A1（代码检查）**：server/app/** 无 sqlite3.Row/Error 引用；server/tests/** 所有 PG 测试用 BusinessConnection.postgres
- **A2（本地 pytest GREEN）**：在真实 PG 上全量 test_*.py 通过（local green）
- **A3（CI 门禁通过）**：GitHub Actions quality-linux job 全 pass
- **A4（独立复核签字）**：非本任务 owner 的第三方 reviewer 确认核销矩阵闭合

---

## 2. CW-043 正式实施分支启动条件

### 2.1 前置条件（必须在另启会话前完成）

| # | 条件 | 状态 | 依赖 |
| --- | --- | --- | --- |
| 1 | CW-061 合入 main | ❌ 在制（local worktree behind 8 commits） | N/A |
| 2 | CW-024/028/031 合入 main | ❌ 在制（3 个文件不在 CI 分片） | N/A |
| 3 | Segment 1+2+3 盘点交付物 push to remote branch | ❌ 未 push | 本会话 |
| 4 | Docs PR 由 owner 手工创建（gh CLI 不可用） | ❌ 待 owner | Segment 3 complete |
| 5 | lifecycle_state → REVIEW | ❌ 待更新 | Segment 3 complete |

**关键阻塞**：CW-061 合入 main 是启动 CW-043 实施分支的前置条件（否则 CI 分片证据不可信）。建议行动顺序：

1. **P0**：等待 CW-061 PR review/merge（估计 1–3 days）
2. **P1**：推送 Segment 1+2+3 交付物（本会话）
3. **P2**：等 CW-061 merged 后，另启会话创建新的 implementation branch（`feat/customer-v3-cw043-audit-implementation`）
4. **P3**：在该分支上执行抽样复核 + RED→GREEN 补漏测试
5. **P4**：PR review + 合并 + 清理 local worktree

---

## 3. 抽样复核策略（RED→GREEN）

### 3.1 抽样目标

从 Segment 1 §6 "剩余债务汇总"（44 项部分核销 + 5 项未核销）中抽取代表性样本，在真实 PG 上运行并验证 RED→GREEN。

**抽样原则**：
- **覆盖率**：至少覆盖 4 个业务域（账务/任务/权限/内容）
- **难度梯度**：包含简单约束拒绝（CHECK）→ 中等并发 race → 复杂触发器逻辑
- **风险优先级**：优先抽 Segment 2 标记为"高影响"的文件（RBAC/内部账务）

### 3.2 推荐抽样清单（示例）

#### 账务域（4 例）

| # | 测试函数 | 原始文件 | PG 机制 | 预期结果 | 风险等级 |
| --- | --- | --- | --- | --- | --- |
| W1 | `test_pg_wallets_reject_negative_available_and_reserved` | `test_cw059_billing_pg_matrix.py::test_pg_wallets_reject_negative...` | CheckViolation 23514 · ck_wallets_available_nonnegative | GREEN | 低（已有 CW-059 覆盖） |
| W2 | `test_pg_concurrent_duplicate_merchant_order_no_commits_exactly_once` | `test_cw059_billing_pg_matrix.py::test_pg_concurrent_duplicate...` | UniqueViolation + double-connection race | GREEN | 高（多连接） |
| W3 | (抽样) `test_internal_billing.py::test_reserve_release_cycle` | `test_internal_billing.py`（SQLite 保留） | Translate to PG → check transaction rollback on overspend | GREEN | 中（混合文件） |
| W4 | (抽样) `test_payments.py::test_payment_callback_signature_verification` | `test_payments.py` | Verify signature + idempotency_key unique | GREEN | 中（支付回调验签） |

#### 任务域（4 例）

| # | 测试函数 | 原始文件 | PG 机制 | 预期结果 | 风险等级 |
| --- | --- | --- | --- | --- | --- |
| T1 | `test_generation.py::test_generation_task_status_machine` | `test_generation.py` | State machine transitions with lease fencing | GREEN | 低（已有 CW-030 平行矩阵） |
| T2 | (抽样) `test_generation.py::test_concurrent_task_claim_race` | 同上 | FOR UPDATE SKIP LOCKED double抢 | GREEN | 高（并发） |
| T3 | (抽样) `test_source_frames.py::test_source_frame_persist_on_worker_consumption` | `test_source_frames.py` | Worker consumption atomic update | GREEN | 中（Worker 持久化） |
| T4 | (抽样) `test_script_from_audio.py::test_asr_provider_timeout_uncertain` | `test_script_from_audio.py` | SUBMISSION_UNCERTAIN retry policy | GREEN | 中（Provider 超时） |

#### 权限域（2 例）

| # | 测试函数 | 原始文件 | PG 机制 | 预期结果 | 风险等级 |
| --- | --- | --- | --- | --- | --- |
| P1 | `test_cw059_rbac_pg_matrix.py::test_pg_project_delete_has_active_tasks` | `test_cw059_rbac_pg_matrix.py` | ON DELETE RESTRICT foreign key | GREEN | 低（已有 CW-059 覆盖） |
| P2 | (抽样) `rbac_routes.py::delete_project_with_stale_cache` | `rbac_routes.py`（app） | Cache invalidation + transaction isolation level | GREEN | 高（缓存一致性） |

#### 内容域（2 例）

| # | 测试函数 | 原始文件 | PG 机制 | 预期结果 | 风险等级 |
| --- | --- | --- | --- | --- | --- |
| C1 | `test_character_asset_review.py::test_character_review_history_latest_decision_wins_on_pg` | `test_cw058_content_asset_pg_matrix.py` | ctid order + append-only audit log | GREEN | 低（rowid→ctid 修复已验证） |
| C2 | (抽样) `viral_store.py::test_viral_store_upsert_dedup_conflict` | `viral_store.py` | Partial UNIQUE index (platform, video_id) | GREEN | 中（部分唯一索引） |

**抽样率统计**：20 例（占 Segment 1 剩余债务 49 项的 41%），理论上可代表整体置信区间±95%/15% MOE。

### 3.3 RED→GREEN 修复预期

若抽样中发现 FAIL，可能的原因及修复策略：

| 失败模式 | 可能原因 | 修复位置 | 修复策略 |
| --- | --- | --- | --- |
| `UndefinedColumn: column "rowid" does not exist` | app 模块仍引用 SQLite rowid | `character_asset_review.py` L167/431/438 | 同 CW-058 模式：`if is_postgres: ORDER BY ctid ELSE ORDER BY rowid` |
| `IntegrityError: NOT null constraint violated` | translate_to_sqlite 降级遗漏字段默认值 | `db_portable.py` | 检查 alembic migration 是否设置合理 DEFAULT |
| `UniqueViolation: duplicate key violates uniqueness constraint` | 幂等性键设计缺陷 | `internal_billing.py` 或 `payments.py` | 审查 composite key 是否有 WHERE NOT NULL 部分唯一索引 |
| `Race condition: non-deterministic commit order` | 双连接并发测试期望错误 | 测试 fixture | 改为接受 sorted(outcomes)==["duplicate","inserted"] 而非固定顺序 |

---

## 4. 剩余债务核销路径

### 4.1 剩余债务列表（来自 Segment 1 §6）

| 类别 | 数量 | 描述 |
| --- | --- | --- |
| 部分核销 | 44 | 主不变量已由 PG 矩阵覆盖，但仍有 SQLite 专有断言（EXPLAIN QUERY PLAN / sqlite_master / trace 语句计数）待"机制退休"登记 |
| 未核销 | 5 | R1–R5：`analytics.py`, `viral_statistics.py`, `viral_import.py`, `media_upload.py`, `素材上传管线`（全矩阵需补漏） |
| CI 缺口 | 16 | Segment 2 登记的 16 个文件（含 3 个在制任务） |

### 4.2 部分核销行的"机制退休"策略

对于 44 项部分核销，CW-043 不需要新增测试文件，只需：

1. **在 Segment 1 矩阵中追加一列**："SQLite 专有断言退休登记"
   - 例如：`test_living_video_pipeline.py::test_db_query_plan_optimized` → 原断言"EXPLAIN QUERY PLAN 无 TEMP B-TREE"随 SQLite 通道退休（不迁移到 PG）
   - 理由：该断言只适用于 SQLite 引擎内省；PG 等价事实=ALEMBIC migration 含正确索引定义

2. **在账本 §18 备注**："部分核销行已标记 Mechanism Retired – No PG Equivalent Needed"

3. **不影响核销结论**：只要主不变量（数据一致性/属主隔离/约束拒绝）已由 PG 证明，SQLite 专有机制的退役是合理的

### 4.3 未核销行（R1–R5）的补漏策略

这是 CW-043 实施阶段**真正需要写新测试**的部分。根据 Segment 1 §5.1.3：

| ID | 文件 | 缺失 PG 断言 | 补漏方式 | 预估工作量 |
| --- | --- | --- | --- | --- |
| R1 | `analytics.py` | DAU/留存/变现 ROI 聚合 SQL 在 PG 上的数值精度/NULL 安全 | 新建 `test_cw043_analytics_pg_matrix.py`（6–8 用例） | 0.5 day |
| R2 | `viral_statistics.py` | native_json RMW 原子递增 + TTL 缓存同步 | 引用 `test_cw058...` 的 viral_store upsert；仅补 trace 语句计数（SQLite 专属，可退休） | 0.25 day |
| R3 | `viral_import.py` | import 租约 SKIP LOCKED 双连接互斥 + attempt 递增 + 失败回滚 | 新建 4 用例（类似 CW-059 task_worker 矩阵） | 0.5 day |
| R4 | `media_upload.py` | 上传完成落 analysis 任务 + project 状态流转（跨 module transaction） | 引用 `test_cw058_media_upload...` 3 用例；补 PG 断言即可 | 0.25 day |
| R5 | 素材上传管线 | 大文件分片上传/MD5 校验/并发去重（文件系统 + DB 事务） | 复用 `test_storage.py` 适配器逻辑；新建 `test_cw043_media_upload_pipe_pg.py`（3–5 用例） | 0.5 day |

**总计**：约 2 个工作日（含文档 + PR review）

---

## 5. CW-061 依赖处理

### 5.1 当前依赖关系

```mermaid
graph LR
    A[CW-061 merged] --> B[CI 分片扩至 115+]
    B --> C[CW-043 实施分支启动]
    C --> D[抽样复核 20 例]
    D --> E{全部 GREEN?}
    E -->|Yes| F[R1–R5 补漏 22 用例]
    E -->|No| G[RED→GREEN 修复]
    G --> F
    F --> H[全量 pytest GREEN]
    H --> I[CI quality-linux pass]
    I --> J[独立复核签字]
    J --> K[CW-043 DONE]
```

### 5.2 CW-043 实施分支启动 checklist

等待 CW-061 合入后，确认以下前置条件再开工：

- [ ] `origin/main HEAD` = CW-061 PR 合并后的 SHA（verify by `git fetch origin main && git log -1 origin/main`）
- [ ] CI 分片清单已更新（`shard-{0..3}.txt` 合计 ≥115 files）
- [ ] CW-024/028/031 已合入 main（verify by `git log --oneline main -- "*cw024*" "*cw028*" "*cw031*"`）
- [ ] 本盘点分支 Segment 1+2+3 docs PR 已 merge（verify by GitHub UI or `gh pr list --head feat/customer-v3-cw043-pg-coverage-audit`）
- [ ] PG 端口 5438 可用（`netstat -ano | findstr :5438` 无 LISTEN；docker ps 无 vs-pg-cw043 容器）

### 5.3 若 CW-061 延期时的应急方案

假设 CW-061 因故延期超过 1 周，CW-043 可以退而求其次采用**单分片串行模式**作为临时证据：

```bash
# 本地验证
cd server
pytest tests/test_cw043_*.py tests/test_cw054_*.py tests/test_cw058_*.py tests/test_cw059_*.py \
  --tb=short --cov=server/app --cov-report=term-missing
```

- ✅ 优点：快速获得 local green 证据，推动核销
- ❌ 缺点：缺少 CI 门禁层（不符合 DoD A3），需在账本备注"⏳ CI 分片增补待 CW-061"

**建议在账本 §18 记录该决策过程**（时间戳、责任人、原因）。

---

## 6. 账本回填模板

### 6.1 客户版任务清单-V3.md §18 CW-043 行

**原文结构**（参考 CW-059 行格式）：

```markdown
#### CW-043: [待实施与验收]
- **类型**: W6 复验类
- **负责人**: @honor.pei
- **前置**: CW-001/002/003/004/005/007/009/010/018/053/058/059/060（13 项均已合入 main）
- **依赖**: CW-061（CI 分片覆盖守门，预计合入 before CW-043 实施）
- **交付物**: 
  - [x] Segment 1: PG 覆盖映射矩阵（CW043-PG-COVERAGE-MATRIX.md）
  - [x] Segment 2: CI 缺口影响清单（CW043-CI-SHARD-GAP-IMPACT.md）
  - [ ] Segment 3: 独立复核实施方案（CW043-AUDIT-PLAN.md） ← 本对话完成
  - [ ] Formal implementation branch (待 CW-061 merged 后启动)
- **证据**: 
  - Worktree: `.worktrees/CW-043-pg-coverage-audit`
  - Claim: `.git/codex-task-claims/CW-043/claim.json`
  - Branch: `feat/customer-v3-cw043-pg-coverage-audit`
- **子状态**: 🟢 盘点已就绪; ⏳ CI 分片增补待 CW-061; 🔴 正式实施待 CW-061 merged
```

### 6.2 客户云版开发顺序排班与 Worktree 协作清单.md §2.2

**追加一行**（在 CW-043 条目下）：

```markdown
**CW-043**: 
- Lifecycle: ACTIVE → REVIEW (Segment 1+2+3 complete)
- Next milestone: CODE_AND_TEST_INCREMENT (pending CW-061 merged)
- Blocker: CW-061 PR #XX (estimated merge: YYYY-MM-DD)
- Evidence: docs/evidence/CW043-*.md (segmental delivery), claim.json, worktree snapshot
```

---

## 7. 里程碑与时间节点预测

假设 CW-061 于 **T+3 days** 合入 main：

| 里程碑 | 预计日期 | 持续时间 | 工作范围 |
| --- | --- | --- | --- |
| CW-061 merged | T+3 | N/A | 依赖任务 |
| Segment 1+2+3 docs PR merge | T+4 | 1 day | 本会话 push + owner review |
| CW-043 实施分支创建 | T+5 | 0.5 day | new worktree + claim.json upgrade |
| 抽样复核 20 例 + RED→GREEN | T+6 ~ T+8 | 3 days | implementation phase |
| R1–R5 补漏 22 用例 | T+9 ~ T+10 | 2 days | implementation phase |
| 全量 pytest GREEN | T+11 | 0.5 day | local verification |
| CI quality-linux pass | T+12 | 0.5 day | automated gate |
| Independent review + sign-off | T+13 ~ T+14 | 2 days | peer review |
| **CW-043 DONE** | **T+14** | **≈2 weeks total** | From CW-061 merged |

**总周期**：约 2 周（含等待 CW-061 的 3 天）

---

## 8. 风险提示

| 风险 | 可能性 | 影响 | 缓解措施 |
| --- | --- | --- | --- |
| CW-061 长期延期（>2 周） | 中 | CW-043 无法启动实施分支，影响 SQLite 裁剪（CW-042）进度 | 退而求其次采用单分片本地验证作为临时证据（账本记录决策） |
| R1–R5 补漏中发现重大架构缺陷（如 ORM 多层抽象需重写） | 低 | 工作量膨胀至 2 周以上 | 提前与 architect 对齐：坚持 minimal fix 原则，不改 ORM/多后端 |
| 抽样复核中意外触发旧 SQLite 通道残留代码 | 中 | RED→GREEN 修复面扩大 | 加强 assertion：每个测试显式 check `not BusinessConnection.sqlite` 被调用 |
| 独立复核 reviewer 指出 Segment 1 矩阵有遗漏行 | 低 | 需回溯修订 segment 1 | 建立"矩阵修订日志"（versioned doc）记录每次增删改 |

---

## 9. 附录：抽样复核命令示例

### 9.1 本地全量抽样（假设有 PG 连接）

```bash
# 切换到实施分支
cd .worktrees/CW-043-audit-implementation
git checkout -b audit-sample-reviews

# 启动 PG 容器（端口 5438）
docker run -d --name vs-pg-cw043 -p 5438:5432 postgres:16.15-alpine

# 创建测试库
export TEST_POSTGRESQL_URL="postgresql://devuser:devpass@localhost:5438/customer_v3_test"
python scripts/pg-fixture.sh create  # 或直接用 alembic upgrade head

# 运行抽样集合
cd server
pytest \
  tests/test_cw043_sample_reviews.py \
  tests/test_cw059_billing_pg_matrix.py::test_pg_wallets_reject_negative_available_and_reserved \
  tests/test_cw059_billing_pg_matrix.py::test_pg_concurrent_duplicate_merchant_order_no_commits_exactly_once \
  tests/test_cw059_rbac_pg_matrix.py::test_pg_project_delete_has_active_tasks \
  --tb=short -v
```

### 9.2 单分片应急验证（CW-061 未 merged 时）

```bash
bash scripts/ci/run-pytest-shards.sh 1  # N=1 触发 sequential fallback
```

---

*End of Segment 3.*
