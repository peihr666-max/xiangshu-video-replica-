# MATERIAL-PERF-A-20260917 证据

> 素材库性能优化第一批：pageSize 与分页窗口化（P0-1）、批量预览授权（P0-2）、失败/过期预览自动重试（P0-4）。
> 上游规格：`docs/素材库显示与页面切换性能根因分析与优化方案-2026-09-17.md` §四 P0 表。

## §14 证据记录

```text
任务/工作包：MATERIAL-PERF-A-20260917（编号外性能优化任务，非 CW/TXX 正式编号）
Owner / Reviewer：ZCode session (GLM-5.3-Flash) 代 honor.pei / 待 PR 评审分配
分支 / 基线 SHA：feat/material-perf-a-20260917 / origin/main@0ce6ed28
上游规格段落：素材库性能根因分析与优化方案 §四 P0-1/P0-2/P0-4
改动文件：server/app/rbac_routes.py；server/tests/test_material_perf_batch_urls.py（新增）；
  server/tests/pg_test_kit.py（allowlist 并集追加 matperf_a_batch_urls_test）；
  client/src/api.ts；client/src/studio/ContentPages.tsx；client/src/api.test.ts；
  client/src/studio/ContentPages.test.tsx；client/src/generated/api.ts（手术式追加）；
  docs/客户云版任务认领登记.md；docs/客户版代码开发清单-V3.md；本证据；分析方案文档
失败测试或回归锁定：server/tests/test_material_perf_batch_urls.py 六项先红（404 → 端点缺失）后绿；
  ContentPages.test.tsx 12 项旧断言随语义升级改写（六条分页→二十四条分页、逐瓦片签名→整页批量、
  用户点击重试→自动重试），并新增分页窗口化 2 项、自动重试封顶 1 项
实现结果：批量授权端点一次写事务复用单端点授权/审计逻辑（逐资产审计行保留、他属/缺失逐条
  ASSET_NOT_FOUND 掩蔽、上限 100、去重保序、auditor 403）；前端素材页整页一次批量授权替代
  逐瓦片 N+1（图片仍走本机缓存判定；generation-only 素材保留单资产通道；批量失败退回逐条）；
  素材页 pageSize 6→24；分页按钮窗口化（首末页+当前页±1+省略号）；失败/过期预览 1s/3s
  自动重签、封顶 2 次，卸载/翻页清理计时器
验证命令与通过数：
  - uv run pytest tests/test_material_perf_batch_urls.py -q → 6 passed（专属 PG 库）
  - uv run pytest tests/test_storage.py tests/test_cw058_content_asset_pg_matrix.py -q → 122 passed（重构回归）
  - npx vitest run src/api.test.ts → 168 passed（含新增批量预览授权 6 项）
  - npx vitest run src/studio/ContentPages.test.tsx → 95 passed（含新增 3 项）
  - 全量门禁见 §2（check:static + run-pytest-shards）
证据层级：AUTOMATED_VERIFIED（本地自动化；未触真实 COS/生产）
安全与可观测性：批量端点继承单端点全部安全性质（require_not_auditor、require_asset_access 属主
  掩蔽、逐资产审计、15 分钟签名、session_epoch）；无新增敏感字段暴露（sha256/size/content_type
  本就可经单资产端点读取）；测试锁定跨用户隔离与审计口径
迁移与回滚：无数据库迁移；端点为纯新增，回滚即还原 rbac_routes.py 与前端调用点
外部授权记录：无（未触真实付费/生产 COS/公网发布）
未测试项：真实 COS 环境下的批量授权链路（无真实凭据，属 STAGING/REAL_CHAIN 层级）；Windows
  NSIS 与 cargo 相关门禁归 CI 三门禁
Lore 提交 SHA：以 PR 当前 head 为准
```

## 1. 关键实现事实

- `POST /api/assets/download-urls`（rbac_routes.py）：请求体 `{asset_ids: [1..100]}`；响应
  `{items: [{asset_id, url?, sha256?, size_bytes?, content_type?, error_code?}]}`。授权主体抽取为
  `_grant_download_for_asset`，与单资产端点 `_create_download_grant` 完全同逻辑（单端点行为不变，
  由 test_storage.py / test_cw058 回归钉住）。
- `getMaterialCachedPreviews(userId, entries, options)`（api.ts）：一次批量授权 + 逐条本机缓存判定
  （与单资产函数共享 `materialPreviewAfterAuthorization`）；图片 populate 写 CacheStorage 的行为
  与单资产通道一致，未回退 MATERIAL-CACHE-20260915 的缓存能力。
- ContentPages 素材页：`loadPreviewsBatch` 整页可见素材一次授权；`generation_task_id` 直出素材保留
  单资产回退；批量整体失败（超时/网络）先释放逐瓦片加载标记再退回逐条路径（该顺序缺陷曾在测试中
  暴露并修复：退回调用若发生在 finally 清理前会被加载标记早退）。
- 自动重试（P0-4）：`retryPreview` 1s/3s 退避、每素材封顶 2 次；签名 URL 媒体加载失败
  （15 分钟过期场景）经 `invalidatePreview` 触发自动重签；卸载/翻页/缓存清理时取消计时器。
- `generated/api.ts` 采用仓内既有的手术式追加惯例（参照 #128/#130 的小规模追加），避免整文件
  重排污染评审。

## 2. 任务收尾全量门禁（2026-09-17 实测）

- [x] `npm run check:static` —— 通过（secret 扫描、Biome、tsc、e2e lint、tauri fmt/check、
      ruff check/format、mypy 159 文件、前端全量 vitest）。
- [x] `bash scripts/ci/run-pytest-shards.sh`（`CI_SHARD_BASE_PORT=5571` 避让并行会话在用
      的 5433 默认 fixture）—— 4 分片全绿：574 + 706 + 663 + 643 = **2586 passed / 1 既有
      skip**（skip 为历史 TLS 用例，与 main 口径一致），110 个测试文件全覆盖守卫通过；
      新增测试文件经 `scripts/ci/build-test-shards.py --shards 4` 重新生成并提交清单。
- [x] 前端全量 `npx vitest run` —— **107 文件 / 1726 passed**（含本任务新增 9 项：
      服务端无关的前端批量预览授权 6 项、分页窗口化 2 项、自动重试封顶 1 项）。

## 门禁执行记录

- 2026-09-17：本地三门禁前置（check:static + 分片全量 pytest + 前端全量 vitest）全部实测
  通过；cargo test / npm audit / 浏览器 E2E / npm run build 按 AGENTS 约定归 CI 三门禁，
  本地未单独执行、不记作通过。
- 2026-09-17 冲突处置重验（后合者重挂+重探针）：#141/#142 合入 main 后本分支 rebase 至
  origin/main@1851e6c0，分片清单经 `build-test-shards.py --shards 4` 整册重生成（111 文件
  覆盖守卫通过，唯一文本冲突 shard-0.txt 取 main 侧后由工具重排，未手工拼接）。重验实测：
  `npm run check:static` 全绿（前端 107 文件 / 1728 passed，与 #141/#142 测试合跑）；分片
  全量 pytest 四片全绿 624+833+628+530 = **2615 passed / 1 既有 skip**（含 #141 新增
  test_viral_link_canonical.py 与本任务测试同片合跑）。#141/#142 与本任务改动文件零交集，
  无语义叠加风险。


## 3. 与其余性能任务的关系

- 任务 B（MATERIAL-THUMBS-B，视频缩略图）、任务 C（MATERIAL-PERF-C，启动与缓存）、
  任务 D（MATERIAL-PERF-D，渲染与打包）尚未开工；按认领登记约定，待前置合并后从最新
  origin/main 另起 worktree，不从本分支派生。
