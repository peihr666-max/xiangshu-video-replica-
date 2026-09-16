# 内容寻址去重：闸门收敛、存量回填、素材去重与回收器通电

日期：2026-09-16。工作分支：`dedup-cas-20260916`（worktree `DEDUP-CAS-20260916`）。
基线：`20260914T0000_local_joint_merge`。迁移新增 `20260916T1400_content_objects`。

本分支交付分四轮，本文是四轮的合并证据。四轮依次是：
**① 删除闸门收敛 → ② 问题修复与回收器通电 → ③ 存量回填与素材库去重 → ④ 人物素材去重**。

## 四轮范围

| 轮次 | 内容 |
| --- | --- |
| ① | 把「同一份字节只留一份物理对象」的**删除侧**收口：17 个 `delete_object` 调用点 → 2 个闸门入口 |
| ② | 修复评审发现的 P1（回收器无生产入口）、P2（`simple_character` 漏判自身引用） |
| ③ | 补阶段 1 存量回填、实现 A2 素材库去重（前后端），让去重真正对用户可见 |
| ④ | 实现 **A3 人物授权文件 / A4 人物原始照片 / A5 简单人物**去重，属主取 `identity.owner_user_id`，并补跨用户红线测试 |

四轮均未改计费语义、未做物理迁移、未提升参考视频为全局 scope，与确认的六项决策一致。

## 一、已发现并修复的真实缺陷

`rbac_routes.delete_project` 的共享判定原写作 `project_id <> %s`。引用方
`project_id IS NULL` 时该表达式求值为 NULL 而非 TRUE，于是**素材库/人物资料这类
用户级资产被判为「无共享引用」**，其对象被删除而别的资产仍在引用。

- 修复前**不可达**（对象键按 asset_id 逐次唯一）；
- A2 接入后**立刻可达**（素材库正是 `project_id IS NULL` 的资产）。

已改为 NULL 安全的 `object_referenced_by_another_asset()`（`id NOT IN` 表达），
并配对照组测试 `test_legacy_null_comparison_would_have_missed_the_null_reference`
——直接证明旧写法会漏判。

## 二、删除闸门设计

两个入口，按「有没有连接」分流，取代全部 17 个直连调用点：

| 入口 | 适用 | 拒绝规则 | 失败姿态 |
| --- | --- | --- | --- |
| `delete_object_outside_content_namespace(storage, key)` | 无连接的孤儿清理（写失败、行还不存在） | 键位于 `content/` 命名空间即拒绝 | 泄漏 1 个对象，回收器兜底 |
| `delete_object_if_unreferenced(conn, storage, key, excluding_asset_ids=…)` | 有连接（行已删或即将删） | ① `content_objects` 有行 ② 存活 `assets` 仍指向同一 `storage_uri` | 拒绝删除并记 warning |

失败姿态是刻意选的：**拒绝是泄漏一个对象，放行错了是删掉别人的共享字节**，
后者不可回滚。因此闸门宁可少删。

`content_store.SqlConnection` 协议只声明 `execute(sql, params: Any)`——`params`
必须是 `Any` 而非 `Sequence[object]`，否则参数逆变会让 `BusinessConnection`
不满足该协议，而 `upload_cleanup` 的 CLI 用的是原生 psycopg 连接。

## 三、一处被测试拦下的回归

`upload_cleanup` 原判据是
`SELECT 1 FROM assets WHERE storage_uri = %s AND NOT (id = %s AND size_bytes = 0 AND sha256 = '')`，
即**只豁免本资产那条零字节 staging 行**。第一轮一度把它替换为
`excluding_asset_ids=[asset_id]`（豁免本资产的**所有**行），语义被放宽：

- 现象：`test_w18_pg_cleanup_expires_pending_and_preserves_completed` 报 `assert 6 == 5`，多删 1 个对象；
- 原因：存在一条**已就绪（completed）**资产的 `assets` 行引用同一对象，原判据据此保护，放宽后不再保护；
- 处理：保留原判据原文（注释写明为何不能委托给 `excluding_asset_ids`），仅把**删字节这一步**收敛到闸门。

**教训（应固化）**：等价替换前要先把原判据的豁免范围逐字拆开——
"排除本资产"与"排除本资产的 staging 行"是两回事。

## 四、回收器通电（第二轮）

第一轮的问题是 `reclaim_expired_content_objects` 只在测试里被调用——
"装了回收器但没通电"。第二轮补了两个入口：

| 入口 | 实现 | 频率 |
| --- | --- | --- |
| CLI | `upload_cleanup.reclaim_content_objects()`，`--reclaim-content [--reclaim-limit N]` | 手动 / 外部 cron |
| Worker | `generation_worker.reclaim_expired_content_objects_throttled()` | 每进程最多 1 小时一次（`CONTENT_RECLAIM_INTERVAL_SECONDS = 3600.0`）；异常只告警不阻塞 |

并加不变式断言：**AST 扫描确认存在生产调用点**，否则构建失败。
这样"运维接线"成为编译期约束，而不是靠人记得。

同时修复 `simple_character`：SELECT 补 `content_object_id` 列，并传入
`excluding_content_object_id`。原写法在 A5 接入后会让自己那条登记行把
`still_referenced` 顶成恒 True，导致对象永不删除。

### ⚠️ 运维陷阱：`--reclaim-content` 会直接删字节

CLI 帮助文字里的「默认只读预览」**只适用于上传清理扫描路径**，`--apply` 也只作用于该路径。
回收分支 `upload_cleanup.reclaim_content_objects()` 没有 `apply` 参数，
`--reclaim-content` 一调用就真删。

安全性**不来自预览，而来自两阶段回收本身**：`ref_count = 0` 且 24h 宽限期已过才入选，
sweeper 锁内重读计数后才动字节，`pinned=True` 永不入选。
首次执行建议用小批量观察（`--reclaim-limit`，1-1000，默认 100）。

## 五、存量回填（第三轮）

`content_objects` 对存量资产本来是空的 → **改造前上传过的老素材去重不命中**。
所以回填不是可选优化，而是 A2 生效的前提。

- `content_store.backfill_content_objects()` + `server/scripts/backfill_content_objects.py` CLI；
- 默认**只读预览**，写库需 `--apply`，`--limit` 控制批次；
- **幂等**：已回填的资产跳过，反复跑会收敛到查不到活干；
- **只建登记行 + 回写 `content_object_id`，不碰字节**（符合决策 5）；
- **历史已存在的重复对象不会被自动合并**，留到引用自然消失后被回收器带走。

## 六、A2 素材库去重（第三轮）

用户最初问题的核心入口。前后端都改了。

**后端** `server/app/materials.py`：

- `MaterialUploadIntentResponse` 新增 `upload_required: bool = True`（**默认 True，
  保证所有既有构造保持旧行为**）与 `reused_from_asset_id: str | None`；
- `_reuse_registered_material()`（`materials.py:709`）：按 (属主 + sha256 + size)
  在 **user 域**查登记表，命中则直接建成 READY 资产并返回 `upload_required=False`；
- `persist_material_upload()`（`:1060`）：上传完成后登记内容对象；并发重复时改指
  已有对象并清理孤儿。

**前端** `client/src`：

- `api.ts` 新增 `putMaterial()` 统一"免传 vs 传输 + complete"，免传时用
  `resolveMaterials([material_id])` 取回素材；
- `ContentPages.tsx` 两处上传调用（"我的上传"、发布封面）改用 `putMaterial()`；
- 同步更新 `generated/api.ts` schema 与 `ContentPages.test.tsx` mock 桩。

安全红线有测试固化：**跨用户同哈希必须不命中**。

## 六之二、A3/A4/A5 人物素材去重（第四轮）

### 收益边界：只省存储，省不掉传输

这三条**做不到 A2 的"免传"**，原因不是实现偷懒，而是完成路径必须读真实字节：

- **A3 授权文件** → `validate_authorization_content()`（PDF / 图片内容校验）；
- **A4 原始照片** → 源图审查（inspection）；
- **A5 简单人物** → 算 sha256 并落成 `character_source_image` 资产。

命中登记表也**不能跳过这些校验**，否则无法确认"这次传的确实是授权书 / 确实是一张合规人脸照"。
所以客户端**仍然要传一次**；收益是服务端**不再写第二份 verified 副本**，新资产直接指向已有对象。

### 改动

| 文件 | 改动 |
| --- | --- |
| `storage.py` | 抽出 `verified_upload_object_key()`。原因：`verified-uploads/{asset_id}/{digest}/{filename}` 嵌了 asset_id，asset_id 每次不同 → 必须**先算 key、再决定是否写**，顺序不能反；抽出也避免两处格式串漂移 |
| `character_identity.py` | 新增 `_identity_owner_user_id()`：属主 = `owner_user_id or created_by or actor.id`（资料归属人，而非操作者） |
| `character_identity.py` | 新增 `_retain_identity_content()`：A3 / A4 **共用**同一个"命中返回已有 uri / 未命中才写"助手，保证语义一致 |
| `character_identity.py` | 两个完成路径登记内容对象并写 `metadata["content_deduplicated"]`；A4 的**失败路径**也传 `content_object_id` 给 `persist_source_inspection_failure()`，否则审查失败的孤儿对象失去引用计数保护 |
| `character_identity.py` | `update_completed_asset()` / `persist_source_inspection_failure()` 的 `content_object_id` 是**可选**形参（有则 UPDATE 该列，无则走原 UPDATE），老调用方行为不变 |
| `simple_character.py` | `_store_source_asset()` 登记内容对象；命中则改指已有对象与 key，本次写下的字节成为孤儿，交给 `upload_cleanup` 走闸门回收，**不在提交前删**（宁可泄漏 1 个可回收对象） |

### 新增测试（`test_dedup_cas_pg.py`）

| 用例 | 断言 |
| --- | --- |
| `test_authorization_upload_reuses_bytes_within_one_owner` | 同属主两次传同一份授权书，`verified-uploads/` 下只应有 **1 个**对象键；第二次 `metadata["content_deduplicated"] = True` 且指向同一 `content_object_id` |
| `test_authorization_upload_never_reuses_another_owners_bytes` | 换用户传**完全相同**的字节必须**不命中**、各自独立占存储——**决策 3（严禁跨用户）的可执行证明** |

⚠️ 断言只数 **verified** 键：**pending 对象仍是 2 个**（客户端真传了两次），
去重只发生在 verified 落库处。最初把断言写成"对象总数 == 1"是错的，已修正。

### 顺带修正一处旧断言

`test_cw058_content_asset_pg_matrix.py` 原要求 `verified-uploads/{asset_id}/` 出现在 `storage_uri`。
人物源图与素材库内容相同时，去重会命中**素材库那份**已验证副本，uri 里的 asset_id 自然不是本次的。
该用例真正守的是**"源文件被覆盖（写入 `b"malicious replacement"`）后资产仍能读到正确字节"**（防篡改），
不是路径里必须有 asset_id → 放宽为 `/verified-uploads/`，**字节与 sha256 断言原样保留**。

### 本轮踩到的坑

1. 断言混淆 pending / verified → 见上。
2. 测试清理顺序触发 FK：`DELETE FROM users` 违反 `fk_person_identities_owner_user_id_users`，
   `_CLEANUP_ORDER` 补 `person_identities`。
3. `_identity_admin` 必须用 `role="admin"`（人物资料上传是管理员门禁），否则建不了 intent。

## 七、验证结果

静态与类型门禁（第四轮收工状态）：

| 门禁 | 结果 |
| --- | --- |
| `ruff check app tests/ scripts/` | All checks passed |
| `ruff format --check app tests/ scripts/` | 通过 |
| `mypy app` | Success: no issues found in 148 source files |
| `scripts/ci/migration_manifest.py --check` | migration guard OK |
| `--check-schema`（干净 head 库） | schema guard OK |

测试矩阵（PG 用例经本地 PG 5433 + Windows fcntl 垫片运行；垫片在仓库外、
不提交，仓库仍保持 POSIX-only）：

| 套件 | 结果 |
| --- | --- |
| `test_dedup_cas_pg.py` + `test_delete_object_gate.py`（第三轮收工） | **55 passed** |
| `test_dedup_cas_pg.py` + `test_delete_object_gate.py`（**第四轮收工**） | **57 passed**（新增 A3 同属主复用 / 跨用户不命中 2 例） |
| 上述 + `test_cw058` + `chain_e2e` + `fencing` + `character_image_authorization` + `async_compat` | **139 passed**（第四轮；含放宽后的 cw058 防篡改用例） |
| 上述 + `test_cw058` + `test_cw059` + `test_cw030` | **175 passed** |
| `test_storage.py` + `test_oral_domain.py` | 130 passed |
| `test_cw030_worker_pg_matrix.py` + `test_cw043_viral_import_pg.py` | 66 passed，6 失败（见下） |
| `test_cw056_supported_head_matrix.py` + `test_postgres_migrations.py` | 36 passed |
| `test_cw057_cli_pg_entry` / `customer_ha_smoke` / `customer_fencing` / `async_compat` / `character_image_authorization` / `business_preflight` | 156 passed |
| `bootstrap_all_env_pg_gate` / `db_pg` / `customer_chain_e2e` / `security_contracts` / `cw028_shared_settings_contract` | 182 passed, 1 skipped |

### 7.1 rebase 到 PR #120 之后的 main（重挂父级）复测

| 门禁 / 套件 | 结果 |
| --- | --- |
| `ruff check` / `ruff format --check` / `mypy app` | All checks passed · 253 files formatted · 148 files 无问题 |
| `migration_manifest.py --check` | migration guard OK |
| `--check-schema`（新建干净库 `dedup_head_probe`，空库→head） | schema guard OK |
| 冻结字面量重测 | counts `tables=94 / columns=1099 / timestamptz=44`，digest `a3fb4c3f…`，表名集 94 项 |
| 迁移链 `test_cw056` + `test_postgres_migrations` | **37 passed** |
| 去重核心 `test_dedup_cas_pg` + `test_delete_object_gate` | **57 passed**（+ P5 两条后闸门套件 32 passed） |
| 回归集 cw058 / chain_e2e / fencing / character_image_authorization / async_compat / oral_domain / worker_concurrency / cw030 | **288 passed** |
| 前端 `npm run check`（node 24） | **100 测试文件 / 1528 用例全绿** |

`test_cw043_viral_import_pg.py` 的 6 项失败是
`test_cached_local_media_moves_to_cos_without_provider_call_or_losing_source`
的 6 个参数化实例，**已在未修改的 main 上复现同样的 6 项失败**，判定为既有问题。

不变式（`test_delete_object_gate.py`，构建即失败）：

1. 除 `storage.py`（实现）与 `content_store.py`（闸门）外，`app/` 下任何模块
   出现 `delete_object` / `_delete_object` 调用即失败（AST 扫描，注释与字符串不干扰）；
2. 16 个历史清理路径必须仍然经对应闸门清理，防止「顺手删掉清理逻辑」式通过；
3. `content/` 命名空间下的键必须被拒，私有键必须放行，且判定是前缀而非子串；
4. `reclaim_expired_content_objects` 必须有生产调用点。

## 八、未完成与风险

- 全部改动**未提交、未推送**，工作树 `DEDUP-CAS-20260916` 处于未提交状态。
- **A3/A4/A5 命中去重时仍会落一份 pending 对象**（客户端必须真传一次，见 §六之二），
  命中后那份字节成为孤儿，依赖 `upload_cleanup` 回收。上线后需观察回收器确实带走它们，
  否则"省存储"的收益会被 pending 副本吃掉。
- [x] ~~**双 head 冲突**~~ **已解决**：`VIRAL-COPY-CACHE-20260915` 的
  `20260915T1600_viral_copy_cache` 已随 PR #120 合入 main（该分支实现 ASR/文稿复用
  `viral_script_cache`，本轮未重复实现）。本分支已 rebase 到该 main，迁移父级
  **重挂**为 `20260915T1600_viral_copy_cache`；`manifest.json` 用 `--record` 重录，
  `test_cw056_supported_head_matrix.py` 的冻结字面量在**新建的干净库**
  （`dedup_head_probe`，空库 → head）上重测：`--check` 与 `--check-schema` 均 OK，
  迁移链测试 **37 passed**。
- [x] ~~**前端未经编译验证**~~ **已验证**：装好 `client/node_modules`（148 包，node ≥ 24）后
  `npm run check` 全绿——`biome check` + `tsc -b` + `vitest run`：100 测试文件 / 1528 用例通过。
- **β 计费语义未实现**（决策 1）：计费行为是测试固化的规格，需与 L3 单独评审。
- **C1/C2 暂缓**：需在生成前按 `(source_sha256, fingerprint)` 拦截才真正省算力，
  涉及 AI 生成与计费，建议单独开任务。
- **`--check-schema` 必须用干净库**：在 `customer_v3_test` 上跑会因其它测试残留的
  scratch 表（`t055_*` / `t05_*`）误报 drift。
