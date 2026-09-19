"""Mode × ratio 契约（纯函数，无 PG）。

2026-09-19 对 MiniMax-H3 真实付费核对的供应商行为（证据见
.dev-env/ratio-probe-20260919/FINDINGS.json）：

* T2VA（仅文本）：ratio 必填且不能为 adaptive，否则供应商 400（err 2013）。
* I2VA/FL2VA/L2VA（含首/尾帧）：ratio 恒为 adaptive，具体值被供应商静默忽略、
  按首帧图片比例渲染。
* Ref2VA（含参考素材）：ratio 可选、默认 adaptive，具体比例被供应商尊重。

build_h3_request 是所有生成流（复刻流 + 独立创作流）共享的 Provider 请求
构建汇聚点，mode 由 content 隐式决定，这里锁定该矩阵。
"""

from __future__ import annotations

import pytest

from app.generation import build_h3_request

REFERENCE_IMAGE = ({"name": "scene", "url": "local://scene.png"},)


def _build(**overrides: object) -> dict:
    kwargs: dict = {
        "prompt_text": "乡墅庭院生成",
        "duration_seconds": 8,
        "resolution": "768P",
    }
    kwargs.update(overrides)
    return build_h3_request(**kwargs)


# ---------------------------------------------------------------------------
# T2VA（仅文本）：adaptive 必须被拒绝（BUG-1），具体比例透传。
# ---------------------------------------------------------------------------


def test_t2v_rejects_adaptive_ratio() -> None:
    with pytest.raises(ValueError, match=r"requires a concrete ratio"):
        _build(ratio="adaptive")


def test_t2v_passes_concrete_ratio_through() -> None:
    assert _build(ratio="16:9")["ratio"] == "16:9"


# ---------------------------------------------------------------------------
# I2VA/FL2VA/L2VA（含首/尾帧）：ratio 归一为 adaptive（BUG-2）。
# ---------------------------------------------------------------------------


def test_first_frame_normalizes_concrete_ratio_to_adaptive() -> None:
    request = _build(first_frame_url="local://first.png", ratio="16:9")
    assert request["ratio"] == "adaptive"


def test_first_frame_keeps_adaptive_ratio() -> None:
    request = _build(first_frame_url="local://first.png", ratio="adaptive")
    assert request["ratio"] == "adaptive"


def test_last_frame_only_normalizes_concrete_ratio_to_adaptive() -> None:
    request = _build(last_frame_url="local://last.png", ratio="9:16")
    assert request["ratio"] == "adaptive"


def test_first_and_last_frame_normalizes_concrete_ratio_to_adaptive() -> None:
    request = _build(
        first_frame_url="local://first.png",
        last_frame_url="local://last.png",
        ratio="4:3",
    )
    assert request["ratio"] == "adaptive"


# ---------------------------------------------------------------------------
# Ref2VA（含参考素材）：ratio 可选，具体比例被供应商尊重，透传。
# ---------------------------------------------------------------------------


def test_reference_keeps_concrete_ratio() -> None:
    request = _build(reference_images=REFERENCE_IMAGE, ratio="16:9")
    assert request["ratio"] == "16:9"


def test_reference_allows_adaptive_ratio() -> None:
    request = _build(reference_images=REFERENCE_IMAGE, ratio="adaptive")
    assert request["ratio"] == "adaptive"


def test_reference_ratio_defaults_to_adaptive() -> None:
    request = _build(reference_images=REFERENCE_IMAGE)
    assert request["ratio"] == "adaptive"


# ---------------------------------------------------------------------------
# 复刻流默认路径（首帧 + adaptive）保持既有契约不变。
# ---------------------------------------------------------------------------


def test_replica_default_first_frame_adaptive_contract_unchanged() -> None:
    request = _build(first_frame_url="local://first.png")
    assert request["ratio"] == "adaptive"
    assert set(request) == {"model", "content", "resolution", "duration", "ratio"}
