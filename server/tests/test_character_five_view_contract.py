"""五视角合同收窄后的存量兼容契约：旧七资产人物照常可用，RIGHT_* 不再派生。"""

from __future__ import annotations

import hashlib

import pytest
from fastapi import HTTPException

from app.character_identity import REQUIRED_CHARACTER_VIEW_TYPES, encode_json
from app.character_reference_matching import (
    SourceFrameFeatures as _Features,
)
from app.character_reference_matching import (
    recommended_body_view,
    validated_publication,
)


class _FakeRow(dict):
    def __getitem__(self, key):  # noqa: D105 - dict access
        return dict.__getitem__(self, key)


def _publication_snapshot(views: list[str]) -> tuple[dict, str]:
    snapshot = {
        "schema_version": "character-publication.v1",
        "character_version_id": "cv-1",
        "required_view_types": views,
        "assets_by_view": {view: {"asset_id": f"asset-{view.lower()}"} for view in views},
    }
    return snapshot, hashlib.sha256(encode_json(snapshot).encode()).hexdigest()


def _version_row(views: list[str]) -> _FakeRow:
    snapshot, publication_hash = _publication_snapshot(views)
    return _FakeRow(
        id="cv-1",
        publication_snapshot_json=encode_json(snapshot),
        publication_hash=publication_hash,
    )


def test_required_view_types_are_exactly_the_five_real_views() -> None:
    assert REQUIRED_CHARACTER_VIEW_TYPES == (
        "FRONT_FACE",
        "FRONT_HALF",
        "FRONT_FULL",
        "LEFT_45",
        "LEFT_SIDE",
    )


def test_legacy_seven_view_publication_still_validates() -> None:
    row = _version_row(
        [
            "FRONT_FACE",
            "FRONT_HALF",
            "FRONT_FULL",
            "LEFT_45",
            "RIGHT_45",
            "LEFT_SIDE",
            "RIGHT_SIDE",
        ]
    )
    result, publication_hash = validated_publication(row)
    assert publication_hash == row["publication_hash"]
    assert set(REQUIRED_CHARACTER_VIEW_TYPES).issubset(set(result["assets_by_view"]))


def test_publication_missing_a_required_view_is_rejected() -> None:
    row = _version_row(["FRONT_FACE", "FRONT_FULL"])
    with pytest.raises(HTTPException) as exc:
        validated_publication(row)
    assert exc.value.detail["code"] == "CHARACTER_PUBLICATION_INVALID"


@pytest.mark.parametrize(
    ("orientation", "expected"),
    [
        ("LEFT_45", "LEFT_45"),
        ("RIGHT_45", "LEFT_45"),
        ("LEFT_SIDE", "LEFT_SIDE"),
        ("RIGHT_SIDE", "LEFT_SIDE"),
    ],
)
def test_right_facing_source_frames_map_to_the_real_left_views(
    orientation: str, expected: str
) -> None:
    features = _Features(
        orientation=orientation,  # type: ignore[arg-type]
        shot_size="FULL_BODY",
        face_visible=True,
        body_completeness="FULL_BODY",
    )
    assert recommended_body_view(features) == expected
