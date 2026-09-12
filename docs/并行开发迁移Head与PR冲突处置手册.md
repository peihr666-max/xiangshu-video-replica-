# 并行开发迁移 Head 与 PR 冲突处置手册

> **文档定位**：本文是多会话并行开发下「迁移 head 对不上 + PR 文件反复冲突」的**处置正本**，由 2026-09-11~12 连续 6 起真实事故的根因与修法总结而来（台账见 §6，每条带 PR 号 + SHA 证据）。后续所有任务的 Owner 在开工、合并 main、push 三个时点按本文执行；与排班清单（§3/§6 流程）、PostgreSQL 规范（迁移红线）互补，不替代。
>
> **维护**：COORD-DEV-PLAYBOOK（无业务 CW 编号的文档维护任务）；发现新模式直接追加 §6 台账并同步 §3/§4 修法。

## 0. 三条铁律（TL;DR）

1. **迁移链单人延长**：新迁移的 `down_revision` 在**开工时**取当时 origin/main 的 head；并行期间 main 前进了，**合并时后合者负责重挂**（`down_revision` → 新 head）+ 重探针（§4）+ bump head 断言。迁移文件只追加、不改名、已发布 revision 逐字节冻结（红线不变）。
2. **注册表文件取并集，绝不整块替换**：`pg_test_kit.RECORDED_TEST_DATABASES`、`reconcile_customer_billing.PG_ONLY_TABLES/PG_ONLY_COLUMNS`、`scripts/ci/test-shards/*`、账本 §18——这些是多方追加的注册表，冲突时取「main 全集 ∪ 本分支自有条目」。整块取 main 版会**静默删掉别人/自己的登记**（事故 ⑤）。
3. **push 前跑 §5 预检清单**：`alembic heads` 恰为 1 且等于本分支预期 head；`--check-coverage` EXIT=0；冻结探针重算通过；docs 冲突按规则解决。**预检不过不 push**——CI 分片一轮 17 分钟，本地 30 秒能拦住的问题不要交给 CI 发现。

## 1. 问题机制：为什么反复发生

三个结构性因素叠加：

- **多会话并行 × 单线 main**：每小时都有 PR squash 进 main；任何在制分支 2~3 小时后就落后。
- **五类「共享注册表」文件**（§3 表）：每个合并进 main 的任务都会追加登记（新迁移 head、新测试数据库、新测试文件、新账本行），其他在制分支上这些文件立即过时。
- **squash 合并的语义稀释**：集成人解决冲突时用旧版本整块覆盖 → main 账本倒退 / 注册表丢行；反向地，分支合并旧 main 后带着陈旧注册表进 CI → 分片崩溃。

具体失效链条（迁移类）：任务 A、B 各自从 head=X 开出新迁移 → 都挂 `X` 为父；A 先合并，main head 变 Y；B 不重挂就合并 → **alembic 双 head**，所有迁移类测试（升级矩阵、head 断言、T07 导入器、schema 冻结）当场崩溃（事故 ③：4 shard 共 141 failed + 1551 errors）。

## 2. 冲突高发文件家族与标准修法

| # | 文件/家族 | 冲突形态 | 标准修法 | 工具 |
| --- | --- | --- | --- | --- |
| 1 | `server/migrations/versions/*.py` | 两个分支各自新增迁移挂同一父 | 后合者改 `down_revision` → 当前 main head；单头验证 | `alembic heads`（须恰 1 个） |
| 2 | `server/tests/test_cw056_supported_head_matrix.py` | 冻结的 `HEAD_SCHEMA_COUNTS`/`HEAD_SCHEMA_DIGEST`/`HEAD_TABLE_NAMES` 与实际 head 漂移 | 用测试模块**自身 helper** 重探针（§4 脚本），逐项更新；新表名进 `HEAD_TABLE_NAMES`；head 常量 `HEAD_REVISION` 指到本分支 head | §4 探针脚本 |
| 3 | ~9 个测试文件里的 head 断言（`version == "0XX_..."`） | head 移动后断言集体失败 | `grep -rln '"08X_'` 全部 bump 到新 head（一次例行动作，18 处 ≈ 1 分钟） | grep + 批量替换 |
| 4 | `server/scripts/reconcile_customer_billing.py` | `PG_ONLY_TABLES` / `PG_ONLY_COLUMNS` 各自追加登记 | **并集**：新增 PG-only 表/列必须在分支上登记，合并冲突时两边都保留 | 手工并集 + ruff |
| 5 | `server/tests/pg_test_kit.py` | `RECORDED_TEST_DATABASES` 丢行（合并解决覆盖） | main 块 ∪ 分支自有条目；**禁整块替换**；每个专用测试库新条目带注释 | 手工并集 |
| 6 | `scripts/ci/test-shards/shard-*.txt` | 分支新增/删除测试文件后 committed 清单过时 | `python3 scripts/ci/build-test-shards.py --shards 4` canonical 再生，再跑 `--check-coverage` | CW-061 守卫会在 CI 拦截 |
| 7 | `docs/客户版任务清单-V3.md`（§18）/`docs/客户版V3任务进度快照.md` | 多会话同改；集成人旧版覆盖 → 账本倒退 | 行集合与 main 一致且本分支无自有行 → 整文件取 main；有自有行 → 合并保留；§18 行编辑**只从 `## 18.` 行号向后定位**（§17 同前缀会误伤） | patrol 巡查兜底 |
| 8 | `docs/客户云版任务认领登记.md` | 并行插行 | Accept both 双行都保留（既定规则）；治本=新登记追加表尾 | — |

## 3. 迁移链三时点规程

**开工时（创建分支后第一件事）**：

```bash
git fetch origin && git rev-parse origin/main          # 记录基线
cd server && alembic heads                              # 当前 main head（恰 1 个）
# 新迁移文件：down_revision = "<上一步的 head>"
# 同时登记三件套（漏一必崩 CI）：
#   ① pg_test_kit.RECORDED_TEST_DATABASES（若建专用测试库）
#   ② reconcile_customer_billing.PG_ONLY_TABLES/PG_ONLY_COLUMNS（PG-only 表/列）
#   ③ scripts/ci/test-shards 再生（新增了测试文件）
```

**在制期间（每次准备 push 前）**：

```bash
git fetch origin && git merge origin/main               # 落后就合，别攒
alembic heads                                           # 仍须单头；若 main 带来新 head → 按"合并时"规程处理
```

**合并时（你的 PR 与已进 main 的另一迁移 PR 冲突/双 head）**：

1. `git merge origin/main`，迁移文件冲突 → 你是后合者，重挂你的 `down_revision` → main 新 head；
2. 跑 §4 探针 → 更新矩阵冻结常量 + `HEAD_REVISION`；
3. bump 全仓 head 断言（家族 #3）；
4. 其余冲突按 §2 表逐家族处理；
5. 本地跑受影响测试全绿再 push（CI 只做最终裁决，不做调试工具）。

**排序纪律**：schema 类 PR 尽量**同日串行合并**（巡查账本会标「合并顺序注意」）；两个 schema PR 同时开着就是双 head 倒计时。

## 4. 冻结事实探针脚本（标准工具）

对空库升到分支 head，用 CW-056 测试模块**自身 helper** 重算冻结值（与测试零漂移；禁止手写等价 SQL）：

```bash
cd server && ../../server/.venv/bin/python - <<'EOF' 2>&1 | grep -vE 'INFO  \[alembic'
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'tests')
import importlib.util
spec = importlib.util.spec_from_file_location('cw056m', 'tests/test_cw056_supported_head_matrix.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
from tests import pg_test_kit as kit
kit.drop_test_database(m.MATRIX_DATABASE); kit.create_test_database(m.MATRIX_DATABASE)
try:
    dsn = m._matrix_dsn(kit.resolve_test_dsn(), m.MATRIX_DATABASE)
    m._upgrade(dsn, m.HEAD_REVISION)
    import psycopg
    with psycopg.connect(dsn) as conn:
        print('TABLES:', len(m._schema_inventory(conn)['tables']))
        print('COUNTS:', m._schema_counts(conn))
        print('DIGEST:', m._inventory_digest(m._schema_inventory(conn)))
finally:
    kit.drop_test_database(m.MATRIX_DATABASE)
EOF
```

前提：`scripts/pg-fixture.sh start`（或分片脚本自管容器）。输出逐项替换矩阵测试的 `HEAD_SCHEMA_COUNTS` / `HEAD_SCHEMA_DIGEST`；`TABLES` 数若变，同步 `HEAD_TABLE_NAMES`。

## 5. push 前预检清单（复制即用）

```text
[ ] git fetch origin；落后就 merge origin/main（冲突按 §2 表逐家族解决）
[ ] cd server && alembic heads —— 恰 1 个，且 == 本分支 HEAD_REVISION/新迁移 revision
[ ] 分支加了迁移？→ ①PG_ONLY 登记 ②专用库 allowlist ③shards 再生 ④矩阵探针重冻结 ⑤head 断言 bump
[ ] python3 scripts/ci/build-test-shards.py --check-coverage —— EXIT=0
[ ] 受影响测试文件本地真实 PG 全绿（pg-fixture 或分片脚本；只跑专项，秒级~分钟级）
[ ] ruff format --check + ruff check（改动文件）—— CI step10 第一道就是它
[ ] 文档冲突已解决（§2 #7 规则），不把冲突推给评审人
[ ] git log origin/main..HEAD 只含本任务提交
```

## 6. 事故台账（2026-09-11~12 实录，全部已修复）

| # | 事故 | 证据 | 根因 | 修法沉淀 |
| --- | --- | --- | --- | --- |
| ① | CW-061 PR #36 期：cw030 白名单被 38ae06c 合并丢失 → main CI 红 | 巡查记录 e6acdc9 | 合并解决整块覆盖注册表 | 铁律 2 |
| ② | #57/#58 并行：083/086 同挂 082 → 后合者双 head，141F+1551E | #57 429885f、#58 00f3808 | 并行 schema PR 无重挂规程 | §3 合并时规程 |
| ③ | #57 与 #58 都合并后，083 仍挂 082 → 与 main 再冲突，11 文件 | 0a3854f（合并提交） | 先合者合并后未通知后合者重挂 | §3 排序纪律 + 重挂 086 实录 |
| ④ | #48 修 allowlist 时整块取 main 版 → 误删分支自有 cw063 条目，10 例 preflight error | c7ac65c | 铁律 2 反面教材 | 铁律 2 的「并集」措辞 |
| ⑤ | #51 分支带 42 行远古账本进 PR（squash 会倒退 main） | be3b8b8 重置提交 | 长寿分支 + 集成人旧版覆盖 | §2 #7 整文件重置规则 |
| ⑥ | #64（CW-078）：测试 SQL 对 counters 表用不存在的 dimension 列（17E）+ T07 契约缺 customer_api_keys（6F）+ 冻结值未重探针（4F） | 386764f | 测试按想象的 schema 写 + 三件套登记漏项 | §3 开工时三件套 + §4 探针 |

**共性**：没有一起是 alembic/CI 的 bug——全部是「并行写入共享状态时缺少合并协议」。本手册就是那份协议。

## 7. 边界与红线（不因本手册改变）

- 迁移文件名冻结（`025_...`~`030_...` 为客户版冻结段；082+ 为增量段）、已发布 revision 逐字节不可改——重挂 `down_revision` 仅适用于**尚未合并进 main** 的分支迁移。
- 真实付费/生产 COS/发码/灰度等人工授权边界不变；业务 DoD 与证据层级不变。
- 合并始终由用户或获授权执行者完成；本文只规范「合并前分支侧的准备与冲突解决」。
