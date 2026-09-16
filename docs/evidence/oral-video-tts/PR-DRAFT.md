# ORAL-VIDEO-TTS: Use video avatars and cloned voices for oral creation

数字人口播统一使用“真人视频分身 + 已确认克隆声音 + 已确认文案”。按选定设计稿重做分身库与上传弹窗，声音档案保留独立标签并统一视觉；移除口播照片分身和整段音频模式入口，保留五视图、场景照、人物置换等图片用途及历史任务处理。

修正口播视频/声音上传在素材复用时仍重复 PUT/complete 的问题，并在后端复用可信探测时长、重新验证声音用途。补充取消上传、切换人物、迟到响应与幂等重试保护；未知用途或完整口播音频不会被带入声音克隆表单。

验证：前端 103 文件 / 1565 passed；最终 PeoplePages 专项 47 passed；口播/素材后端专项 205 passed；Biome、TypeScript、Ruff、mypy、Tauri fmt/check、E2E lint、secret scan 通过。后端全量原始 2388 passed / 5 failed / 1 skipped；5 项均因 Linux 容器缺少 Windows worktree 的 Git 元数据而失败，正确只读挂载后原测试补验全部通过（1 + 3 + 1），唯一测试覆盖合计 2393 passed / 1 既有 TLS 配置 skip。原始报告与补验证据分别保留。桌面、手机、空态、弹窗和创作导航已在浏览器验收，设计报告通过。

边界：未调用真实付费飞影克隆或成片，未运行 Windows NSIS 门禁，未合并部署。没有数据库迁移，回退方式为 revert 本任务 PR。独立 PR 评审与三门禁完成后才可进入合并流程。

证据：`docs/evidence/ORAL-VIDEO-TTS-20260916.md`、`docs/evidence/oral-video-tts/visual-review.md`。

本文件仅为待提交 PR 正文。当前 GitHub 连接返回账号停用且本地无可用 Git 凭据，尚未创建远程 PR。
