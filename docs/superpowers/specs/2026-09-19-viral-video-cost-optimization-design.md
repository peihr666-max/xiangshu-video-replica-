# 爆款视频模块成本优化设计

**日期**：2026-09-19  
**状态**：Draft  
**作者**：AI Assistant + 用户协作  
**目标运行环境**：桌面单机版（Tauri）为主

---

## 1. 背景与目标

### 1.1 业务背景

项目核心功能为爆款短视频创作，包含视频复刻流水线：上传参考视频 → AI 拆解分镜（Gemini）→ 人物置换首帧（GPT-Image-2）→ 编译 H3 Prompt → 提交 MiniMax H3 生成。

当前爆款视频模块（`viral_*` 系列代码）已实现：
- TikHub API 封装抖音 / 视频号搜索
- 运营方每周批采集 + 全量云归档
- 客户浏览已发布批次（不调 TikHub）
- 按批均摊计费模型

### 1.2 成本痛点

平台承担的成本：
1. **云存储成本**：所有搜索结果强制预归档到平台 COS（原分辨率，5-20 MB/条）
2. **流量成本**：客户浏览播放都走平台 COS CDN
3. **API 成本**：TikHub 搜索按次计费，平台先垫付再均摊

随着客户数增长，预归档量指数增长，但大部分视频从未被复刻使用，造成浪费。

### 1.3 优化目标

1. **降低平台云存储成本 80%+**：只归档真正被使用的视频
2. **降低平台流量成本 80%+**：大部分播放走 TikHub CDN
3. **API 成本客户直付**：无坏账风险，加价转售盈利
4. **保留规模红利**：元数据共享 + 精选池共享 + H3 共享对象库
5. **提升客户体验**：自由搜索 + 本地缓存 + UGC 精选

---

## 2. 现状分析

### 2.1 当前架构

```
运营方每周批采集（预设关键词）
  → TikHub 搜索
  → 落 viral_videos 元数据表
  → 强制云归档（viral_media_preparations → COS）
  → 发布（storage_uri IS NOT NULL）
  → 客户浏览（只读已发布批次）
  → 客户导入项目（拷贝到项目命名空间）
  → 视频复刻流水线
```

**关键代码**：
- `viral_tikhub.py`：TikHub API 封装
- `viral_collection.py`：每周批采集调度
- `viral_media_preparation.py`：强制云归档
- `viral_store.py`：元数据持久化（`_PUBLISHED_SQL` 要求 `storage_uri IS NOT NULL`）
- `viral_collection_billing.py`：按批均摊计费
- `viral_import.py`：导入到项目

### 2.2 技术约束

**H3 视频生成必须公链**：
- `generation.py:571-572`：`if not _h3_request_media_urls_are_https(request): raise H3ProviderFailed("METASO H3 requires HTTPS media URLs")`
- `reference_video` / `reference_audio` / `reference_image` 都必须签名 HTTPS URL

**Gemini 拆解 / GPT-Image-2 首帧可以直传**：
- `analysis_routes.py`：走本地 asset 路径，不必须公链
- 桌面端本地 ffmpeg 抽帧 → 直传供应商 API

**TikHub play_url 有效期几小时**：
- 用户搜完当场不下载，几小时后就播不了
- 需要本地缓存或按需刷新

### 2.3 规模红利

当前架构的共享层：
- `viral_videos` 元数据表：跨客户共享（去重复用）
- `viral_script_cache` 口播稿缓存：跨客户共享
- `viral_media_preparations` 云归档对象：跨客户共享（但成本由平台承担）

**关键洞察**：元数据成本可忽略（200 字节/条），视频文件才是大头（5-20 MB/条）。应该砍的是"强制视频文件预归档"，不是整个共享层。

---

## 3. 设计方案

### 3.1 架构分层

```
┌─────────────────────────────────────────────────────────────┐
│ 桌面单机版（Tauri）                                          │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ 客户前端：搜索 / 浏览 / 播放 / 下载 / 复刻 / 精选    │  │
│  └──────────────────────────────────────────────────────┘  │
│              ↓                          ↓                   │
│  ┌──────────────────┐      ┌────────────────────────────┐ │
│  │ 本地缓存层        │      │ 本地 ffmpeg/ffprobe         │ │
│  │ - 视频文件（自动）│      │ - 抽帧、探测时长、转码     │ │
│  │ - 元数据 SQLite  │      │ - 首帧图片、480p 低分辨率  │ │
│  └──────────────────┘      └────────────────────────────┘ │
└────────────┬─────────────────────────────┬────────────────┘
             │                             │
             ↓                             ↓
      ┌─────────────┐             ┌────────────────────────┐
      │ 平台 API 网关│             │ 直传路径（本地→供应商）│
      │ (计费+代理) │             │ - Gemini inline_data   │
      └──────┬──────┘             │ - GPT-Image-2 首帧图   │
             │                    └────────────────────────┘
             ↓
      ┌─────────────────────────────────────────────────────┐
      │ 平台服务端                                           │
      │ ┌─────────────────────────────────────────────────┐ │
      │ │ 共享层（几乎零成本）                            │ │
      │ │ - viral_videos 元数据表（跨客户复用）           │ │
      │ │ - viral_script_cache 口播稿缓存                 │ │
      │ │ - 精选池元数据 + 封面                           │ │
      │ └─────────────────────────────────────────────────┘ │
      │ ┌─────────────────────────────────────────────────┐ │
      │ │ 精选池云存储（平台承担）                        │ │
      │ │ - 低分辨率版视频（480p，2-5 MB/条）             │ │
      │ │ - cos://viral/featured/{platform}/{video_id}.mp4│ │
      │ │ - 所有客户共享浏览                              │ │
      │ └─────────────────────────────────────────────────┘ │
      │ ┌─────────────────────────────────────────────────┐ │
      │ │ H3 共享对象库（平台承担）                       │ │
      │ │ - 原分辨率版视频（H3 触发时按需上传）           │ │
      │ │ - cos://viral/shared/{content_hash}.mp4         │ │
      │ │ - 引用计数，跨客户复用                          │ │
      │ └─────────────────────────────────────────────────┘ │
      └─────────────────────────────────────────────────────┘
```

**存储分层规则**：
- **用户搜索的视频**：原分辨率，自动下载到本地磁盘，**不占平台云存储**
- **精选池的视频**：低分辨率（480p），存到云，**所有客户共享浏览**
- **H3 生成用的视频**：原分辨率，按需上传到共享对象库，**跨客户复用**

### 3.2 关键流程

#### 流程 1：用户搜索（每次扣费）

```
用户输入关键词 
  → 服务端调 TikHub 搜索（不管 viral_videos 是否有缓存）
  → 扣费 viral_search（¥0.10/次）
  → 返回元数据 + TikHub play_url
  → 桌面端自动下载视频文件到本地（走 TikHub CDN）
  → 落 local_viral_cache（SQLite）
  → 用户可以本地播放、复刻
```

**关键设计**：
- **每次搜索必扣费**（不管缓存）→ 简化逻辑，保证平台稳定收入
- **自动下载视频文件**到本地 → 用户立即可用，无需等待
- **走 TikHub CDN** → 平台零流量成本

#### 流程 2：用户添加精选（免费）

```
用户在搜索结果点"添加为精选"
  → 服务端检查 viral_videos.is_featured
  → 如果未精选：
     a. 从 TikHub 下载原视频 → ffmpeg 转码 480p → 上传到 cos://viral/featured/
     b. 落 viral_videos（is_featured=1, featured_source='user', featured_by_user_id=客户）
     c. 不扣费（鼓励 UGC）
  → 如果已精选：
     a. 只更新 featured_count += 1（多用户添加）
     b. 不重复转码上传
```

**关键设计**：
- **免费** → 鼓励用户贡献内容，精选池是共享资源
- **转码成本平台承担** → 480p 低分辨率版成本极低（2-5 MB/条）
- **去重** → 已精选的视频不重复转码上传

#### 流程 3：管理员添加精选

```
管理员在后台选择视频（从 viral_videos 或手动输入链接）
  → 触发转码 + 上传（同流程 2）
  → 落 viral_videos（is_featured=1, featured_source='admin', featured_by_admin_id=管理员）
```

#### 流程 4：管理员取消用户精选

```
管理员在后台看到 featured_source='user' 的精选
  → 点"取消精选" → 标记 is_featured=0
  → 云存储对象保留（其他客户可能已在用）
  → 等 reference_count=0 且 30 天无访问后硬删
```

**关键设计**：
- **不立即删除云存储对象** → 避免影响其他客户
- **延迟硬删** → 给复用窗口 + 应对误删恢复

#### 流程 5：用户浏览精选池

```
用户打开"精选"页面
  → 服务端返回 is_featured=1 的视频（元数据 + 低分辨率 COS URL）
  → 用户播放低分辨率版（走平台 COS CDN）
  → 用户点"复刻" → 需要原分辨率 → 触发流程 6
```

#### 流程 6：用户复刻（关键分支）

```
1. 检查本地缓存（local_viral_cache）：
   - 有 → 直接用本地文件
   - 无 → 从 TikHub 下载到本地（临时目录）

2. Gemini 拆解 / GPT-Image-2 首帧：
   - 桌面端本地 ffmpeg 抽帧 + 分段
   - 直传供应商 API（inline_data）
   - 落 viral_script_cache（跨客户共享）
   - 不占云存储

3. H3 生成（必须公链）：
   a. 查 viral_media_objects（共享对象库）
   b. 已有 → 签名 URL，reference_count += 1
   c. 没有 → 从 TikHub 下载原视频 → 上传到 cos://viral/shared/ → 创建对象
   d. 调 H3 API（reference_video=签名 URL）
   e. 生成完成 → 落 projects → 客户下载成品

4. H3 引用 expires_at = now() + 7 天，到期自动 reference_count -= 1
```

**关键设计**：
- **优先用本地缓存** → 避免重复下载
- **Gemini/GPT-Image-2 直传** → 不占云存储
- **H3 共享对象库** → 跨客户复用，摊薄成本
- **引用计数 + 过期** → 自动清理未复用对象

#### 流程 7：用户主动"同步到云"（可选）

```
桌面端"本地素材库"选视频 → 点"同步到云"
  → 上传到 cos://viral/customer/{user_id}/{hash}.mp4
  → 创建 viral_media_objects（is_private=1, owner_user_id=客户）
  → 创建 viral_media_references（purpose='cloud_sync'）
  → 扣 viral_cloud_storage 费（GB·月）
  → 客户可在"云端素材库"查看、下载、删除
  → 删除 → reference_count -= 1 → 归零软删 → 7 天后硬删
```

**关键设计**：
- **客户私有对象** → 隔离存储，只有归属客户能访问
- **按用量计费** → GB·月，可主动删除停止计费

### 3.3 数据库 Schema

#### 改造 `viral_videos` 表（新增精选相关字段）

```sql
ALTER TABLE viral_videos ADD COLUMN is_featured integer NOT NULL DEFAULT 0;
ALTER TABLE viral_videos ADD COLUMN featured_source text CHECK(featured_source IN ('user','admin'));
ALTER TABLE viral_videos ADD COLUMN featured_by_user_id text REFERENCES users(id);
ALTER TABLE viral_videos ADD COLUMN featured_by_admin_id text;  -- 管理员 ID（如果有 admins 表）
ALTER TABLE viral_videos ADD COLUMN featured_at timestamptz;
ALTER TABLE viral_videos ADD COLUMN featured_count integer NOT NULL DEFAULT 0;
ALTER TABLE viral_videos ADD COLUMN featured_storage_uri text;  -- cos://viral/featured/...
ALTER TABLE viral_videos ADD COLUMN featured_size_bytes bigint; -- 低分辨率版大小
```

**索引**：
```sql
CREATE INDEX idx_viral_featured ON viral_videos(is_featured, featured_at DESC) WHERE is_featured = 1;
CREATE INDEX idx_viral_featured_source ON viral_videos(featured_source) WHERE is_featured = 1;
```

#### 新增 `viral_media_objects` 表（H3 共享对象库 + 私有对象）

```sql
CREATE TABLE viral_media_objects (
    id text PRIMARY KEY,
    content_hash text NOT NULL UNIQUE,        -- SHA256，去重键
    platform text NOT NULL,                    -- douyin/wechat_channels
    video_id text NOT NULL,
    media_kind text NOT NULL,                  -- video/audio/cover
    storage_uri text NOT NULL,                 -- cos://viral/shared/{hash}.mp4 或 cos://viral/customer/{user_id}/{hash}.mp4
    size_bytes bigint NOT NULL,
    duration_ms integer,
    is_private integer NOT NULL DEFAULT 0,     -- 0=共享池 1=客户私有
    owner_user_id text REFERENCES users(id),   -- 私有对象的归属
    created_by_user_id text REFERENCES users(id), -- 首个上传者（成本归因）
    reference_count integer NOT NULL DEFAULT 0,
    last_accessed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz                     -- 软删除
);

CREATE INDEX idx_viral_media_objects_hash ON viral_media_objects(content_hash);
CREATE INDEX idx_viral_media_objects_platform_video ON viral_media_objects(platform, video_id);
CREATE INDEX idx_viral_media_objects_private ON viral_media_objects(owner_user_id, is_private) WHERE is_private = 1;
CREATE INDEX idx_viral_media_objects_deleted ON viral_media_objects(deleted_at) WHERE deleted_at IS NOT NULL;
```

#### 新增 `viral_media_references` 表（引用关系）

```sql
CREATE TABLE viral_media_references (
    id text PRIMARY KEY,
    object_id text NOT NULL REFERENCES viral_media_objects(id),
    user_id text NOT NULL REFERENCES users(id),
    purpose text NOT NULL,                     -- h3_generation/project_import/cloud_sync
    project_id text,                           -- 如果关联项目
    expires_at timestamptz,                    -- H3 引用 7 天过期
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(object_id, user_id, purpose, COALESCE(project_id,''))
);

CREATE INDEX idx_viral_media_references_object ON viral_media_references(object_id);
CREATE INDEX idx_viral_media_references_user ON viral_media_references(user_id);
CREATE INDEX idx_viral_media_references_expires ON viral_media_references(expires_at) WHERE expires_at IS NOT NULL;
```

#### 废弃 `viral_media_preparations` 表

- 迁移数据到 `viral_media_objects` 后废弃
- 或改为"临时下载任务"表（只存 H3 触发时的一次性下载状态）

#### 桌面端本地 SQLite（不在服务端）

```sql
CREATE TABLE local_viral_cache (
    platform TEXT NOT NULL,
    video_id TEXT NOT NULL,
    file_path TEXT NOT NULL,              -- 本地磁盘路径
    file_size INTEGER NOT NULL,
    content_hash TEXT,                    -- SHA256，用于去重和上云
    metadata_json TEXT,                   -- 缓存的元数据
    downloaded_at TEXT NOT NULL,
    last_accessed_at TEXT,
    PRIMARY KEY(platform, video_id)
);

CREATE INDEX idx_local_cache_accessed ON local_viral_cache(last_accessed_at);
```

**自动清理策略**：
- 保留最近 N 条（可配置，默认 100）
- 超过时删除最久未访问的（`last_accessed_at` 最早）

### 3.4 计费模型

| 计费项 | 触发 | 承担方 | 单价 | 备注 |
|---|---|---|---|---|
| `viral_search` | **每次搜索**（不管缓存） | 客户直付 | ¥0.10/次 | 简化逻辑，保证平台收入 |
| `viral_featured_upload` | 用户添加精选 | **免费** | ¥0 | 鼓励 UGC，转码成本平台承担 |
| `viral_data`（保留） | 管理员批采集精选池 | 平台承担 | ¥0 | 运营投入 |
| `viral_gemini_analyze` | 视频拆解 | 客户直付 | 现状 | 桌面端直传，无云存储费 |
| `viral_gpt_image` | 首帧置换 | 客户直付 | 现状 | 桌面端直传，无云存储费 |
| `viral_h3_generate` | H3 视频生成 | 客户直付 | 现状 | 含公链签名 URL |
| `viral_shared_storage` | H3 共享对象库 | **平台承担** | ¥0 | 规模红利 |
| `viral_featured_storage` | 精选池低分辨率版 | **平台承担** | ¥0 | 运营投入 |
| `viral_cloud_storage` | 客户主动同步私有对象 | 客户直付 | ¥0.5/GB·月 | 含 CDN 流量，可主动删除 |

**关键设计**：
- **每次搜索必扣费**（不管缓存）→ 简化逻辑，保证平台稳定收入
- **精选池存储费平台承担**（低分辨率版成本极低，480p 约 2-5 MB/条）
- **H3 共享对象库存储费平台承担**（跨客户复用，摊薄成本）
- **用户添加精选免费**（鼓励 UGC，精选池是共享资源）
- **客户私有对象存储费客户承担**（按用量公平计费）

**平台盈利点**：
- `viral_search` 加价转售（TikHub 成本 ¥0.05 → 售价 ¥0.10，毛利 50%）
- `viral_h3_generate` 加价转售（现状）
- `viral_gemini_analyze` / `viral_gpt_image` 加价转售（现状）
- `viral_cloud_storage` 加价转售（COS 成本 ¥0.12/GB·月 → 售价 ¥0.5/GB·月，毛利 76%）

---

## 4. 迁移路径（6 个 Phase，6-9 周）

### Phase 1：元数据共享 + 自由搜索（1-2 周）

**目标**：新增客户自由搜索能力，元数据跨客户共享

**任务**：
- 新增 `/viral/search` 接口（客户自由搜索）
- 元数据落 `viral_videos`（跨客户共享）
- 计费项 `viral_search` 上线（每次搜索必扣费）
- **不改**预归档逻辑（向后兼容）

**验收标准**：
- 客户可以输入任意关键词搜索
- 搜索结果元数据落库，跨客户可见
- 每次搜索扣费 ¥0.10
- 现有精选池功能不受影响

### Phase 2：共享对象库（2-3 周）

**目标**：H3 生成路径改为"先查共享对象库，没有才上传"

**任务**：
- 新增 `viral_media_objects` + `viral_media_references` 表
- 迁移 `viral_media_preparations` 数据到 `viral_media_objects`
- H3 生成路径改为"先查共享对象库，没有才上传"
- **废弃**强制预归档（`_PUBLISHED_SQL` 移除 `storage_uri IS NOT NULL`）
- 引用计数 + 过期清理任务

**验收标准**：
- H3 生成时，如果共享对象库已有该视频，直接复用（零上传成本）
- 如果没有，按需上传到 `cos://viral/shared/`
- 引用计数正确，过期自动清理
- 现有精选池功能不受影响

### Phase 3：桌面端本地缓存（1-2 周）

**目标**：桌面端自动下载视频文件到本地，复刻路径优先用本地缓存

**任务**：
- 桌面端 `local_viral_cache` 表 + Tauri 下载能力
- 搜索后自动下载视频文件到本地
- 复刻路径优先用本地缓存
- Gemini/GPT-Image-2 直传路径
- 自动清理策略（保留最近 N 条）

**验收标准**：
- 客户搜索后，视频文件自动下载到本地
- 客户可以在本地播放、复刻
- 复刻时优先用本地缓存（无需重新下载）
- 本地缓存超过 N 条时自动清理最久未访问的

### Phase 4：双通道精选（1-2 周）

**目标**：用户 + 管理员都可以添加精选，管理员可取消用户精选

**任务**：
- 改造 `viral_videos` 表（新增精选相关字段）
- 用户添加精选接口（免费）
- 管理员添加精选接口
- 管理员取消用户精选接口
- 精选池转码 + 上传任务（480p 低分辨率）
- 精选池浏览接口（返回低分辨率 COS URL）

**验收标准**：
- 用户可以在搜索结果点"添加为精选"
- 管理员可以在后台添加/取消精选
- 精选池视频以 480p 低分辨率版存储
- 客户浏览精选池时播放低分辨率版
- 用户添加 vs 管理员添加有明确标识（`featured_source`）

### Phase 5：客户主动同步（1 周）

**目标**：客户可以主动上传本地视频到云（跨设备访问）

**任务**：
- 客户端"云端素材库"UI
- 私有对象上传/删除接口
- 计费项 `viral_cloud_storage` 上线
- COS 对象生命周期策略（7 天后硬删）

**验收标准**：
- 客户可以在"本地素材库"选择视频"同步到云"
- 客户可以在"云端素材库"查看、下载、删除
- 云存储用量 + 月费估算清晰可见
- 删除后停止计费

### Phase 6：清理与监控（1 周）

**目标**：引用计数归零对象的软删除 + 30 天硬删任务，监控与报表

**任务**：
- 引用计数归零对象的软删除任务
- 软删除后 30 天硬删 COS 对象
- 共享对象库命中率监控（评估规模红利）
- 客户云存储用量报表
- 精选池使用统计

**验收标准**：
- 引用计数归零的对象自动软删除
- 软删除后 30 天无新引用则硬删
- 监控报表清晰展示共享对象库命中率、云存储用量、精选池使用统计

**风险与回滚**：
- 每个 Phase 独立可回滚（数据库迁移有 `downgrade`）
- Phase 2 是关键风险点（改 H3 生成路径），需要充分测试 + 灰度发布
- 保留 `viral_media_preparations` 表 30 天（应急回滚）

---

## 5. 风险与权衡

### 5.1 技术风险

| 风险 | 影响 | 缓解措施 |
|---|---|---|
| **H3 生成路径改造失败** | 复刻功能瘫痪 | Phase 2 充分测试 + 灰度发布 + 保留回滚路径 |
| **TikHub play_url 过期** | 用户无法播放 | 前端触发刷新（服务端调 TikHub 详情接口） |
| **本地磁盘爆满** | 桌面端崩溃 | 自动清理策略（保留最近 N 条） |
| **共享对象库引用计数错误** | 对象误删或泄漏 | 定期巡检 + 软删除延迟 30 天 |

### 5.2 业务风险

| 风险 | 影响 | 缓解措施 |
|---|---|---|
| **每次搜索必扣费引起客户不满** | 客户流失 | 明确定价 + 提供精选池免费浏览 |
| **用户添加精选质量参差不齐** | 精选池内容混乱 | 管理员可取消用户精选 + 内容审核机制 |
| **低分辨率版影响预览体验** | 客户不满意 | 480p 平衡清晰度与成本 + 复刻时自动拉取原分辨率 |

### 5.3 成本权衡

| 项目 | 现状 | 方案 A | 权衡 |
|---|---|---|---|
| **平台云存储成本** | 全量预归档 | 只存精选池 480p + H3 共享对象 | ⬇ **80-90%** |
| **平台流量成本** | 客户播放走平台 COS | 大部分走 TikHub CDN | ⬇ **80%+** |
| **平台 API 成本** | 先垫付再均摊 | 客户按次直付 | 无坏账风险 |
| **客户成本公平性** | 按批均摊（无论是否用） | 按用量直付 | ✅ 更公平 |
| **规模红利** | 有（但被预归档成本抵消） | 有（共享对象库 + 元数据缓存） | ✅ 保留 + 强化 |
| **首页精选内容** | 有 | 有（480p 低分辨率版） | ✅ 保留 |
| **客户自由搜索** | ❌ 无 | ✅ 有 | 新增能力 |
| **桌面端离线能力** | ❌ 无 | ✅ 有（本地缓存） | 新增能力 |
| **UGC 精选** | ❌ 无 | ✅ 有（用户添加精选） | 新增能力 |

---

## 6. 成本估算

### 6.1 假设

- 客户数：100 → 1000（增长 10 倍）
- 每个客户每周搜索 10 次
- 每次搜索返回 10 条视频
- 每条视频平均 10 MB（原分辨率）/ 3 MB（480p）
- 精选池：每周 top 15 条/周
- H3 生成：每个客户每月 5 次
- 共享对象库命中率：70%（热门爆款被多客户复用）

### 6.2 现状成本（100 客户）

| 项目 | 计算 | 年成本 |
|---|---|---|
| **云存储** | 100 客户 × 10 次/周 × 10 条 × 10 MB × 52 周 = 52 GB | ¥75（¥0.12/GB·月 × 12） |
| **流量** | 100 客户 × 10 次/周 × 10 条 × 10 MB × 52 周 = 52 GB | ¥26（¥0.5/GB × 52） |
| **TikHub API** | 100 客户 × 10 次/周 × 52 周 = 52000 次 | ¥2600（¥0.05/次） |
| **总计** | | **¥2701/年** |

### 6.3 方案 A 成本（100 客户）

| 项目 | 计算 | 年成本 |
|---|---|---|
| **精选池云存储** | 15 条/周 × 3 MB × 52 周 = 2.3 GB | ¥3.3（¥0.12/GB·月 × 12） |
| **H3 共享对象库** | 100 客户 × 5 次/月 × 10 MB × 12 月 × 30%（未命中）= 18 GB | ¥26（¥0.12/GB·月 × 12） |
| **精选池流量** | 100 客户 × 10 次/周 × 3 MB × 52 周 = 15.6 GB | ¥7.8（¥0.5/GB × 52） |
| **TikHub API** | 100 客户 × 10 次/周 × 52 周 = 52000 次 | ¥2600（¥0.05/次） |
| **总计** | | **¥2637/年** |

**节省**：¥64/年（2.4%）—— 100 客户时节省不明显

### 6.4 方案 A 成本（1000 客户）

| 项目 | 计算 | 年成本 |
|---|---|---|
| **精选池云存储** | 15 条/周 × 3 MB × 52 周 = 2.3 GB | ¥3.3 |
| **H3 共享对象库** | 1000 客户 × 5 次/月 × 10 MB × 12 月 × 30% = 180 GB | ¥260 |
| **精选池流量** | 1000 客户 × 10 次/周 × 3 MB × 52 周 = 156 GB | ¥78 |
| **TikHub API** | 1000 客户 × 10 次/周 × 52 周 = 520000 次 | ¥26000 |
| **总计** | | **¥26341/年** |

**现状成本（1000 客户）**：
- 云存储：520 GB → ¥750
- 流量：520 GB → ¥260
- TikHub API：520000 次 → ¥26000
- **总计**：¥27010/年

**节省**：¥669/年（2.5%）—— 1000 客户时节省仍不明显

### 6.5 关键洞察

**成本大头是 TikHub API（¥26000/年），不是云存储（¥750/年）**。

方案 A 的核心价值不是"节省成本"，而是：
1. **API 成本客户直付** → 平台无坏账风险，加价转售盈利
2. **云存储成本可控** → 不会随客户数指数增长
3. **规模红利** → 共享对象库命中率越高，成本越低
4. **客户体验提升** → 自由搜索 + 本地缓存 + UGC 精选

**盈利模型**：
- TikHub API 成本 ¥0.05/次 → 售价 ¥0.10/次 → 毛利 50%
- 1000 客户 × 10 次/周 × 52 周 = 520000 次
- 年收入：¥52000
- 年成本：¥26000
- **年毛利：¥26000（50%）**

---

## 7. 附录

### 7.1 关键代码文件

- `viral_tikhub.py`：TikHub API 封装
- `viral_collection.py`：每周批采集调度
- `viral_media_preparation.py`：云归档（改造为按需归档）
- `viral_store.py`：元数据持久化（移除 `storage_uri IS NOT NULL` 要求）
- `viral_collection_billing.py`：计费（改造为每次搜索扣费）
- `viral_import.py`：导入到项目（改造为优先用本地缓存）
- `generation.py:571-572`：H3 必须公链的硬约束

### 7.2 数据库迁移

- `20260913T1600_shared_viral_media.py`：现有共享媒体迁移
- `20260915T1600_viral_copy_cache.py`：现有口播稿缓存迁移
- **新增**：`20260920T0000_viral_cost_optimization.py`（本方案迁移）

### 7.3 计费项配置

- `billing_catalog.py`：新增 `viral_search` / `viral_cloud_storage` 计费项
- `retail_snapshot()`：定价快照

### 7.4 桌面端 Tauri 能力

- 新增 `download_viral_video(platform, video_id, play_url)` IPC 命令
- 新增 `local_viral_cache` SQLite 表
- 新增自动清理策略（保留最近 N 条）

### 7.5 监控指标

- 共享对象库命中率（目标 > 70%）
- 精选池使用统计（浏览量、复刻量）
- 客户云存储用量（按客户、按月）
- 本地缓存命中率（目标 > 80%）
- TikHub API 调用次数（按客户、按关键词）

---

## 8. 下一步

1. **用户 review 本设计文档** → 确认无误后 commit
2. **调用 writing-plans skill** → 生成详细实施计划（Phase 1-6 的具体任务、文件、验收标准）
3. **按 Phase 顺序实施** → 每个 Phase 独立可测试、可回滚
4. **灰度发布** → Phase 2（H3 生成路径改造）需要充分测试 + 灰度
5. **监控与优化** → 根据实际数据调整定价、清理策略、共享对象库命中率

---

**文档版本**：v1.0  
**最后更新**：2026-09-19  
**状态**：待用户 review
