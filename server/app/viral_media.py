"""爆款视频媒体管线（C4 重启）.

把爆款视频的媒体文件取回并落到主存储（COS / 本地盘），供提取文案、
视频复刻与详情页播放复用：

- 抖音：音频优先（``music.play_url`` 原声 mp3），无音频直链时取最低
  分辨率 MP4（bit_rate 最低档，客户端层已选好）。
- 视频号：无音频直链 → 详情接口取 ``full_url`` + ``decode_key`` →
  内存解密（仅前 128 KiB 变换，其余透传，不落盘）。

对象 key 确定性命名（``viral/{platform}/{video_id}.{mp3|mp4}``）：
同平台同视频只拉取/解密一次，重复请求命中已存对象后直接签名返回。
调用方须传入**新鲜**的 ``ViralVideo``（视频号 exportId 会过期，路由层
负责在缓存过期时重新搜索刷新）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol, cast
from urllib.request import Request, urlopen

from app.storage import DownloadIntent, StoredObject
from app.viral_decrypt import decrypt_head, is_encrypted_mp4
from app.viral_tikhub import (
    PLATFORM_DOUYIN,
    PLATFORM_WECHAT,
    ViralSourceClient,
    ViralSourceError,
    ViralVideo,
)

VIRAL_STORAGE_PREFIX = "viral"
VIRAL_MEDIA_URL_TTL = timedelta(hours=6)
_DEFAULT_FETCH_TIMEOUT_SECONDS = 60.0
_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"

logger = logging.getLogger(__name__)


class ViralMediaError(ViralSourceError):
    """爆款媒体获取失败（文案中性，不含供应商名称）。"""


@dataclass(frozen=True)
class ViralMediaResult:
    kind: str  # "audio" | "video"
    storage_uri: str
    url: str
    size: int
    content_type: str
    cache_hit: bool


def viral_media_key(platform: str, video_id: str, kind: str) -> str:
    extension = "mp3" if kind == "audio" else "mp4"
    return f"{VIRAL_STORAGE_PREFIX}/{platform}/{video_id}.{extension}"


class ViralStorage(Protocol):
    """媒体管线需要的最小存储面（``StorageAdapter`` 的结构子集）."""

    def head_object(self, key: str) -> StoredObject | None: ...

    def put_object(self, key: str, content: bytes, *, content_type: str) -> StoredObject: ...

    def create_download_intent(
        self, key: str, *, expires_in: timedelta, can_read: bool
    ) -> DownloadIntent: ...


class UrlFetcher:
    """下载远端媒体字节（可注入以便测试）."""

    def __init__(self, *, timeout_seconds: float = _DEFAULT_FETCH_TIMEOUT_SECONDS) -> None:
        self.timeout_seconds = timeout_seconds

    def fetch(self, url: str) -> bytes:
        request = Request(url, headers={"User-Agent": _USER_AGENT}, method="GET")
        with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
            return cast(bytes, response.read())


def _fetch_or_raise(fetcher: UrlFetcher, url: str) -> bytes:
    try:
        return fetcher.fetch(url)
    except ViralSourceError:
        raise
    except Exception as exc:  # noqa: BLE001 - 远端 CDN 可能抛出任意异常
        logger.warning("Viral media download failed: %s", type(exc).__name__)
        raise ViralMediaError("该视频素材暂时无法获取，请稍后重试") from exc


class ViralMediaPipeline:
    """按平台把爆款视频媒体取回主存储并返回可播放/下载的签名地址."""

    def __init__(
        self,
        *,
        client: ViralSourceClient,
        storage: ViralStorage,
        fetcher: UrlFetcher | None = None,
    ) -> None:
        self._client = client
        self._storage = storage
        self._fetcher = fetcher or UrlFetcher()

    def fetch(self, video: ViralVideo) -> ViralMediaResult:
        kind, content_type = self._resolve_kind(video)
        key = viral_media_key(video.platform, video.video_id, kind)
        existing = self._storage.head_object(key)
        if existing is not None:
            return self._result(key, existing, kind, content_type, cache_hit=True)
        content = self._download_content(video, kind)
        stored = self._storage.put_object(key, content, content_type=content_type)
        return self._result(key, stored, kind, content_type, cache_hit=False)

    # -- 内部 -----------------------------------------------------------------

    def _resolve_kind(self, video: ViralVideo) -> tuple[str, str]:
        if video.platform == PLATFORM_DOUYIN:
            if video.audio_url:
                return "audio", "audio/mpeg"
            if video.play_url:
                return "video", "video/mp4"
            raise ViralMediaError("该视频暂无可用的媒体地址")
        if video.platform == PLATFORM_WECHAT:
            return "video", "video/mp4"
        raise ViralMediaError("暂不支持的视频平台")

    def _download_content(self, video: ViralVideo, kind: str) -> bytes:
        if video.platform == PLATFORM_DOUYIN:
            url = video.audio_url if kind == "audio" else video.play_url
            if not url:
                raise ViralMediaError("该视频暂无可用的媒体地址")
            content = _fetch_or_raise(self._fetcher, url)
            if kind == "video" and is_encrypted_mp4(content[:8]):
                raise ViralMediaError("该视频素材暂时无法获取，请稍后重试")
            return content
        if video.platform == PLATFORM_WECHAT:
            return self._download_wechat_video(video)
        raise ViralMediaError("暂不支持的视频平台")

    def _download_wechat_video(self, video: ViralVideo) -> bytes:
        export_id = str(video.native.get("export_id") or "")
        if not export_id:
            raise ViralMediaError("该视频素材暂时无法获取，请稍后重试")
        nonce = video.native.get("object_nonce_id") or None
        try:
            detail = self._client.wechat_video_detail(export_id=export_id, object_nonce_id=nonce)
        except ViralSourceError as exc:
            raise ViralMediaError("该视频素材暂时无法获取，请稍后重试") from exc
        if not detail.full_url or not detail.decode_key:
            raise ViralMediaError("该视频素材暂时无法获取，请稍后重试")
        content = _fetch_or_raise(self._fetcher, detail.full_url)
        if is_encrypted_mp4(content[:8]):
            content = decrypt_head(content, detail.decode_key)
        if is_encrypted_mp4(content[:8]):
            # 解密后仍不是标准 MP4：decode_key 不匹配或文件异常。
            raise ViralMediaError("该视频素材暂时无法获取，请稍后重试")
        return content

    def _result(
        self,
        key: str,
        stored: StoredObject,
        kind: str,
        content_type: str,
        *,
        cache_hit: bool,
    ) -> ViralMediaResult:
        intent = self._storage.create_download_intent(
            key, expires_in=VIRAL_MEDIA_URL_TTL, can_read=True
        )
        return ViralMediaResult(
            kind=kind,
            storage_uri=stored.uri,
            url=intent.url,
            size=stored.size,
            content_type=stored.content_type,
            cache_hit=cache_hit,
        )
