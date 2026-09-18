# MATERIAL-THUMBS-B-20260917 证据

> 素材库性能优化第二批：视频素材缩略图（P0-3）。
> 上游规格：`docs/素材库显示与页面切换性能根因分析与优化方案-2026-09-17.md` §四 P0-3。

## §14 证据记录

```text
任务/工作包：MATERIAL-THUMBS-B-20260917（编号外性能优化任务）
Owner / Reviewer：ZCode session (GLM-5.3-Flash) 代 honor.pei / 待 PR 评审分配
分支 / 基线 SHA：feat/material-thumbs-b-20260917 / origin/main@07de759e（含已合并 #143）
上游规格段落：素材库性能根因分析与优化方案 §四 P0-3
改动文件：server/app/material_thumbs.py（新增）；server/app/generation.py、
  generation_routes.py、media.py、materials.py、material_routes.py、rbac_routes.py；
  server/tests/test_material_thumbs.py（新增）；server/tests/pg_test_kit.py（allowlist 并集）；
  client/src/api.ts、studio/ContentPages.tsx、api.test.ts、studio/ContentPages.test.tsx、
  generated/api.ts；scripts/ci/test-shards/*（重生成）；任务认领登记、代码开发清单、本证据
失败测试或回归锁定：test_material_thumbs.py 先红（模块缺失→抽帧参数两处 ffmpeg 语法
  实测修正）后绿；前端新增缩略图瓦片/历史回退/批量缩略图映射用例
实现结果：视频入库三通道（生成成片归档、参考视频上传、素材上传）在内容字节在手处抽
  首帧 JPEG（≤480px，确定性键 <key>.thumb.jpg），键记 assets.metadata_json（零迁移）；
  批量授权对带键视频签 7 天缩略图 URL；前端网格视频瓦片用 img 懒加载展示封面、不再
  经服务端代理流式拉原视频，详情面板 poster 先行、播放不变；历史无键视频降级现有占位
验证命令与通过数：test_material_thumbs.py 8 项 + test_material_perf_batch_urls.py 6 项
  （PG 专属库）；前端 ContentPages 97 + api.test 170；check:static 全绿（前端 107 文件
  /1731 项）；分片全量 pytest 结果见门禁执行记录
证据层级：AUTOMATED_VERIFIED（本地自动化；真实 COS/生产未触）
安全与可观测性：缩略图签名与原视频同一通道同一属主校验（thumbnail_url 仅对已通过
  require_asset_access 的资产签发）；不新增敏感暴露（键本就在该用户资产元数据内）；
  抽帧/落存储全部在写事务之外（外部 I/O 红线）
迁移与回滚：无迁移；回滚还原本 PR 文件即可（多余缩略图对象成为无引用垃圾，无害）
外部授权记录：无
未测试项：真实 COS 端到端抽帧链路（STAGING 层级）；口播成片视频未接抽帧（来源写入点
  在 oral worker，留待后续增量）；存量数据无回填（生产全新空库无存量，见数据处置决议）
Lore 提交 SHA：以 PR 当前 head 为准
```

## 门禁执行记录

- 2026-09-17：`npm run check:static` 全绿（前端 107 文件 / 1731 passed，mypy 160 文件）；
  分片全量 pytest（CI_SHARD_BASE_PORT=5571 避让并行会话 fixture）四片全绿
  636+803+674+510 = **2623 passed / 1 既有 skip**，112 测试文件覆盖守卫通过。
