"""爆款视频路由（C4 重启）.

- ``GET /api/viral/videos?platform=&sort=``：按服务端配置的关键词聚合
  两个平台的最近 7 天爆款列表（结果带 TTL 缓存，作为计费护栏）。
- ``POST /api/viral/videos/media``：按需取媒体文件（抖音音频优先/低清
  兜底；视频号解密后直传主存储），返回带签名的可播放地址。

供应商红线：所有响应文案与字段保持中性，不出现数据源供应商名称。
"""

from __future__ import annotations

import hmac
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from app.auth import AuthenticatedUser, Database
from app.media_routes import get_media_storage
from app.settings import settings_encryption_key
from app.storage import StorageBackendUnavailable, local_download_signature
from app.viral_keywords import viral_categories, viral_keyword
from app.viral_media import VIRAL_MEDIA_URL_TTL, ViralMediaPipeline, ViralMediaResult
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
    native: dict[str, Any]


class ViralListResponse(BaseModel):
    platform: str
    sort: str
    categories: list[str]
    items: list[ViralVideoItem]
    fetchedAt: str


class ViralMediaRequest(BaseModel):
    platform: str = Field(min_length=1)
    videoId: str = Field(min_length=1)


class ViralMediaResponse(BaseModel):
    kind: str
    url: str
    contentType: str
    cacheHit: bool


class _CacheEntry:
    __slots__ = ("fetched_at", "videos")

    def __init__(self, videos: list[ViralVideo], fetched_at: datetime) -> None:
        self.videos = videos
        self.fetched_at = fetched_at


_cache: dict[tuple[str, str, str], _CacheEntry] = {}
_cache_lock = threading.Lock()


def _now() -> datetime:
    return datetime.now(UTC)


def get_viral_source_client(conn: Database) -> ViralSourceClient:
    """数据源客户端依赖入口（测试可通过 dependency_overrides 替换）."""
    try:
        return viral_source_client_from_settings(conn)
    except ViralSourceUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "VIRAL_SOURCE_UNAVAILABLE", "message": str(exc)},
        ) from exc


ViralSourceClientDep = Annotated[ViralSourceClient, Depends(get_viral_source_client)]


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


def _collect_videos(
    client: ViralSourceClient,
    *,
    platform: str,
    sort: str,
    max_age: timedelta,
) -> list[ViralVideo]:
    """按分类聚合平台列表；缓存新鲜则直接复用（计费护栏）."""
    collected: list[ViralVideo] = []
    seen: set[str] = set()
    now = _now()
    for category in viral_categories():
        keyword = viral_keyword(category, platform)
        if not keyword:
            continue
        cache_key = (platform, category, sort)
        with _cache_lock:
            entry = _cache.get(cache_key)
            if entry is not None and now - entry.fetched_at <= max_age:
                videos = entry.videos
            else:
                videos = _fetch_videos(client, platform, category, keyword, sort)
                _cache[cache_key] = _CacheEntry(videos, now)
        for video in videos:
            if video.video_id in seen:
                continue
            seen.add(video.video_id)
            collected.append(video)
    return collected


def reset_viral_cache() -> None:
    """清空进程内列表缓存（测试与运维用）."""
    with _cache_lock:
        _cache.clear()


def _item(video: ViralVideo) -> ViralVideoItem:
    return ViralVideoItem(**video.to_client_dict())


@router.get("/videos", response_model=ViralListResponse)
def list_viral_videos(
    conn: Database,
    actor: AuthenticatedUser,
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
    try:
        videos = _collect_videos(client, platform=platform, sort=sort, max_age=VIRAL_LIST_CACHE_TTL)
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
        fetchedAt=_now().isoformat(),
    )


@router.post("/videos/media", response_model=ViralMediaResponse)
def fetch_viral_video_media(
    payload: ViralMediaRequest,
    conn: Database,
    actor: AuthenticatedUser,
    client: ViralSourceClientDep,
) -> ViralMediaResponse:
    if payload.platform not in _VALID_PLATFORMS:
        raise HTTPException(
            status_code=400,
            detail={"code": "VIRAL_PLATFORM_INVALID", "message": "不支持的视频平台"},
        )
    try:
        videos = _collect_videos(
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
        (candidate for candidate in videos if candidate.video_id == payload.videoId),
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
    pipeline = ViralMediaPipeline(client=client, storage=storage)
    try:
        result: ViralMediaResult = pipeline.fetch(video)
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
    return ViralMediaResponse(
        kind=result.kind,
        url=_browser_playable_url(result.url, actor),
        contentType=result.content_type,
        cacheHit=result.cache_hit,
    )


_VIRAL_FILE_SCHEME = "local://"
_VIRAL_KEY_PREFIX = "viral/"
_VIRAL_SIGNATURE_ASSET = "viral-media"
_VIRAL_SIGNATURE_EPOCH = "viral"


def _browser_playable_url(intent_url: str, actor: AuthenticatedUser) -> str:
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
    path = urlsplit(intent_url).path
    key = path.lstrip("/")
    if not key.startswith(_VIRAL_KEY_PREFIX):
        raise HTTPException(status_code=502, detail={"code": "VIRAL_MEDIA_URL_UNSUPPORTED"})
    expires_at = str(int(time.time()) + int(VIRAL_MEDIA_URL_TTL.total_seconds()))
    signature = local_download_signature(
        key,
        expires_at,
        user_id=actor.id,
        asset_id=_VIRAL_SIGNATURE_ASSET,
        session_epoch=_VIRAL_SIGNATURE_EPOCH,
        secret=settings_encryption_key(),
    )
    return (
        f"/api/viral/videos/media/file?key={quote(key)}"
        f"&expires={expires_at}&user_id={quote(actor.id)}&sig={signature}"
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
    if int(expires) < int(time.time()):
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
        content = storage.get_object(key)
    except StorageBackendUnavailable:
        raise HTTPException(
            status_code=503, detail={"code": "STORAGE_BACKEND_UNAVAILABLE"}
        ) from None
    if stored is None:
        raise HTTPException(status_code=404, detail={"code": "OBJECT_NOT_FOUND"})
    return Response(
        content=content,
        media_type=stored.content_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )
