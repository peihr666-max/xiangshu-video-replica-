"""联系张裁剪契约：五个已发布视角必须逐格对应真实面板。

2026-09 前的旧合同从五面板联系张派生出七个资产（半身再裁剪 + 右侧视图
镜像伪造）；五视角合同落地后只允许五个 1:1 真实裁剪，镜像/半身派生
一律不得再出现在发布结果里。
"""

import hashlib
import struct

from app.character_identity import REQUIRED_CHARACTER_VIEW_TYPES
from app.simple_character import contact_sheet_placeholder_png, crop_contact_sheet_views

EXPECTED_FIVE_VIEWS = {
    "FRONT_FULL",
    "LEFT_45",
    "LEFT_SIDE",
    "FRONT_FACE",
    "LEFT_45_FACE",
}


def _crop(seed: bytes) -> dict[str, bytes]:
    crops = crop_contact_sheet_views(contact_sheet_placeholder_png(seed), "image/png")
    assert crops is not None
    return crops


def _png_size(png: bytes) -> tuple[int, int]:
    return struct.unpack(">II", png[16:24])


def test_contact_sheet_crops_exactly_the_five_real_views() -> None:
    crops = _crop(b"seed-1")

    assert set(crops) == EXPECTED_FIVE_VIEWS
    assert set(crops) == set(REQUIRED_CHARACTER_VIEW_TYPES)
    for png in crops.values():
        assert png.startswith(b"\x89PNG")


def test_derived_views_from_the_legacy_seven_asset_contract_are_gone() -> None:
    crops = _crop(b"seed-2")

    assert "FRONT_HALF" not in crops
    assert "RIGHT_45" not in crops
    assert "RIGHT_SIDE" not in crops


def test_five_views_are_five_distinct_panels() -> None:
    crops = _crop(b"seed-3")

    digests = {view: hashlib.sha256(png).hexdigest() for view, png in crops.items()}
    assert len(set(digests.values())) == 5


def test_left_45_face_is_the_lower_right_close_up_panel() -> None:
    crops = _crop(b"seed-4")

    face_w, _ = _png_size(crops["FRONT_FACE"])
    face45_w, _ = _png_size(crops["LEFT_45_FACE"])
    full_h = _png_size(crops["FRONT_FULL"])[1]
    face45_h = _png_size(crops["LEFT_45_FACE"])[1]
    # 右列上下堆叠：两个近景同宽，各占约一半高度，与全身列不同。
    assert face45_w == face_w
    assert abs(face45_h - full_h / 2) < full_h / 4
