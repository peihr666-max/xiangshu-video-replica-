"""MATERIAL-THUMBS-B-20260917 — 视频素材缩略图（P0-3）PG 矩阵.

对应分析报告《素材库显示与页面切换性能根因分析与优化方案-2026-09-17》P0-3：
素材库网格的视频瓦片此前只能让浏览器经服务端代理流式拉原视频出首帧
（每页 6–24 路转发流）。本模块钉住缩略图链路的安全与语义不变量：

- 抽帧：ffmpeg 取首帧缩为 ≤480px JPEG，缩略图对象键与原对象键同址派生
  （``<object_key>.thumb.jpg``），任何抽帧/存储失败都不得影响原视频可用性。
- 记录：缩略图键写入 ``assets.metadata_json``（零迁移；列表 CTE 全分支已带出
  metadata_json）。
- 列表：``MaterialItem.thumbnail_key`` 透出元数据中的缩略图键；无缩略图的
  历史/口播素材保持 None（前端降级为现状占位）。
- 批量授权：对带缩略图键的视频资产，``DownloadUrlItem.thumbnail_url`` 额外
  签出 7 天有效的缩略图对象 URL（同一签名通道、同一属主校验；审计口径不变）。
  图片/音频/无键视频一律 None，不新增暴露面。

抽帧用真实 ffmpeg（lavfi 生成测试视频，与 test_cw058_content_asset_pg_matrix.py
同一手法）；存储在 FakeStorageAdapter 处替身；授权语义复用 MATERIAL-PERF-A 的
批量授权矩阵与专属 PG 库 ``matthumbs_test``。
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import pytest

from app.material_thumbs import (
    extract_thumbnail_jpeg,
    store_video_thumbnail,
    thumbnail_key_for,
)

JPEG_MAGIC = b"\xff\xd8"


def make_test_video(duration_seconds: float = 1.0) -> bytes:
    """用 lavfi 生成一段真实可解码的测试视频（同 CW-058 手法）."""
    from app.media_tools import resolve_media_binary

    with tempfile.TemporaryDirectory(prefix="matthumbs-") as directory:
        media_path = Path(directory) / "source.mp4"
        subprocess.run(
            [
                resolve_media_binary("ffmpeg"),
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"testsrc=duration={duration_seconds}:size=1280x720:rate=10",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(media_path),
            ],
            check=True,
            capture_output=True,
        )
        return media_path.read_bytes()


def test_thumbnail_key_is_deterministic_and_adjacent() -> None:
    assert (
        thumbnail_key_for("materials/employee_1/a/original.mp4")
        == "materials/employee_1/a/original.mp4.thumb.jpg"
    )
    assert (
        thumbnail_key_for("generation-results/t1/abc.mp4")
        == "generation-results/t1/abc.mp4.thumb.jpg"
    )


def test_extract_thumbnail_produces_small_jpeg() -> None:
    content = make_test_video()
    thumb = extract_thumbnail_jpeg(content)
    assert thumb is not None
    assert thumb.startswith(JPEG_MAGIC)
    # 缩略图必须显著小于原视频，否则网格批量下发失去意义。
    assert len(thumb) < 200_000


def test_extract_thumbnail_tolerates_garbage_and_returns_none() -> None:
    assert extract_thumbnail_jpeg(b"not a video at all") is None


def test_store_video_thumbnail_puts_adjacent_object_and_returns_key() -> None:
    from app.storage import FakeStorageAdapter

    storage = FakeStorageAdapter(provider="fake", bucket="matthumbs-tests")
    original_key = "generation-results/task-1/digest.mp4"
    storage.put_object(original_key, make_test_video(), content_type="video/mp4")
    key = store_video_thumbnail(storage, original_key, make_test_video())
    assert key == thumbnail_key_for(original_key)
    stored = storage.get_object(key)
    assert stored is not None and stored.startswith(JPEG_MAGIC)


def test_store_video_thumbnail_never_breaks_on_bad_content() -> None:
    from app.storage import FakeStorageAdapter

    storage = FakeStorageAdapter(provider="fake", bucket="matthumbs-tests")
    key = store_video_thumbnail(storage, "materials/x/a.mp4", b"garbage")
    assert key is None


# ---------------------------------------------------------------------------
# PG 部分：列表透出 metadata_json.thumbnail_key + 批量授权签发缩略图 URL
# ---------------------------------------------------------------------------

import hashlib  # noqa: E402
from collections.abc import Iterator  # noqa: E402
from contextlib import contextmanager  # noqa: E402
from urllib.parse import parse_qs, urlsplit  # noqa: E402

import psycopg  # noqa: E402
from cryptography.fernet import Fernet  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pg_test_kit import (  # noqa: E402
    create_test_database,
    drop_test_database,
    require_pg_or_explicit_skip,
    upgrade_test_database_to_head,
)

from app.customer_fence import get_business_db  # noqa: E402
from app.db_pg import DATABASE_URL_ENV, close_pg_pool  # noqa: E402
from app.db_portable import BusinessConnection  # noqa: E402
from app.storage import FakeStorageAdapter  # noqa: E402

MATTHUMBS_TEST_DB = "matthumbs_test"
BATCH_URL = "/api/assets/download-urls"
DAY = 86_400


@pytest.fixture(scope="module")
def matthumbs_dsn() -> Iterator[str]:
    require_pg_or_explicit_skip()
    dsn = create_test_database(MATTHUMBS_TEST_DB)
    upgrade_test_database_to_head(dsn)
    try:
        yield dsn
    finally:
        drop_test_database(MATTHUMBS_TEST_DB)


@pytest.fixture()
def pg(matthumbs_dsn: str) -> Iterator[psycopg.Connection]:
    close_pg_pool()
    conn = psycopg.connect(matthumbs_dsn, autocommit=True)
    conn.execute("SET session_replication_role = replica")
    conn.execute("TRUNCATE users, assets, audit_logs CASCADE")
    conn.execute("SET session_replication_role = DEFAULT")
    with conn.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO users (id, username, display_name, role) VALUES (%s, %s, %s, %s)",
            [
                ("employee_1", "employee_1", "Employee One", "employee"),
                ("employee_2", "employee_2", "Employee Two", "employee"),
            ],
        )
    try:
        yield conn
    finally:
        conn.close()
        close_pg_pool()


@pytest.fixture()
def lane_env(matthumbs_dsn: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    close_pg_pool()
    monkeypatch.setenv(DATABASE_URL_ENV, matthumbs_dsn)
    monkeypatch.setenv("VIDEO_REPLICA_SETTINGS_KEY", Fernet.generate_key().decode("ascii"))
    yield matthumbs_dsn
    close_pg_pool()


@pytest.fixture()
def fake_storage(monkeypatch: pytest.MonkeyPatch) -> FakeStorageAdapter:
    storage = FakeStorageAdapter(provider="fake", bucket="matthumbs-tests")
    monkeypatch.setattr("app.rbac_routes.storage_for_asset", lambda _conn, _uri: storage)
    return storage


class ScopedBusinessDb:
    def __init__(self, bus: BusinessConnection, user_id: str, role: str) -> None:
        self._bus = bus
        self._user_id = user_id
        self._role = role

    @contextmanager
    def write(self):
        from app.auth import CurrentUser

        yield (
            self._bus,
            CurrentUser(  # type: ignore[arg-type]
                id=self._user_id,
                username=self._user_id,
                display_name=self._user_id,
                role=self._role,
            ),
        )


def seed_video_asset(
    pg: psycopg.Connection,
    asset_id: str,
    owner: str,
    *,
    thumbnail_key: str | None,
) -> str:
    storage = FakeStorageAdapter(provider="fake", bucket="matthumbs-tests")
    stored = storage.put_object(f"perf/{asset_id}.mp4", b"mp4-bytes", content_type="video/mp4")
    if thumbnail_key:
        storage.put_object(thumbnail_key, b"\xff\xd8thumb", content_type="image/jpeg")
    metadata = {"thumbnail_key": thumbnail_key} if thumbnail_key else {}
    digest = hashlib.sha256(asset_id.encode()).hexdigest()
    pg.execute(
        """
        INSERT INTO assets (
            id, project_id, kind, storage_uri, sha256, size_bytes,
            content_type, created_by_user_id, metadata_json
        )
        VALUES (%s, NULL, 'material_video', %s, %s, 1024, 'video/mp4', %s, %s)
        """,
        (asset_id, stored.uri, digest, owner, json.dumps(metadata)),
    )
    return digest


def batch_client(app, pg: psycopg.Connection, user_id: str = "employee_1") -> TestClient:
    bus = BusinessConnection.postgres(pg)
    app.dependency_overrides[get_business_db] = lambda: ScopedBusinessDb(bus, user_id, "employee")
    return TestClient(app)


def test_batch_signs_seven_day_thumbnail_url_for_videos_with_thumb(
    lane_env: str, pg: psycopg.Connection, fake_storage: FakeStorageAdapter
) -> None:
    import time

    from app.main import app

    seed_video_asset(
        pg, "thumb_video", "employee_1", thumbnail_key="perf/thumb_video.mp4.thumb.jpg"
    )
    seed_video_asset(pg, "legacy_video", "employee_1", thumbnail_key=None)
    client = batch_client(app, pg)
    response = client.post(BATCH_URL, json={"asset_ids": ["thumb_video", "legacy_video"]})
    assert response.status_code == 200
    items = {item["asset_id"]: item for item in response.json()["items"]}
    # 带缩略图键的视频：额外签出 7 天有效的缩略图对象 URL（同一签名通道）。
    thumb_url = items["thumb_video"]["thumbnail_url"]
    assert thumb_url is not None
    assert "/api/assets/signed-objects/perf%2Fthumb_video.mp4.thumb.jpg" in thumb_url or (
        "thumb_video.mp4.thumb.jpg" in thumb_url
    )
    query = parse_qs(urlsplit(thumb_url).query)
    assert {"expires", "user_id", "asset_id", "sig"} <= set(query)
    assert query["asset_id"][0] == "thumb_video"
    expires = int(query["expires"][0])
    assert 6 * DAY <= expires - int(time.time()) <= 8 * DAY
    assert items["thumb_video"]["url"].startswith("/api/assets/signed-objects/")
    # 历史无缩略图视频：主 URL 照常，缩略图 URL 为 None（前端降级占位）。
    assert items["legacy_video"]["url"] is not None
    assert items["legacy_video"]["thumbnail_url"] is None
    app.dependency_overrides.clear()


def test_batch_masks_foreign_video_and_omits_its_thumbnail(
    lane_env: str, pg: psycopg.Connection, fake_storage: FakeStorageAdapter
) -> None:
    from app.main import app

    seed_video_asset(pg, "foreign_video", "employee_2", thumbnail_key="perf/f.mp4.thumb.jpg")
    client = batch_client(app, pg)
    response = client.post(BATCH_URL, json={"asset_ids": ["foreign_video"]})
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["error_code"] == "ASSET_NOT_FOUND"
    assert item["thumbnail_url"] is None
    app.dependency_overrides.clear()


def test_material_item_exposes_thumbnail_key_from_metadata() -> None:
    from app.materials import material_item

    class Row(dict):
        __getattr__ = dict.__getitem__

    row = Row(
        {
            "source_type": "asset",
            "source_id": "asset-1",
            "owner_user_id": "employee_1",
            "asset_id": "asset-1",
            "generation_task_id": None,
            "project_id": None,
            "person_id": None,
            "title_override": None,
            "base_title": "成片",
            "base_group": "任务结果",
            "source": "generation",
            "content_type": "video/mp4",
            "size_bytes": 2048,
            "metadata_json": json.dumps(
                {"thumbnail_key": "generation-results/t/abc.mp4.thumb.jpg"}
            ),
            "created_at": "2026-09-17 10:00:00",
            "status": "ready",
            "delivery": "stored",
            "media_type": "video",
            "hidden": 0,
            "group_override": None,
            "character_views_json": "[]",
        }
    )
    item = material_item(row)
    assert item.thumbnail_key == "generation-results/t/abc.mp4.thumb.jpg"
    no_thumb = material_item(Row({**row, "metadata_json": "{}"}))
    assert no_thumb.thumbnail_key is None
