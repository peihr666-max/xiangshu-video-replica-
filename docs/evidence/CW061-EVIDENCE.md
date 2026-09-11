# CW-061 证据文件 — CI 分片清单覆盖率守卫（修复 CW-044 §18.2 fail-open 缺口）

任务：CW-061（代码与测试增量 · CI 门禁职责不缺失 · 独立紧急修复，不依赖任何前置）
分支：`feat/customer-v3-cw061-ci-shard-coverage-guard`（独立 worktree `E:/众墅之家爆款短视频创作/.worktrees/CW-061-ci-shard-coverage-guard`，从 `origin/main@426afa3` 创建）
来源：CW-044 前置盘点 §18.2「最高优先发现」——CI Linux 门 server pytest 只执行 committed 分片清单内的测试文件，清单陈旧即静默漏跑，缺口 fail-open、单向增长、本地永不暴露。owner 2026-09-11 选择「立即另开修复任务」，本会话立项 CW-061 承接。
上游规格：CW-044 `docs/evidence/CW044-INVENTORY.md` §18.2 收口点位 SH-5（重生清单）+ SH-6（fail-closed 守卫）+ CI-7（覆盖率断言步骤）。

---

## 1. 交付差额（对 §18.2 三点位逐条收口）

| §18.2 点位 | 缺口 | 本 PR 处置 |
| --- | --- | --- |
| SH-5 | committed `shard-{0..3}.txt` 并集 = 99，仓库实有 113（base 112 + 本任务新增测试文件），**14 个测试文件 CI 从不执行** | `build-test-shards.py --shards 4` 重生四份清单，覆盖全 113（28/26/29/30，均衡 spread ~0.0s）；重生后 `--check-coverage` RC=0 |
| SH-6 | `run-pytest-shards.sh` `resolve_manifests()` 在 4 份 committed 清单齐全时直接 `return 0`，**不校验并集完整性** | committed 分支采用前调用 `build-test-shards.py --check-coverage`，缺口/幽灵非空即 `exit 1`（fail-closed，不降级 sequential——降级会掩盖陈旧、让清单腐烂） |
| CI-7 | `ci.yml` `quality-linux` 无全量 pytest 兜底（`check:static` = 旧 `npm run check` 去掉尾部全量 pytest） | sharded pytest 步骤**之前**插入独立断言步骤 `Assert shard manifests cover every test file`，`run: python3 scripts/ci/build-test-shards.py --check-coverage`，非 0 即门禁失败并打印缺口清单 |

**根因**：分片清单是「白名单」语义——runner 只跑清单内文件；清单一旦陈旧，新测试文件静默排除在 CI 之外，而本地顺序跑（`run_sequential` 传整个 `server/tests`）反而全覆盖，故缺口在本机永不暴露。修复把「清单必须覆盖全集」从隐式假设变为**机器强制的门禁断言**。

## 2. `find_uncovered_tests()` + `--check-coverage`（SH-6 核心 / CI-7 复用）

- `scripts/ci/build-test-shards.py` 新增纯函数 `find_uncovered_tests(manifest_dir, tests_root) -> (uncovered, ghosts)`：
  - `uncovered` = 发现的 `test_*.py` 中不在任何清单并集的文件（CI 会静默跳过）；
  - `ghosts` = 清单条目中已不是发现测试文件的项（重命名/删除遗留）；
  - 两表均排序，确定性可复核；清单条目按字符串 strip 后与 `discover_test_files()` 逐字比对（同一 repo-relative posix 拼写）。
- 新增 `--check-coverage` 只读模式：读 `--out-dir`（默认 committed 清单目录）与 `--tests-root`（默认 `server/tests`），缺口或幽灵非空 → 打印明细 + `return 1`；完整 → `return 0`。**不写任何文件**，故 CI-7 断言步骤与 SH-6 runner 守卫复用同一入口，双保险。
- 该文件不在 ruff/mypy 作用域（`check:static` 只跑 `ruff check server` / `ruff format --check server` / `mypy server/app`），新增代码风格与既有文件一致。

## 3. runner fail-closed 守卫（SH-6）

- `scripts/ci/run-pytest-shards.sh` `resolve_manifests()` committed 分支（清单齐全）采用前插入 `--check-coverage`；失败即 `exit 1`，触发既有 cleanup trap 正常清理。
- **不降级到 sequential**：降级虽能覆盖全集但会掩盖陈旧、让 committed 清单永不强制更新；fail-closed 迫使开发者重生并提交清单。清单不齐全（N 不匹配）的既有重生分支用 `build-test-shards.py --shards n` 发现全集，天然无缺口，不需守卫。

## 4. ci.yml CI-7 断言步骤

- `.github/workflows/ci.yml` `quality-linux`：在 `Run static quality checks`（`check:static`）之后、`Run sharded PostgreSQL pytest` 之前插入 `Assert shard manifests cover every test file` 步骤。
- 顺序契约由 `test_build_contracts.py::test_ci_shard_coverage_guard_is_wired` 机器断言：`workflow.index("build-test-shards.py --check-coverage") < workflow.index("bash scripts/ci/run-pytest-shards.sh")`。

## 5. SH-5 重生结果

- `python3 scripts/ci/build-test-shards.py --shards 4` → `shard-0/1/2/3.txt` = 28/26/29/30，共 113 文件，各 ~252.3s（复用既有 `test-durations.json` profile，新文件按 1.0s 默认成本入最短分片）。
- `python3 scripts/ci/build-test-shards.py --check-coverage` → `coverage OK: 113 discovered test file(s) fully covered`，RC=0。
- **自证单向增长**：本任务新增的 `test_cw061_shard_coverage_guard.py` 在重生前正是第 14 个未覆盖文件（旧并集 99 vs 发现 113）——每加一个测试文件缺口 +1，与 §18.2 论断一致；SH-6/CI-7 守卫此后使这类漏跑无法再静默发生。

## 6. 验证记录（本机 Windows，纯离线，无需 PG/Docker）

- **TDD RED**：新增 `tests/test_cw061_shard_coverage_guard.py`（7 用例）+ `test_build_contracts.py` 追加 `test_ci_shard_coverage_guard_is_wired` → 实现前 **8 failed / 6 passed**（失败原因精确为 `AttributeError: no attribute 'find_uncovered_tests'` 与 `'--check-coverage' not in runner`）。
- **TDD GREEN**：实现 SH-5/SH-6/CI-7 后 → **14 passed**（7 CW-061 + 7 build_contracts，既有 6 契约测试零回归）。
  - 覆盖：`find_uncovered_tests` 缺失/完整/幽灵三态、`--check-coverage` CLI 缺口 exit 1 / 完整 exit 0、committed 清单覆盖真实全集、变异检测（删一条清单条目 → 守卫精确报出该文件）。
- **静态门**：`ruff check server` All checks passed；`ruff format --check server` 309 files already formatted（新测试文件已 `ruff format`）；`verify_no_secrets.sh` exit 0（CI 同款）。
- **回归面**：`git grep` 证实 tracked 测试中仅 `test_build_contracts.py` 引用这些 CI 脚本，回归面即该两文件，均全绿。

## 7. 与相邻任务的边界

- **CW-044**：本任务收口其 §18.2 三点位（SH-5/SH-6/CI-7），是 CW-044「CI 门禁职责不缺失」范围内**唯一不依赖 CW-040/041/042/043 的可立即修项**；不触碰 CW-044 盘点分支（`feat/customer-v3-cw044-ci-doc-inventory`）的任何文件。
- **CW-043**：§18.2 明确「CW-043 开工前必须先修」——本守卫使 CW-043 的 PG 覆盖核销建立在一个不会静默漏跑的 CI 门之上。
- **CW-060**：其新增 `test_cw060_operator_isolation.py` 正是 §18.2 漏跑名单成员之一；本 PR 重生后已纳入清单，CI 将真实执行。

## 8. 诚实边界

- `test-durations.json` **未刷新**：刷新需 Docker+PG 全量 `pytest --durations=0` 跑；本 PR 复用既有 profile 重生清单，覆盖率与 profile 无关（profile 只影响分片均衡，不影响是否覆盖）。新文件按 1.0s 默认成本入片，实测 ~0.1s，均衡影响可忽略。profile 刷新建议随下一次全量 PG 基线跑顺带更新。
- 全量 pytest 与三门禁最终以 CI 为准；本机仅跑受影响的两个测试文件 + 静态门（纯离线可判定部分），未在真实 Docker/PG 环境跑分片全流程。
- ci.yml 步骤未经 GitHub Actions 实跑验证（本机无 `gh` CLI）；YAML 结构与相邻 step 逐字对齐，契约测试钉住关键子串与顺序。
- 证据等级 `AUTOMATED_VERIFIED`（本地自动化，离线契约范围）。
