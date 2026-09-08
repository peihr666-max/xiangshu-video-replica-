"""爆款视频路由（C4 重启）.

- ``GET /api/viral/videos?platform=&sort=``：按服务端配置的关键词聚合
  两个平台的最近 7 天爆款列表（结果带 TTL 缓存，作为计费护栏）。
- ``POST /api/viral/videos/media``：按需取媒体文件（抖音音频优先/低清
  兜底；视频号解密后直传主存储），返回带签名的可播放地址。

供应商红线：所有响应文案与字段保持中性，不出现数据源供应商名称。
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path as FilePath
from typing import Annotated, Any, Literal, cast
from urllib.parse import quote, unquote, urlsplit
from uuid import NAMESPACE_URL, uuid5

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from pydantic import BaseModel, Field

from app.auth import Database
from app.customer_fence import BusinessDbDep
from app.db import connect_database
from app.db_pg import DATABASE_URL_ENV, pg_transaction
from app.db_portable import BusinessConnection
from app.media_routes import api_base_url, get_media_storage
from app.permissions import require_not_auditor
from app.settings import settings_encryption_key
from app.storage import StorageBackendUnavailable, local_download_signature
from app.viral_keywords import viral_categories, viral_keyword
from app.viral_media import (
    VIRAL_MEDIA_URL_TTL,
    CoverEnricher,
    UrlFetcher,
    ViralMediaPipeline,
    ViralMediaResult,
    guess_image_content_type,
    viral_cover_key,
    viral_media_key,
)
from app.viral_statistics import refresh_viral_statistics
from app.viral_store import (
    fetch_state_is_fresh,
    get_viral_video,
    lock_viral_scope,
    mark_fetch_state,
    update_viral_cover,
    update_viral_statistics,
    upsert_viral_videos,
    viral_fetched_at,
    viral_session_lock,
)
from app.viral_store import (
    list_viral_videos as list_stored_viral_videos,
)
from app.viral_tikhub import (
    PLATFORM_DOUYIN,
    PLATFORM_WECHAT,
    ViralSourceClient,
    ViralSourceError,
    ViralSourceUnavailable,
    ViralVideo,
    viral_source_client_from_settings,
)

router = APIRouter(prefix="/api/viral", tags=["viral"])

SORT_HOT = "hot"
SORT_LATEST = "latest"
_VALID_SORTS = (SORT_HOT, SORT_LATEST)
_VALID_PLATFORMS = (PLATFORM_DOUYIN, PLATFORM_WECHAT)

_DOUYIN_SORT_TYPE = {SORT_HOT: "1", SORT_LATEST: "2"}
_WECHAT_SORT = {SORT_HOT: "hot", SORT_LATEST: "latest"}

VIRAL_LIST_CACHE_TTL = timedelta(hours=1)
VIRAL_MEDIA_FRESHNESS = timedelta(minutes=10)
logger = logging.getLogger(__name__)
# 桌面单进程：同平台并发页面请求共享一次回源，库内时间戳仍是刷新依据。
_REFRESH_LOCKS = {platform: threading.Lock() for platform in _VALID_PLATFORMS}
_COVER_LOCKS = {platform: threading.Lock() for platform in _VALID_PLATFORMS}


class ViralVideoItem(BaseModel):
    platform: str
    videoId: str
    category: str
    title: str
    author: str
    authorAvatar: str | None
    verified: bool
    coverUrl: str | None
    durationMs: int
    likes: int
    comments: int | None
    shares: int | None
    collects: int | None
    publishedAt: int | None
    publishedDisplay: str | None
    likeDisplay: str | None
    tags: list[str]
    hasPlayableAudio: bool
    playUrl: str | None = None
    native: dict[str, Any] = Field(default_factory=dict)


class ViralListResponse(BaseModel):
    platform: str
    sort: str
    categories: list[str]
    items: list[ViralVideoItem]
    fetchedAt: str | None
    source: Literal["database"] = "database"
    stale: bool = False


class ViralMediaRequest(BaseModel):
    platform: str = Field(min_length=1)
    videoId: str = Field(min_length=1)
    # 播放需要视频；缺省按管线默认（抖音音频优先）。
    kind: Literal["audio", "video"] | None = None


class ViralStatisticsRequest(BaseModel):
    videoIds: list[str] = Field(min_length=1, max_length=12)


class ViralStatisticsResponse(BaseModel):
    items: list[ViralVideoItem]


class ViralMediaResponse(BaseModel):
    kind: str
    url: str
    contentType: str
    cacheHit: bool
    video: ViralVideoItem | None = None


class ViralImportRequest(BaseModel):
    kind: Literal["audio", "video"]


class ViralImportResponse(BaseModel):
    project_id: str
    asset_id: str
    kind: Literal["audio", "video"]


def _now() -> datetime:
    return datetime.now(UTC)


def get_viral_source_client(conn: Database) -> ViralSourceClient | None:
    """数据源客户端依赖入口（测试可通过 dependency_overrides 替换）."""
    try:
        return viral_source_client_from_settings(conn)
    except ViralSourceUnavailable:
        return None


ViralSourceClientDep = Annotated[ViralSourceClient | None, Depends(get_viral_source_client)]


def _fetch_videos(
    client: ViralSourceClient, platform: str, category: str, keyword: str, sort: str
) -> list[ViralVideo]:
    if platform == PLATFORM_DOUYIN:
        return client.douyin_search(
            keyword=keyword,
            category=category,
            sort_type=_DOUYIN_SORT_TYPE.get(sort, "1"),
        )
    if platform == PLATFORM_WECHAT:
        return client.wechat_search(
            keyword=keyword,
            category=category,
            sort=_WECHAT_SORT.get(sort, SORT_HOT),
        )
    raise ViralSourceError("暂不支持的视频平台")


def _open_worker_connection() -> tuple[BusinessConnection, Callable[[], None]]:
    """后台线程专用连接：按当前运行模式新开一条业务连接（用完即关）."""
    if os.environ.get(DATABASE_URL_ENV, "").strip():
        stack = ExitStack()
        try:
            pg_conn = stack.enter_context(pg_transaction())
            return BusinessConnection.postgres(pg_conn), stack.close
        except BaseException:
            stack.close()
            raise

    db_path = os.environ.get("VIDEO_REPLICA_DB_PATH")
    if not db_path:
        raise RuntimeError("VIDEO_REPLICA_DB_PATH is required for cover enrichment")
    conn = BusinessConnection.sqlite(connect_database(FilePath(db_path)))
    return conn, conn.close


def _spawn_cover_enrich(enricher: CoverEnricher, videos: list[ViralVideo]) -> None:
    pending = [video for video in videos if not video.cover_key and video.cover_url]
    if not pending:
        return
    lock = _COVER_LOCKS[pending[0].platform]
    if not lock.acquire(blocking=False):
        return

    def worker() -> None:
        try:
            conn, close = _open_worker_connection()
            try:
                with ThreadPoolExecutor(max_workers=10) as pool:
                    futures = [pool.submit(enricher.enrich, video) for video in pending]
                    # 单张下载完即串行回写，避免慢封面阻塞整批可用副本。
                    for future in as_completed(futures):
                        result = future.result()
                        if result.cover_key:
                            update_viral_cover(
                                conn,
                                platform=result.platform,
                                video_id=result.video_id,
                                cover_key=result.cover_key,
                            )
            finally:
                close()
        except Exception as exc:
            logger.warning("Viral cover enrichment failed: %s", type(exc).__name__)
        finally:
            lock.release()

    threading.Thread(target=worker, name="viral-cover-enrich", daemon=True).start()


def _collect_videos(
    conn: BusinessConnection,
    client: ViralSourceClient | None,
    *,
    platform: str,
    sort: str,
    max_age: timedelta,
    enricher: CoverEnricher | None = None,
    allow_refresh: bool = True,
) -> list[ViralVideo]:
    """响应始终从库读取；同平台冷请求等待首轮落库，随后复用。"""
    with _REFRESH_LOCKS[platform], viral_session_lock(conn, f"viral:refresh:{platform}:{sort}"):
        if allow_refresh and not fetch_state_is_fresh(
            conn, platform=platform, sort=sort, max_age=max_age
        ):
            failures: list[ViralSourceError] = []
            jobs: list[tuple[str, str]] = []
            for category in viral_categories():
                keyword = viral_keyword(category, platform)
                if not keyword or fetch_state_is_fresh(
                    conn, platform=platform, sort=f"{sort}:category:{category}", max_age=max_age
                ):
                    continue
                if fetch_state_is_fresh(
                    conn,
                    platform=platform,
                    sort=f"{sort}:retry:{category}",
                    max_age=timedelta(minutes=1),
                ):
                    failures.append(ViralSourceError("爆款数据源暂时不可用，请稍后重试"))
                else:
                    jobs.append((category, keyword))
            if client is None:
                failures.append(ViralSourceUnavailable("爆款数据源尚未配置"))
            else:
                # 分类独立回源并分别记成功状态；一类失败不丢掉已付费取得的数据。
                with ThreadPoolExecutor(max_workers=4) as pool:
                    futures = {
                        pool.submit(
                            _fetch_videos, client, platform, category, keyword, sort
                        ): category
                        for category, keyword in jobs
                    }
                    outcomes: dict[str, list[ViralVideo] | ViralSourceError] = {}
                    for future in as_completed(futures):
                        category = futures[future]
                        try:
                            outcomes[category] = future.result()
                        except ViralSourceError as exc:
                            outcomes[category] = exc
                        except (ValueError, TypeError):
                            outcomes[category] = ViralSourceError("爆款数据源返回异常，请稍后重试")

                    # HTTP 保持并行，数据库按配置顺序串行写入；跨分类同 video_id
                    # 时，最终归属不受 future 完成先后影响。
                    for category, _keyword in jobs:
                        outcome = outcomes[category]
                        if isinstance(outcome, ViralSourceError):
                            failure = outcome
                            failures.append(failure)
                            mark_fetch_state(
                                conn, platform=platform, sort=f"{sort}:retry:{category}"
                            )
                            logger.warning(
                                "Viral refresh failed for %s/%s: %s",
                                platform,
                                category,
                                type(failure).__name__,
                            )
                            continue
                        upsert_viral_videos(conn, outcome)
                        mark_fetch_state(
                            conn, platform=platform, sort=f"{sort}:category:{category}"
                        )
            if not failures:
                mark_fetch_state(conn, platform=platform, sort=sort)
            elif not list_stored_viral_videos(conn, platform=platform, sort=sort):
                raise failures[0]
        videos = list_stored_viral_videos(conn, platform=platform, sort=sort)
    if enricher is not None:
        _spawn_cover_enrich(enricher, videos)
    return videos


def _item(video: ViralVideo) -> ViralVideoItem:
    item = ViralVideoItem(**video.to_client_dict())
    if item.coverUrl and item.coverUrl.startswith("/"):
        # 自有稳定封面路由：下发绝对地址，跨源前端（桌面/开发）可直接加载。
        item.coverUrl = f"{api_base_url()}{item.coverUrl}"
    return item


@router.get("/videos", response_model=ViralListResponse)
def list_viral_videos(
    db: BusinessDbDep,
    client: ViralSourceClientDep,
    platform: str = PLATFORM_DOUYIN,
    sort: str = SORT_HOT,
) -> ViralListResponse:
    if platform not in _VALID_PLATFORMS:
        raise HTTPException(
            status_code=400,
            detail={"code": "VIRAL_PLATFORM_INVALID", "message": "不支持的视频平台"},
        )
    if sort not in _VALID_SORTS:
        raise HTTPException(
            status_code=400, detail={"code": "VIRAL_SORT_INVALID", "message": "不支持的排序方式"}
        )
    with db.write() as (conn, actor):
        try:
            videos = _collect_videos(
                conn,
                client,
                platform=platform,
                sort=sort,
                max_age=VIRAL_LIST_CACHE_TTL,
                enricher=_cover_enricher_or_none(conn) if actor.role != "auditor" else None,
                allow_refresh=actor.role != "auditor",
            )
        except ViralSourceUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "VIRAL_SOURCE_UNAVAILABLE", "message": str(exc)},
            ) from exc
        except ViralSourceError as exc:
            raise HTTPException(
                status_code=502,
                detail={"code": "VIRAL_SOURCE_UPSTREAM", "message": str(exc)},
            ) from exc
        return ViralListResponse(
            platform=platform,
            sort=sort,
            categories=viral_categories(),
            items=[_item(video) for video in videos],
            fetchedAt=viral_fetched_at(conn, platform=platform, sort=sort),
            stale=not fetch_state_is_fresh(
                conn, platform=platform, sort=sort, max_age=VIRAL_LIST_CACHE_TTL
            ),
        )


@router.post("/videos/statistics", response_model=ViralStatisticsResponse)
def fetch_viral_video_statistics(
    payload: ViralStatisticsRequest,
    db: BusinessDbDep,
    client: ViralSourceClientDep,
) -> ViralStatisticsResponse:
    with db.write() as (conn, actor):
        require_not_auditor(
            conn,
            actor=actor,
            action="viral.statistics.refresh",
            entity_type="viral_video",
            entity_id=payload.videoIds[0],
        )
        videos = refresh_viral_statistics(conn, client, payload.videoIds)
        return ViralStatisticsResponse(items=[_item(video) for video in videos])


@router.post("/videos/media", response_model=ViralMediaResponse)
def fetch_viral_video_media(
    payload: ViralMediaRequest,
    db: BusinessDbDep,
    client: ViralSourceClientDep,
) -> ViralMediaResponse:
    with db.write() as (conn, actor):
        require_not_auditor(
            conn,
            actor=actor,
            action="viral.media.fetch",
            entity_type="viral_video",
            entity_id=payload.videoId,
        )
        return _fetch_viral_video_media(conn, actor.id, client, payload)


def _fetch_viral_video_media(
    conn: BusinessConnection,
    actor_id: str,
    client: ViralSourceClient | None,
    payload: ViralMediaRequest,
) -> ViralMediaResponse:
    if payload.platform not in _VALID_PLATFORMS:
        raise HTTPException(
            status_code=400,
            detail={"code": "VIRAL_PLATFORM_INVALID", "message": "不支持的视频平台"},
        )
    video = get_viral_video(conn, platform=payload.platform, video_id=payload.videoId)
    if video is None:
        # 库中暂无：回源一次（新库/视频首次被直接引用）。
        try:
            refreshed = _collect_videos(
                conn,
                client,
                platform=payload.platform,
                sort=SORT_HOT,
                max_age=VIRAL_MEDIA_FRESHNESS,
            )
        except ViralSourceUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "VIRAL_SOURCE_UNAVAILABLE", "message": str(exc)},
            ) from exc
        except ViralSourceError as exc:
            raise HTTPException(
                status_code=502,
                detail={"code": "VIRAL_SOURCE_UPSTREAM", "message": str(exc)},
            ) from exc
        video = next(
            (candidate for candidate in refreshed if candidate.video_id == payload.videoId),
            None,
        )
    if video is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "VIRAL_VIDEO_NOT_FOUND",
                "message": "该视频已不在爆款列表中，请刷新后重试",
            },
        )
    storage = get_media_storage(conn)
    needs_video = payload.kind == "video" or not video.audio_url
    cached_video = (
        storage.head_object(viral_media_key(video.platform, video.video_id, "video"))
        if video.platform == PLATFORM_DOUYIN and needs_video
        else None
    )
    if (
        video.platform == PLATFORM_DOUYIN
        and needs_video
        and cached_video is None
        and video.native.get("_playback_version") != 1
    ):
        if client is None:
            raise HTTPException(
                status_code=503,
                detail={"code": "VIRAL_SOURCE_UNAVAILABLE", "message": "爆款数据源尚未配置"},
            )
        scope = f"playback:{video.video_id}"
        retry_scope = f"playback:retry:{video.video_id}"
        try:
            with _REFRESH_LOCKS[video.platform]:
                # 等锁期间另一请求可能已经修复；数据库里的版本才是可播放依据。
                video = (
                    get_viral_video(conn, platform=video.platform, video_id=video.video_id) or video
                )
                if video.native.get("_playback_version") != 1:
                    if fetch_state_is_fresh(
                        conn,
                        platform=video.platform,
                        sort=retry_scope,
                        max_age=timedelta(minutes=1),
                    ):
                        raise ViralSourceError("爆款视频源暂时无法刷新，请稍后重试")
                    try:
                        refreshed = _fetch_videos(
                            client,
                            video.platform,
                            video.category,
                            viral_keyword(video.category, video.platform) or "自建房",
                            SORT_HOT,
                        )
                    except (ViralSourceError, ValueError, TypeError) as exc:
                        mark_fetch_state(conn, platform=video.platform, sort=retry_scope)
                        raise ViralSourceError("爆款视频源暂时无法刷新，请稍后重试") from exc
                    upsert_viral_videos(conn, refreshed)
                    repaired = get_viral_video(
                        conn, platform=video.platform, video_id=video.video_id
                    )
                    if repaired is None or repaired.native.get("_playback_version") != 1:
                        mark_fetch_state(conn, platform=video.platform, sort=retry_scope)
                        raise ViralSourceError("爆款视频源暂时无法刷新，请稍后重试")
                    mark_fetch_state(conn, platform=video.platform, sort=scope)
                    video = repaired
        except ViralSourceError as exc:
            raise HTTPException(
                status_code=502, detail={"code": "VIRAL_MEDIA_UPSTREAM", "message": str(exc)}
            ) from exc
    pipeline = ViralMediaPipeline(client=client, storage=storage)
    try:
        result: ViralMediaResult = pipeline.fetch(video, prefer=payload.kind)
    except ViralSourceUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "VIRAL_SOURCE_UNAVAILABLE", "message": str(exc)},
        ) from exc
    except ViralSourceError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "VIRAL_MEDIA_UPSTREAM", "message": str(exc)},
        ) from exc
    finally:
        detail = getattr(pipeline, "detail", None)
        if detail is not None:
            update_viral_statistics(
                conn, platform=video.platform, video_id=video.video_id, detail=detail
            )
            video = get_viral_video(conn, platform=video.platform, video_id=video.video_id) or video
    return ViralMediaResponse(
        video=_item(video),
        kind=result.kind,
        url=_browser_playable_url(result.url, actor_id),
        contentType=result.content_type,
        cacheHit=result.cache_hit,
    )


@router.post(
    "/videos/{platform}/{video_id:path}/import",
    response_model=ViralImportResponse,
)
def import_viral_video_asset(
    platform: str,
    video_id: str,
    payload: ViralImportRequest,
    db: BusinessDbDep,
    client: ViralSourceClientDep,
) -> ViralImportResponse:
    if platform not in _VALID_PLATFORMS:
        raise HTTPException(status_code=404, detail={"code": "VIRAL_VIDEO_NOT_FOUND"})
    with db.write() as (conn, actor):
        require_not_auditor(
            conn,
            actor=actor,
            action="viral.asset.import",
            entity_type="viral_video",
            entity_id=video_id,
        )
        lock_viral_scope(
            conn,
            f"viral:import:{actor.id}:{platform}:{video_id}:{payload.kind}",
        )
        video = get_viral_video(conn, platform=platform, video_id=video_id)
        if video is None:
            raise HTTPException(status_code=404, detail={"code": "VIRAL_VIDEO_NOT_FOUND"})
        project_id = str(uuid5(NAMESPACE_URL, f"viral-project:{actor.id}:{platform}:{video_id}"))
        project_name = f"爆款复刻 · {video.title.strip()[:48] or video.video_id}"
        conn.execute(
            """
            INSERT INTO projects (id, owner_user_id, name, status)
            VALUES (%s, %s, %s, 'ACTIVE')
            ON CONFLICT (id) DO NOTHING
            """,
            (project_id, actor.id, project_name),
        )
        project = conn.execute(
            "SELECT owner_user_id, status FROM projects WHERE id = %s",
            (project_id,),
        ).fetchone()
        if project is None or project["owner_user_id"] != actor.id:
            raise HTTPException(status_code=409, detail={"code": "PROJECT_OWNERSHIP_CONFLICT"})
        if project["status"] != "ACTIVE":
            raise HTTPException(status_code=409, detail={"code": "PROJECT_NOT_ACTIVE"})
        import_identity = (
            f"viral-import:{actor.id}:{project_id}:{platform}:{video_id}:{payload.kind}"
        )
        asset_id = str(uuid5(NAMESPACE_URL, import_identity))
        existing = conn.execute(
            "SELECT kind FROM assets WHERE id = %s AND project_id = %s AND created_by_user_id = %s",
            (asset_id, project_id, actor.id),
        ).fetchone()
        if existing is not None:
            existing_kind = "audio" if existing["kind"] == "source_audio" else "video"
            return ViralImportResponse(
                project_id=project_id,
                asset_id=asset_id,
                kind=cast(Literal["audio", "video"], existing_kind),
            )
        storage = get_media_storage(conn)
        try:
            media = ViralMediaPipeline(client=client, storage=storage).fetch(
                video, prefer=payload.kind
            )
        except ViralSourceError as exc:
            raise HTTPException(
                status_code=502,
                detail={"code": "VIRAL_MEDIA_UPSTREAM", "message": str(exc)},
            ) from exc
        key = viral_media_key(platform, video_id, media.kind)
        stored = storage.head_object(key)
        if stored is None:
            raise HTTPException(status_code=502, detail={"code": "VIRAL_MEDIA_ARCHIVE_MISSING"})
        asset_kind = "source_audio" if media.kind == "audio" else "source_video"
        conn.execute(
            """
            INSERT INTO assets (
                id, project_id, kind, storage_uri, sha256, size_bytes,
                content_type, created_by_user_id, metadata_json
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (
                asset_id,
                project_id,
                asset_kind,
                stored.uri,
                stored.sha256,
                stored.size,
                stored.content_type,
                actor.id,
                json.dumps(
                    {"source": "viral", "platform": platform, "video_id": video_id},
                    ensure_ascii=True,
                    sort_keys=True,
                ),
            ),
        )
        conn.commit()
        return ViralImportResponse(
            project_id=project_id,
            asset_id=asset_id,
            kind=cast(Literal["audio", "video"], media.kind),
        )


_VIRAL_FILE_SCHEME = "local://"
_VIRAL_KEY_PREFIX = "viral/"
_VIRAL_SIGNATURE_ASSET = "viral-media"
_VIRAL_SIGNATURE_EPOCH = "viral"


def _browser_playable_url(intent_url: str, user_id: str) -> str:
    """把本地存储的 ``local://`` URI 转成浏览器可用的签名文件路由.

    云存储（COS）返回预签名 HTTPS 直链，原样返回；本地盘（桌面单机）
    的 ``local://`` URI 浏览器无法访问，改发自带 HMAC 的文件端点。
    """
    if intent_url.startswith(("http://", "https://")):
        return intent_url
    if not intent_url.startswith(_VIRAL_FILE_SCHEME):
        raise HTTPException(
            status_code=502,
            detail={"code": "VIRAL_MEDIA_URL_UNSUPPORTED"},
        )
    # urlsplit 会把 local:// 后的 bucket 解析成 hostname，path 即 /<key>。
    path = unquote(urlsplit(intent_url).path)
    key = path.lstrip("/")
    if not key.startswith(_VIRAL_KEY_PREFIX):
        raise HTTPException(status_code=502, detail={"code": "VIRAL_MEDIA_URL_UNSUPPORTED"})
    expires_at = str(int(time.time()) + int(VIRAL_MEDIA_URL_TTL.total_seconds()))
    signature = local_download_signature(
        key,
        expires_at,
        user_id=user_id,
        asset_id=_VIRAL_SIGNATURE_ASSET,
        session_epoch=_VIRAL_SIGNATURE_EPOCH,
        secret=settings_encryption_key(),
    )
    return (
        f"{api_base_url()}/api/viral/videos/media/file?key={quote(key)}"
        f"&expires={expires_at}&user_id={quote(user_id)}&sig={signature}"
    )


def _cover_enricher_or_none(conn: Database) -> CoverEnricher | None:
    """封面落存储 enricher；存储不可用时返回 None（列表照常返回）."""
    try:
        storage = get_media_storage(conn)
        return CoverEnricher(storage=storage, fetcher=UrlFetcher())
    except HTTPException:
        return None


@router.get("/covers/{platform}/{video_id:path}")
def get_viral_cover(
    conn: Database,
    platform: str,
    video_id: Annotated[str, Path(min_length=1, max_length=256)],
) -> Response:
    """自有存储的长期封面副本（源站签名链接会过期）.

    无需登录：封面本身是公开内容，对象 key 由路由参数确定性派生，
    不接受任意 key。视频号 ID 是可含斜杠的 opaque ID，必须与库中记录精确匹配。
    """
    if platform not in _VALID_PLATFORMS or not video_id:
        raise HTTPException(status_code=404, detail={"code": "OBJECT_NOT_FOUND"})
    video = get_viral_video(conn, platform=platform, video_id=video_id)
    if (
        video is None
        or "\\" in video_id
        or any(part in {".", ".."} for part in video_id.split("/"))
    ):
        raise HTTPException(status_code=404, detail={"code": "OBJECT_NOT_FOUND"})
    storage = get_media_storage(conn)
    key = viral_cover_key(platform, video_id)
    try:
        stored = storage.head_object(key)
    except StorageBackendUnavailable:
        raise HTTPException(
            status_code=503, detail={"code": "STORAGE_BACKEND_UNAVAILABLE"}
        ) from None
    if stored is None:
        raise HTTPException(status_code=404, detail={"code": "OBJECT_NOT_FOUND"})
    content = storage.get_object(key)
    # 本地盘适配器按文件名猜类型，封面 key 无扩展名 → 按魔数自行判定。
    return Response(
        content=content,
        media_type=guess_image_content_type(content, key),
        headers={"Cache-Control": "public, max-age=604800"},
    )


@router.get("/videos/media/file")
def download_viral_media_file(
    conn: Database,
    key: Annotated[str, Query(min_length=1)],
    expires: Annotated[str, Query(min_length=1, max_length=20)],
    user_id: Annotated[str, Query(min_length=1)],
    sig: Annotated[str, Query(min_length=1)],
) -> Response:
    # 签名即授权（绑定 user_id + 过期时间），与本地资产签名下载同一模式；
    # 浏览器 <audio>/<video> 标签无法携带身份头，故不设登录依赖。
    if not expires.isascii() or not expires.isdecimal() or int(expires) < int(time.time()):
        raise HTTPException(status_code=403, detail={"code": "VIRAL_MEDIA_FORBIDDEN"})
    if not key.startswith(_VIRAL_KEY_PREFIX):
        raise HTTPException(status_code=403, detail={"code": "VIRAL_MEDIA_FORBIDDEN"})
    expected = local_download_signature(
        key,
        expires,
        user_id=user_id,
        asset_id=_VIRAL_SIGNATURE_ASSET,
        session_epoch=_VIRAL_SIGNATURE_EPOCH,
        secret=settings_encryption_key(),
    )
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(status_code=403, detail={"code": "VIRAL_MEDIA_FORBIDDEN"})
    storage = get_media_storage(conn)
    try:
        stored = storage.head_object(key)
        if stored is None:
            raise HTTPException(status_code=404, detail={"code": "OBJECT_NOT_FOUND"})
        content = storage.get_object(key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "OBJECT_NOT_FOUND"}) from None
    except StorageBackendUnavailable:
        raise HTTPException(
            status_code=503, detail={"code": "STORAGE_BACKEND_UNAVAILABLE"}
        ) from None
    return Response(
        content=content,
        media_type=stored.content_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )
