from __future__ import annotations

import shutil
import sqlite3
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth import get_database
from app.db import connect_database, initialize_database
from app.db_portable import BusinessConnection
from app.generation_worker import run_worker_once
from app.main import app
from app.media_routes import get_media_storage
from app.source_frame_routes import ExtractSourceFramesRequest, get_source_frame_extractor
from app.source_frames import (
    ExtractedSourceFrame,
    FFmpegSourceFrameExtractor,
    SourceFrameCandidateAssessment,
    SourceFrameSemanticInspection,
    score_grayscale_frame,
)
from app.storage import FakeStorageAdapter


@dataclass(frozen=True)
class FakeSourceFrameExtractor:
    def extract(
        self,
        content: bytes,
        *,
        filename: str,
        timestamps_seconds: tuple[float, ...],
    ) -> list[ExtractedSourceFrame]:
        assert content == b"reference-video"
        assert filename == "reference.mp4"
        return [
            ExtractedSourceFrame(
                timestamp_seconds=timestamp,
                image=f"frame-{timestamp}".encode(),
                technical_score=round(timestamp / 12, 3),
            )
            for timestamp in timestamps_seconds
        ]


@dataclass(frozen=True)
class EmptySourceFrameExtractor:
    def extract(
        self,
        content: bytes,
        *,
        filename: str,
        timestamps_seconds: tuple[float, ...],
    ) -> list[ExtractedSourceFrame]:
        return [ExtractedSourceFrame(timestamp_seconds=0.5, image=b"")]


@dataclass(frozen=True)
class SemanticSourceFrameInspector:
    def inspect_source_frame_candidates(
        self,
        frames: list[ExtractedSourceFrame],
    ) -> SourceFrameSemanticInspection:
        assert len(frames) == 5
        return SourceFrameSemanticInspection(
            candidates=[
                SourceFrameCandidateAssessment(
                    candidate_index=index,
                    person_count=1,
                    person_visibility_score=0.98 if index == 0 else 0.4,
                    face_clarity_score=0.98 if index == 0 else 0.4,
                    unobstructed_score=0.98 if index == 0 else 0.4,
                    pose_suitability_score=0.98 if index == 0 else 0.4,
                    motion_blur_detected=False,
                    notes=[],
                )
                for index in range(len(frames))
            ],
            provider="test-semantic-source-frame",
            model="test-semantic-source-frame-v1",
        )


@pytest.fixture()
def db_path(tmp_path: Path) -> Iterator[Path]:
    path = tmp_path / "source-frames.db"
    with initialize_database(path) as conn:
        seed_data(conn)
    yield path


@pytest.fixture()
def storage() -> FakeStorageAdapter:
    return FakeStorageAdapter(provider="fake", bucket="private-bucket")


@pytest.fixture()
def client(
    db_path: Path,
    storage: FakeStorageAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    # Migrated routes (BusinessDb.write) open their own SQLite connection from
    # the env path; it must point at the same database the override yields.
    monkeypatch.setenv("VIDEO_REPLICA_DB_PATH", str(db_path))

    def database_override() -> Iterator[BusinessConnection]:
        conn = BusinessConnection.sqlite(connect_database(db_path))
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_database] = database_override
    app.dependency_overrides[get_media_storage] = lambda: storage
    app.dependency_overrides[get_source_frame_extractor] = FakeSourceFrameExtractor
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def seed_data(conn: sqlite3.Connection) -> None:
    conn.executemany(
        """
        INSERT INTO users (id, username, display_name, role)
        VALUES (?, ?, ?, ?)
        """,
        [
            ("employee_1", "employee_1", "Employee One", "employee"),
            ("employee_2", "employee_2", "Employee Two", "employee"),
            ("auditor_1", "auditor_1", "Auditor One", "auditor"),
        ],
    )
    conn.executemany(
        """
        INSERT INTO projects (id, owner_user_id, name)
        VALUES (?, ?, ?)
        """,
        [
            ("project_owned", "employee_1", "Owned Project"),
            ("project_other", "employee_2", "Other Project"),
        ],
    )
    conn.execute(
        """
        INSERT INTO assets (
            id, project_id, kind, storage_uri, sha256, size_bytes, content_type,
            created_by_user_id, metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "reference_owned",
            "project_owned",
            "reference_video",
            "fake://private-bucket/projects/project_owned/uploads/reference_owned/reference.mp4",
            "reference-hash",
            len(b"reference-video"),
            "video/mp4",
            "employee_1",
            '{"duration_seconds": 12.0}',
        ),
    )
    conn.commit()


def auth_headers(user_id: str) -> dict[str, str]:
    return {"X-Dev-User-Id": user_id}


def complete_source_frame_task(
    client: TestClient,
    db_path: Path,
    storage: FakeStorageAdapter,
    *,
    payload: dict[str, object] | None = None,
    extractor: object | None = None,
    quality_inspector: object | None = None,
) -> dict[str, object]:
    queued = client.post(
        "/api/projects/project_owned/source-frames/extract",
        json=payload or {"asset_id": "reference_owned"},
        headers=auth_headers("employee_1"),
    )
    assert queued.status_code == 202
    with BusinessConnection.sqlite(connect_database(db_path)) as conn:
        processed = run_worker_once(
            conn,
            worker_id="source-frame-test-worker",
            storage=storage,
            source_frame_extractor=extractor or FakeSourceFrameExtractor(),
            source_frame_quality_inspector=quality_inspector,
            max_tasks=1,
        )
    assert processed == 1
    task = client.get(
        f"/api/source-frame-tasks/{queued.json()['id']}",
        headers=auth_headers("employee_1"),
    )
    assert task.status_code == 200
    assert task.json()["status"] == "SUCCEEDED"
    latest = client.get(
        "/api/projects/project_owned/source-frames/latest",
        headers=auth_headers("employee_1"),
    )
    assert latest.status_code == 200
    return dict(latest.json())


def test_owner_can_extract_candidates_and_confirm_one(
    client: TestClient,
    db_path: Path,
    storage: FakeStorageAdapter,
) -> None:
    storage.put_object(
        "projects/project_owned/uploads/reference_owned/reference.mp4",
        b"reference-video",
        content_type="video/mp4",
    )

    body = complete_source_frame_task(
        client,
        db_path,
        storage,
    )
    assert body["kind"] == "source_frame_candidates"
    assert body["version_number"] == 1
    candidates = body["payload"]["candidates"]
    assert [candidate["timestamp_seconds"] for candidate in candidates] == [
        10.8,
        8.4,
        6.0,
        3.6,
        1.2,
    ]
    assert [candidate["score"] for candidate in candidates] == [0.9, 0.7, 0.5, 0.3, 0.1]
    assert all(candidate["asset_id"] for candidate in candidates)
    first_asset = candidates[0]["asset_id"]
    stored = storage.head_object(f"projects/project_owned/source-frames/{first_asset}.jpg")
    assert stored is not None
    assert stored.content_type == "image/jpeg"

    confirmed = client.post(
        "/api/projects/project_owned/source-frames/confirm",
        json={
            "source_frame_asset_id": candidates[1]["asset_id"],
            "character_features": {
                "orientation": "LEFT_45",
                "shot_size": "HALF_BODY",
                "face_visible": True,
                "body_completeness": "UPPER_BODY",
            },
        },
        headers=auth_headers("employee_1"),
    )
    latest = client.get(
        "/api/projects/project_owned/source-frames/selection/latest",
        headers=auth_headers("employee_1"),
    )

    assert confirmed.status_code == 200
    assert confirmed.json()["payload"]["source_frame_asset_id"] == candidates[1]["asset_id"]
    assert confirmed.json()["payload"]["character_features"] == {
        "orientation": "LEFT_45",
        "shot_size": "HALF_BODY",
        "face_visible": True,
        "body_completeness": "UPPER_BODY",
    }
    assert latest.status_code == 200
    assert latest.json()["id"] == confirmed.json()["id"]
    with BusinessConnection.sqlite(connect_database(db_path)) as conn:
        asset = conn.execute(
            "SELECT kind, content_type FROM assets WHERE id = ?",
            (candidates[1]["asset_id"],),
        ).fetchone()
    assert asset is not None
    assert asset["kind"] == "source_frame"
    assert asset["content_type"] == "image/jpeg"


def test_semantic_source_frame_score_can_beat_a_sharper_but_unsuitable_frame(
    client: TestClient,
    db_path: Path,
    storage: FakeStorageAdapter,
) -> None:
    storage.put_object(
        "projects/project_owned/uploads/reference_owned/reference.mp4",
        b"reference-video",
        content_type="video/mp4",
    )

    body = complete_source_frame_task(
        client,
        db_path,
        storage,
        quality_inspector=SemanticSourceFrameInspector(),
    )

    candidates = body["payload"]["candidates"]
    assert body["payload"]["semantic_quality_status"] == "VERIFIED"
    assert candidates[0]["timestamp_seconds"] == 1.2
    assert candidates[0]["semantic_score"] == 0.98
    assert candidates[0]["score"] > candidates[-1]["score"]
    assert "人物完整度" in candidates[0]["selection_reason"]


def test_source_frame_extraction_requires_owner_and_ready_reference(
    client: TestClient,
    storage: FakeStorageAdapter,
) -> None:
    storage.put_object(
        "projects/project_owned/uploads/reference_owned/reference.mp4",
        b"reference-video",
        content_type="video/mp4",
    )

    forbidden = client.post(
        "/api/projects/project_owned/source-frames/extract",
        json={"asset_id": "reference_owned"},
        headers=auth_headers("employee_2"),
    )
    missing = client.post(
        "/api/projects/project_missing/source-frames/extract",
        json={"asset_id": "reference_owned"},
        headers=auth_headers("employee_2"),
    )

    assert forbidden.status_code == 404
    assert forbidden.content == missing.content


def test_confirmation_rejects_assets_outside_the_latest_candidate_set(
    client: TestClient,
    db_path: Path,
    storage: FakeStorageAdapter,
) -> None:
    storage.put_object(
        "projects/project_owned/uploads/reference_owned/reference.mp4",
        b"reference-video",
        content_type="video/mp4",
    )
    complete_source_frame_task(
        client,
        db_path,
        storage,
    )

    response = client.post(
        "/api/projects/project_owned/source-frames/confirm",
        json={"source_frame_asset_id": "not-a-candidate"},
        headers=auth_headers("employee_1"),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "SOURCE_FRAME_CANDIDATE_NOT_FOUND"


def test_reextracting_source_frames_makes_the_previous_selection_stale(
    client: TestClient,
    db_path: Path,
    storage: FakeStorageAdapter,
) -> None:
    storage.put_object(
        "projects/project_owned/uploads/reference_owned/reference.mp4",
        b"reference-video",
        content_type="video/mp4",
    )
    first = complete_source_frame_task(
        client,
        db_path,
        storage,
    )
    confirmed = client.post(
        "/api/projects/project_owned/source-frames/confirm",
        json={"source_frame_asset_id": first["payload"]["candidates"][0]["asset_id"]},
        headers=auth_headers("employee_1"),
    )
    assert confirmed.status_code == 200

    second = complete_source_frame_task(
        client,
        db_path,
        storage,
    )
    selection = client.get(
        "/api/projects/project_owned/source-frames/selection/latest",
        headers=auth_headers("employee_1"),
    )

    assert second["id"] != first["id"]
    assert selection.status_code == 409
    assert selection.json()["detail"]["code"] == "SOURCE_FRAME_SELECTION_STALE"


def test_owner_can_reextract_manually_selected_timestamps_across_the_full_video(
    client: TestClient,
    db_path: Path,
    storage: FakeStorageAdapter,
) -> None:
    storage.put_object(
        "projects/project_owned/uploads/reference_owned/reference.mp4",
        b"reference-video",
        content_type="video/mp4",
    )

    response = complete_source_frame_task(
        client,
        db_path,
        storage,
        payload={
            "asset_id": "reference_owned",
            "timestamps_seconds": [0.2, 8.8],
        },
    )
    payload = response["payload"]
    assert payload["requested_timestamps_seconds"] == [0.2, 8.8]
    assert [candidate["timestamp_seconds"] for candidate in payload["candidates"]] == [8.8, 0.2]


def test_manual_source_frame_timestamp_must_be_inside_the_video_duration(
    client: TestClient,
    storage: FakeStorageAdapter,
) -> None:
    storage.put_object(
        "projects/project_owned/uploads/reference_owned/reference.mp4",
        b"reference-video",
        content_type="video/mp4",
    )
    response = client.post(
        "/api/projects/project_owned/source-frames/extract",
        json={"asset_id": "reference_owned", "timestamps_seconds": [12.0]},
        headers=auth_headers("employee_1"),
    )

    assert response.status_code == 422


@pytest.mark.parametrize("invalid_value", [float("nan"), float("inf"), float("-inf")])
def test_manual_source_frame_timestamp_rejects_non_finite_values(
    invalid_value: float,
) -> None:
    with pytest.raises(ValidationError):
        ExtractSourceFramesRequest.model_validate(
            {"asset_id": "reference_owned", "timestamps_seconds": [invalid_value]}
        )


@pytest.mark.parametrize("timestamps", [[-0.1], [1.0, 1.0]])
def test_manual_source_frame_timestamp_rejects_invalid_ranges_or_duplicates(
    client: TestClient,
    timestamps: list[float],
) -> None:
    response = client.post(
        "/api/projects/project_owned/source-frames/extract",
        json={"asset_id": "reference_owned", "timestamps_seconds": timestamps},
        headers=auth_headers("employee_1"),
    )

    assert response.status_code == 422


def test_technical_frame_score_prefers_high_detail_over_a_flat_frame() -> None:
    flat_score = score_grayscale_frame(bytes([128]) * 64)
    detailed_score = score_grayscale_frame(bytes([0, 255]) * 32)

    assert 0 <= flat_score <= 1
    assert 0 <= detailed_score <= 1
    assert detailed_score > flat_score


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
def test_ffmpeg_extractor_returns_scored_jpegs_for_requested_timestamps(tmp_path: Path) -> None:
    video_path = tmp_path / "reference.mp4"
    created = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x90:rate=10",
            "-t",
            "4",
            "-c:v",
            "mpeg4",
            str(video_path),
        ],
        capture_output=True,
        check=False,
        timeout=15,
    )
    assert created.returncode == 0

    frames = FFmpegSourceFrameExtractor().extract(
        video_path.read_bytes(),
        filename=video_path.name,
        timestamps_seconds=(0.2, 1.5, 2.8),
    )

    assert [frame.timestamp_seconds for frame in frames] == [0.2, 1.5, 2.8]
    assert all(frame.image.startswith(b"\xff\xd8") for frame in frames)
    assert all(frame.technical_score is not None for frame in frames)
    assert all(
        frame.technical_score is not None and 0 <= frame.technical_score <= 1 for frame in frames
    )


def test_empty_extracted_frame_is_reported_as_an_extraction_failure(
    client: TestClient,
    db_path: Path,
    storage: FakeStorageAdapter,
) -> None:
    storage.put_object(
        "projects/project_owned/uploads/reference_owned/reference.mp4",
        b"reference-video",
        content_type="video/mp4",
    )
    queued = client.post(
        "/api/projects/project_owned/source-frames/extract",
        json={"asset_id": "reference_owned"},
        headers=auth_headers("employee_1"),
    )

    assert queued.status_code == 202
    with BusinessConnection.sqlite(connect_database(db_path)) as conn:
        run_worker_once(
            conn,
            worker_id="source-frame-empty-worker",
            storage=storage,
            source_frame_extractor=EmptySourceFrameExtractor(),
            max_tasks=1,
        )
    task = client.get(
        f"/api/source-frame-tasks/{queued.json()['id']}",
        headers=auth_headers("employee_1"),
    )
    assert task.status_code == 200
    assert task.json()["status"] == "FAILED"
    assert task.json()["error_code"] == "SOURCE_FRAME_EXTRACTION_FAILED"


def test_database_failure_removes_uploaded_candidate_frames(
    client: TestClient,
    db_path: Path,
    storage: FakeStorageAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage.put_object(
        "projects/project_owned/uploads/reference_owned/reference.mp4",
        b"reference-video",
        content_type="video/mp4",
    )

    def fail_insert_version(*args: object, **kwargs: object) -> sqlite3.Row:
        raise sqlite3.IntegrityError("simulated persistence failure")

    monkeypatch.setattr("app.source_frames.insert_version", fail_insert_version)
    queued = client.post(
        "/api/projects/project_owned/source-frames/extract",
        json={"asset_id": "reference_owned"},
        headers=auth_headers("employee_1"),
    )

    assert queued.status_code == 202
    with BusinessConnection.sqlite(connect_database(db_path)) as conn:
        run_worker_once(
            conn,
            worker_id="source-frame-db-failure-worker",
            storage=storage,
            source_frame_extractor=FakeSourceFrameExtractor(),
            max_tasks=1,
        )
    task = client.get(
        f"/api/source-frame-tasks/{queued.json()['id']}",
        headers=auth_headers("employee_1"),
    )
    assert task.status_code == 200
    assert task.json()["status"] == "FAILED"
    assert task.json()["error_code"] == "SOURCE_FRAME_PERSIST_FAILED"
    assert not [key for key in storage._objects if "/source-frames/" in key]
