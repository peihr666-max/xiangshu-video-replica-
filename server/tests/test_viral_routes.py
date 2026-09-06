"""爆款视频路由测试：列表聚合、缓存护栏、媒体动作与供应商红线."""

from __future__ import annotations

from collections.abc import Iterator
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
    _cache,
    _now,
    get_viral_source_client,
    reset_viral_cache,
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
        else {"aweme_id": video_id},
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
    reset_viral_cache()
    try:
        yield TestClient(app), stub
    finally:
        app.dependency_overrides.clear()
        reset_viral_cache()


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
    # 把缓存时间戳拨回到 TTL 之外。
    for entry in _cache.values():
        entry.fetched_at = _now() - VIRAL_LIST_CACHE_TTL - timedelta(minutes=1)
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

        def fetch(self, video):
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

        def fetch(self, video):
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
    assert url.startswith("/api/viral/videos/media/file?key=viral/douyin/")
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
