# MIGRATION-GUARD-20260912 — 迁移链守卫工具化 · 证据

- **任务**：MIGRATION-GUARD-20260912（无业务 CW 编号的 CI/工程效能维护任务）
- **日期**：2026-09-12
- **基线**：`origin/main` @ `360cb1f84abe0ff064f32c5334ed0470253bb6f4`（PR #68 COORD-DEV-PLAYBOOK 合并后）
- **分支**：`chore/migration-guard-20260912`
- **worktree**：`E:/众墅之家爆款短视频创作/.worktrees/MIGRATION-GUARD-20260912`
- **证据层级**：`AUTOMATED_VERIFIED`

## 1. 目标与定位

把[《并行开发迁移 Head 与 PR 冲突处置手册》](../并行开发迁移Head与PR冲突处置手册.md)的人工步骤机械化为可执行命令：

| 手册条目 | 原形态 | 现形态 |
| --- | --- | --- |
| §4 冻结事实探针 | 手工复制粘贴 heredoc + 手抄数字 | `migration_manifest.py --print-schema` |
| §5 push 前预检清单 | 人肉逐条勾 | `migration_manifest.py --check`（CI 已接线） |
| §2 家族 #2/#3 | 「逐项手改」「18 处 ≈ 1 分钟」 | 独立重算 + 双跑比对 |
| §2 家族 #6 | shards 再生 | 不变（CW-061 已有守卫），本任务只跟随再生 |

**工具不拥有真源**：`HEAD_REVISION` / `PUBLISHED_*` / CW-056 冻结矩阵仍以 `server/tests/test_cw056_supported_head_matrix.py` 为准；工具用 `ast.literal_eval` 读取（**不执行该模块**）后独立重算再比对。这是「双跑」：两套实现必须同时正确，任一侧漂移都会红。

## 2. 交付物

**新增**

| 文件 | 内容 |
| --- | --- |
| `scripts/ci/migration_manifest.py` | 守卫与生成器；四个模式，静态半部纯标准库 `ast`（免 alembic、免 PG、免 venv） |
| `server/migrations/manifest.json` | 生成物：图谱、已发布链哈希、命名策略锚点、逐 revision 文件字节 |
| `server/tests/test_migration_guard_manifest.py` | 16 个用例：真实树契约 + 双跑 parity + 9 个变异反例 + 接线契约 |
| `docs/adr/adr-migration-chain-guard-tooling.md` | ADR |
| `docs/evidence/MIGRATION-GUARD-20260912-EVIDENCE.md` | 本文件 |

**修改**

| 文件 | 改动 |
| --- | --- |
| `.github/workflows/ci.yml` | `quality-linux` 内新增 `Assert migration chain invariants`，排在分片 pytest **之前** |
| `deploy/postgres/migrate.sh` | 对 `alembic heads` 与 `alembic current` 都计数并要求恰为 1 |
| `docs/并行开发迁移Head与PR冲突处置手册.md` | 新增 §5.1 指向工具（增量；不改其原有规定） |
| `docs/客户云版任务认领登记.md` | 追加本任务占用行 |
| `scripts/ci/test-shards/shard-{0..3}.txt` | 再生（新增测试文件）+ 行尾归一为 LF |

**刻意不修改**：`server/migrations/env.py`、`server/alembic.ini`（探索确认对拓扑零假设）、任何迁移文件、任何既有 head 字面量、`server/tests/pg_test_kit.py`（见 §6）。

## 3. 验证记录（均为本次实际执行）

### 3.1 守卫

| 命令 | 结果 |
| --- | --- |
| `python scripts/ci/migration_manifest.py --check` | `==> migration guard OK`，RC 0 |
| `--record` | 写入 `server/migrations/manifest.json`（444 行，全 LF） |
| `--check-schema`（真实 PG @5443，库在 head） | `==> schema guard OK`，RC 0 |
| `--check-schema`（真实 PG，库为空/未到 head） | **RC 1**，如实报 `alembic_version rows [] != ['089_customer_api_keys']` |
| `--print-schema` | 输出与 CW-056 既有冻结字面量**逐项相等** |

最后两行是一对：守卫在两种库状态下给出相反结论，说明这条断言不是恒真。

### 3.2 双跑 parity（关键命题）

在真实 PG 上实测 head schema，与 CW-056 手写冻结字面量比对：

```text
script heads          : ['089_customer_api_keys']
test HEAD_REVISION    : 089_customer_api_keys
MEASURED tables       : 78
MEASURED digest       : 8fe43e165b0d3882e72773a0a8345ca40cb1bd5a88d968584bc6567158cb5700
counts == literals    : True
digest == literal     : True
tables == literal set : True
```

### 3.3 测试

| 范围 | 命令 | 结果 |
| --- | --- | --- |
| 守卫契约 | `pytest server/tests/test_migration_guard_manifest.py` | **16 passed** |
| 综合（迁移矩阵 + 守卫 + 既有契约 + PG 工具包） | `pytest test_cw056_… test_migration_guard_manifest test_build_contracts test_customer_ha_smoke test_cw061_… test_pg_test_kit` | **90 passed，1 failed**（见 §6，该 1 项为本地垫片产物，非提交内容） |
| 分片覆盖 | `python scripts/ci/build-test-shards.py --check-coverage` | `coverage OK: 123 discovered test file(s) fully covered` |
| 静态门（CI 口径） | `ruff check server` / `ruff format --check server` / `mypy server/app` | 全过 / 334 files already formatted / Success 124 files |
| 秘密扫描 | `bash scripts/verify_no_secrets.sh` | `No hardcoded secrets detected` |

### 3.4 变异测试（守卫必须**会**失败）

一个从不失败的守卫等于没有守卫，故每条不变量都配反例：

| 变异 | 守卫反应 |
| --- | --- |
| 从已发布点分叉出第二个 head | `expected exactly one migration head, got [...]` |
| **merge revision 收口该双头**（正向） | 不再报多 head，且不动已发布段 |
| 新增迁移不按时间戳命名 | `new revisions must use the timestamp naming policy ...; offending: [...]` |
| **符合策略的时间戳新迁移**（正向对照） | **不产生命名类 failure**——防止「凡新增皆报错」伪装成正常 |
| **违规命名后重新 `--record`**（洗白尝试） | **仍被报出**——锚点不会随记录前移 |
| 手改清单里的锚点 | `manifest naming_policy.adoption_head is ... but this script pins ...` |
| 改动一个已记录 revision 的文件字节 | `<rev>: migration file changed since the manifest was recorded` |
| 两个文件声明同一 revision id | `duplicate revision id`（fail-closed） |
| 已发布段内出现分支点 | `published chain must stay linear` |

### 3.5 本机（Windows）失败归因

分片全量在本机跑出的失败**全部**经未改动 main 的对照 worktree 逐项确认为**既有环境问题**，与本任务无关：

| 失败集合 | 未改动 main 上 | 本分支上 |
| --- | --- | --- |
| `test_cw009_security_matrix_export.py`（4） | 同样失败 | 同样失败 |
| `test_cw033_pitr_drill_validation.py`（21） | 同样失败 | 同样失败 |
| `test_security_contracts.py::test_no_sentry_sdk_enters_the_server_runtime` | 同样失败 | 同样失败 |

这些用例驱动 bash 演练脚本 / 检查 POSIX 行为，在 Windows 上本就不可用。**本任务提交的改动引入的新失败为 0。**

## 4. 精确结论与边界

**得到**：漂移在数秒内、在 17 分钟的分片 pytest 之前被拦住；§4 探针可复现且跨机器一致（原 `.dev-env` freeze probe 不在任何 commit 或 worktree，该步骤此前只剩散文描述）；「已落地迁移被静默改写」有了机器痕迹；新迁移不再有抢号问题。

**不声称**：

1. 清单证明的是**「当前树与最后一次记录一致」**，**不是「没有人改写过历史」**。已发布段（base..055）的不可变性由 CW-056 的内容级/关系级 sha256 承担；056+ 段一个愿意重新 `--record` 的人仍可静默改写——本任务不声称堵住该口子。该边界写进 `manifest.json` 的 `basis` 字段。
2. 证据层级上限 `AUTOMATED_VERIFIED`，不证明真实授权链路上可用。
3. **未删除**任何既有手写字面量。10 个文件约 20 处 head 字面量与 CW-056 冻结矩阵**原样保留**（双跑）。删除属双跑成功后的独立后续任务。
4. 证据红线（`CW001-RELEASE-BASELINE.md:58,94`、`CW056-EVIDENCE.md:73-76` 记载的「纯线性链、无 `down_revision` 元组」）**未修改**。其重签归 owner；本任务只提供重验证据（§3.4 的线性不变量与 merge-revision 支持）。
5. 不替 #67（CW-075，迁移 090）等在制 PR 收口；本任务只保证收口手段可用。

## 5. 过程中发现并修正的三处问题（如实记录）

### 5.1 两处初始判断被实测推翻

| 初始判断 | 实测事实 | 影响 |
| --- | --- | --- |
| main 迁移矩阵「预期红」，等 integrator 重算冻结值 | **绿**。`test_cw056:125-131` 那段「仍冻结在 083 基线（tables=77/columns=913）、B 组预期红」的注释已过期；字面量实际已随 CW-078 合并更新到 089 的真实值（78/923） | 双跑 parity 的语义从「与陈旧字面量比对」改为「与实时测量比对」，见 §3.2 |
| `migrate.sh` 多头时「静默取第一个 head 判定成功」 | 脚本多头时 `migrate.sh:28` 的 `alembic upgrade head` 会因 `MultipleHeads`→`CommandError` **硬失败**（`_upgrade_revs` 内触发，`set -e` 中止）。真正缺口在 `:36`：`alembic current \| awk 'NR==1'` 面对**库里多行 `alembic_version`** 时只读首行 | 修复性质从「补一个不存在的守卫」改为「堵多行 alembic_version 的误判」，两侧都计数 |

两处都是**注释与代码漂移**——正是本任务要机械化掉的那类问题。`test_cw056:125-131` 的过期注释**未修改**（属 CW-056 冻结矩阵区，改动需独立评审），此处登记为已知文档漂移。

### 5.2 自引入的命名锚点洗白漏洞（已在提交前修掉）

初版让 `--record` 把 `naming_policy.adoption_head` 前移到当前 head。于是存在一条自我豁免路径：**加一个违规命名的迁移 → 跑 `--record`（锚点随之推到它）→ 提交**，此后锚点就是违规者自己，它落在豁免集里，再怎么 `--check` 都查不出来。

修法：锚点写成生成器里的常量 `NAMING_POLICY_ADOPTION_HEAD`（**不从清单读取**），`--check` 断言清单记录的锚点等于该常量；`check_naming_policy` 在锚点未知时 fail-closed 抛错而不是静默返回空（「策略失效」与「没有违规」在结果上无法区分）。两条对应反例见 §3.4。

### 5.3 自引入的跨平台行尾缺陷（已在提交前修掉）

`--record` 初版用 `Path.write_text`，在 Windows 上写出 **CRLF**。后果不只是 diff 噪声：`run-pytest-shards.sh` 读 shard 清单时每个路径尾部带 `\r`，pytest 报 `file or directory not found: server/tests/test_activation_code_schema.py`——**分片门直接失败**。这与 `.gitattributes` 的 `* text=auto eol=lf` 冲突。

修法：`write_manifest` 显式 `newline="\n"`；已重新生成 manifest 与 shard 清单并归一为 LF（现均为 0 个 CRLF）。注意 `scripts/ci/build-test-shards.py` 在 Windows 上同样会写 CRLF，属既有行为，本任务不改它，只在生成后归一。

## 6. 关于 `server/tests/pg_test_kit.py`：一次"改了又撤回"的取舍

**结论：该文件保持原样，本任务零改动。**

`pg_test_kit` 顶层 `import fcntl`（POSIX-only），在 Windows 上导致 **collection error**——一个 `ImportError` 会隐藏整个文件里的所有测试。我一度加了 `try/except ImportError` 守卫，理由是：手册 §5 要求「本地跑受影响测试全绿再 push」，而该守卫是能在本机验证 PG 套件的前提。

**撤回的理由**：实测发现该守卫会把「collection error」变成运行时 `RuntimeError`，从而让 `test_cw078_api_keys.py`（11 项）与 `test_pg_test_kit.py::test_shared_suite_lock_is_exclusive` 由「根本没跑」变成「跑了并失败」。而这**只影响一个仓库自己声明不支持的平台**——`pg_test_kit.py:322` 原文：「fcntl is POSIX-only; CI runs pytest on Linux only (windows-nsis builds the desktop app without executing the Python suites)」。为了不受支持的平台改动共享基础设施、还引入新失败，不划算。

**取而代之**：本地验证改用 `sitecustomize` 垫片（Python 标准机制，通过 `PYTHONPATH` 注入，**不进入仓库**）：

```bash
mkdir -p E:/migshield && cat > E:/migshield/sitecustomize.py <<'EOF'
import sys, types
try:
    import fcntl
except ImportError:
    m = types.ModuleType("fcntl")
    m.LOCK_EX, m.LOCK_SH, m.LOCK_NB, m.LOCK_UN = 2, 1, 4, 8
    m.flock = lambda *a, **k: None
    sys.modules["fcntl"] = m
EOF
PYTHONPATH=E:/migshield TEST_POSTGRESQL_URL=... pytest server/tests/test_cw056_supported_head_matrix.py
```

**该垫片会把 `test_shared_suite_lock_is_exclusive` 判失败**（空实现没有互斥性）——§3.3 里的那 1 项 failed 即此，不是提交内容的问题。CI（Linux）不注入垫片，两边都不受影响。

同类地，生成器 `_load_cw056_module()` 内部保留了一个 fcntl 桩，**作用域限于我自己新增的文件**，只为让 schema 模式能在 Windows 开发机上跑。CI/Linux 上走真 import，桩不生效。

## 7. 引用

- [并行开发迁移 Head 与 PR 冲突处置手册](../并行开发迁移Head与PR冲突处置手册.md)（PR #68，`360cb1f`）
- [ADR: 迁移链守卫工具化](../adr/adr-migration-chain-guard-tooling.md)
- [CW-053 DB 语义清单](CW053-DB-SEMANTIC-INVENTORY.md) §3 E1
- [CW-061 证据](CW061-EVIDENCE.md) §1（分片覆盖守卫，本任务 CI 接线沿用其范式）
