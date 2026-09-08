"""爆款视频路由测试：列表聚合、缓存护栏、媒体动作与供应商红线."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.auth import Database, get_database
from app.db import connect_database, initialize_database
from app.db_portable import BusinessConnection
from app.main import app
from app.viral_routes import (
    VIRAL_LIST_CACHE_TTL,
    ViralSourceClient,
    _now,
    get_viral_source_client,
)


class StubViralClient(ViralSourceClient):
    """不发起网络请求的桩客户端."""

    def __init__(self) -> None:
        super().__init__(api_key="stub-key")
        self.douyin_calls: list[dict[str, Any]] = []
        self.wechat_calls: list[dict[str, Any]] = []

    def douyin_search(self, *, keyword, category="", sort_type="1", publish_time="7"):
        self.douyin_calls.append(
            {
                "keyword": keyword,
                "category": category,
                "sort_type": sort_type,
                "publish_time": publish_time,
            }
        )
        return [
            _video(
                platform="douyin",
                video_id=f"dy-{keyword}-{index}",
                category=category,
                audio_url=f"https://cdn.test/{keyword}-{index}.mp3",
            )
            for index in range(2)
        ]

    def wechat_search(self, *, keyword, category="", sort="hot", publish_time="week", pages=3):
        self.wechat_calls.append({"keyword": keyword, "category": category, "sort": sort})
        return [
            _video(
                platform="wechat_channels",
                video_id=f"wx-{keyword}-{index}",
                category=category,
            )
            for index in range(3)
        ]


_AUTH_HEADERS = {"X-Dev-User-Id": "employee_1"}


def _video(
    *,
    platform: str,
    video_id: str,
    category: str,
    audio_url: str | None = None,
) -> Any:
    from app.viral_tikhub import ViralVideo

    return ViralVideo(
        platform=platform,
        video_id=video_id,
        category=category,
        title=f"标题 {video_id} #标签一 #标签二",
        author="作者",
        author_avatar=None,
        verified=platform == "douyin",
        cover_url=f"https://cdn.test/{video_id}.jpg",
        duration_ms=11_000,
        likes=123,
        comments=4 if platform == "douyin" else None,
        shares=5 if platform == "douyin" else None,
        collects=6 if platform == "douyin" else None,
        published_at=1788602461,
        published_display="1天前" if platform == "wechat_channels" else None,
        like_display="1.2万" if platform == "wechat_channels" else None,
        tags=["标签一", "标签二"],
        play_url=f"https://cdn.test/{video_id}.mp4",
        audio_url=audio_url,
        native={"doc_id": video_id, "export_id": "export/e1"}
        if platform == "wechat_channels"
        else {"aweme_id": video_id, "_playback_version": 1},
    )


@pytest.fixture()
def client(tmp_path: Path) -> Iterator[tuple[TestClient, StubViralClient]]:
    database_path = tmp_path / "viral.db"
    with initialize_database(database_path) as conn:
        conn.execute(
            """
            INSERT INTO users (id, username, display_name, role)
            VALUES ('employee_1', 'employee_1', 'Employee One', 'employee')
            """
        )
        conn.execute(
            "INSERT INTO users (id, username, display_name, role) "
            "VALUES ('auditor_1', 'auditor_1', 'Auditor One', 'auditor')"
        )
        conn.execute(
            "INSERT INTO users (id, username, display_name, role) "
            "VALUES ('employee_2', 'employee_2', 'Employee Two', 'employee')"
        )

    def database_override() -> Iterator[BusinessConnection]:
        conn = BusinessConnection.sqlite(connect_database(database_path))
        try:
            yield conn
        finally:
            conn.close()

    stub = StubViralClient()

    def viral_client_override(conn: Database) -> ViralSourceClient:
        return stub

    app.dependency_overrides[get_database] = database_override
    app.dependency_overrides[get_viral_source_client] = viral_client_override
    try:
        with pytest.MonkeyPatch.context() as mp:
            # 后台封面落存储线程按环境变量自开连接，指向同一测试库。
            mp.setenv("VIDEO_REPLICA_DB_PATH", str(database_path))
            yield TestClient(app), stub
    finally:
        app.dependency_overrides.clear()


def test_list_douyin_videos_aggregates_categories(
    client: tuple[TestClient, StubViralClient],
) -> None:
    http, stub = client
    response = http.get("/api/viral/videos", params={"platform": "douyin"}, headers=_AUTH_HEADERS)
    assert response.status_code == 200
    payload = response.json()
    assert payload["platform"] == "douyin"
    assert payload["categories"] == ["建房预算", "户型设计", "施工避坑", "庭院案例"]
    # 每个分类 2 条，共 8 条（不同分类 video_id 不同，无去重合并）。
    assert len(payload["items"]) == 8
    assert stub.douyin_calls[0]["sort_type"] == "1"
    assert stub.douyin_calls[0]["publish_time"] == "7"
    first = payload["items"][0]
    assert first["platform"] == "douyin"
    assert first["tags"] == ["标签一", "标签二"]
    assert first["hasPlayableAudio"] is True
    # 供应商红线：响应正文不得出现数据源供应商名称。
    assert "tikhub" not in response.text.lower()


def test_list_videos_uses_cache_within_ttl(client: tuple[TestClient, StubViralClient]) -> None:
    http, stub = client
    first = http.get("/api/viral/videos", params={"platform": "douyin"}, headers=_AUTH_HEADERS)
    assert first.status_code == 200
    calls_after_first = len(stub.douyin_calls)
    second = http.get("/api/viral/videos", params={"platform": "douyin"}, headers=_AUTH_HEADERS)
    assert second.status_code == 200
    assert len(stub.douyin_calls) == calls_after_first


def test_list_videos_refetches_after_ttl(client: tuple[TestClient, StubViralClient]) -> None:
    http, stub = client
    assert (
        http.get(
            "/api/viral/videos", params={"platform": "douyin"}, headers=_AUTH_HEADERS
        ).status_code
        == 200
    )
    calls_after_first = len(stub.douyin_calls)
    # 把拉取状态拨回到 TTL 之外（库内条目保留，回源按视频 ID 去重刷新）。
    stale = (_now() - VIRAL_LIST_CACHE_TTL - timedelta(minutes=1)).isoformat()
    from app.viral_routes import _open_worker_connection

    db_conn, close = _open_worker_connection()
    try:
        db_conn.execute("UPDATE viral_fetch_state SET fetched_at = %s", (stale,))
        db_conn.commit()
    finally:
        close()
    assert (
        http.get(
            "/api/viral/videos", params={"platform": "douyin"}, headers=_AUTH_HEADERS
        ).status_code
        == 200
    )
    assert len(stub.douyin_calls) > calls_after_first


def test_list_wechat_videos_and_latest_sort(client: tuple[TestClient, StubViralClient]) -> None:
    http, stub = client
    response = http.get(
        "/api/viral/videos",
        params={"platform": "wechat_channels", "sort": "latest"},
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 200
    assert len(response.json()["items"]) == 12
    assert stub.wechat_calls[0]["sort"] == "latest"
    latest_item = response.json()["items"][0]
    assert latest_item["likeDisplay"] == "1.2万"


def test_list_videos_rejects_invalid_platform(client: tuple[TestClient, StubViralClient]) -> None:
    http, _ = client
    response = http.get("/api/viral/videos", params={"platform": "kuaishou"}, headers=_AUTH_HEADERS)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "VIRAL_PLATFORM_INVALID"


def test_media_returns_url_and_red_line_holds(
    client: tuple[TestClient, StubViralClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    http, _ = client

    class StubPipeline:
        def __init__(self, *, client, storage) -> None:
            pass

        def fetch(self, video, *, prefer=None):
            from app.viral_media import ViralMediaResult

            return ViralMediaResult(
                kind="audio",
                storage_uri=f"test://viral/douyin/{video.video_id}.mp3",
                url=f"https://storage.test/viral/douyin/{video.video_id}.mp3",
                size=1024,
                content_type="audio/mpeg",
                cache_hit=False,
            )

    import app.viral_routes as routes

    monkeypatch.setattr(routes, "ViralMediaPipeline", StubPipeline)
    monkeypatch.setattr(routes, "get_media_storage", lambda conn: object())
    response = http.post(
        "/api/viral/videos/media",
        json={"platform": "douyin", "videoId": "dy-自建房预算-0"},
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "audio"
    assert payload["contentType"] == "audio/mpeg"
    assert payload["url"].startswith("https://storage.test/")
    assert "tikhub" not in response.text.lower()


def test_media_external_work_has_no_business_transaction_and_session_switch_blocks_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from app.viral_media import ViralMediaResult
    from app.viral_routes import ViralMediaRequest, fetch_viral_video_media

    class FakeConn:
        def commit(self) -> None:
            pass

    class SwitchingDb:
        active = 0
        actors = iter((SimpleNamespace(id="user-1"),) * 2 + (SimpleNamespace(id="user-2"),))

        @contextmanager
        def write(self):
            self.active += 1
            try:
                yield FakeConn(), next(self.actors)
            finally:
                self.active -= 1

    db = SwitchingDb()
    video = _video(
        platform="douyin",
        video_id="video-session-switch",
        category="建房预算",
        audio_url="https://cdn.test/audio.mp3",
    )

    class Pipeline:
        detail = None

        def __init__(self, **_kwargs):
            pass

        def fetch(self, _video, *, prefer=None):
            assert db.active == 0
            return ViralMediaResult(
                "audio", "test://cached", "https://storage.test/a.mp3", 12, "audio/mpeg", False
            )

    monkeypatch.setattr("app.viral_routes.require_not_auditor", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.viral_routes.get_viral_video", lambda *args, **kwargs: video)
    monkeypatch.setattr("app.viral_routes.claim_viral_work", lambda *args, **kwargs: "token")
    monkeypatch.setattr("app.viral_routes.get_media_storage", lambda _conn: object())
    monkeypatch.setattr("app.viral_routes.ViralMediaPipeline", Pipeline)
    monkeypatch.setattr(
        "app.viral_routes.update_viral_statistics",
        lambda *args, **kwargs: pytest.fail("旧会话不得写统计"),
    )

    with pytest.raises(Exception) as error:
        fetch_viral_video_media(
            ViralMediaRequest(platform="douyin", videoId=video.video_id, kind="audio"),
            db,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
        )
    assert getattr(error.value, "status_code", None) == 409


def test_statistics_provider_work_runs_between_short_business_transactions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from app.viral_routes import ViralStatisticsRequest, fetch_viral_video_statistics

    class FakeConn:
        def commit(self) -> None:
            pass

    class FakeDb:
        active = 0

        @contextmanager
        def write(self):
            self.active += 1
            try:
                yield FakeConn(), SimpleNamespace(id="user-1")
            finally:
                self.active -= 1

    db = FakeDb()
    video = _video(platform="wechat_channels", video_id="stats-1", category="庭院案例")
    monkeypatch.setattr("app.viral_routes.require_not_auditor", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "app.viral_routes.plan_viral_statistics_refresh",
        lambda *_args: ([video], [video], []),
    )
    monkeypatch.setattr("app.viral_routes.claim_viral_work", lambda *_args: "token")
    monkeypatch.setattr("app.viral_routes.viral_work_is_owned", lambda *args, **kwargs: True)
    monkeypatch.setattr("app.viral_routes.release_viral_work", lambda *args, **kwargs: True)

    def fetch_without_database(_client, _pending):
        assert db.active == 0
        return {}

    monkeypatch.setattr(
        "app.viral_routes.fetch_viral_statistics_without_database", fetch_without_database
    )
    monkeypatch.setattr(
        "app.viral_routes.apply_viral_statistics_refresh",
        lambda *_args: [video],
    )
    response = fetch_viral_video_statistics(
        ViralStatisticsRequest(videoIds=[video.video_id]),
        db,  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
    )
    assert response.items[0].videoId == video.video_id


def test_media_storage_failure_releases_durable_claim_without_masking_error(
    client: tuple[TestClient, StubViralClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    http, _ = client
    assert http.get("/api/viral/videos?platform=douyin", headers=_AUTH_HEADERS).status_code == 200
    video_id = "dy-自建房预算-0"

    class FailingStorage:
        def head_object(self, _key):
            raise RuntimeError("storage unavailable")

    monkeypatch.setattr("app.viral_routes.get_media_storage", lambda _conn: FailingStorage())
    with pytest.raises(RuntimeError, match="storage unavailable"):
        http.post(
            "/api/viral/videos/media",
            json={"platform": "douyin", "videoId": video_id, "kind": "video"},
            headers=_AUTH_HEADERS,
        )
    with BusinessConnection.sqlite(
        connect_database(Path(os.environ["VIDEO_REPLICA_DB_PATH"]))
    ) as conn:
        claim = conn.execute(
            "SELECT 1 FROM viral_work_claims WHERE scope = %s",
            (f"viral:media:douyin:{video_id}:video",),
        ).fetchone()
    assert claim is None


def test_media_unknown_video_returns_404(client: tuple[TestClient, StubViralClient]) -> None:
    http, _ = client
    response = http.post(
        "/api/viral/videos/media",
        json={"platform": "douyin", "videoId": "missing-id"},
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "VIRAL_VIDEO_NOT_FOUND"


class _StubLocalStorage:
    """最小本地存储桩：head/get 即可驱动签名文件路由."""

    def __init__(self, objects: dict[str, tuple[bytes, str]]) -> None:
        self.objects = objects

    def head_object(self, key):
        from types import SimpleNamespace

        entry = self.objects.get(key)
        if entry is None:
            return None
        content, content_type = entry
        return SimpleNamespace(
            key=key,
            uri=f"local://local-private/{key}",
            size=len(content),
            content_type=content_type,
            sha256="sha-" + str(len(content)),
        )

    def get_object(self, key):
        return self.objects[key][0]


def test_local_media_url_converts_to_signed_file_route(
    client: tuple[TestClient, StubViralClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    http, _ = client

    class StubPipeline:
        def __init__(self, *, client, storage) -> None:
            pass

        def fetch(self, video, *, prefer=None):
            from app.viral_media import ViralMediaResult

            return ViralMediaResult(
                kind="audio",
                storage_uri=f"local://local-private/viral/douyin/{video.video_id}.mp3",
                url=f"local://local-private/viral/douyin/{video.video_id}.mp3?method=GET&expires=1",
                size=16,
                content_type="audio/mpeg",
                cache_hit=False,
            )

    import app.viral_routes as routes

    monkeypatch.setattr(
        routes,
        "settings_encryption_key",
        lambda: "MTIzNDU2Nzg5MGFiY2RlZjAxMjM0NTY3ODkwYWJjZGVm",
    )
    video_id = "dy-自建房预算-0"
    storage_key = f"viral/douyin/{video_id}.mp3"
    monkeypatch.setattr(routes, "ViralMediaPipeline", StubPipeline)
    monkeypatch.setattr(
        routes,
        "get_media_storage",
        lambda conn: _StubLocalStorage({storage_key: (b"ID3-fake-audio", "audio/mpeg")}),
    )
    response = http.post(
        "/api/viral/videos/media",
        json={"platform": "douyin", "videoId": video_id},
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 200
    url = response.json()["url"]
    assert "/api/viral/videos/media/file?key=viral/douyin/" in url
    assert url.startswith("http://")  # 绝对地址：跨源前端可直接使用
    # 签名 URL 自带授权，浏览器直接 GET 可取回字节。
    file_response = http.get(url)
    assert file_response.status_code == 200
    assert file_response.content == b"ID3-fake-audio"
    assert file_response.headers["content-type"] == "audio/mpeg"
    # 篡改签名被拒绝。
    tampered = url.replace("sig=", "sig=x")
    assert http.get(tampered).status_code == 403
    # 非 viral 前缀的对象 key 被拒绝。
    assert (
        http.get(
            "/api/viral/videos/media/file?key=projects%2Fx.bin&expires=9999999999&user_id=admin1&sig=abc"
        ).status_code
        == 403
    )


class _CoverStorage(_StubLocalStorage):
    """可写的存储桩：验证封面落存储与命中."""

    def __init__(self) -> None:
        super().__init__({})
        self.put_calls: list[str] = []

    def put_object(self, key, content, *, content_type):
        from types import SimpleNamespace

        self.objects[key] = (content, content_type)
        self.put_calls.append(key)
        return SimpleNamespace(
            key=key,
            uri=f"local://local-private/{key}",
            size=len(content),
            content_type=content_type,
            sha256="sha-" + str(len(content)),
        )


class _OkFetcher:
    def fetch(self, url: str) -> bytes:
        return b"fake-cover-bytes"


def test_list_enriches_covers_into_storage(
    client: tuple[TestClient, StubViralClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.viral_routes as routes

    storage = _CoverStorage()
    monkeypatch.setattr(routes, "get_media_storage", lambda conn: storage)
    monkeypatch.setattr(routes, "UrlFetcher", lambda *a, **kw: _OkFetcher())
    http = client[0]
    result = http.get("/api/viral/videos", params={"platform": "douyin"}, headers=_AUTH_HEADERS)
    assert result.status_code == 200
    items = result.json()["items"]
    assert items, "列表应有条目"

    # 后台落存储是异步的：轮询直到封面副本入库并回写 cover_key。
    deadline = time.time() + 10
    refreshed = items[0]
    while time.time() < deadline:
        again = http.get("/api/viral/videos", params={"platform": "douyin"}, headers=_AUTH_HEADERS)
        assert again.status_code == 200
        refreshed = again.json()["items"][0]
        if "/api/viral/covers/douyin/" in refreshed["coverUrl"]:
            break
        time.sleep(0.05)

    assert storage.put_calls, "后台封面落存储应发生"
    assert "/api/viral/covers/douyin/" in refreshed["coverUrl"], (
        "封面副本入库后列表应换成自有稳定地址"
    )
    # 稳定路由直接可取，无需登录。
    cover = http.get(refreshed["coverUrl"])
    assert cover.status_code == 200
    assert cover.content == b"fake-cover-bytes"
    assert cover.headers["content-type"].startswith("image/")

    # 命中存储副本后不再重复下载：清空记录，再次请求列表应零新增。
    storage.put_calls.clear()
    deadline = time.time() + 2
    while time.time() < deadline and not storage.put_calls:
        time.sleep(0.05)
    assert not storage.put_calls, "已有副本的视频不应重复下载"


def test_cover_route_rejects_bad_ids(
    client: tuple[TestClient, StubViralClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    http, _ = client
    monkeypatch.setattr("app.viral_routes.get_media_storage", lambda conn: _CoverStorage())
    assert http.get("/api/viral/covers/kuaishou/x").status_code == 404
    assert http.get("/api/viral/covers/douyin/..%2Fsecret").status_code == 404
    assert http.get("/api/viral/covers/douyin/missing-cover").status_code == 404


def test_cached_list_reports_persisted_fetch_time(client):
    http, stub = client
    first = http.get("/api/viral/videos?platform=douyin", headers=_AUTH_HEADERS)
    second = http.get("/api/viral/videos?platform=douyin", headers=_AUTH_HEADERS)
    assert second.json()["fetchedAt"] == first.json()["fetchedAt"]
    assert second.json()["source"] == "database"
    assert second.json()["stale"] is False
    assert len(stub.douyin_calls) == 4


def test_concurrent_cold_lists_share_one_refresh(client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    http, stub = client
    original = stub.douyin_search
    barrier = Barrier(2)

    def slow_search(**kwargs):
        time.sleep(0.05)
        return original(**kwargs)

    monkeypatch.setattr(stub, "douyin_search", slow_search)

    def request():
        barrier.wait(timeout=5)
        return http.get("/api/viral/videos?platform=douyin", headers=_AUTH_HEADERS)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: request(), range(2)))
    assert all(result.status_code == 200 for result in results)
    assert len(stub.douyin_calls) == 4


def test_parallel_category_results_are_persisted_in_config_order(client, monkeypatch):
    http, stub = client

    def shared_video(*, keyword, category="", **kwargs):
        # 首分类最慢，强制 future 完成顺序与配置顺序相反。
        if category == "建房预算":
            time.sleep(0.08)
        elif category == "户型设计":
            time.sleep(0.04)
        stub.douyin_calls.append({"keyword": keyword, "category": category, **kwargs})
        return [_video(platform="douyin", video_id="shared", category=category)]

    monkeypatch.setattr(stub, "douyin_search", shared_video)

    response = http.get("/api/viral/videos?platform=douyin", headers=_AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json()["items"][0]["category"] == "庭院案例"


def test_partial_category_failure_cools_down_then_retries_only_failed_category(client, monkeypatch):
    from app.viral_routes import _open_worker_connection
    from app.viral_tikhub import ViralSourceError

    http, stub = client
    original = stub.douyin_search
    failed_once = False

    def sometimes_fails(**kwargs):
        nonlocal failed_once
        if kwargs["category"] == "户型设计" and not failed_once:
            failed_once = True
            stub.douyin_calls.append(dict(kwargs))
            raise ViralSourceError("暂时失败")
        return original(**kwargs)

    monkeypatch.setattr(stub, "douyin_search", sometimes_fails)

    first = http.get("/api/viral/videos?platform=douyin", headers=_AUTH_HEADERS)
    assert first.status_code == 200
    assert len(first.json()["items"]) == 6
    assert len(stub.douyin_calls) == 4

    second = http.get("/api/viral/videos?platform=douyin", headers=_AUTH_HEADERS)
    assert second.status_code == 200
    assert len(stub.douyin_calls) == 4

    stale = (_now() - timedelta(minutes=2)).isoformat()
    conn, close = _open_worker_connection()
    try:
        conn.execute(
            """
            UPDATE viral_fetch_state SET fetched_at = %s
            WHERE platform = %s AND sort = %s
            """,
            (stale, "douyin", "hot:retry:户型设计"),
        )
        conn.commit()
    finally:
        close()

    third = http.get("/api/viral/videos?platform=douyin", headers=_AUTH_HEADERS)
    assert third.status_code == 200
    assert len(third.json()["items"]) == 8
    assert len(stub.douyin_calls) == 5
    assert stub.douyin_calls[-1]["category"] == "户型设计"


@pytest.mark.parametrize("error_type", [ValueError, TypeError])
def test_malformed_category_preserves_other_results(client, monkeypatch, error_type):
    http, stub = client
    original = stub.douyin_search

    def malformed_category(**kwargs):
        if kwargs["category"] == "户型设计":
            stub.douyin_calls.append(dict(kwargs))
            raise error_type("untrusted numeric field")
        return original(**kwargs)

    monkeypatch.setattr(stub, "douyin_search", malformed_category)

    first = http.get("/api/viral/videos?platform=douyin", headers=_AUTH_HEADERS)
    second = http.get("/api/viral/videos?platform=douyin", headers=_AUTH_HEADERS)

    assert first.status_code == 200
    assert len(first.json()["items"]) == 6
    assert second.status_code == 200
    assert len(stub.douyin_calls) == 4
    assert "untrusted" not in first.text.lower()


def test_refresh_failure_returns_database_without_advancing_timestamp(client, monkeypatch):
    from app.viral_routes import _open_worker_connection
    from app.viral_tikhub import ViralSourceError

    http, stub = client
    first = http.get("/api/viral/videos?platform=douyin", headers=_AUTH_HEADERS)
    stale = (_now() - VIRAL_LIST_CACHE_TTL - timedelta(minutes=1)).isoformat()
    conn, close = _open_worker_connection()
    try:
        conn.execute("UPDATE viral_fetch_state SET fetched_at = %s", (stale,))
        conn.commit()
    finally:
        close()

    def failed(**kwargs):
        raise ViralSourceError("数据源暂不可用")

    monkeypatch.setattr(stub, "douyin_search", failed)
    result = http.get("/api/viral/videos?platform=douyin", headers=_AUTH_HEADERS)
    assert result.status_code == 200
    assert len(result.json()["items"]) == len(first.json()["items"])
    assert result.json()["fetchedAt"] == stale
    assert result.json()["stale"] is True


def test_public_cover_route_does_not_fetch_or_write_missing_copy(client, monkeypatch):
    from app.viral_routes import _open_worker_connection
    from app.viral_store import upsert_viral_videos

    storage = _CoverStorage()
    monkeypatch.setattr("app.viral_routes.get_media_storage", lambda conn: storage)
    monkeypatch.setattr("app.viral_routes.UrlFetcher", lambda *a, **kw: _OkFetcher())
    conn, close = _open_worker_connection()
    try:
        upsert_viral_videos(
            conn, [_video(platform="douyin", video_id="recover", category="建房预算")]
        )
    finally:
        close()
    result = client[0].get("/api/viral/covers/douyin/recover")
    assert result.status_code == 404
    assert storage.put_calls == []


def test_auditor_list_reads_cache_without_triggering_paid_refresh(client):
    http, stub = client
    seeded = http.get("/api/viral/videos?platform=douyin", headers=_AUTH_HEADERS)
    assert seeded.status_code == 200
    calls = len(stub.douyin_calls)

    response = http.get(
        "/api/viral/videos?platform=douyin",
        headers={"X-Dev-User-Id": "auditor_1"},
    )

    assert response.status_code == 200
    assert len(response.json()["items"]) == len(seeded.json()["items"])
    assert len(stub.douyin_calls) == calls


def test_auditor_cannot_trigger_statistics_or_media_writes(client):
    http, _ = client
    headers = {"X-Dev-User-Id": "auditor_1"}
    statistics = http.post(
        "/api/viral/videos/statistics",
        json={"videoIds": ["video-1"]},
        headers=headers,
    )
    media = http.post(
        "/api/viral/videos/media",
        json={"platform": "douyin", "videoId": "video-1"},
        headers=headers,
    )

    assert statistics.status_code == 403
    assert media.status_code == 403


def test_import_viral_media_creates_owner_project_and_is_idempotent(client, monkeypatch):
    http, _ = client
    assert http.get("/api/viral/videos?platform=douyin", headers=_AUTH_HEADERS).status_code == 200
    video_id = "dy-自建房预算-0"
    key = f"viral/douyin/{video_id}.browser.mp4"
    storage = _CoverStorage()
    storage.put_object(key, b"\x00\x00\x00 ftypisom", content_type="video/mp4")

    class StubPipeline:
        calls = 0

        def __init__(self, *, client, storage) -> None:
            pass

        def fetch(self, video, *, prefer=None):
            from app.viral_media import ViralMediaResult

            type(self).calls += 1
            return ViralMediaResult(
                kind="video",
                storage_uri=f"local://local-private/{key}",
                url="https://storage.test/audio",
                size=9,
                content_type="video/mp4",
                cache_hit=True,
            )

    monkeypatch.setattr("app.viral_routes.get_media_storage", lambda conn: storage)
    monkeypatch.setattr("app.viral_routes.ViralMediaPipeline", StubPipeline)
    url = f"/api/viral/videos/douyin/{video_id}/import"
    first = http.post(url, json={"kind": "video"}, headers=_AUTH_HEADERS)
    second = http.post(url, json={"kind": "video"}, headers=_AUTH_HEADERS)

    assert first.status_code == 200, first.text
    assert second.json() == first.json()
    assert StubPipeline.calls == 1
    project = http.get(f"/api/projects/{first.json()['project_id']}", headers=_AUTH_HEADERS)
    assert project.status_code == 200, project.text
    assert project.json()["reference_asset_id"] == first.json()["asset_id"]
    queued = http.post(
        f"/api/projects/{first.json()['project_id']}/analysis-tasks",
        json={"asset_id": first.json()["asset_id"], "duration_seconds": 10},
        headers=_AUTH_HEADERS,
    )
    assert queued.status_code == 202, queued.text
    conn, close = __import__(
        "app.viral_routes", fromlist=["_open_worker_connection"]
    )._open_worker_connection()
    try:
        row = conn.execute(
            "SELECT project_id, created_by_user_id FROM assets WHERE id = %s",
            (first.json()["asset_id"],),
        ).fetchone()
        assert tuple(row) == (first.json()["project_id"], "employee_1")
        project = conn.execute(
            "SELECT owner_user_id, status FROM projects WHERE id = %s",
            (first.json()["project_id"],),
        ).fetchone()
        assert tuple(project) == ("employee_1", "ACTIVE")
    finally:
        close()


def test_import_viral_media_is_isolated_between_users(client, monkeypatch):
    http, _ = client
    assert http.get("/api/viral/videos?platform=douyin", headers=_AUTH_HEADERS).status_code == 200
    video_id = "dy-自建房预算-0"
    key = f"viral/douyin/{video_id}.mp3"
    storage = _CoverStorage()
    storage.put_object(key, b"ID3-audio", content_type="audio/mpeg")

    class StubPipeline:
        def __init__(self, *, client, storage) -> None:
            pass

        def fetch(self, video, *, prefer=None):
            from app.viral_media import ViralMediaResult

            return ViralMediaResult(
                kind="audio",
                storage_uri=f"local://local-private/{key}",
                url="https://storage.test/audio",
                size=9,
                content_type="audio/mpeg",
                cache_hit=True,
            )

    monkeypatch.setattr("app.viral_routes.get_media_storage", lambda conn: storage)
    monkeypatch.setattr("app.viral_routes.ViralMediaPipeline", StubPipeline)
    url = f"/api/viral/videos/douyin/{video_id}/import"
    first = http.post(url, json={"kind": "audio"}, headers=_AUTH_HEADERS)
    second = http.post(
        url,
        json={"kind": "audio"},
        headers={"X-Dev-User-Id": "employee_2"},
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["project_id"] != first.json()["project_id"]
    assert second.json()["asset_id"] != first.json()["asset_id"]
    conn, close = __import__(
        "app.viral_routes", fromlist=["_open_worker_connection"]
    )._open_worker_connection()
    try:
        owner = conn.execute(
            "SELECT owner_user_id FROM projects WHERE id = %s",
            (second.json()["project_id"],),
        ).fetchone()
        assert owner["owner_user_id"] == "employee_2"
    finally:
        close()


def test_cover_route_accepts_persisted_wechat_base64_id_with_slash(client, monkeypatch):
    from urllib.parse import quote

    from app.viral_media import viral_cover_key
    from app.viral_routes import _open_worker_connection
    from app.viral_store import upsert_viral_videos

    video_id = "finderobjv0abc/def+ghi="
    storage = _CoverStorage()
    key = viral_cover_key("wechat_channels", video_id)
    storage.put_object(key, b"jpeg-cover", content_type="image/jpeg")
    monkeypatch.setattr("app.viral_routes.get_media_storage", lambda conn: storage)
    conn, close = _open_worker_connection()
    try:
        upsert_viral_videos(
            conn, [_video(platform="wechat_channels", video_id=video_id, category="建房预算")]
        )
    finally:
        close()
    response = client[0].get("/api/viral/covers/wechat_channels/" + quote(video_id, safe=""))
    assert response.status_code == 200
    assert response.content == b"jpeg-cover"
    assert client[0].get("/api/viral/covers/wechat_channels/finderobj/../secret").status_code == 404


def test_cover_route_accepts_real_wechat_id_with_consecutive_slashes(client, monkeypatch):
    from urllib.parse import quote

    from app.viral_media import viral_cover_key
    from app.viral_routes import _open_worker_connection
    from app.viral_store import upsert_viral_videos

    video_id = "finderobjv0POr//CKfOesFBgIVVkCT4LG1YHnvIIJ9FmgsD4gFi9o="
    storage = _CoverStorage()
    key = viral_cover_key("wechat_channels", video_id)
    storage.put_object(key, b"jpeg-cover", content_type="image/jpeg")
    monkeypatch.setattr("app.viral_routes.get_media_storage", lambda conn: storage)
    conn, close = _open_worker_connection()
    try:
        upsert_viral_videos(
            conn, [_video(platform="wechat_channels", video_id=video_id, category="建房预算")]
        )
    finally:
        close()

    response = client[0].get("/api/viral/covers/wechat_channels/" + quote(video_id, safe=""))

    assert response.status_code == 200
    assert response.content == b"jpeg-cover"
    assert "//" not in key


def test_list_remains_available_from_database_without_source_configuration(client):
    http, stub = client
    first = http.get("/api/viral/videos?platform=douyin", headers=_AUTH_HEADERS)
    app.dependency_overrides[get_viral_source_client] = lambda: None
    cached = http.get("/api/viral/videos?platform=douyin", headers=_AUTH_HEADERS)
    assert cached.status_code == 200
    assert cached.json()["items"] == first.json()["items"]
    assert len(stub.douyin_calls) == 4


def test_media_statistics_are_persisted_and_returned_to_client(client, monkeypatch):
    from types import SimpleNamespace

    from app.viral_media import ViralMediaResult

    class StatsPipeline:
        detail = SimpleNamespace(like_count=42, comment_count=0, forward_count=8, fav_count=9)

        def __init__(self, **kwargs):
            pass

        def fetch(self, video, *, prefer=None):
            return ViralMediaResult(
                "video", "test://cached", "https://storage.test/v.mp4", 12, "video/mp4", False
            )

    monkeypatch.setattr("app.viral_routes.ViralMediaPipeline", StatsPipeline)
    monkeypatch.setattr("app.viral_routes.get_media_storage", lambda conn: object())
    http, stub = client
    initial = http.get("/api/viral/videos?platform=wechat_channels", headers=_AUTH_HEADERS)
    video_id = initial.json()["items"][0]["videoId"]
    media = http.post(
        "/api/viral/videos/media",
        headers=_AUTH_HEADERS,
        json={"platform": "wechat_channels", "videoId": video_id, "kind": "video"},
    )
    assert media.status_code == 200
    updated = media.json()["video"]
    assert (updated["likes"], updated["comments"], updated["shares"], updated["collects"]) == (
        42,
        0,
        8,
        9,
    )
    assert updated["likeDisplay"] is None
    calls = len(stub.wechat_calls)
    again = http.get("/api/viral/videos?platform=wechat_channels", headers=_AUTH_HEADERS)
    assert next(v for v in again.json()["items"] if v["videoId"] == video_id)["comments"] == 0
    assert len(stub.wechat_calls) == calls


def test_media_failure_still_persists_detail_statistics(client, monkeypatch):
    from types import SimpleNamespace

    from app.viral_media import ViralMediaError

    class FailingCdnPipeline:
        def __init__(self, **kwargs):
            self.detail = None

        def fetch(self, video, *, prefer=None):
            self.detail = SimpleNamespace(
                like_count=51, comment_count=2, forward_count=3, fav_count=4
            )
            raise ViralMediaError("该视频素材暂时无法获取，请稍后重试")

    monkeypatch.setattr("app.viral_routes.ViralMediaPipeline", FailingCdnPipeline)
    monkeypatch.setattr("app.viral_routes.get_media_storage", lambda conn: object())
    http, _stub = client
    initial = http.get("/api/viral/videos?platform=wechat_channels", headers=_AUTH_HEADERS)
    video_id = initial.json()["items"][0]["videoId"]

    media = http.post(
        "/api/viral/videos/media",
        headers=_AUTH_HEADERS,
        json={"platform": "wechat_channels", "videoId": video_id, "kind": "video"},
    )
    refreshed = http.get(
        "/api/viral/videos?platform=wechat_channels", headers=_AUTH_HEADERS
    ).json()["items"]
    stored = next(item for item in refreshed if item["videoId"] == video_id)

    assert media.status_code == 502
    assert (stored["likes"], stored["comments"], stored["shares"], stored["collects"]) == (
        51,
        2,
        3,
        4,
    )


def test_concurrent_legacy_douyin_media_repairs_source_once(client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from dataclasses import replace
    from threading import Barrier
    from types import SimpleNamespace

    from app.viral_media import ViralMediaResult
    from app.viral_routes import _open_worker_connection
    from app.viral_store import upsert_viral_videos

    class CachedPipeline:
        detail = None

        def __init__(self, **kwargs):
            pass

        def fetch(self, video, *, prefer=None):
            return ViralMediaResult(
                "video", "test://cached", "https://storage.test/v.mp4", 12, "video/mp4", True
            )

    http, stub = client
    conn, close = _open_worker_connection()
    try:
        upsert_viral_videos(
            conn,
            [
                replace(
                    _video(platform="douyin", video_id="legacy", category="建房预算"),
                    native={"aweme_id": "legacy"},
                )
            ],
        )
    finally:
        close()

    def slow_repair(**kwargs):
        stub.douyin_calls.append(dict(kwargs))
        time.sleep(0.08)
        return [
            replace(
                _video(platform="douyin", video_id="legacy", category="建房预算"),
                native={"aweme_id": "legacy", "_playback_version": 1},
            )
        ]

    monkeypatch.setattr(stub, "douyin_search", slow_repair)
    monkeypatch.setattr("app.viral_routes.ViralMediaPipeline", CachedPipeline)
    monkeypatch.setattr(
        "app.viral_routes.get_media_storage",
        lambda conn: SimpleNamespace(head_object=lambda key: None),
    )
    barrier = Barrier(2)

    def request():
        barrier.wait(timeout=5)
        return http.post(
            "/api/viral/videos/media",
            headers=_AUTH_HEADERS,
            json={"platform": "douyin", "videoId": "legacy", "kind": "video"},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: request(), range(2)))

    assert all(response.status_code == 200 for response in responses)
    assert len(stub.douyin_calls) == 1


def test_legacy_douyin_repair_requires_target_and_cools_down_failure(client, monkeypatch):
    from dataclasses import replace
    from types import SimpleNamespace

    from app.viral_routes import _open_worker_connection
    from app.viral_store import upsert_viral_videos

    http, stub = client
    conn, close = _open_worker_connection()
    try:
        upsert_viral_videos(
            conn,
            [
                replace(
                    _video(platform="douyin", video_id="legacy-missing", category="建房预算"),
                    native={"aweme_id": "legacy-missing"},
                )
            ],
        )
    finally:
        close()

    def misses_target(**kwargs):
        stub.douyin_calls.append(dict(kwargs))
        return [_video(platform="douyin", video_id="other", category="建房预算")]

    monkeypatch.setattr(stub, "douyin_search", misses_target)
    monkeypatch.setattr(
        "app.viral_routes.get_media_storage",
        lambda conn: SimpleNamespace(head_object=lambda key: None),
    )
    monkeypatch.setattr(
        "app.viral_routes.ViralMediaPipeline",
        lambda **kwargs: pytest.fail("旧播放源不得进入媒体管线"),
    )

    responses = [
        http.post(
            "/api/viral/videos/media",
            headers=_AUTH_HEADERS,
            json={"platform": "douyin", "videoId": "legacy-missing", "kind": "video"},
        )
        for _ in range(2)
    ]

    assert [response.status_code for response in responses] == [502, 502]
    assert len(stub.douyin_calls) == 1
    assert all("tikhub" not in response.text.lower() for response in responses)


def test_legacy_douyin_audio_does_not_require_source_repair(client, monkeypatch):
    from dataclasses import replace

    from app.viral_media import ViralMediaResult
    from app.viral_routes import _open_worker_connection
    from app.viral_store import upsert_viral_videos

    class AudioPipeline:
        detail = None

        def __init__(self, **kwargs):
            pass

        def fetch(self, video, *, prefer=None):
            return ViralMediaResult(
                "audio", "test://cached", "https://storage.test/a.mp3", 12, "audio/mpeg", True
            )

    http, _stub = client
    conn, close = _open_worker_connection()
    try:
        upsert_viral_videos(
            conn,
            [
                replace(
                    _video(platform="douyin", video_id="legacy-audio", category="建房预算"),
                    native={"aweme_id": "legacy-audio"},
                    audio_url="https://cdn.test/legacy-audio.mp3",
                )
            ],
        )
    finally:
        close()

    app.dependency_overrides[get_viral_source_client] = lambda: None
    monkeypatch.setattr("app.viral_routes.ViralMediaPipeline", AudioPipeline)
    monkeypatch.setattr("app.viral_routes.get_media_storage", lambda conn: object())

    response = http.post(
        "/api/viral/videos/media",
        headers=_AUTH_HEADERS,
        json={"platform": "douyin", "videoId": "legacy-audio", "kind": "audio"},
    )

    assert response.status_code == 200
    assert response.json()["kind"] == "audio"


def test_local_media_url_decodes_storage_key_exactly_once(client, monkeypatch):
    from datetime import UTC, datetime
    from urllib.parse import parse_qs, urlsplit

    from app.storage import local_download_signature
    from app.viral_routes import (
        _VIRAL_SIGNATURE_ASSET,
        _VIRAL_SIGNATURE_EPOCH,
        _browser_playable_url,
    )

    secret = "test-signing-secret"
    monkeypatch.setattr("app.viral_routes.settings_encryption_key", lambda: secret)
    key = "viral/wechat_channels/finderobjabc/def+ghi=.mp4"
    from urllib.parse import quote

    url = _browser_playable_url("local://local-private/" + quote(key), "employee_1")
    query = parse_qs(urlsplit(url).query)
    assert query["key"] == [key]
    assert query["sig"] == [
        local_download_signature(
            key,
            query["expires"][0],
            user_id="employee_1",
            asset_id=_VIRAL_SIGNATURE_ASSET,
            session_epoch=_VIRAL_SIGNATURE_EPOCH,
            secret=secret,
        )
    ]
    assert int(query["expires"][0]) > datetime.now(UTC).timestamp()
