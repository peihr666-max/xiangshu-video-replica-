"""五视角合同收窄后的存量兼容契约：旧七资产人物照常可用，RIGHT_* 不再派生。"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock

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
from app.simple_character import SIMPLE_CONTACT_SHEET_PROMPT, scene_contact_sheet_prompt
from app.simple_character_routes import read_simple_library


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


def test_five_view_prompts_require_live_action_skin_and_reject_plastic_ai_texture() -> None:
    scene_prompt = scene_contact_sheet_prompt(
        scene_description="乡村工地",
        costume_description="蓝色施工马甲",
    )
    for prompt in (SIMPLE_CONTACT_SHEET_PROMPT, scene_prompt):
        # 提示词按行宽折行，断言只关心措辞本身，不应被折行位置左右。
        flat = " ".join(prompt.split())
        assert "skin microtexture" in flat
        assert "fine pores" in flat
        assert "individual hair strands" in flat
        assert "waxy or plastic skin" in flat
        assert "CGI sheen" in flat
        assert "beauty filter" in flat or "beauty-filter" in flat


@pytest.mark.parametrize("legacy_views", [[], ["RIGHT_45", "RIGHT_SIDE"], ["IMPORTED_REFERENCE"]])
def test_library_response_accepts_legacy_assets_without_breaking_all_people(legacy_views) -> None:
    """Exercise the library mapper AND response validation with historical rows."""
    rows = [
        {
            "identity_id": "identity-1",
            "display_name": "历史人物",
            "owner_user_id": "customer-1",
            "identity_status": "ACTIVE",
            "persona_id": "persona-1",
            "occupation": "讲解员",
            "appearance_constraints_json": "{}",
            "version_id": "version-1",
            "version_number": 1,
            "published_at": "2026-09-01T00:00:00Z",
            "snapshot_json": "{}",
            "view_type": view,
            "asset_id": f"asset-{view}",
        }
        for view in [*REQUIRED_CHARACTER_VIEW_TYPES, *legacy_views]
    ]
    conn = MagicMock()
    conn.execute.side_effect = [
        MagicMock(fetchone=lambda: {"total": 1}),
        MagicMock(fetchall=lambda: [{"id": "identity-1", "created_at": "2026-09-01"}]),
        MagicMock(fetchall=lambda: rows),
    ]
    page = read_simple_library(
        conn=conn,
        actor=SimpleNamespace(id="customer-1", role="customer"),
        limit=12,
        cursor=None,
        query="",
    )
    assert page.total == 1
    assert page.items[0].display_name == "历史人物"
    assert {view.view_type for view in page.items[0].views} == set(REQUIRED_CHARACTER_VIEW_TYPES)


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
