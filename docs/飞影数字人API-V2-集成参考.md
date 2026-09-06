# 飞影数字人 API V2 · 集成参考（C1 开发正本）

> 来源：用户提供的官方文档 https://api.hifly.cc/hifly.html（2026-09-06 快照摘录）。
> 用途：C1 数字人口播整链（分身/声音/克隆/口播生成/计费）的前后端开发依据。
> 接入原则遵循仓库红线：**API Token 只进服务端密钥存储（provider_settings，Fernet 加密），不入码、不入库、不入 PR**。

## 1. 通用约定

- Base URL：`https://hfw-api.hifly.cc`（V2 接口；旧 `api.hifly.cc` 已废弃）。
- 认证：请求头 `Authorization: Bearer ${token}`，token 在飞影个人中心 → API 明细获取。
- 响应统一信封：`{"code": 0, "msg": "", "data": {...}}`；`code != 0` 即业务失败。
- 分页参数：`page`（≥1）+ `size`（≤100），分页信息在 `data.page_info`。
- 上传：先 `POST /api/v2/hifly/tool/create_upload_url`（body: `file_extension`）→ 返回
  `upload_url` + `content_type` + `file_id`；再用 `PUT upload_url` 上传二进制（带 `Content-Type`）。

## 2. 接口清单

### 数字人（分身）
| 接口 | 方法与路径 | 关键参数 | 返回 |
|---|---|---|---|
| 视频克隆分身 | POST `/api/v2/hifly/avatar/create_by_video` | `title`(≤20字)、`video_url` 或 `file_id`、`aigc_flag`(必填 bool) | `task_id` |
| 照片克隆分身 | POST `/api/v2/hifly/avatar/create_by_image` | 同上（**企业专属会员**，消耗积分） | `task_id` |
| 克隆任务状态 | GET `/api/v2/hifly/avatar/task?task_id=` | — | `status` 1 等待/2 处理中/3 完成/4 失败 + `avatar_id` |
| 公共数字人列表 | GET `/api/v2/hifly/avatar/list?page&size&kind=2` | `kind=2` 公共 | 分页 `list[]`（id/title/cover_url 等） |

### 声音
| 接口 | 方法与路径 | 关键参数 | 返回 |
|---|---|---|---|
| 克隆声音 | POST `/api/v2/hifly/voice/create` | `title`(≤20字)、`voice_type=8`、`audio_url` 或 `file_id`（mp3/m4a/wav，≤20M，**5秒–3分钟**） | `task_id` |
| 编辑声音属性 | POST `/api/v2/hifly/voice/edit` | `voice`、`rate`/`volume`/`pitch`（字符串） | — |
| 声音列表 | GET `/api/v2/hifly/voice/list?page&size&kind` | `kind=1` 我克隆的 / `kind=2` 公共 | 分页 `list[]` |
| 克隆任务状态 | GET `/api/v2/hifly/voice/task?task_id=` | — | `status` + `voice` + `demo_url` |

### 创作（口播视频/音频）
| 接口 | 方法与路径 | 关键参数 | 返回 |
|---|---|---|---|
| 音频驱动视频 | POST `/api/v2/hifly/video/create_by_audio` | `audio_url`/`file_id`、`avatar`(必填)、`title`、`aigc_flag`（消耗积分） | `task_id` |
| 文本驱动视频(TTS) | POST `/api/v2/hifly/video/create_by_tts` | `voice`(必填)、`text`(≤10000字)、`avatar`、`title`、字幕参数 `st_*`、`aigc_flag`（消耗积分） | `task_id` |
| 文本转音频(TTS) | POST `/api/v2/hifly/audio/create_by_tts` | `voice`、`text`、`title`（消耗积分） | `task_id` |
| 视频任务状态 | GET `/api/v2/hifly/video/task?task_id=` | — | `status` + **`video_Url`（临时链接，必须转存 COS）** + `duration` |

字幕参数（`st_show=true` 时生效）：`st_font_name`、`st_font_size`(1-100)、`st_primary_color`、
`st_outline_color`（`0xRRGGBB(AA)`）、`st_width`/`st_height`（≤1920/1080）、`st_x`/`st_y`（像素坐标）。

### 账户
- 积分余额：GET `/api/v2/hifly/account/credit` → `data.credit`。
- 回调（webhook）：可选，创建类任务默认有回调；需公网可达 URL。**桌面单机/内网部署无公网回调，
  统一采用任务状态轮询**（与现有 metaso H3 轮询一致）；轮询失败有 5 分钟内重试兜底。

## 3. 错误码（选摘，客户端需映射为中文可读错误）

| code | 含义 |
|---|---|
| 11 | 参数异常（如 aigc_flag 缺失） |
| 14 | 未找到资源 |
| 1001 | 并发任务数超限 |
| 1002 | 积分余额不足 |
| 1005/1006 | 会员/权限不足（照片克隆分身为企业专属） |
| 1009/1013 | 声音数量/限制类 |
| 1011 | 疑似名人（拒绝克隆） |
| 1015 | 提交任务数超限 |
| 2003 | token 无效 |
| 2011-2016 | 文件下载/格式/大小/时长校验失败 |

## 4. 与本产品的映射（studio 前端口播表单 ↔ 飞影接口）

| 前端（`studio/CreationPages.tsx` 口播表单） | 飞影接口 | 说明 |
|---|---|---|
| 人物 → 口播分身（avatars，`ready` 标记） | avatar `create_by_video`（人物视频上传）/ `create_by_image`（单张照片，企业专属） | 克隆任务完成 → 落库 avatar_id → ready |
| 声音档案（voices，`confirmed` 标记） | voice `create`（音频 5s–3min）+ `voice/task` 轮询 | 克隆完成 → voice_id + demo_url |
| 文本驱动口播（script 文案 + 分身 + 声音） | `video/create_by_tts`（voice + text + avatar + `st_*` 字幕参数） | 样式/字幕开关直接映射 `st_show` 等 |
| 音频驱动口播（完整音频） | `video/create_by_audio`（audio_url/file_id + avatar） | 音频先经 create_upload_url 上传 |
| 音频工坊（可选产出） | `audio/create_by_tts` | 仅文案转音频 |
| 成片归档 | `video/task` 拿临时 `video_Url` → 转存 COS | 与现有 H3 ARCHIVED 流程一致 |
| 计费 | 平台侧钱包 RESERVE/SETTLE + 管理端单价（复用现有计费）；平台向飞影消耗积分 | 管理端需展示飞影积分余额（account/credit） |

## 5. 已知边界 / 决策

1. **照片克隆分身是企业专属**（1005/1006 拒绝普通会员）：前端"单张照片制作分身"入口需按服务端能力开关，
   默认隐藏，除非商户开通企业会员。
2. `video_Url` 是临时链接：任务成功后必须立即转存 COS（复用现有归档机制），前端预览走平台签名 URL。
3. 无公网回调条件：全部任务采用**轮询**（avatar/voice/video task 接口），沿用 generation worker 的分步租约模式。
4. 每平台只配一个飞影 token（全局 provider 级），多租户计费在平台侧钱包完成。
5. Token、积分余额属于运营敏感信息：只在管理端设置页展示掩码；`account/credit` 仅管理端可见。
