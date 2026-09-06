# 素材库与永久保存实施证据（2026-09-06）

## 结论

素材库已形成服务端列表、按 ID 恢复、通用上传、预览下载、创作引用和基础管理闭环。口播页可以直接上传 MP3 并把真实资产 ID 写入草稿。新 H3 成片会归档到当前应用存储，归档成功后才结算；归档失败保留供应商结果并有限重试。代码不再创建项目素材与成片的 180 天自动过期规则，保存 COS 配置时会读取现有生命周期配置，仅移除历史媒体 180 天规则；其他业务规则原样保留。

证据层级：素材库代码与自动化为 `AUTOMATED_VERIFIED`；真实生产 COS 生命周期删除为 `REAL_CHAIN_VERIFIED`。

## 主要实现

- `server/app/materials.py` / `material_routes.py`：统一素材投影、分页筛选、批量恢复、上传和偏好管理。
- `server/migrations/versions/063_studio_material_preferences.py`：素材名称、分组、隐藏偏好及查询索引。
- `server/app/permissions.py` / `oral.py`：素材 owner 隔离、口播输入类型/状态/归属校验和口播结果本人读取。
- `client/src/studio/ContentPages.tsx`：云端列表、通用上传、类型/来源/名称筛选、预览、下载、重命名、分组、隐藏和按类型用于创作。
- `client/src/studio/live.ts` / `StudioWorkspace.tsx`：云草稿按素材 ID 回填并重新签发预览链接。
- `client/src/studio/CreationPages.tsx`：口播音频 MP3 直传、进度提示、资产回流和草稿引用。
- `server/app/generation.py` / `generation_worker.py`：H3 正常完成、归档重试及提交不确定恢复均写入自有存储；PostgreSQL Worker 把供应商下载/COS 写入放在短事务之外。
- `server/app/storage.py` / `settings_routes.py`：移除历史 180 天媒体过期规则，永久保存；清理失败返回明确状态并写审计，不伪报成功。

## 生命周期安全边界

- 只识别并删除历史规则 ID `expire-project-media-180d`、`expire-generation-results-180d`，或等价的指定前缀 + 180 天规则。
- 只有历史规则时删除桶生命周期配置；还存在无关规则时，用保留规则覆盖写回。
- 桶本来没有生命周期配置时按幂等成功处理。
- 生命周期 API 失败不会阻断 COS 凭据保存，但响应和审计状态为 `failed`，不能据此宣称生产桶已永久保存。

## 自动化验证

- 前端素材/API/草稿恢复专项：5 个文件，177 passed。
- H3 归档、素材权限、客户链路、Worker 恢复及口播异步兼容联合专项：251 passed。
- 全仓门禁（2026-09-07 复验）：secret 扫描通过；Biome/TypeScript 通过；前端 69 个测试文件、897 passed；E2E 静态检查通过；Tauri `cargo fmt --check`/`cargo check --locked` 通过；Python Ruff/format/mypy 通过；服务端全量 1780 passed。
- 现存非阻断提示：jsdom 不实现 `Window.scrollTo`；macOS 编译时两个 Windows 凭据常量未使用；Starlette TestClient 有 1 条 httpx 弃用警告。

## 真实 COS 结果

使用本机已保存的加密 COS 配置请求生命周期接口，腾讯云返回 HTTP 403 `AccessDenied`。随后使用已登录的腾讯云主账号控制台核验并删除目标桶中的两条历史规则：`expire-project-media-180d`（`projects/`，180 天删除）和 `expire-generation-results-180d`（`generation-results/`，180 天删除）。用户在最终生产删除前明确回复“确认删除”。两条规则删除后整页刷新，生命周期规则表仍为空，只显示“添加规则”。因此：

- 代码策略已改为永久保存；
- 生产桶旧 180 天规则已经删除，刷新复验为 0 条，COS 生命周期层已改为永久保存；
- 当前应用凭据仍无法读取或修改桶生命周期，自动化查询/清理能力仍受权限限制；
- 该权限限制不影响本次主账号控制台已完成的生产变更，但后续若要由应用自动管理生命周期，仍需给 API 执行身份授予相应权限。

## 未执行的真实链路

- 没有调用付费 Metaso 生成接口，也没有向生产 COS 上传测试成片；这两项仍需凭据与生产环境 UAT。
- 已存在的历史 `DIRECT` 任务继续兼容读取，不在本次代码变更中自动回迁到 COS。

生产变更记录另见 `docs/evidence/cos-permanent-retention-production-2026-09-06.md`。
