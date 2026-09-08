"""视频号列表统计补采的缓存、并发与失败冷却测试."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from app.db import connect_database, initialize_database
from app.db_portable import BusinessConnection
from app.viral_statistics import (
    apply_viral_statistics_refresh,
    fetch_viral_statistics_without_database,
    plan_viral_statistics_refresh,
)
from app.viral_store import get_viral_video, upsert_viral_videos
from app.viral_tikhub import (
    PLATFORM_DOUYIN,
    PLATFORM_WECHAT,
    ViralSourceClient,
    ViralSourceError,
    ViralVideo,
    WechatVideoDetail,
)


def _open(path: Path) -> BusinessConnection:
    return BusinessConnection.sqlite(connect_database(path))


_test_refresh_lock = threading.Lock()


def refresh_viral_statistics(conn, client, video_ids):
    with _test_refresh_lock:
        videos, pending, invalid = plan_viral_statistics_refresh(conn, video_ids)
        if client is None:
            return videos
        outcomes = fetch_viral_statistics_without_database(client, pending)
        refreshed = apply_viral_statistics_refresh(conn, video_ids, pending, invalid, outcomes)
        conn.commit()
        return refreshed


def _video(
    video_id: str = "video-1",
    *,
    platform: str = PLATFORM_WECHAT,
    native: dict[str, object] | None = None,
) -> ViralVideo:
    return ViralVideo(
        platform=platform,
        video_id=video_id,
        category="庭院案例",
        title="农村庭院设计",
        author="作者",
        author_avatar=None,
        verified=False,
        cover_url="https://cdn.test/cover.jpg",
        duration_ms=10_000,
        likes=10,
        comments=None,
        shares=None,
        collects=None,
        published_at=int(datetime.now(UTC).timestamp()),
        published_display="1小时前",
        like_display="10",
        tags=["农村庭院"],
        native=native
        or {"export_id": f"export/{video_id}", "object_nonce_id": f"nonce-{video_id}"},
    )


def _detail(
    *,
    likes: int | None = 20,
    comments: int | None = 3,
    shares: int | None = 4,
    collects: int | None = 5,
) -> WechatVideoDetail:
    return WechatVideoDetail(
        object_id="object-1",
        object_nonce_id=None,
        title="农村庭院设计",
        description=None,
        nickname="作者",
        username=None,
        create_time=None,
        like_count=likes,
        fav_count=collects,
        forward_count=shares,
        comment_count=comments,
        city=None,
        full_url=None,
        decode_key=None,
        cover_url=None,
        duration_ms=None,
        width=None,
        height=None,
    )


class _FakeClient:
    def __init__(
        self,
        *,
        detail: WechatVideoDetail | None = None,
        error: Exception | None = None,
        delay: float = 0,
    ) -> None:
        self.detail = detail or _detail()
        self.error = error
        self.delay = delay
        self.calls: list[tuple[str, str | None]] = []
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def wechat_video_detail(
        self, *, export_id: str, object_nonce_id: str | None = None
    ) -> WechatVideoDetail:
        with self._lock:
            self.calls.append((export_id, object_nonce_id))
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                time.sleep(self.delay)
            if self.error:
                raise self.error
            return self.detail
        finally:
            with self._lock:
                self.active -= 1


def _client(fake: _FakeClient) -> ViralSourceClient:
    return cast(ViralSourceClient, fake)


def test_second_and_concurrent_refresh_reuse_success_cache(tmp_path: Path) -> None:
    db_path = tmp_path / "viral.db"
    initialize_database(db_path).close()
    conn = _open(db_path)
    try:
        upsert_viral_videos(conn, [_video()])
        fake = _FakeClient(delay=0.05)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda _: refresh_viral_statistics(conn, _client(fake), ["video-1"]),
                    range(2),
                )
            )
        refresh_viral_statistics(conn, _client(fake), ["video-1"])

        assert len(fake.calls) == 1
        assert all(result[0].comments == 3 for result in results)
    finally:
        conn.close()


def test_success_cache_survives_reopen_and_private_metadata_stays_server_side(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "viral.db"
    initialize_database(db_path).close()
    first = _open(db_path)
    upsert_viral_videos(first, [_video()])
    refresh_viral_statistics(first, _client(_FakeClient()), ["video-1"])
    first.close()

    reopened = _open(db_path)
    try:
        fake = _FakeClient()
        videos = refresh_viral_statistics(reopened, _client(fake), ["video-1"])
        assert fake.calls == []
        assert "_statistics_checked_at" in videos[0].native
        assert "_statistics_checked_at" not in videos[0].to_client_dict()["native"]
    finally:
        reopened.close()


def test_refresh_limits_detail_calls_to_three_workers(tmp_path: Path) -> None:
    db_path = tmp_path / "viral.db"
    initialize_database(db_path).close()
    conn = _open(db_path)
    try:
        videos = [_video(f"video-{index}") for index in range(5)]
        upsert_viral_videos(conn, videos)
        fake = _FakeClient(delay=0.05)

        refreshed = refresh_viral_statistics(
            conn, _client(fake), [video.video_id for video in videos]
        )

        assert len(refreshed) == 5
        assert len(fake.calls) == 5
        assert fake.max_active == 3
    finally:
        conn.close()


def test_no_client_and_legacy_complete_statistics_reuse_database_values(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "viral.db"
    initialize_database(db_path).close()
    conn = _open(db_path)
    try:
        complete = replace(_video(), comments=1, shares=2, collects=3)
        upsert_viral_videos(conn, [complete])
        fake = _FakeClient()

        cached = refresh_viral_statistics(conn, _client(fake), ["video-1"])
        without_client = refresh_viral_statistics(conn, None, ["video-1"])

        assert fake.calls == []
        assert cached == without_client
        assert (cached[0].comments, cached[0].shares, cached[0].collects) == (1, 2, 3)
    finally:
        conn.close()


def test_search_upsert_preserves_only_statistics_metadata_and_replaces_export(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "viral.db"
    initialize_database(db_path).close()
    conn = _open(db_path)
    try:
        checked_at = datetime.now(UTC).isoformat()
        retry_at = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
        old = _video(
            native={
                "export_id": "export/expired",
                "object_nonce_id": "old-nonce",
                "_statistics_checked_at": checked_at,
                "_statistics_retry_at": retry_at,
            }
        )
        old_other_platform = _video(
            platform=PLATFORM_DOUYIN,
            native={"aweme_id": "old", "_statistics_checked_at": checked_at},
        )
        upsert_viral_videos(conn, [old, old_other_platform])
        statements: list[str] = []
        conn.set_trace_callback(statements.append)

        fresh = replace(
            old,
            native={"export_id": "export/fresh", "object_nonce_id": "fresh-nonce"},
        )
        fresh_other_platform = replace(old_other_platform, native={"aweme_id": "fresh"})
        upsert_viral_videos(conn, [fresh, fresh_other_platform])

        stored = get_viral_video(conn, platform=PLATFORM_WECHAT, video_id="video-1")
        assert stored is not None
        assert stored.native == {
            "export_id": "export/fresh",
            "object_nonce_id": "fresh-nonce",
            "_statistics_checked_at": checked_at,
            "_statistics_retry_at": retry_at,
        }
        metadata_reads = [
            statement
            for statement in statements
            if "SELECT platform, video_id, native_json FROM viral_videos" in statement
        ]
        assert len(metadata_reads) == 2
    finally:
        conn.close()


def test_real_zero_updates_and_partial_detail_does_not_overwrite_known_values(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "viral.db"
    initialize_database(db_path).close()
    conn = _open(db_path)
    try:
        upsert_viral_videos(
            conn,
            [
                replace(
                    _video(
                        native={
                            "export_id": "export/video-1",
                            "_statistics_checked_at": (
                                datetime.now(UTC) - timedelta(hours=25)
                            ).isoformat(),
                        }
                    ),
                    likes=9,
                    comments=8,
                    shares=7,
                    collects=6,
                )
            ],
        )
        fake = _FakeClient(detail=_detail(likes=0, comments=None, shares=0, collects=None))

        videos = refresh_viral_statistics(conn, _client(fake), ["video-1"])

        assert (videos[0].likes, videos[0].comments, videos[0].shares, videos[0].collects) == (
            0,
            8,
            0,
            6,
        )
        assert "_statistics_checked_at" in videos[0].native
        assert "_statistics_retry_at" not in videos[0].native
    finally:
        conn.close()


def test_error_sets_retry_cooldown_without_polluting_success_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "viral.db"
    initialize_database(db_path).close()
    conn = _open(db_path)
    try:
        upsert_viral_videos(conn, [_video()])
        fake = _FakeClient(error=ViralSourceError("sensitive upstream detail"))
        warnings: list[tuple[object, ...]] = []
        monkeypatch.setattr(
            "app.viral_statistics.logger.warning", lambda *args: warnings.append(args)
        )

        first = refresh_viral_statistics(conn, _client(fake), ["video-1"])
        second = refresh_viral_statistics(conn, _client(fake), ["video-1"])

        assert len(fake.calls) == 1
        assert first[0].comments is None
        assert second[0].comments is None
        assert "_statistics_retry_at" in second[0].native
        assert "_statistics_checked_at" not in second[0].native
        assert warnings[0][-1] == "ViralSourceError"
        assert "sensitive upstream detail" not in repr(warnings)
    finally:
        conn.close()


def test_detail_without_any_statistics_is_failure_not_success_cache(tmp_path: Path) -> None:
    db_path = tmp_path / "viral.db"
    initialize_database(db_path).close()
    conn = _open(db_path)
    try:
        upsert_viral_videos(conn, [_video()])
        fake = _FakeClient(detail=_detail(likes=None, comments=None, shares=None, collects=None))

        videos = refresh_viral_statistics(conn, _client(fake), ["video-1"])

        assert len(fake.calls) == 1
        assert "_statistics_retry_at" in videos[0].native
        assert "_statistics_checked_at" not in videos[0].native
    finally:
        conn.close()


def test_unknown_and_non_wechat_ids_do_not_call_detail_api(tmp_path: Path) -> None:
    db_path = tmp_path / "viral.db"
    initialize_database(db_path).close()
    conn = _open(db_path)
    try:
        upsert_viral_videos(conn, [_video(platform=PLATFORM_DOUYIN)])
        fake = _FakeClient()

        videos = refresh_viral_statistics(conn, _client(fake), ["missing", "video-1", "missing"])

        assert videos == []
        assert fake.calls == []
    finally:
        conn.close()
