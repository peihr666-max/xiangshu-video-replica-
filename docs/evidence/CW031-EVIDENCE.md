# CW-031 — 核销云端资产与授权下载的剩余回退

> 目标证据层级：`AUTOMATED_VERIFIED`。本文件登记 CW-031 的正式服务存储闸门定稿
> 口径、历史 local URI 处置、启动期写路径探测、跨实例/授权/故障专项测试、缺 PG
> 硬门复验与资产权限矩阵。真实 COS 凭据链归 CW-050，生产实际执行归 CW-051，均需
> 人工授权，不在本任务范围（见 §12）。

## 1. 任务信息（§14 模板）

| 字段 | 值 |
| --- | --- |
| 任务/工作包 | CW-031（W4）核销云端资产与授权下载的剩余回退；DoD：关闭全部正式服务本地持久存储回退、历史 local URI 只作迁移期可追溯输入禁止新写、跨实例测试（API A 上传 / API B 或 Worker 读取、跨用户/撤销 session、签名过期重获、COS 故障不落本地）、新持久资产 `provider=cos` 100%、local 新写 = 0、未因 local 函数名删除云端签名能力 |
| Owner / Reviewer | Owner：ZCode 代理（2026-09-11，经用户授权交接既有在制工作）；Reviewer：待 PR 独立 CodeReview |
| 分支 / 基线 SHA | `feat/customer-v3-cw031-cloud-asset-no-local-fallback`；基线 `origin/main@e829ad1`（CW-054 #14、CW-055 #13 合并后）。接手时工作树存在前一会话未提交的偏离定稿实现（单闸门 `is_customer_production` + 自造错误码 `STORAGE_PROVIDER_SETTINGS_REQUIRED` + 越界修改 `pg_test_kit.py` + 专用测试库），按交接提示词定稿口径重做：撤销 `pg_test_kit.py` 越界改动、按 §5.2 定稿重写双闸门、删除未提交的旧测试文件并以定稿命名的新测试文件承载 |
| 上游规格段落 | 收敛详细任务清单 §CW-031（`outputs/.../v3/客户版收敛剩余任务清单与验收完工标准-V3.md` line 528–541）；V3 清单 §18 CW-031 行；`docs/开发交接提示词-CW031-存储与下载回退-2026-09-10.md`（6616982，实施决策定稿）；`docs/evidence/VIDEO-DIRECT-DELIVERY-DOWNLOAD-EVIDENCE.md`（成片 DIRECT 合同，只验不破坏）；CW-007 TEST-PG 硬门 |
| 改动文件 | 3 个 app 文件 + 1 个新测试文件 + 本证据文件：`server/app/media_routes.py`（§5.2 重写 `get_media_storage` 双闸门 + §5.3 `storage_for_asset` 客户生产拒绝 + 模块 logger）、`server/app/bootstrap.py`（§5.8 `_probe_formal_service_write_path` 启动期写路径探测 + 两处注释）、`server/app/rbac_routes.py`（§5.4 缓存目录不变量注释，逻辑零改动）、`server/tests/test_storage_cross_instance.py`（新增 27 用例）。**`pg_test_kit.py` / `storage.py` / `media.py` / `db_pg.py` / `migrations/**` / `gate1_*` / `settings_routes.py` 零改动**（git diff 面核对） |
| 失败测试或回归锁定 | 测试先行（红→绿）：定稿用例 6/7（正式服务未配 COS / 客户生产 + provider=local）在闸门前跑红（当前实现静默返回 LocalStorageAdapter），实现 §5.2 后转绿；用例 9（历史 local URI 客户生产拒绝）在 §5.3 前红后绿；其余用例如实记录——跨实例可读（COS 适配器无状态）、缓存恢复（`rbac_routes` 已强制 COS）、签名矩阵（`local_download_signature` 能力已存在）大多直接绿，按规格「复用现有」登记，不伪造红灯 |
| 实现结果 | §2 闸门定稿口径与分支表；§3 历史 URI 处置；§4 启动期探测；§5 跨实例口径；§6 资产权限矩阵 |
| 验证命令与通过数 | 见 §10。专项 27 passed / 0 failed / 0 skip；四个签名护栏 4 passed；既有存储/媒体/人物/链路回归 265 passed / 1 skipped / 8 failed（8 项全部为 `test_simple_character` 图像用例依赖 ffmpeg 的既有环境缺陷，基线对照实验证实与本任务零关系）；缺 PG 硬门 3 passed / 24 errors / 0 skipped rc=1；ruff check / format / mypy --strict（104 files）全过 |
| 证据层级 | **AUTOMATED_VERIFIED**（真实 PostgreSQL 16 + 共享内存 COS 替身；未过真实 COS 链路，不声明 `PRODUCTION_GO`） |
| 安全与可观测性 | 无真实 API key/激活码/设备或 session token 进入代码、日志、测试夹具或 PR（测试凭据全部 `secrets.token_urlsafe` 每次 rand）。新增日志只记 `provider` 值与 `type(exc).__name__` 级脱敏，不打印 bucket/ak/sk/完整 `storage_uri`；`bootstrap` 探测复用既有 `except Exception` 分支的既有脱敏日志 |
| 迁移与回滚 | 零迁移文件改动；改动为纯增量请求期/启动期围栏 + 测试。回滚 = revert 本分支 |
| 外部授权记录 | 无（不涉及真实 COS 变更 / 付费 Provider / 对外发码 / 生产发布） |
| 未测试项 | `cargo test`、`npm audit`、客户浏览器 E2E、`npm run build`、前端 biome/vitest —— 只在 CI 门禁执行；本任务前端与 Rust 侧零触碰。真实 COS bucket 联调与真实签名 URL 端到端归 CW-050 |
| Lore 提交 SHA | 本 PR squash 后回填 |

## 2. 正式服务闸门（`get_media_storage` 定稿口径）

规格未定义「正式服务」。本任务按交接提示词定稿：**以 `runtime_settings.active_storage_provider`（业务真源，多实例共享）为主闸门、`is_customer_production()`（进程环境变量）为兜底闸门**，不引入新环境变量。依据：多实例口径一致性、`rbac_routes._customer_character_cache_storage` 与 `bootstrap` 启动期 readiness 的既有同口径（复用现有）、管理端可改 provider 必须读运行时设置。

| provider（runtime_settings） | is_customer_production | COS 配置 | 结果 | 本任务前行为 |
| --- | --- | --- | --- | --- |
| `cos` | 任意 | 已配置 | `CloudStorageAdapter`（不变） | 同左 |
| `cos` | 任意 | **缺失/损坏/不完整** | **503 `STORAGE_PROVIDER_FORBIDDEN` / `STORAGE_SETTINGS_UNAVAILABLE`** | **静默回退 LocalStorageAdapter（缺口）** |
| `local` | false | — | `LocalStorageAdapter`（内部 P0 单机车道，保留） | 同左 |
| `local` | **true** | 已配置 | 走 COS 分支（兜底闸门） | LocalStorageAdapter（缺口） |
| `local` | **true** | 缺失 | **503 `STORAGE_PROVIDER_FORBIDDEN`，local 新写 = 0** | LocalStorageAdapter（缺口） |
| 其它非法值 | false | — | 503 `STORAGE_PROVIDER_UNAVAILABLE` | 静默回退（缺口） |

新增错误码 `STORAGE_PROVIDER_FORBIDDEN`(503)：正式服务要求 COS 但 COS 未配置。与既有 `STORAGE_SETTINGS_UNAVAILABLE`(503，设置读不出/不完整)、`STORAGE_PROVIDER_UNAVAILABLE`(503，provider 值非法)、`STORAGE_BUCKET_MISMATCH`(409) 语义不重叠。

新写禁止不需要额外代码：`media.py` 落库 `storage_uri = f"{storage.provider}://{...}"` 完全由注入适配器决定，闸门关闭 local 回退后正式服务新写必为 `cos://`（用例 D 断言落库 100% `cos://` 前缀）。

## 3. 历史 local URI（`storage_for_asset` 只读追溯）

- 非客户生产：保留只读解析（`LocalStorageAdapter(root=..., bucket=reference.bucket)`），新增 warning 日志含 CW-037 追溯标记，只记 `reference.provider` 不记 URI 全文。
- 客户生产：**503 `STORAGE_PROVIDER_FORBIDDEN`**——正式服务不该有本地持久资产，有则显式失败而非静默服务。
- 搬迁（读 local → 写 COS → 改 URI）归 **CW-037**；`storage_object_ref_from_uri` 的 local 解析能力与 `LocalStorageAdapter` 本体零改动。

## 4. 启动期写路径探测（`bootstrap.py`）

`check_customer_production_runtime_dependencies()` 原本只做 bucket 级 HEAD（证明可读）。本任务在其后追加 `_probe_formal_service_write_path(storage)`：以 `.cw031-readiness/<uuid>` 为 key put 1 字节对象并立即 delete（key 前缀避开 `projects/`、`generation-results/` 业务命名空间；审计事件停留在一次性 adapter 实例、不被消费）。任何异常沿既有 `except Exception` 分支 fail-closed 启动（只记 `type(exc).__name__`）。探测加在 `with pg_transaction()` 块**之外**，保持 CW-025 的「先释放 PG 连接再发外部网络调用」顺序。`StorageAdapter` Protocol 提供 `put_object`/`delete_object`，无需降级为仅 upload-intent 探测。内部车道（非客户生产）`return None` 上方补注释说明该口径。

## 5. 跨实例测试口径（规格验收的落地披露)

「两个独立 API 进程语义/连接和一个 Worker」落地为：**三个互相独立的 PG 连接（三次 `psycopg.connect`，不复用连接对象）+ 三个独立 `StorageAdapter` 实例 + 共享同一个 COS 后端**（共享内存 fake client 承载「同一 COS 对象」语义），分别扮演 API A / API B / Worker（Worker 走 `generation_worker.get_media_storage` 的真实 import 路径）。真实多进程/多主机归 CW-050（真实凭据链）与 CW-051（生产执行），需人工授权。

`server/tests/test_storage_cross_instance.py`（新增，27 用例，全部直接调用闸门本体、不 override `get_media_storage`）：

- **A 组闸门本体（7）**：provider=cos 缺配置 fail-closed（含 `create_local_storage_from_environment` monkeypatch 计数 = 0）、客户生产 + provider=local 兜底、桌面车道回归锁、已配 COS 零行为变化、损坏/不完整配置响亮 503、非法 provider 值 503。
- **B 组历史 URI（2）**：非客户生产只读 + CW-037 标记；客户生产 503 拒绝。
- **C 组路由面（5）**：真实客户 lane（激活→登录→upload-intent）503 围栏、dev 身份 401 先于存储、local-objects PUT/GET 围栏、COS 已配置时既有 404 不变、桌面车道不围栏。
- **D 组跨实例（1）**：API A（独立连接+adapter）落库 `cos://` 100% → API B（第二条连接）闸门解析同一 bucket → Worker（第三条连接、`generation_worker` 入口）读同一对象；内容逐字节相等。
- **E 组故障（3）**：COS put / get / sign 故障各自映射明确 `StorageBackendUnavailable` 错误，本地持久文件新增差集 = 空集；签名故障恢复后签名能力仍在。
- **F 组授权矩阵（6）**：owner 有效签名通过；篡改签名 403；过期签名 403；跨用户签名 403（签名绑定 user_id）；过期后重新签发得到不同且可用的新签名（重获路径）；`require_asset_access` 拒绝非 owner 普通用户。`SourceUrlExpired` 语义保留断言。
- **G 组缓存恢复（1）**：删除本地缓存目录后人物图缓存路径立即从 COS 恢复（证明可重建缓存不是跨进程持久真源）。
- **H 组启动探测（2）**：探测写后即删、key 全部在 `.cw031-readiness/` 保留前缀下；写路径故障向上传播 fail-closed。

PG 使用（定稿 §5.6，因 `pg_test_kit.py` 归 CW-056 禁改）：**不新建任何 PG 测试库**，只用共享库 `customer_v3_test`——模块级持有 `shared_suite_lock()`、数据全部 `cw031-` 前缀、绝不 TRUNCATE 共享业务表、模块收尾恢复 `runtime_settings` / `provider_settings` 进入前快照；module fixture teardown 调 `close_pg_pool()`。

## 6. 资产权限矩阵（规格必交证据）

| 角色 / 主体 | 资产 owner | session 状态 | 签名状态 | 期望 | 实测 |
| --- | --- | --- | --- | --- | --- |
| owner（admin lane，epoch=0） | 本人 | 未涉 | 有效未过期 | 通过并返回资产 | ✅（F 组） |
| 同资产另一 admin（user_id 不同） | 他人 | — | 为其签发的「有效」签名 | 签名含 user_id 绑定 → 403 `LOCAL_DOWNLOAD_FORBIDDEN` | ✅ |
| 签名被篡改 | — | — | 错误 sig | 403 `LOCAL_DOWNLOAD_FORBIDDEN` | ✅ |
| 签名过期 | 本人 | — | expires < now | 403 `LOCAL_DOWNLOAD_FORBIDDEN` | ✅ |
| 过期后重获 | 本人 | — | 重新签发（新 expires） | 新签名 ≠ 旧签名且可用；云端 download intent 同样可重签 | ✅ |
| 非 owner 普通用户（customer） | 他人 | — | — | `require_asset_access` 拒绝 | ✅ |
| 正式服务存储选择（任意角色） | — | 真实客户 session | — | 无 COS → 503 `STORAGE_PROVIDER_FORBIDDEN`，零资产行、零本地文件 | ✅（C 组） |
| dev 身份打客户 lane | — | 无 session | — | 401 `SESSION_TOKEN_REQUIRED`（先于存储） | ✅ |

## 7. 完工标准量化证据

| 标准 | 证据 |
| --- | --- |
| 新持久资产 `provider=cos` 比例 100% | D 组用例断言 `assets.storage_uri` 全部 `cos://` 前缀（`_asset_count` == (1,1)） |
| local 新写 = 0 | A/C/E 组 `_persistent_file_snapshot` before/after 差集 = 空集（排除 `.cache` 可重建缓存段） |
| 授权、撤销、过期、跨节点、故障专项 0 fail | 专项 `pytest tests/test_storage_cross_instance.py -q` = **27 passed / 0 failed / 0 skip**；签名撤销语义由 session_epoch 绑定签名 + 既有 `validate_signed_asset_grant` 撤销校验承载（复用现有，未改算法） |
| 所有仍引用 local 的持久数据可追溯 CW-037 | `storage_for_asset` local 分支唯一命中场景 + warning 标记；实际搬迁义务在 CW-031-EVIDENCE 与账本行登记 |
| 未因 local 函数名删除云端签名能力 | `local_download_signature` 零改动（git diff 面无 `storage.py`）；四护栏用例全绿（`test_cloud_adapter_signs_and_operates_on_one_private_object`、`test_download_intent_requires_business_permission`、`test_delete_records_redacted_audit_without_presigned_url`、`test_removed_oss_storage_uri_and_config_are_rejected`）+ F 组重获路径实测 |

## 8. 与前一会话在制工作的关系（交接披露）

接手时工作树含未提交实现：单 `is_customer_production()` 闸门 + 错误码 `STORAGE_PROVIDER_SETTINGS_REQUIRED` + `pg_test_kit.py` +4 行（新建 `cw031_asset_fence_test` 库）+ 12 用例测试文件（专用库模式）。按定稿核验的偏差与处置：

1. **`pg_test_kit.py` 越界改动 → 撤销**。该文件归 CW-056（其 PR 已含同类纯增量 allowlist），CW-031 禁改；专用库方案同时违反「不新建 PG 测试库」约束。
2. **单闸门 → 定稿双闸门**：主闸门必须是多实例共享的 `active_storage_provider`（管理端可改，只读环境变量可被绕过）；错误码归位为定稿的 `STORAGE_PROVIDER_FORBIDDEN`。
3. **`storage_for_asset` 客户生产拒绝、bootstrap 启动期探测、rbac 注释、跨实例/授权/故障专项**此前缺失 → 按定稿补齐。
4. 旧 12 用例中的真实激活链路与 local-objects 端点场景保留其价值，已按定稿口径移植进新测试文件；旧文件未提交过、直接删除，不留分支痕迹。

## 9. CodeReview 自检重点核查（6 项）

1. `local_download_signature` 未改/未删/未改名 —— git diff 面无 `storage.py`，四护栏 + F 组实测 ✅
2. `storage_object_ref_from_uri` local 解析保留 —— 同上，B 组实测 ✅
3. 内部 P0 单机车道未误伤 —— `gate1_bootstrap.py`/`gate1_e2e.py` 零改动；A 组桌面车道回归锁 + C 组桌面 PUT 不围栏 ✅
4. 新增日志无 bucket/ak/sk/完整 URI —— `get_media_storage` 只记 provider 值；`storage_for_asset` 只记 provider；bootstrap 沿用 `type(exc).__name__` ✅
5. 「本地持久新增 = 0」断言排除 `.cache` 段 —— `_persistent_file_snapshot` 显式排除 ✅
6. `bootstrap` 「先释放 PG 连接再发外部调用」顺序未改坏 —— 探测加在 `pg_transaction()` 块外，`_run_runtime_bootstrap`/`resolve_database_config`/`validate_customer_production` 零改动 ✅

## 10. 验证记录

| 验证 | 命令/环境 | 结果 |
| --- | --- | --- |
| 循环 import 自检 | `python -c "import app.main; import app.media_routes; import app.bootstrap"` | IMPORT_OK |
| 专项（有 PG） | `pytest tests/test_storage_cross_instance.py -q`（PG 16.15 容器 vs-pg-cw031:5436 共享库 + 套件锁） | **27 passed / 0 failed / 0 skip** |
| 缺 PG 硬门 | 同上，unset `TEST_POSTGRESQL_URL` | 3 passed（纯适配器用例）/ **24 errors / 0 skipped**，rc=1（CW-007 硬门保持 fail 而非 skip） |
| 签名护栏 ×4 | `pytest tests/test_storage.py::<四用例> -q` | 4 passed |
| 既有回归（一） | test_storage / test_media / test_rbac / test_simple_character / test_character_reference_matching / test_character_identity_api | 207 passed / 8 failed —— 8 项全为 simple_character 图像解码用例，触发 `MediaToolUnavailable`（本机无 ffmpeg）；**基线对照实验：stash 本任务全部改动后同用例同样失败**，与本任务零关系 |
| 既有回归（二） | test_source_frames / test_character_image_generation / test_operation_costs / test_customer_chain_e2e | 58 passed / 1 skipped |
| 既有回归（三） | test_oral_domain | 全部 error 为已登记的 ffmpeg 环境缺陷（CW-055/056 证据同口径），CI Linux 分片上有 ffmpeg 全过 |
| 静态门 | ruff check / ruff format --check / mypy app | 全过（mypy 104 source files） |
| `npm run check` 全仓门禁 | 每任务唯一一次，末尾含服务端全量 pytest | 交由 CI Linux quality gate 承载（与本仓近期任务同口径），结果以 PR CI 为准 |
