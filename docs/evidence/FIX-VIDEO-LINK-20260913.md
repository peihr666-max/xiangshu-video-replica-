# FIX-VIDEO-LINK-20260913 — 抖音链接媒体预检修复

用户提供的抖音精选 modal_id 链接能够被解析服务正确识别。失败依次位于本机 Fake-IP DNS、M4A 音频类型校验，以及 Windows 临时文件仍被打开时 ffprobe 无法读取。修复后同一解析结果的音频、视频均实际下载并通过预检。

## 实现与边界

- 仅对域名的系统 DNS 全部返回 `198.18.0.0/15` 的情况，通过固定公网 IP、验证 TLS 的 DNS JSON 查询获取公网地址。继续禁止 IP 字面量、私网/混合地址；每次跳转重新校验并固定实际连接 IP。查询只包含域名，不包含视频 URL 的签名参数。
- 音频接受实际 M4A 容器，仍经过 ffprobe；存储 MIME 与项目文件扩展名匹配。保留原缓存 key，避免破坏既有媒体准备记录。
- ffprobe 在临时目录中读取已关闭的文件，结束后清理，兼容 Windows。
- 明确的 DNS 失败返回脱敏网络提示；用户主动重试时生成新幂等键，避免永久重放失败回执。未知提交态继续保留原键，不自动重新调用解析服务。

## 验证

| 验证 | 实际结果 |
| --- | --- |
| 失败测试先行 | Fake-IP 1 failed；M4A/Windows 文件读取 2 failed；DNS 失败回执重试 1 failed |
| 定向回归 | 媒体与预检 50 passed，工作台 75 passed |
| 本地 Linux 静态门 | secret、Biome、TS、1400 前端测试、e2e lint、Tauri fmt/check、ruff/format/mypy 全通过 |
| 本地 PG 全量 | 1969 passed、1 failed、1 原有 TLS skip；唯一失败为临时测试口令 `test` 同时出现在用户名/库名中的误报，隔离 PG 更换合成口令后 test_db_pg 全部 84 passed。其余文件未重复全量执行 |
| 用户原链接缓存复验 | 音频 4,763,212 字节 `audio/mp4`、视频 51,822,510 字节 `video/mp4`；两者下载和真实 ffprobe 预检通过 |
| 代码评审 | 本轮代码自检：SSRF、重定向、TLS、失败重试、缓存 MIME 和临时文件清理；不冒称独立人工评审 |

首次静态门登录 shell 没有保留 Cargo PATH：此前 secret/前端/e2e 检查已通过，调整为非登录 shell 后仅继续剩余 Tauri 与 Python 检查。原始失败记录保留。新增测试已登记 shard-0；不修改门禁规则。

本地日志和脱敏诊断位于仓库上级 `outputs/video-link-fix-20260913`。解析原始响应仅作本机加密缓存，不进入仓库、PR 或日志。DNS JSON 协议依据 [Cloudflare 官方文档](https://developers.cloudflare.com/1.1.1.1/encryption/dns-over-https/make-api-requests/dns-json/)。

## §14 任务证据

```text
任务/工作包：FIX-VIDEO-LINK-20260913 / 用户链接 422 维护
Owner / Reviewer：Codex 01a09858-332a-7a92-9449-a176f93dffe5 / 代码自检及 PR 门禁
分支 / 基线 SHA：fix/video-link-media-422-20260913 / f401a0b48b4d336154e42574db302e2b6787e515
上游规格段落：用户抖音链接报错与一次诊断授权；AGENTS 标准流程，任务账本 §12、§14、§15、§18 维护增量
改动文件：viral_media.py、viral_import_routes.py、viral_import.py、media.py；test_viral_media.py、新增 test_viral_link_media.py；MainPages.tsx 与测试；shard-0 登记及本任务账本证据
失败测试或回归锁定：三个真实根因和终态回执重试分别 RED→GREEN，见上表
实现结果：同一解析结果可下载并预检，不因 M4A 或 Windows 文件锁误报媒体失效
验证命令与通过数：pytest 定向 50 passed；MainPages 75 passed；npm run check:static 按连续步骤完成，前端1400 passed；全量 PG 1969 pass/1环境失败/1既有skip，修正临时口令后受影响文件84 passed
证据层级：AUTOMATED_VERIFIED；原链接媒体下载/预检实测，不将其扩大为转写/视频生成真实链路验收
安全与可观测性：TLS与公网IP固定不降低；私网、IP字面量、混合DNS拒绝；错误脱敏；加密诊断缓存不提交
迁移与回滚：无迁移，正常 revert 本任务代码；原存储缓存命名兼容
外部授权记录：用户明确允许1次已配置解析服务诊断；已使用且仅使用1次。后续复验均解密本机缓存，无第二次解析调用
未测试项：不启动付费转写、图片/视频生成或生产COS写入；用户在用LOCAL-JOINT服务尚未切换到此分支
Lore 提交 SHA：由本任务 PR 当前 head / squash 记录
```

远程 PR 三门禁、合并及 main 校验待取得真实结果后归档，不以本地通过代替。
