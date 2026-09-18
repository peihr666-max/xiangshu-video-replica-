# MATERIAL-PERF-D-20260917 证据

> 素材库性能优化第四批：渲染与打包（P1-3 切片：任务轮询无变化跳过重渲染；P1-4 切片：vendor 分包；P1-5：轮询治理）。

## §14 证据记录

```text
任务/工作包：MATERIAL-PERF-D-20260917（编号外性能优化任务）
Owner / Reviewer：ZCode session (GLM-5.3-Flash) 代 honor.pei / 待 PR 评审分配
分支 / 基线 SHA：perf/material-perf-d-20260917 / origin/main@07de759e
上游规格段落：素材库性能根因分析与优化方案 §四 P1-3/P1-4/P1-5
改动文件：client/src/customer/useCustomerSession.ts；client/src/studio/WorkspaceNotifications.tsx；
  client/src/studio/live.ts（sameTasks）；client/src/studio/StudioWorkspace.tsx（轮询 setData 跳过）；
  client/vite.config.ts；client/src/studio/live.test.ts；scripts/ci/test-shards/*；三份任务文档
失败测试或回归锁定：live.test 新增 sameTasks 用例（4 断言）；StudioWorkspace 100 项
  全量回归通过
实现结果：①通知 30s 轮询与心跳 30s 轮询在 document.hidden 时暂停（空闲/后台请求≈0）；
  ②20s 任务轮询经 sameTasks 判定无实质变化时不产生新 data 引用——空闲期不再每 20s
  全树重渲染；③rolldown output.advancedChunks 拆出 react-vendor chunk（本地构建实测
  产出 react-vendor/index/CustomerWorkspace 三 chunk）
明确不做（留档）：context value useMemo 需先将五个捕获可变 draft 的闭包 useCallback 化
  （强行 memo 会导致闭包过期，属独立重构）；页面级 React.lazy 涉及渲染语义；品牌
  activation-background 1.64MB 属 BRAND-IDENTITY 任务归属
验证命令与通过数：live.test 71 项、StudioWorkspace.test 100 项通过；check:static 全绿
  （前端 107 文件 / 1729 项，mypy 159 文件）；本地 npm run build 仅作分包健全性验证
  （不计门禁）；分片全量见门禁执行记录
证据层级：AUTOMATED_VERIFIED（本地自动化）
安全与可观测性：轮询暂停仅影响 hidden 状态（恢复可见自动续上，语义由现有用例覆盖）；
  不改变任何鉴权/授权路径
迁移与回滚：无迁移；纯前端+构建配置，还原本 PR 文件即回滚
外部授权记录：无
未测试项：rolldown 分包的 CI Windows/NSIS 打包产物归三门禁；真实体感需真机验收
Lore 提交 SHA：以 PR 当前 head 为准
```

## 门禁执行记录

- 2026-09-17：`npm run check:static` 全绿（前端 107 文件 / 1729 passed）；分片全量
  pytest（5571 端口段）四片全绿 624+833+628+530 = **2615 passed / 1 既有 skip**。
