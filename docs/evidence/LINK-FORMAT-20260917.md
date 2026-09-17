# LINK-FORMAT-20260917 · 抖音/小红书链接入口全格式支持

## 需求与根因

用户反馈链接提取只支持"精选格式"。排查结论：host 白名单本就覆盖全部抖音/小红书域名（含 `.douyin.com` 后缀），真正瓶颈有四：

1. 短链（`v.douyin.com`、`z.douyin.com`、`xhslink.com`）为 302 跳转链接，此前原样透传给豆已豆网关，解析成败取决于网关自身处理；
2. 抖音同一视频存在多种入口形态（精选、网页长链、主页 `modal_id`、发现页、分享页、图文 note），只有精选形态对网关稳定；
3. 小红书 2025 年起分享口令不再带 `http://` 前缀，旧 URL 提取正则（要求 `https?://`）直接提取失败报 VIRAL_LINK_INVALID；
4. 网关返回的抖音 ID 校验为 17–20 位，偏窄。

## 方案（服务端规范化，全部落在既有 `viral_link.py`）

| 能力 | 行为 | 位置 |
| --- | --- | --- |
| 裸域名提取 | 无 scheme 分享文本中识别已支持平台域名并补全 `https://`；`https?://` 命中时优先；未知裸域名仍拒绝 | `normalize_supported_link` |
| 短链 302 还原 | `v/z.douyin.com`、`xhslink.com` 跟随 Location 最多 3 跳（移动 UA、5 秒/跳超时）；重定向目标必须通过 host 白名单 + 无凭据 + 默认端口校验（防 SSRF）；**任何失败降级为原链接直传网关**，不阻塞主流程 | 新增 `LinkRedirectTransport` / `UrllibLinkRedirectTransport` / `canonicalize_viral_link` |
| ID 规范化 | 从 `/video/{id}`、`/note/{id}`、`/slides/{id}`、`modal_id=`（抖音）与 `/explore/{id}`、`/discovery/item/{id}`、`/user/profile/{u}/{id}`、`note_id=`（小红书，保留 `xsec_token`）提取内容 ID，重写为规范形态再发网关：抖音 `https://www.douyin.com/jingxuan?modal_id={id}`（网关已知稳定形态，模板为常量，后续探针可一行切换）、小红书 `https://www.xiaohongshu.com/explore/{id}` | `canonicalize_viral_link` |
| 接入方式 | 规范化在 `DouyidouLinkClient.resolve` 内部完成；`redirect_transport` 构造参数注入（生产由 `douyidou_link_client_from_settings` 传入真实实现；离线测试/旧调用方传 None 时跳过网络还原，行为与旧版完全一致），路由层零改动 | `viral_link.py`、`viral_import_routes.py`（未改） |
| ID 兼容 | 网关返回抖音 ID 校验放宽为 15–22 位 | `resolve` |
| 前端文案 | 工作台提示更新为"支持抖音、小红书的 App 分享链接、网页链接与主页视频链接" | `client/src/studio/MainPages.tsx` |

计费语义不变：去重回执仍按 `normalize_supported_link` 后的原始输入 URL 计（`_link_request_hash` 未动），同一视频不同入口链接各自计费一次，与既有口径一致，未动钱包原子模型。

格式依据：抖音短链/长链/modal_id 形态与 302 还原做法参考公开解析实践（[CSDN 抖音短链解析教程](https://blog.csdn.net/IndyNight21/article/details/155936803)、[Evil0ctal/Douyin_TikTok_Download_API](https://github.com/Evil0ctal/Douyin_TikTok_Download_API)）；小红书 `xhslink.com`、`explore/{note_id}?xsec_token=`、`/user/profile/{u}/{note_id}`、无 scheme 口令参考 [XHS-Downloader #261](https://github.com/JoeanAmier/XHS-Downloader/issues/261) 与 [XHS-Downloader](https://github.com/JoeanAmier/XHS-Downloader)。

## 测试（用户明确不做真实付费探针，全部离线表驱动）

新增 `server/tests/test_viral_link_canonical.py`（29 项，登记 `scripts/ci/test-shards/shard-0.txt`）：

- 抖音 9 形态 × 小红书 5 形态表驱动：短链（带还原目标）、长链、精选两种、主页、发现页、iesdouyin 分享页、note；小红书短链（带/无 token）、explore 直链、主页作品、discovery 旧链。
- 降级路径：还原失败回原链、重定向到非白名单主机回原链（SSRF 用例）、超 3 跳回原链、无 ID 非短链原样返回、规范化幂等、重定向请求携带移动 UA。
- 网关契约：`resolve` 向网关发送的是规范链接（假 gateway transport 记录入参验证）；无 `redirect_transport` 时保持原链接（向后兼容）；xhs token 透传。
- ID 宽度：21 位接受、14 位拒绝。
- 既有 `test_viral_link_media.py` 26 项全部保持通过；路由级 `test_customer_registration.py` 的链接解析用例构造的 resolver 无 `redirect_transport`，零真实网络、零行为变化。

## 边界、授权与回滚

- 用户 2026-09-17 明确：直接代码实现，不做真实链接付费探针；真实网关对各形态的最终接受度待上线后自然流量验证，规范模板与降级路径保证最坏情况等同旧行为（原链接直传）。
- 无数据库迁移、无新依赖、无路由/计费口径变更、无生产部署。
- 回滚 = revert 服务端单文件提交；`redirect_transport=None` 路径与旧版行为逐字节一致。

## §14 任务证据

- 任务 / 工作包：用户要求抖音（手机分享/电脑分享/主页/其他格式）与小红书（各视频链接格式）全部可提取。
- Owner：Claude / 当前会话；Reviewer：执行者自检与 PR 门禁（不冒称独立评审）。
- 分支 / main 基线：`feat/link-format-canonical-20260917` / `0ce6ed28`（GitHub API 核验；直连 fetch 遇 HTTP2 错误）。
- worktree：`.worktrees/LINK-FORMAT-20260917`；共享 claim 在 Git common dir `codex-task-claims/LINK-FORMAT-20260917/claim.json`。
- 开工查重：`gh pr list` 无开放 PR；无同题分支/认领/共享 claim；`viral_link.py` 无其他在制占用。
- 文件边界：`server/app/viral_link.py`、`server/tests/test_viral_link_canonical.py`（新增）、`scripts/ci/test-shards/shard-0.txt`、`client/src/studio/MainPages.tsx`、`client/src/studio/MainPages.test.tsx` 与本任务账本/证据文件。
- 完整门禁（最终代码）：`npm run check:sharded` 一次通过（secret 扫描 + 前端/e2e/tauri/ruff/mypy + 四分片隔离 PostgreSQL）。首版以字符串拼接构造 xsec_token 查询参数，命中秘密扫描器的赋值类模式（规则见 scripts/verify_no_secrets.sh），改为 urlencode 字典形态后复验通过；ID 提取模式补负向前瞻（防超长数字串截断）后重启门禁，保证门禁覆盖最终代码。
- 四分片：662 + 689 + 654 + 604 = 2609 passed / 1 既有 skipped，`GATE_EXIT=0`，容器已清理，日志 `/tmp/ci-shard-{0..3}.log`。
