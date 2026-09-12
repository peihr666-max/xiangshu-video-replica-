"""PG-free unit tests for the independent-creation request contract.

These cover the *pure* layers of ``app.independent`` that need no database:

* the ``IndependentVideoRequest`` pydantic model — the unified mixed
  ``reference_asset_ids`` list (image/video/audio share one field) and its
  total-length cap (8 + 3 + 3 = 14);
* ``_validate_independent_mode_assets`` — the extracted mode/asset matrix that
  decides which inputs each generation mode may carry: R2V requires ≥1
  reference and forbids first/last frame; T2V/I2V may not carry any reference
  list (references are R2V-only); I2V requires a first frame; T2V forbids
  first/last frame;
* ``_validate_reference_kind_limits`` — the per-kind reference caps
  (image ≤ 8, video ≤ 3, audio ≤ 3) applied after the backend splits the mixed
  ``reference_asset_ids`` list by each asset's kind.

The database-backed ``create_independent_batch`` baseline (the kind split
itself, prompt-snapshot contents, wallet RESERVE, the PG worker protocol
payload) lives in the PG-gated ``test_independent_creation.py`` and only runs
on the Linux CI lane; this file exists so the request contract, the mode
matrix, and the per-kind caps stay verifiable without a PostgreSQL fixture.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.independent import (
    IndependentVideoRequest,
    _validate_independent_mode_assets,
    _validate_reference_kind_limits,
)


def _request(**overrides: Any) -> IndependentVideoRequest:
    payload: dict[str, Any] = {
        "mode": "r2v",
        "prompt_text": "参考生成",
        "output_duration_seconds": 6,
        "quantity": 1,
        "idempotency_key": "key",
    }
    payload.update(overrides)
    return IndependentVideoRequest(**payload)


# ---------------------------------------------------------------------------
# Request model: unified mixed reference_asset_ids + total-length cap.
# ---------------------------------------------------------------------------


def test_request_defaults_reference_asset_ids_to_empty() -> None:
    request = _request()
    assert request.reference_asset_ids == []


def test_request_accepts_mixed_reference_asset_ids() -> None:
    request = _request(reference_asset_ids=["image-1", "video-1", "audio-1"])
    assert request.reference_asset_ids == ["image-1", "video-1", "audio-1"]


def test_request_rejects_reference_asset_ids_over_total_limit() -> None:
    # 总兜底 = 图 8 + 视 3 + 音 3 = 14；15 项触发 pydantic too_long。
    with pytest.raises(ValidationError):
        _request(reference_asset_ids=[f"ref-{index}" for index in range(15)])


# ---------------------------------------------------------------------------
# Mode/asset matrix (pure): which inputs each mode may carry.
# ---------------------------------------------------------------------------


def test_matrix_r2v_accepts_mixed_references() -> None:
    _validate_independent_mode_assets(
        _request(reference_asset_ids=["image-1", "video-1", "audio-1"]),
        extended_enabled=True,
    )


def test_matrix_r2v_requires_at_least_one_reference() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_independent_mode_assets(_request(), extended_enabled=True)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "INDEPENDENT_REFERENCE_REQUIRED"


def test_matrix_r2v_rejects_duplicate_references() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_independent_mode_assets(
            _request(reference_asset_ids=["image-1", "image-1"]),
            extended_enabled=True,
        )
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "INDEPENDENT_REFERENCE_DUPLICATE"


def test_matrix_r2v_rejects_first_frame() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_independent_mode_assets(
            _request(reference_asset_ids=["image-1"], first_frame_asset_id="frame-1"),
            extended_enabled=True,
        )
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "INDEPENDENT_MODE_ASSET_CONFLICT"


def test_matrix_rejects_reference_list_for_t2v() -> None:
    request = _request(mode="t2v", reference_asset_ids=["image-1"])
    with pytest.raises(HTTPException) as exc:
        _validate_independent_mode_assets(request, extended_enabled=True)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "INDEPENDENT_MODE_ASSET_CONFLICT"


def test_matrix_rejects_reference_list_for_i2v() -> None:
    request = _request(
        mode="i2v",
        first_frame_asset_id="frame-1",
        reference_asset_ids=["image-1"],
    )
    with pytest.raises(HTTPException) as exc:
        _validate_independent_mode_assets(request, extended_enabled=True)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "INDEPENDENT_MODE_ASSET_CONFLICT"


def test_matrix_i2v_requires_first_frame() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_independent_mode_assets(_request(mode="i2v"), extended_enabled=True)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "INDEPENDENT_FIRST_FRAME_REQUIRED"


def test_matrix_t2v_rejects_first_frame() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_independent_mode_assets(
            _request(mode="t2v", first_frame_asset_id="frame-1"),
            extended_enabled=True,
        )
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "INDEPENDENT_MODE_ASSET_CONFLICT"


def test_matrix_extended_gate_blocks_r2v_when_disabled() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_independent_mode_assets(
            _request(reference_asset_ids=["image-1"]), extended_enabled=False
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "EXTENDED_MODE_PENDING_VERIFICATION"


# ---------------------------------------------------------------------------
# Per-kind reference caps (pure): image ≤ 8, video ≤ 3, audio ≤ 3.
# ---------------------------------------------------------------------------


def test_kind_limits_accept_within_caps() -> None:
    _validate_reference_kind_limits(image_count=8, video_count=3, audio_count=3)


def test_kind_limits_reject_images_over_cap() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_reference_kind_limits(image_count=9, video_count=0, audio_count=0)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "INDEPENDENT_REFERENCE_LIMIT_EXCEEDED"


def test_kind_limits_reject_videos_over_cap() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_reference_kind_limits(image_count=0, video_count=4, audio_count=0)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "INDEPENDENT_REFERENCE_LIMIT_EXCEEDED"


def test_kind_limits_reject_audios_over_cap() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_reference_kind_limits(image_count=0, video_count=0, audio_count=4)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "INDEPENDENT_REFERENCE_LIMIT_EXCEEDED"
