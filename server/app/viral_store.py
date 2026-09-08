"""爆款视频参考库持久化（C4 重启）.

搜索结果按 ``(platform, video_id)`` 唯一 upsert 到 ``viral_videos``：
跨分类/跨排序去重，互动数据随每次回源刷新，未再出现的条目保留在库中
作为长期参考。列表读取走库，回源判据由 ``viral_fetch_state`` 提供
（TTL 内只读库不请求上游，作为计费护栏）。

SQL 一律走 ``BusinessConnection.execute``（PostgreSQL ``%s`` 占位符，
SQLite 由 ``translate_to_sqlite`` 翻译）。
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from app.db_portable import BusinessConnection
from app.viral_tikhub import MAX_TAGS, ViralVideo, WechatVideoDetail, is_irrelevant_viral_video

VIRAL_FETCH_TTL = timedelta(hours=1)
STATISTICS_CHECKED_AT_KEY = "_statistics_checked_at"
STATISTICS_RETRY_AT_KEY = "_statistics_retry_at"
_STATISTICS_METADATA_KEYS = (STATISTICS_CHECKED_AT_KEY, STATISTICS_RETRY_AT_KEY)
_METADATA_LOOKUP_CHUNK_SIZE = 400
# 桌面服务是单进程；统一串行化 native_json 的读改写，避免不同请求互相覆盖。
_NATIVE_JSON_RMW_LOCK = threading.RLock()


def lock_viral_scope(conn: BusinessConnection, scope: str) -> None:
    """Serialize paid refresh and native-json RMW across PostgreSQL instances."""
    if conn.is_postgres:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (scope,))


@contextmanager
def viral_session_lock(conn: BusinessConnection, scope: str) -> Iterator[None]:
    """Hold a PostgreSQL lock across helpers that commit their own writes."""
    if not conn.is_postgres:
        yield
        return
    conn.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", (scope,))
    try:
        yield
    finally:
        conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (scope,))


_UPSERT_SQL = """
INSERT INTO viral_videos (
    platform, video_id, category, title, author, author_avatar, verified,
    cover_url, cover_key, duration_ms, likes, comments, shares, collects,
    published_at, published_display, like_display, tags_json,
    play_url, audio_url, native_json
) VALUES (
    %s, %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s, %s
)
ON CONFLICT (platform, video_id) DO UPDATE SET
    category = excluded.category,
    title = excluded.title,
    author = excluded.author,
    author_avatar = COALESCE(excluded.author_avatar, viral_videos.author_avatar),
    verified = excluded.verified,
    cover_url = COALESCE(excluded.cover_url, viral_videos.cover_url),
    duration_ms = COALESCE(NULLIF(excluded.duration_ms, 0), viral_videos.duration_ms),
    likes = excluded.likes,
    comments = COALESCE(excluded.comments, viral_videos.comments),
    shares = COALESCE(excluded.shares, viral_videos.shares),
    collects = COALESCE(excluded.collects, viral_videos.collects),
    published_at = COALESCE(excluded.published_at, viral_videos.published_at),
    published_display = COALESCE(excluded.published_display, viral_videos.published_display),
    like_display = excluded.like_display,
    tags_json = CASE WHEN excluded.tags_json = '[]' THEN viral_videos.tags_json
                     ELSE excluded.tags_json END,
    play_url = COALESCE(excluded.play_url, viral_videos.play_url),
    audio_url = COALESCE(excluded.audio_url, viral_videos.audio_url),
    native_json = excluded.native_json,
    updated_at = CURRENT_TIMESTAMP
"""

_ORDER_BY = {
    "hot": "likes DESC, published_at DESC, video_id",
    "latest": "published_at DESC, likes DESC, video_id",
}


def _row_to_video(row: Any) -> ViralVideo:
    mapping = dict(row)
    tags = json.loads(mapping.get("tags_json") or "[]")
    native = json.loads(mapping.get("native_json") or "{}")
    return ViralVideo(
        platform=str(mapping["platform"]),
        video_id=str(mapping["video_id"]),
        category=str(mapping.get("category") or ""),
        title=str(mapping.get("title") or ""),
        author=str(mapping.get("author") or ""),
        author_avatar=mapping.get("author_avatar"),
        verified=bool(mapping.get("verified")),
        cover_url=mapping.get("cover_url"),
        cover_key=mapping.get("cover_key"),
        duration_ms=int(mapping.get("duration_ms") or 0),
        likes=int(mapping.get("likes") or 0),
        comments=mapping.get("comments"),
        shares=mapping.get("shares"),
        collects=mapping.get("collects"),
        published_at=mapping.get("published_at"),
        published_display=mapping.get("published_display"),
        like_display=mapping.get("like_display"),
        tags=[str(tag) for tag in tags][:MAX_TAGS],
        play_url=mapping.get("play_url"),
        audio_url=mapping.get("audio_url"),
        native=native if isinstance(native, dict) else {},
    )


def _video_row(video: ViralVideo) -> tuple[object, ...]:
    return (
        video.platform,
        video.video_id,
        video.category,
        video.title,
        video.author,
        video.author_avatar,
        1 if video.verified else 0,
        video.cover_url,
        video.cover_key,
        video.duration_ms,
        video.likes,
        video.comments,
        video.shares,
        video.collects,
        video.published_at,
        video.published_display,
        video.like_display,
        json.dumps(video.tags[:MAX_TAGS], ensure_ascii=False),
        video.play_url,
        video.audio_url,
        json.dumps(video.native, ensure_ascii=False),
    )


def _native_from_json(value: object) -> dict[str, Any]:
    try:
        native = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return native if isinstance(native, dict) else {}


def _cached_statistics_metadata(
    conn: BusinessConnection, videos: list[ViralVideo]
) -> dict[tuple[str, str], dict[str, Any]]:
    by_platform: dict[str, list[str]] = {}
    for video in videos:
        ids = by_platform.setdefault(video.platform, [])
        if video.video_id not in ids:
            ids.append(video.video_id)

    cached: dict[tuple[str, str], dict[str, Any]] = {}
    for platform, video_ids in by_platform.items():
        for start in range(0, len(video_ids), _METADATA_LOOKUP_CHUNK_SIZE):
            chunk = video_ids[start : start + _METADATA_LOOKUP_CHUNK_SIZE]
            placeholders = ", ".join("%s" for _ in chunk)
            rows = conn.execute(
                f"""
                SELECT platform, video_id, native_json FROM viral_videos
                WHERE platform = %s AND video_id IN ({placeholders})
                """,
                (platform, *chunk),
            ).fetchall()
            for row in rows:
                native = _native_from_json(row["native_json"])
                metadata = {key: native[key] for key in _STATISTICS_METADATA_KEYS if key in native}
                if metadata:
                    cached[(str(row["platform"]), str(row["video_id"]))] = metadata
    return cached


def _merge_cached_statistics_metadata(
    conn: BusinessConnection, videos: list[ViralVideo]
) -> list[ViralVideo]:
    cached = _cached_statistics_metadata(conn, videos)
    merged: list[ViralVideo] = []
    for video in videos:
        metadata = cached.get((video.platform, video.video_id))
        if not metadata:
            merged.append(video)
            continue
        native = dict(video.native)
        native.update(metadata)
        merged.append(replace(video, native=native))
    return merged


def upsert_viral_videos(conn: BusinessConnection, videos: list[ViralVideo]) -> None:
    """按 (platform, video_id) 去重写入/刷新条目."""
    with _NATIVE_JSON_RMW_LOCK:
        for platform in sorted({video.platform for video in videos}):
            lock_viral_scope(conn, f"viral:upsert:{platform}")
        for video in _merge_cached_statistics_metadata(conn, videos):
            conn.execute(_UPSERT_SQL, _video_row(video))
        conn.commit()


def list_viral_videos(conn: BusinessConnection, *, platform: str, sort: str) -> list[ViralVideo]:
    order = _ORDER_BY.get(sort, _ORDER_BY["hot"])
    rows = conn.execute(
        f"""
        SELECT * FROM viral_videos
        WHERE platform = %s AND (published_at IS NULL OR published_at >= %s)
        ORDER BY {order}
        """,
        (platform, int((datetime.now(UTC) - timedelta(days=7)).timestamp())),
    ).fetchall()
    return [_row_to_video(row) for row in rows if not is_irrelevant_viral_video(str(row["title"]))]


def get_viral_video(conn: BusinessConnection, *, platform: str, video_id: str) -> ViralVideo | None:
    row = conn.execute(
        """
        SELECT * FROM viral_videos
        WHERE platform = %s AND video_id = %s
        """,
        (platform, video_id),
    ).fetchone()
    return _row_to_video(row) if row is not None else None


def update_viral_cover(
    conn: BusinessConnection,
    *,
    platform: str,
    video_id: str,
    cover_key: str,
) -> None:
    """封面落存储成功后回写 key（路由据此下发自有稳定地址）."""
    conn.execute(
        """
        UPDATE viral_videos
        SET cover_key = %s, updated_at = CURRENT_TIMESTAMP
        WHERE platform = %s AND video_id = %s
        """,
        (cover_key, platform, video_id),
    )
    conn.commit()


def fetch_state_is_fresh(
    conn: BusinessConnection, *, platform: str, sort: str, max_age: timedelta
) -> bool:
    row = conn.execute(
        """
        SELECT fetched_at FROM viral_fetch_state
        WHERE platform = %s AND sort = %s
        """,
        (platform, sort),
    ).fetchone()
    if row is None:
        return False
    try:
        fetched_at = datetime.fromisoformat(str(row["fetched_at"]))
    except ValueError:
        return False
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=UTC)
    return datetime.now(UTC) - fetched_at <= max_age


def mark_fetch_state(conn: BusinessConnection, *, platform: str, sort: str) -> None:
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """
        INSERT INTO viral_fetch_state (platform, sort, fetched_at)
        VALUES (%s, %s, %s)
        ON CONFLICT (platform, sort) DO UPDATE SET
            fetched_at = excluded.fetched_at
        """,
        (platform, sort, now),
    )
    conn.commit()


def viral_fetched_at(conn: BusinessConnection, *, platform: str, sort: str) -> str | None:
    row = conn.execute(
        "SELECT fetched_at FROM viral_fetch_state WHERE platform = %s AND sort = %s",
        (platform, sort),
    ).fetchone()
    return str(row["fetched_at"]) if row else None


def update_viral_statistics(
    conn: BusinessConnection, *, platform: str, video_id: str, detail: WechatVideoDetail
) -> None:
    """复用媒体详情响应，仅回填实际返回的统计；搜索缺失字段不冲掉补采结果。"""
    with _NATIVE_JSON_RMW_LOCK:
        lock_viral_scope(conn, f"viral:upsert:{platform}")
        row = conn.execute(
            "SELECT native_json FROM viral_videos WHERE platform = %s AND video_id = %s FOR UPDATE",
            (platform, video_id),
        ).fetchone()
        if row is None:
            return
        native = _native_from_json(row["native_json"])
        native[STATISTICS_CHECKED_AT_KEY] = datetime.now(UTC).isoformat()
        native.pop(STATISTICS_RETRY_AT_KEY, None)
        conn.execute(
            """
            UPDATE viral_videos SET
                likes = COALESCE(%s, likes), comments = COALESCE(%s, comments),
                shares = COALESCE(%s, shares), collects = COALESCE(%s, collects),
                like_display = CASE WHEN %s IS NOT NULL THEN NULL ELSE like_display END,
                native_json = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE platform = %s AND video_id = %s
            """,
            (
                detail.like_count,
                detail.comment_count,
                detail.forward_count,
                detail.fav_count,
                detail.like_count,
                json.dumps(native, ensure_ascii=False),
                platform,
                video_id,
            ),
        )
        conn.commit()


def mark_viral_statistics_failure(
    conn: BusinessConnection, *, platform: str, video_id: str
) -> None:
    """记录详情补采失败时间，供短冷却复用；不改成功时间与已有统计。"""
    with _NATIVE_JSON_RMW_LOCK:
        lock_viral_scope(conn, f"viral:upsert:{platform}")
        row = conn.execute(
            "SELECT native_json FROM viral_videos WHERE platform = %s AND video_id = %s FOR UPDATE",
            (platform, video_id),
        ).fetchone()
        if row is None:
            return
        native = _native_from_json(row["native_json"])
        native[STATISTICS_RETRY_AT_KEY] = datetime.now(UTC).isoformat()
        conn.execute(
            """
            UPDATE viral_videos SET native_json = %s, updated_at = CURRENT_TIMESTAMP
            WHERE platform = %s AND video_id = %s
            """,
            (json.dumps(native, ensure_ascii=False), platform, video_id),
        )
        conn.commit()
