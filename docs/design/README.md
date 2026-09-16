# 设计资料

设计资料集中放在本目录。业务实现入口见[开发导航](../development/README.md)，产品实际静态资源仍由 `client/` 管理。

| 分类 | 内容 |
| --- | --- |
| [reviews](reviews/) | V1.1–V1.4 六套审核包，原文件名及版本完整保留 |
| [V1.4 完整审核图册](reviews/前端页面V1.4-完整审核包-2026-09-05/00-打开审核.html) | 21 个审核项与原图；作为该版实现的历史设计基线 |
| [previews](previews/) | 按日期保留的设计方向与效果图 |
| [prototypes](prototypes/) | 独立 HTML 原型 |
| [references](references/) | 爆款页面布局与叠图参考 |
| [admin-redesign](admin-redesign/) | 管理后台设计和出图提示词 |
| [最近归档的视觉记录](../evidence/design-qa-20260917.md) | 从原仓库根目录 design-qa.md 迁入的已跟踪验收记录 |

图册自检可从仓库根目录运行：

```bash
node "docs/design/reviews/前端页面V1.3-数字人口播整合-2026-09-05/99-审核图册检查.mjs"
(cd "docs/design/reviews/前端页面V1.4-完整审核包-2026-09-05" && node --test review.test.cjs)
```

审核包内部的图片、脚本与清单一起迁移，相对路径保持完整。旧记录中的个人机器绝对路径保留作历史信息。新的设计资料按用途继续放在上述分类，版本号和日期用于区分历史，不在仓库顶层新建审核包。
