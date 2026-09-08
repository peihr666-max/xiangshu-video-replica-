from __future__ import annotations

from pathlib import Path

import pytest

from app.auth import CurrentUser
from app.db import initialize_database
from app.db_portable import BusinessConnection
from app.generation_worker import run_worker_once
from app.oral_composer import build_ffmpeg_command, calculate_text_layout, composition_capabilities
from app.oral_compositions import (
    CompositionConflictError,
    CompositionDomainError,
    cancel_composition,
    claim_composition,
    complete_composition,
    create_composition,
    fail_composition,
    retry_composition,
)


def _actor(user_id: str = "owner") -> CurrentUser:
    return CurrentUser(id=user_id, username=user_id, display_name=user_id, role="employee")


@pytest.fixture
def conn(tmp_path: Path) -> BusinessConnection:
    raw = initialize_database(tmp_path / "compositions.db")
    business = BusinessConnection.sqlite(raw)
    for user_id in ("owner", "other"):
        business.execute(
            "INSERT INTO users (id, username, display_name, role) VALUES (%s, %s, %s, 'employee')",
            (user_id, user_id, user_id),
        )
    business.execute(
        "INSERT INTO person_identities (id, owner_user_id, display_name, status) "
        "VALUES ('identity', 'owner', 'Owner', 'ACTIVE')"
    )
    business.execute(
        "INSERT INTO oral_avatars (id, identity_id, owner_user_id, title, status, "
        "source_kind, source_asset_id) VALUES "
        "('avatar', 'identity', 'owner', 'Avatar', 'READY', 'VIDEO', 'source')"
    )
    business.execute(
        "INSERT INTO assets (id, project_id, kind, storage_uri, sha256, size_bytes, "
        "content_type, created_by_user_id) VALUES "
        "('original', NULL, 'oral_video', 'local://oral/original.mp4', 'hash', 10, "
        "'video/mp4', 'owner')"
    )
    business.execute(
        "INSERT INTO oral_tasks (id, owner_user_id, identity_id, avatar_id, mode, title, "
        "status, result_asset_id, estimated_cost_fen, idempotency_key) VALUES "
        "('oral-task', 'owner', 'identity', 'avatar', 'TTS', 'Result', 'SUCCEEDED', "
        "'original', 1000, 'oral-source-key')"
    )
    business.commit()
    yield business
    raw.close()


def test_three_templates_have_distinct_bounded_pixel_layouts() -> None:
    bottom = calculate_text_layout("底部字幕", template="bottom_caption", width=1080, height=1920)
    center = calculate_text_layout("居中色带", template="center_banner", width=1080, height=1920)
    top = calculate_text_layout("顶部标题", template="top_title", width=1080, height=1920)
    assert bottom.box[1] > 1400
    assert 650 < center.box[1] < 1100
    assert top.box[1] < 400
    for layout in (bottom, center, top):
        assert layout.box[0] >= 0 and layout.box[2] <= 1080
        assert layout.box[1] >= 0 and layout.box[3] <= 1920


def test_long_chinese_text_wraps_and_shrinks_without_overflow() -> None:
    layout = calculate_text_layout(
        "这是一个必须完整显示且不能被画布边缘截断的超长中文标题" * 5,
        template="center_banner",
        width=1080,
        height=1920,
    )
    assert "".join(layout.lines) == "这是一个必须完整显示且不能被画布边缘截断的超长中文标题" * 5
    assert layout.box[2] <= 1080 and layout.box[3] <= 1920
    assert layout.font_size >= 8
    assert len(layout.lines) * int(layout.font_size * 1.35) <= layout.box[3] - layout.box[1]


def test_ffmpeg_command_uses_platform_encoder_without_gpl_codec() -> None:
    command = build_ffmpeg_command(
        source_path=Path("source.mp4"),
        overlay_path=Path("overlay.png"),
        output_path=Path("output.mp4"),
        platform="darwin",
    )
    joined = " ".join(command)
    assert "overlay=0:0" in joined
    assert "h264_videotoolbox" in command
    assert "libx264" not in joined and "libx265" not in joined


def test_capability_does_not_claim_ready_without_a_font(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VIDEO_REPLICA_COMPOSE_FONT_PATH", raising=False)
    result = composition_capabilities()
    assert result.available is False
    assert result.font is False
    assert any("FONT_PATH" in reason for reason in result.reasons)


def test_create_is_owner_scoped_and_idempotent(conn: BusinessConnection) -> None:
    created = create_composition(
        conn,
        actor=_actor(),
        oral_task_id="oral-task",
        template="bottom_caption",
        text="你好",
        idempotency_key="compose-key-0001",
    )
    replay = create_composition(
        conn,
        actor=_actor(),
        oral_task_id="oral-task",
        template="bottom_caption",
        text="你好",
        idempotency_key="compose-key-0001",
    )
    assert created["source_asset_id"] == "original"
    assert replay["id"] == created["id"]
    assert replay["replayed"] is True
    with pytest.raises(CompositionConflictError):
        create_composition(
            conn,
            actor=_actor(),
            oral_task_id="oral-task",
            template="top_title",
            text="不同请求",
            idempotency_key="compose-key-0001",
        )
    with pytest.raises(CompositionDomainError):
        create_composition(
            conn,
            actor=_actor("other"),
            oral_task_id="oral-task",
            template="bottom_caption",
            text="越权",
            idempotency_key="compose-key-0002",
        )


def test_cancel_queued_and_retry_failed_create_auditable_version(conn: BusinessConnection) -> None:
    first = create_composition(
        conn,
        actor=_actor(),
        oral_task_id="oral-task",
        template="top_title",
        text="标题",
        idempotency_key="compose-key-0003",
    )
    cancelled = cancel_composition(conn, actor=_actor(), composition_id=str(first["id"]))
    assert cancelled["status"] == "CANCELLED"

    failed = create_composition(
        conn,
        actor=_actor(),
        oral_task_id="oral-task",
        template="center_banner",
        text="重试",
        idempotency_key="compose-key-0004",
    )
    lease = claim_composition(conn, worker_id="worker")
    assert lease is not None
    fail_composition(conn, lease=lease, error_message="render failed")
    retried = retry_composition(
        conn,
        actor=_actor(),
        composition_id=str(failed["id"]),
        idempotency_key="compose-retry-key-0004",
    )
    assert retried["id"] != failed["id"]
    assert retried["retry_of_id"] == failed["id"]
    assert retried["version"] == int(failed["version"]) + 1
    replay = retry_composition(
        conn,
        actor=_actor(),
        composition_id=str(failed["id"]),
        idempotency_key="compose-retry-key-0004",
    )
    assert replay["id"] == retried["id"] and replay["replayed"] is True


def test_success_switches_active_and_failure_preserves_previous(conn: BusinessConnection) -> None:
    old = create_composition(
        conn,
        actor=_actor(),
        oral_task_id="oral-task",
        template="bottom_caption",
        text="旧版",
        idempotency_key="compose-key-0005",
    )
    old_lease = claim_composition(conn, worker_id="worker")
    assert old_lease is not None
    complete_composition(
        conn,
        lease=old_lease,
        storage_uri="local://oral/composed-old.mp4",
        sha256="old-hash",
        size_bytes=20,
    )

    new = create_composition(
        conn,
        actor=_actor(),
        oral_task_id="oral-task",
        template="top_title",
        text="新版",
        idempotency_key="compose-key-0006",
    )
    new_lease = claim_composition(conn, worker_id="worker")
    assert new_lease is not None
    fail_composition(conn, lease=new_lease, error_message="boom")
    active = conn.execute(
        "SELECT id FROM oral_compositions WHERE oral_task_id = %s AND is_active = 1",
        ("oral-task",),
    ).fetchone()
    assert active is not None and active["id"] == old["id"]
    task = conn.execute(
        "SELECT result_asset_id FROM oral_tasks WHERE id = %s", ("oral-task",)
    ).fetchone()
    assert task is not None and task["result_asset_id"] == "original"
    assert new["source_asset_id"] == "original"


def test_worker_composes_with_injected_storage_and_runner(
    conn: BusinessConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import generation_worker
    from app.storage import FakeStorageAdapter

    storage = FakeStorageAdapter(provider="fake", bucket="test")
    source = storage.put_object("oral/original.mp4", b"source-video", content_type="video/mp4")
    conn.execute(
        "UPDATE assets SET storage_uri = %s WHERE id = 'original'",
        (source.uri,),
    )
    conn.commit()
    create_composition(
        conn,
        actor=_actor(),
        oral_task_id="oral-task",
        template="bottom_caption",
        text="Worker",
        idempotency_key="compose-key-worker",
    )
    calls: list[tuple[bytes, str, str]] = []

    def fake_compose(*, source: bytes, text: str, template: str, runner: object) -> bytes:
        calls.append((source, text, template))
        return b"composed-video"

    monkeypatch.setattr(generation_worker, "compose_video", fake_compose)
    assert (
        run_worker_once(
            conn,
            worker_id="worker",
            storage=storage,
            composition_runner=lambda command, timeout: None,  # type: ignore[arg-type,return-value]
            max_tasks=1,
        )
        == 1
    )
    assert calls == [(b"source-video", "Worker", "bottom_caption")]
    row = conn.execute(
        "SELECT status, is_active, result_asset_id FROM oral_compositions "
        "WHERE idempotency_key = 'compose-key-worker'"
    ).fetchone()
    assert row is not None and row["status"] == "SUCCEEDED" and row["is_active"] == 1


def test_expired_lease_is_recovered_and_old_worker_is_fenced(
    conn: BusinessConnection,
) -> None:
    created = create_composition(
        conn,
        actor=_actor(),
        oral_task_id="oral-task",
        template="top_title",
        text="Lease",
        idempotency_key="compose-key-lease",
    )
    old = claim_composition(conn, worker_id="old-worker")
    assert old is not None
    conn.execute(
        "UPDATE oral_compositions SET locked_until = '2000-01-01T00:00:00+00:00' WHERE id = %s",
        (created["id"],),
    )
    conn.commit()
    current = claim_composition(conn, worker_id="new-worker")
    assert current is not None
    assert current.lease_token != old.lease_token and current.attempt == old.attempt + 1
    with pytest.raises(CompositionConflictError):
        complete_composition(
            conn,
            lease=old,
            storage_uri="local://oral/stale.mp4",
            sha256="stale",
            size_bytes=1,
        )


def test_paid_work_keeps_priority_over_local_composition(
    conn: BusinessConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import generation_worker
    from app.storage import FakeStorageAdapter

    calls: list[str] = []
    monkeypatch.setattr(
        generation_worker,
        "_run_sqlite_oral_step",
        lambda *args, **kwargs: calls.append("oral") or True,
    )
    monkeypatch.setattr(
        generation_worker,
        "_run_sqlite_composition_step",
        lambda *args, **kwargs: calls.append("composition") or True,
    )
    assert (
        run_worker_once(
            conn,
            worker_id="worker",
            storage=FakeStorageAdapter(provider="fake", bucket="test"),
            max_tasks=1,
        )
        == 1
    )
    assert calls == ["oral"]


def test_http_contract_paths_are_registered() -> None:
    from app.oral_compose_routes import router

    routes = {
        (route.path, method)
        for route in router.routes
        for method in getattr(route, "methods", set()) or set()
    }
    assert ("/api/oral/compose-capabilities", "GET") in routes
    assert ("/api/oral/tasks/{oral_task_id}/compositions", "GET") in routes
    assert ("/api/oral/tasks/{oral_task_id}/compositions", "POST") in routes
    assert ("/api/oral/compositions/{composition_id}/cancel", "POST") in routes
    assert ("/api/oral/compositions/{composition_id}/retry", "POST") in routes
