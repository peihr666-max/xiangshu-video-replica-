# MATERIAL-PERF-C-20260917 证据

> 素材库性能优化第三批：启动与缓存（P0-5 double bootstrap、P0-6 超时与切片重试、P1-1 页间缓存、P1-2 签名复用）。

## §14 证据记录

```text
任务/工作包：MATERIAL-PERF-C-20260917（编号外性能优化任务）
Owner / Reviewer：ZCode session (GLM-5.3-Flash) 代 honor.pei / 待 PR 评审分配
分支 / 基线 SHA：perf/material-perf-c-20260917 / origin/main@07de759e
上游规格段落：素材库性能根因分析与优化方案 §四 P0-5/P0-6/P1-1/P1-2
改动文件：client/src/studio/StudioWorkspace.tsx（1 行依赖收敛）；client/src/api.ts；
  client/src/studio/live.ts；client/src/studio/pageCache.ts（新增）；MainPages.tsx；
  api.test.ts、studio/pageCache.test.ts（新增）、studio/live.test.ts；scripts/ci/test-shards/*
失败测试或回归锁定：api.test 新增签名缓存 3 项（TTL 复用/fresh 绕过/跨资产隔离）；
  live.test 新增切片重试 1 项；既有"缓存命中时鉴权HTTP仍拒绝旧字节"等安全用例
  全部原样通过（fresh 逃生口保住每次新授权语义）
实现结果：见代码开发清单本任务文件边界段
验证命令与通过数：pageCache/api/live 三套 245 项 + StudioWorkspace 100 项通过；
  check:static 全绿（前端 107 文件 / 1735 项，mypy 159 文件）；分片全量见门禁执行记录
证据层级：AUTOMATED_VERIFIED（本地自动化）
安全与可观测性：fresh 逃生口保证素材预览授权每次新签（吊销即时生效语义不变）；
  签名缓存随会话代际整体失效（换号/登出绝不复用旧授权）
迁移与回滚：无迁移；纯前端改动，还原本 PR 文件即回滚
外部授权记录：无
未测试项：真实弱网环境的首开体感（需真机验收）；分片全量为服务端回归性质
  （本任务零服务端改动）
Lore 提交 SHA：以 PR 当前 head 为准
```

## 门禁执行记录

- 2026-09-17：`npm run check:static` 全绿（前端 107 文件 / 1735 passed）；分片全量
  pytest（5571 端口段）四片全绿 624+833+628+530 = **2615 passed / 1 既有 skip**。
- 2026-09-17 冲突处置重验（后合者重挂+重探针）：#145（任务B）/ #144 合入 main 后
  本分支 rebase 至 origin/main@68969a7f；唯一冲突为两份协作文档（双方各自追加段
  落），按"保留双方登记行"并集解决，分片清单由工具整册重生成（112 文件覆盖守卫
  通过），与任务B 代码零文本冲突。重验实测：`npm run check:static` 全绿（前端
  107 文件 / 1738 passed，与任务B/首帧单张的测试合跑）；分片全量 pytest 四片全绿
  （含任务B 全部服务端用例合跑）。
