# 代码评审：资产去重 / 内容寻址（DEDUP-CAS-20260916）

- 日期：2026-09-16（**第三轮后更新**：A3/A4/A5 人物素材去重已实现并补测）
- 评审范围：worktree `DEDUP-CAS-20260916`（分支 `dedup-cas-20260916`，未提交）
- 对照基准：`docs/design/资产去重与内容寻址方案-20260916.md`
  （设计文档已同步进本 worktree 的 `docs/design/`，初稿原在主仓库且未跟踪）
- **结论（第三轮后）**：初版评审发现的 5 个问题中，**P1 / P2 / P3 已修复**；
  **A2、A3、A4、A5 均已实现**，B2 已取消 copy；
  剩余 P4（β 计费语义）、P5（生命周期约定）与 C1/C2 属**有意暂缓**。
  **核心防事故能力（阶段 2 闸门 + 回收器通电）已具备，可进入合入评审。**

---

## 〇、两轮结论对照

| 项 | 第一轮结论 | 复审状态 |
|---|---|---|
| 阶段 0 建表加列 | ✅ 完成 | ✅ 完成 |
| 阶段 1 存量回填 | ❌ 未做 | ✅ **已补齐**（函数 + CLI + 测试） |
| 阶段 2 删除闸门收敛 17→2 | ✅ 完成 | ✅ 完成 |
| **回收器生产入口** | ❌ **P1：无任何入口** | ✅ **已通电**（CLI + worker 节流） |
| `simple_character` 排除自身 | ❌ **P2：未来 bug** | ✅ **已修**（补列 + 传参 + 回归测试） |
| A2 素材库去重 | ❌ 未做 | ✅ **已实现**（后端 + 前端 + 类型 + 测试） |
| B2 爆款导入取消 copy | ✅ 完成 | ✅ 完成 |
| C1/C2 首帧 / 源帧去重 | ❌ 未做 | ⏸ **有意暂缓**（需在生成前拦截，涉及计费） |
| A3/A4/A5 人物素材去重 | ❌ 未做 | ✅ **已实现**（属主内去重，只省存储；见 §3.5） |
| β 计费语义（决策 1） | ❌ 全仓 0 处 | ⏸ **有意暂缓**（计费是测试固化的规格） |
| 阶段 4 懒迁移 | ❌ 未做 | ❌ 未做 |

---

## 一、需求对照：做了什么，没做什么

| 设计阶段 / 决策 | 内容 | 状态 |
|---|---|---|
| 阶段 0 | 建 `content_objects`、加 `assets.content_object_id`、加索引 | ✅ 完成 |
| 阶段 1 | **存量回填** | ✅ **完成**（见 §2.3） |
| 阶段 2 | **删除闸门收敛 17→2** + 修 `project_id IS NULL` 缺陷 | ✅ 完成 |
| 阶段 3-A2 | 素材库上传去重 | ✅ **完成**（见 §2.4） |
| 阶段 3-B2 | 爆款导入取消 `copy_object` | ✅ 完成 |
| 阶段 3-C1/C2 | 首帧 / 源帧去重 | ⏸ 暂缓（见 §2.5） |
| 阶段 3-A3/A4/A5 | 人物素材去重 | ✅ **完成**（见 §3.5） |
| 阶段 4 | 懒迁移 | ❌ 未做 |
| L3 | 拆解 / ASR 结果复用 | ⏸ 暂缓；ASR 侧由未合并分支 `VIRAL-COPY-CACHE-20260915` 承担 |
| 决策 1 | **β 计费语义** | ⏸ **暂缓**，全仓仍 0 处 `reused_from` / `content.reused` |
| 决策 2 | 参考视频不升 global | ✅ 符合（维持 user 域，未动 A1） |
| 决策 3 | 人物素材严禁跨用户 | ✅ **表结构 + 链路均已保障**：`scope_owner` + 两条 partial unique index；A3/A4/A5 属主取 `identity.owner_user_id`，**并有跨用户红线测试**（换用户传同字节必须不命中） |
| 决策 4 | 回收延迟 24h | ✅ `RECLAIM_DELAY_HOURS=24`，有测试锁定默认值 |
| 决策 5 | 不物理搬迁存量 | ✅ 无任何搬迁 |
| 决策 6 | 闸门 PR 单独且最先合入 | ✅ 本轮即闸门 PR |

### 1.1 用户最初问题的答案（分入口，务必区分）

| 入口 | 去重现状 | 说明 |
|---|---|---|
| **A1 项目内参考视频上传**<br>`POST /api/assets/upload-intent` | ✅ **本来就有** | `media.py:265 reuse_owned_completed_upload`：同项目复用同一 `asset_id`；跨项目新建 asset 行指向同一 URI；返回 `upload_required=False` 前端免传；审计 `asset.upload_deduplicated`。**属存量功能，本轮未接入 `content_objects`** |
| **A2 素材库上传**<br>`POST /api/studio/materials/upload-intent` | ✅ **已实现（免传）** | 按（属主 + sha256 + size）在 user 域查登记表，命中即 `upload_required=False` **浏览器不用传**；上传完成后登记内容对象 |
| **A3 人物授权文件**<br>`person-identities/{id}/authorization-upload-intent` | ✅ **已实现（省存储，仍需传）** | 完成路径必须读真实字节做 `validate_authorization_content()`，命中也**不能跳过校验** → 客户端仍传一次，但服务端**不再写第二份 verified 副本**，新资产直接指向已有对象 |
| **A4 人物原始照片**<br>`person-identities/{id}/source-upload-intent` | ✅ **已实现（省存储，仍需传）** | 同 A3；额外把 `content_object_id` 传进 `persist_source_inspection_failure()`，避免审查失败的孤儿对象失去引用计数保护 |
| **A5 简单人物（免训练）上传**<br>`/api/simple-characters/upload-intent` | ✅ **已实现（省存储，仍需传）** | 命中后本次写下的字节成为孤儿，交给 `upload_cleanup` 走闸门回收，**刻意不在提交前删** |

> **这是最容易混淆的一点**：用户最初问"上传能不能去重"，在 A1 上本来就有答案，
> 但 A1 与 A2 是两条独立链路。本轮补的是 A2。
>
> ⚠️ **A3/A4/A5 与 A1/A2 的收益不同，别混为一谈**：A1/A2 是**免传**（省带宽 + 体感秒传），
> A3/A4/A5 只是**不写第二份 verified 副本**（只省存储）。原因见 §3.5。

---

## 二、发现的问题与处理（按严重度）

### ✅ P1｜回收器没有任何生产入口 —— **已修复**

> **原问题**：`reclaim_expired_content_objects` 全仓只在测试里被调用：没有 worker、
> 没有定时任务，`upload_cleanup.py` 的 CLI 也没有挂载。当时影响为 0（唯一写入方
> `viral_import` 用 `pinned=True`），但一旦 A2 接入非 pinned 对象，字节只增不减。

**修复**：补了两个入口，并加了不变式测试防止再次"装了不通电"。

| 入口 | 实现 | 说明 |
|---|---|---|
| CLI | `upload_cleanup.reclaim_content_objects()`，`--reclaim-content` / `--reclaim-limit` | 手动或外部 cron |
| Worker | `generation_worker.reclaim_expired_content_objects_throttled()` | `CONTENT_RECLAIM_INTERVAL_SECONDS = 3600.0`，每进程最多 1 小时一次；异常只告警不阻塞任务 |

`test_delete_object_gate.py` 新增断言：**AST 扫描确认存在生产调用点**，
否则构建失败——这是把"运维接线"变成编译期约束，而不是靠人记得。

### ✅ P2｜`simple_character` 的登记行检查没有排除自己 —— **已修复**

> **原问题**：`SELECT id, storage_uri FROM assets ...` 未取 `content_object_id`，
> 且 `object_referenced_by_content_registry()` 未传 `excluding_content_object_id`。
> A5 接入后删身份会让自己那条登记行把 `still_referenced` 顶成恒 True → 对象永不删除。

**修复**：SELECT 补 `content_object_id` 列，调用处传入 `excluding_content_object_id`，
并在 `test_dedup_cas_pg.py` 加了回归测试（断言"排除自身之后不应再算作引用"）。

### ✅ P3｜无存量回填（阶段 1 债务）—— **已补齐**

> **原问题**：`content_objects` 对存量资产全空，A2 对老素材不生效。

**修复**：`content_store.backfill_content_objects()` +
`server/scripts/backfill_content_objects.py` CLI。

- 默认**只读预览**，写库需显式 `--apply`；`--limit` 控制批次。
- **幂等**：已回填的资产跳过，反复跑会收敛到查不到活干。
- **只建登记行 + 回写 `content_object_id`，不碰字节**（符合决策 5）。
- 注意：**历史已存在的重复对象不会被自动合并**，它们留到引用自然消失后被回收器带走。

### ⏸ P4｜β 计费语义未实现 —— **有意暂缓**

设计决策 1 要求复用时落审计 `action="content.reused"` 和计费凭据 `reused_from`。
目前**全仓仍 0 处**。

**暂缓理由（不是遗漏，是纪律）**：本项目计费行为是**测试固化的规格**——
"看着像 bug 就改"会破坏已固化的对账口径。动 `billing_operations` 前必须先 grep
出描述该行为的用例。建议与 L3 一起单独评审。

### ⏸ P5｜一处"看起来更安全，其实没有"的改动 —— 无回归，约定待固化

```python
# viral_media_preparation.py:313
content_store.delete_object_outside_content_namespace(self.storage, lease.key)
```

`lease.key` 是 `viral/prepared/{scope}/{identity}/{attempt}.{ext}`，**不是 `content/` 前缀**
→ 闸门放行，行为与改动前**完全一致**（无回归，也没有获得新保护）。

新增的跨模块依赖：B2 取消 copy 后，项目资产直接指向这个缓存 key。
风险低（只删当前 attempt，attempt 不同则 key 不同），但**建议后续补测试固化这个生命周期约定**。

---

## 三、第二轮新增实现（复审范围）

### 3.1 A2 素材库去重（用户最初问题的核心入口）

**后端** `server/app/materials.py`：

- `MaterialUploadIntentResponse` 新增 `upload_required: bool = True`（**默认 True，
  保证所有既有构造保持旧行为**）与 `reused_from_asset_id: str | None`。
- `_reuse_registered_material()`（`materials.py:709`）：按 (属主 + sha256 + size)
  在 user 域查登记表，命中则直接建成 READY 资产并返回 `upload_required=False`。
- `persist_material_upload()`（`:1060`）：上传完成后登记内容对象；并发重复时改指
  已有对象并清理孤儿。

**前端** `client/src`：

- `api.ts` 新增 `putMaterial()` 统一"免传 vs 传输 + complete"；免传时用
  `resolveMaterials([material_id])` 取回素材。
- `ContentPages.tsx` 两处上传调用（"我的上传"、发布封面）改用 `putMaterial()`。
- 同步更新 `generated/api.ts` schema 与 `ContentPages.test.tsx` mock 桩。

> ⚠️ **前端未经编译验证**：本工作区 `client/node_modules` 不存在（无 typescript），
> 跑不了 `tsc -b` / `vitest` / `biome check`。**合入前必须在能装依赖的环境补跑 `npm run check`。**

### 3.2 回收器通电

见 §2 P1。

### 3.3 `simple_character` 排除自身

见 §2 P2。

### 3.4 存量回填

见 §2 P3。

### 3.5 A3/A4/A5 人物素材去重（第三轮新增）

**先把收益边界讲清楚**：这三条做不到 A2 的"免传"。

完成路径必须读到真实字节——A3 要 `validate_authorization_content()`，A4 要过源图审查，
A5 要算 sha256 并落成 `character_source_image`。命中登记表也**不能跳过这些校验**，
否则无法确认"这次传的确实是授权书 / 确实是一张合规的人脸照"。
所以**客户端仍然要传一次**；收益是服务端**不再写第二份 verified 副本**（省存储，不省带宽）。

**改动清单**：

| 文件 | 改动 |
|---|---|
| `storage.py` | 抽出 `verified_upload_object_key()`，让去重能在**写之前**算出同一个 key（key 嵌了 asset_id，每次不同，**顺序不能反**），也避免两处格式串漂移 |
| `character_identity.py` | 新增 `_identity_owner_user_id()`（属主 = `owner_user_id or created_by or actor.id`）；新增 `_retain_identity_content()` 供 A3/A4 **共用**，保证"命中返回已有 uri / 未命中才写"语义一致 |
| `character_identity.py` | 两个完成路径登记内容对象并写 `metadata["content_deduplicated"]`；A4 的**失败路径**也传 `content_object_id`，否则审查失败的孤儿对象失去引用计数保护 |
| `character_identity.py` | `update_completed_asset()` / `persist_source_inspection_failure()` 的 `content_object_id` 做成**可选**形参（有则 UPDATE 该列，无则走原 UPDATE），老调用方行为不变 |
| `simple_character.py` | `_store_source_asset()` 登记内容对象；命中则改指已有对象与 key，本次写下的字节成为孤儿，**交给 `upload_cleanup` 走闸门回收，不在提交前删** |

**测试**（`test_dedup_cas_pg.py`）：

- `test_authorization_upload_reuses_bytes_within_one_owner`——同属主两次传同一份授权书，
  `verified-uploads/` 下应只有 **1 个**对象键；第二次 `metadata["content_deduplicated"] = True`
  且指向同一 `content_object_id`。
  ⚠️ **只数 verified 键**：pending 对象仍是 2 个（客户端真传了两次），去重只发生在 verified 落库处。
- `test_authorization_upload_never_reuses_another_owners_bytes`——换一个用户传**完全相同**的字节，
  必须**不命中**、各自独立占存储。这是**决策 3（严禁跨用户）的可执行证明**，不是可选项。

**顺带修正一处旧断言**：`test_cw058_content_asset_pg_matrix.py` 原要求
`verified-uploads/{asset_id}/` 出现在 `storage_uri` 里。人物源图与素材库内容相同时，
去重会命中**素材库那份**已验证副本，uri 里的 asset_id 自然不再是本次的。
该用例真正守的是"源文件被覆盖后资产仍能读到正确字节"（防篡改），不是路径里必须有 asset_id，
故放宽为 `/verified-uploads/`，**字节与 sha256 断言原样保留**。

**本轮踩到的两个坑（值得记住）**：

1. 一开始断言"对象总数 == 1"是错的——pending 对象必然有 2 个。断言必须区分 pending / verified。
2. 测试清理顺序触发 FK 冲突（`DELETE FROM users` 违反 `fk_person_identities_owner_user_id_users`），
   `_CLEANUP_ORDER` 需补 `person_identities`。

---

## 四、已验证排除的风险（避免误报）

| 疑点 | 结论 |
|---|---|
| COS `head_object` 能否返回 sha256？<br>（若不能，B2 的校验会让导入 100% 失败） | ✅ **安全**。sha256 来自 `x-cos-meta-sha256` 自定义头；viral cache 对象由 `put_file`（`storage.py:685`）与 `put_object`（`:730`）写入，**均带该头** |
| `head_object(source.key)` 会不会双重加前缀？ | ✅ **不会**。`_object_key`（`storage.py:357-361`）**幂等**：已带前缀则原样返回；且 `key_prefix` 默认为空 |
| 原 `copy_object` 与新 `head_object` 的校验强度是否一致？ | ✅ 一致。原 `copy_object` 最终也是 `head_object(destination)` 返回，同样依赖该头 |

---

## 五、做得好的地方

1. **闸门的失败姿态正确**：拒绝 = 泄漏一个对象（sweeper 兜底）；放行错 = 删掉他人共享字节且不可回滚。宁可少删。
2. **NULL 缺陷修得干净**：改用 `id NOT IN` 排除自身，并配对照组测试
   `test_legacy_null_comparison_would_have_missed_the_null_reference`——直接证明旧写法会漏判。
3. **两阶段回收防竞态到位**：`FOR UPDATE SKIP LOCKED` + 锁内重读 `ref_count`。
4. **事务边界正确**：`release_assets_content_objects` 与 DELETE 同一事务，storage I/O 移到 commit 之后。
5. **不变式测试有防御性**：AST 扫描 + 要求 16 个历史清理路径**仍经闸门**，防止后人删掉清理逻辑骗过门禁。
6. **回填默认预览、幂等、不搬迁字节**——符合"先看清再动手"的运维纪律。
7. **A2 的 `upload_required` 默认 True**：新增字段不破坏任何既有构造，是低风险扩展方式。

---

## 六、合入前清单（复审后）

- [x] 补回收器调度入口（P1）→ **已完成**
- [x] 修 `simple_character` 的 `excluding_content_object_id`（P2）→ **已完成**
- [x] 存量回填（P3）→ **已完成**
- [x] A2 素材库去重 → **已完成**
- [x] A3/A4/A5 人物素材去重 → **已完成**（见 §3.5）
- [ ] **前端补跑 `npm run check`**（本工作区无法编译验证）
- [ ] 观察 A3/A4/A5 命中时的 **pending 孤儿**是否被 `upload_cleanup` 正常回收
      （客户端必须真传一次，命中后那份字节靠回收器带走；否则"省存储"收益被 pending 副本吃掉）
- [ ] 处理双 head：`20260916T1400_content_objects` 与 `VIRAL-COPY-CACHE-20260915` 的
      `20260915T1600_viral_copy_cache` 同父，合并需重定父级
- [ ] β 计费语义（决策 1）与 L3 一起单独评审
- [ ] C1/C2 若要做，需先定"复用帧是否计费"
- [ ] 建议补测试固化 B2 的缓存对象生命周期约定（P5）
- [ ] 全部改动**提交并推送**（当前仍在 worktree 未提交）
