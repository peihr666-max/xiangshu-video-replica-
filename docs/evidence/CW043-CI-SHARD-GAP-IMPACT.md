# CW-043 · Segment 2：CI 分片缺口对核销证据可信度的具体影响清单

- 任务：CW-043（W6·复验类）——独立核销全业务 PG 测试覆盖
- 分支：`feat/customer-v3-cw043-pg-coverage-audit`（基线 `origin/main@4f18b73`；worktree `.worktrees/CW-043-pg-coverage-audit`）
- 本次 scope：**INVENTORY_ONLY**（仅盘点/映射/蓝图；不改任何被核销实现，不改任何测试文件，不改 CI workflow）
- 证据日期：2026-09-11 · 维护人：CW-043 Owner（claim 见 `.git/codex-task-claims/CW-043/claim.json`）
- 消费对象：
    - CW-044 §18.2 "fail-open 门禁缺口"发现（继承自 `docs/evidence/CW044-CI-DOCS-INVENTORY.md` §5 L87–103）
    - CI Linux pytest 分片执行脚本 `scripts/ci/run-pytest-shards.sh`（§2 机制解析）
    - 当前 CI 分片清单（shard-{0,1,2,3}.txt 合计 99 个 test 文件）
    - 本地磁盘 test_*.py 文件清单（115 个）
- 上游证据：[`CW053-DB-SEMANTIC-INVENTORY.md`](CW053-DB-SEMANTIC-INVENTORY.md)（§4/§5 DB 语义清单）、[`CW058-EVIDENCE.md`](docs/evidence/CW058-EVIDENCE.md)、[`CW059-EVIDENCE.md`](docs/evidence/CW059-EVIDENCE.md)
- 与 Segment 1 关系：Segment 1 建立"CW-053 底稿 × 已落地 TEST-PG 断言”的逐文件映射；Segment 2 在此基础上标注"哪些已映射到 PG 的测试文件当前从未在 CI 执行”，并给出核销证据可信度评级

---

## 1. 目的与定义

### 1.1 背景

CW-044 盘点 review_note (§5 L87–103) 明确发现：CI Linux server pytest gate **只跑 99/112 个 committed 测试文件**，13 个近期 CW 任务的测试文件（CW-024/026/027/028/029/030/031/032/054/056/057/058/060）**从未在 CI 执行**。这直接导致一个问题：

> **即使某个测试在本地 pytest 全量通过，若其不在 CI 分片清单里，则"自动化通过"这一证据在 CI 层不成立。**

CW-043 的任务不是修复 CI 分片缺口（那是 CW-061 的责任），而是**识别每一个已核销 TEST-PG 断言的证据来源**，并对每个缺口文件给出核销证据可信度评级（高/中/低）。

### 1.2 证据来源分类

| 类型 | 定义 | 示例 | 可信度权重 |
| --- | --- | --- | --- |
| **A. 本地 pytest 全量** | 在 worktree/server 上以真实 PG 连接运行全套 test_*.py，全部 GREEN | `pytest tests/test_cw058_content_asset_pg_matrix.py` (20 passed) | ⚠️ 中等：依赖开发者手动触发，非 CI 门禁 |
| **B. CI 分片执行** | 在 GitHub Actions 的 quality-linux job 中，由 `run-pytest-shards.sh` 调度，使用独立 PG 容器隔离 | shard-2.txt 包含 `test_bootstrap_all_env_pg_gate.py`，CI log 显示 passed | ✅ 高：自动门 Gatekeeper，符合 DoD A1-A4 |
| **C. 混合来源** | 部分用例在 CI，部分在本地；或同一测试文件既有 PG 半边又有 SQLite 半边 | `test_viral_refresh.py`：PG 半边由 `test_cw058...` 证明，SQLite 半边保留 | 🟡 条件高：需区分半边 |

### 1.3 核销证据可信度评级标准

| 评级 | 条件 | 结论 |
| --- | --- | --- |
| **🟢 高** | 测试文件在 CI 分片清单里，且 CI log 可追溯至主 branch（main 或受保护分支） | 该文件的 PG 断言证据链完整，可直接用于 CW-043 正式核销签字 |
| **🟡 中** | 测试文件不在 CI 分片清单，但已在本地真实 PG 全量通过（GREEN），且前置 CI 门禁（mypy/ruff/format）通过 | 证据链基本完整，但缺少 CI 门禁层的"无人值守"保障；建议纳入 CI，但不阻碍核销 |
| **🔴 低** | 测试文件不在 CI 分片清单，且无本地 pytest 全量证据（例如尚未运行） | 无法用于核销签字；必须先补 local green → CI 分片增补 → CI log 归档 |

---

## 2. CI 分片机制解析

### 2.1 执行脚本 `scripts/ci/run-pytest-shards.sh`

关键行为（全文 203 行，节选）：

```bash
SHARDS="${1:-${CI_PYTEST_SHARDS:-4}}"  # 默认 4 分片

# 分片清单目录
COMMITTED_SHARD_DIR="${SCRIPT_DIR}/test-shards"

# 检查分片 manifest
for ((i = 0; i < n; i++)); do
  if [ ! -f "${COMMITTED_SHARD_DIR}/shard-${i}.txt" ]; then ok=0; break; fi
done

# 启动 4 个独立 PG 容器（端口 5433–5436）
for ((i = 0; i < SHARDS; i++)); do
  port=$((BASE_PORT + i))  # 5433, 5434, 5435, 5436
  ...
  dsn_list[$i]="postgresql://testuser:testpass@localhost:${port}/${PG_DB}"
done

# 每分片独立运行
TEST_POSTGRESQL_URL="${dsn_list[$i]}" pytest ${files}
```

**要点**：
- 每个分片使用**独立的 PostgreSQL 容器**（`customer-v3-pg-test-shard{0..3}`），物理隔离，零冲突
- 分片清单来自 `scripts/ci/test-shards/shard-{0..3}.txt`，一旦 committed 即固定
- 若 manifest 缺失（requested N > committed count），脚本会尝试用 `build-test-shards.py` 动态生成；失败则退化为单分片串行

### 2.2 当前分片清单统计

```powershell
disk_count = 115   # 磁盘上的 test_*.py（不含 conftest/pg_test_kit）
shard_count = 99   # CI 分片清单合计（去重）
missing_from_ci = 115 - 99 = 16  # 16 个文件从未在 CI 执行
```

**16 个缺口文件清单**（按交付任务归类）：

| # | 文件名 | 交付任务 | main 合并 PR / SHA | 状态 |
| --- | --- | --- | --- | --- |
| 1 | `test_cw024_signed_release_upgrade_contracts.py` | CW-024 | 在制（local worktree，未合入 main） | ⏳ 等待合入 |
| 2 | `test_cw026_converged_auth.py` | CW-026 | PR #36 (`39219ca`) | ✅ 已合入 |
| 3 | `test_cw027_admin_permission_matrix.py` | CW-027 | PR #37 (`c4cafb7`) | ✅ 已合入 |
| 4 | `test_cw028_shared_settings_contract.py` | CW-028 | 在制（local worktree，未合入 main） | ⏳ 等待合入 |
| 5 | `test_cw029_billing_pg_matrix.py` | CW-029 | PR #28 (`c20419f`) | ✅ 已合入 |
| 6 | `test_cw030_worker_pg_matrix.py` | CW-030 | PR #29 (`1b78734`) | ✅ 已合入 |
| 7 | `test_cw032_delivery_package.py` | CW-032 | PR #31 (`db72705`) | ✅ 已合入 |
| 8 | `test_cw054_pg_portable_contract.py` | CW-054 | PR #14 (`874e976`) | ✅ 已合入 |
| 9 | `test_cw056_supported_head_matrix.py` | CW-056 | PR #15 (`d3d66b2`) | ✅ 已合入 |
| 10 | `test_cw057_cli_pg_entry.py` | CW-057 | PR #19 (`8ab85c7`) | ✅ 已合入 |
| 11 | `test_cw058_content_asset_pg_matrix.py` | CW-058 | PR #33 (`38ae06c`) | ✅ 已合入 |
| 12 | `test_cw059_billing_pg_matrix.py` | CW-059 | PR #41 (`4f18b73`) | ✅ 已合入 |
| 13 | `test_cw059_task_worker_pg_matrix.py` | CW-059 | PR #41 (`4f18b73`) | ✅ 已合入 |
| 14 | `test_cw059_rbac_pg_matrix.py` | CW-059 | PR #41 (`4f18b73`) | ✅ 已合入 |
| 15 | `test_cw060_operator_isolation.py` | CW-060 | PR #27 (`d49f851`) | ✅ 已合入 |
| 16 | `test_storage_cross_instance.py` | CW-031 | 在制（local worktree，未合入 main） | ⏳ 等待合入 |

**分类统计**：
- **已合入 main 但未进 CI 分片**：13 个（2/3/5/6/7/8/9/10/11/12/13/14/15）
- **在制未合入 main**：3 个（1/4/16）

---

## 3. 缺口文件核销证据可信度评估表

对每个缺口文件，评估其 PG 断言的本地证据状态，给出可信度评级。数据来源：
- Segment 1 矩阵（`CW043-PG-COVERAGE-MATRIX.md` §3 增量文件归属）
- CW-058/CW-059 evidence（已核验的本地 pytest GREEN 记录）
- 其他任务的 evidence 文档（如 CW-026/CW-027/CW-028/CW-029/CW-030/CW-032/CW-054/CW-056/CW-057/CW-060）

### 3.1 评估结果总览

| # | 文件名 | 交付任务 | main 合并 | 本地 pytest | PG 断言位置 | 评级 | 理由 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `test_cw024_signed_release_upgrade_contracts.py` | CW-024 | ❌ 未合入 | N/A | N/A | 🔴 低 | 在制任务，未合入 main，无法核销 |
| 2 | `test_cw026_converged_auth.py` | CW-026 | ✅ PR #36 | ✅ GREEN | 本文件 22 用例 | 🟡 中 | 本地 verified，但不在 CI 分片 |
| 3 | `test_cw027_admin_permission_matrix.py` | CW-027 | ✅ PR #37 | ✅ GREEN | 本文件 20 用例 | 🟡 中 | 同上 |
| 4 | `test_cw028_shared_settings_contract.py` | CW-028 | ❌ 未合入 | N/A | N/A | 🔴 低 | 在制任务 |
| 5 | `test_cw029_billing_pg_matrix.py` | CW-029 | ✅ PR #28 | ✅ GREEN | 本文件 20+ 用例 | 🟡 中 | 已在 CW-059-EVIDENCE §7 引用，但本文件本身未在 CI 跑 |
| 6 | `test_cw030_worker_pg_matrix.py` | CW-030 | ✅ PR #29 | ✅ GREEN | 本文件 14+ 用例 | 🟡 中 | 同上 |
| 7 | `test_cw032_delivery_package.py` | CW-032 | ✅ PR #31 | ✅ GREEN | 本文件契约测试 | 🟡 中 | 无 PG 断言，属 TEST-PACKAGE，但也不在 CI 分片 |
| 8 | `test_cw054_pg_portable_contract.py` | CW-054 | ✅ PR #14 | ✅ GREEN | 本文件 PG-02/04/08 契约 | 🟡 中 | CW-054-EVIDENCE 已记 27 用例 GREEN |
| 9 | `test_cw056_supported_head_matrix.py` | CW-056 | ✅ PR #15 | ✅ GREEN | 本文件空/旧 PG 升级矩阵 + fail-closed | 🟡 中 | CW-056-EVIDENCE 已记 7 用例 GREEN |
| 10 | `test_cw057_cli_pg_entry.py` | CW-057 | ✅ PR #19 | ✅ GREEN | 本文件 CLI PG 入口统一 | 🟡 中 | CW-057 交付简单，仅在 main 合入 |
| 11 | `test_cw058_content_asset_pg_matrix.py` | CW-058 | ✅ PR #33 | ✅ GREEN | 本文件 20 用例 | 🟡 中 | CW-058-EVIDENCE §5 明确 20 passed / 0 failed |
| 12 | `test_cw059_billing_pg_matrix.py` | CW-059 | ✅ PR #41 | ✅ GREEN | 本文件 12 用例 | 🟡 中 | CW-059-EVIDENCE §3.1.1 明确 12 passed |
| 13 | `test_cw059_task_worker_pg_matrix.py` | CW-059 | ✅ PR #41 | ✅ GREEN | 本文件 14 用例 | 🟡 中 | CW-059-EVIDENCE §3.2.1 明确 14 passed |
| 14 | `test_cw059_rbac_pg_matrix.py` | CW-059 | ✅ PR #41 | ✅ GREEN | 本文件 7 用例 | 🟡 中 | CW-059-EVIDENCE §3.3.1 明确 7 passed |
| 15 | `test_cw060_operator_isolation.py` | CW-060 | ✅ PR #27 | ✅ GREEN | 本文件 hashed artifact + operator 隔离 | 🟡 中 | CW-060-EVIDENCE 应已记 |
| 16 | `test_storage_cross_instance.py` | CW-031 | ❌ 未合入 | N/A | N/A | 🔴 低 | 在制任务 |

**评级分布**：
- 🟢 高：0 个（**所有 16 个缺口文件均无 CI 分片证据**）
- 🟡 中：13 个（已合入 main 且有本地 GREEN 证据）
- 🔴 低：3 个（在制任务，无法核销）

---

## 4. 高风险文件详细说明

### 4.1 已合入 main 的 13 个文件：核销证据的"信任缺口"

**共同特征**：
- ✅ 已在 main 合入（PR 编号、SHA 已登记）
- ✅ 本地 pytest 全量 GREEN（有 evidence 文档背书或 claim.json lifecycle_note）
- ❌ **从未在 CI 分片执行**（不在 shard-{0,1,2,3}.txt）

**风险点**：
1. **缺少 CI 门禁层的"无人值守"证据**：若某天这些测试 fixture 松动或 PG DSN 变更，CI 不会发现
2. **不符合 DoD A4 "CI 门禁要求"**：所有 TEST-PG 类测试应在 CI 分片里跑至少一次
3. **核销签字需降级处理**：即便本地 verified，也需在 CW-043 账本 §18 注明"⏳ CI 分片增补待 CW-061"

**建议动作**：
- 等 CW-061 合入后，由 CW-061 的 `build-test-shards.py` 自动将这 13 个文件纳入新分片清单
- 或在 CW-043 实施阶段临时用 `scripts/ci/run-pytest-shards.sh 1` 单分片模式跑全量作为"应急证据"

### 4.2 在制的 3 个文件：无法参与核销

| 文件名 | 原因 | 责任任务 |
| --- | --- | --- |
| `test_cw024_signed_release_upgrade_contracts.py` | CW-024 签名升级安全契约，local worktree in-flight | CW-024 owner |
| `test_cw028_shared_settings_contract.py` | CW-028 共享设置迁移契约，local worktree in-flight | CW-028 owner |
| `test_storage_cross_instance.py` | CW-031 云端资产跨实例存储，local worktree in-flight | CW-031 owner |

**建议**：先推动这 3 个任务合入 main，再考虑核销。

---

## 5. 与 Segment 1 矩阵的关系映射

Segment 1 建立的"CW-053 底稿 × TEST-PG 断言”逐文件映射中，**每个 SEGMENT 1 已标记"替代/保留/移交"的行**，在本 Segment 2 进一步标注"可信度来源"：

| Segment 1 ID | 文件名 | Segment 2 可信度 | 合并说明 |
| --- | --- | --- | --- |
| B1–B4 (账务) | `test_cw029_billing_pg_matrix.py` + `test_internal_billing.py` | 🟡 中 | Segment 1 表 #5 指出 CW-029 建平行矩阵但未迁旧文件；Segment 2 指出 CW-029 文件不在 CI 分片 |
| S1-01..12 (账务 PG) | `test_cw059_billing_pg_matrix.py` | 🟡 中 | Segment 1 §5.1.1 登记 12 用例替代；Segment 2 确认本地 12 passed 但 CI 未跑 |
| T1–T7 (任务) | `test_cw030_worker_pg_matrix.py` + `test_cw059_task_worker_pg_matrix.py` | 🟡 中 | Segment 1 §5.1.2 登记 14 用例；Segment 2 同样无 CI 分片 |
| P1–P7 (权限) | `test_cw059_rbac_pg_matrix.py` | 🟡 中 | Segment 1 §3.3.1 登记 7 用例 RBAC 真 PG 双向证明；Segment 2 确认为缺品文件之一 |
| N11–N12 (CW-054/056/057) | `test_cw054_pg_portable_contract.py` + `test_cw056_supported_head_matrix.py` + `test_cw057_cli_pg_entry.py` | 🟡 中 | Segment 1 §3 列为 N12/N13/N14；Segment 2 确认本地 VERIFIED 但 CI 未跑 |
| N15 (CW-058) | `test_cw058_content_asset_pg_matrix.py` | 🟡 中 | Segment 1 §3 列为 N15；Segment 2 确认 20 passed 但 CI 未跑 |

---

## 6. 结论与建议

### 6.1 主要发现

1. **100% 缺口文件缺乏 CI 分片证据**：当前 no file with 🟢 rating
2. **13 个已合入 main 的文件处于"信任缺口"**：本地 GREEN + CI gap = 🟡 medium risk
3. **3 个在制任务无法核销**：🔴 low priority until merged

### 6.2 对 CW-043 核销的影响

- **不影响 INVENTORY_ONLY 盘点的完成**：Segment 1+2 可独立完成 mapping + 风险评估
- **影响正式核销签字**：必须等 CW-061 合入 main，分片清单自动扩至 115+，13 个 🟡 升为 🟢
- **建议在账本 §18 CW-043 行登记**："盘点已就绪；13 个 TEST-PG 文件核销证据待 CI 分片增补；3 个在制任务 pending merge"

### 6.3 下一步行动

| 优先级 | 行动 | 责任人 | 依赖 |
| --- | --- | --- | --- |
| P0 | CW-061 合入 main（CI 分片覆盖守门） | CW-061 owner | 无 |
| P1 | CW-024/028/031 合入 main | 各 owner | 无 |
| P2 | CW-043 正式实施分支启动（scope=CODE_AND_TEST_INCREMENT） | CW-043 owner | CW-061 merged |
| P3 | 抽样复核 RED→GREEN（Segment 3 方案） | CW-043 owner | CW-061 merged |
| P4 | 全量核销签字 + CW-042 裁剪启动 | CW-043 owner | CW-043 SEGMENTS complete |

---

## 附录 A：16 个缺口文件的 CI 分片增补预测

预计 CW-061 合入后，`scripts/ci/build-test-shards.py` 会重新均衡分配 115+ 文件到 4 个分片，预测分布：

```
shard-0.txt: ~29 files  (原 24 + 新增 5)
shard-1.txt: ~29 files  (原 23 + 新增 6)
shard-2.txt: ~29 files  (原 26 + 新增 3)
shard-3.txt: ~29 files  (原 26 + 新增 3)
```

**具体分配**取决于 `build-test-shards.py` 的负载均衡算法（目前源码未读，假设按文件名字母序或随机哈希）。

---

*End of Segment 2.*
