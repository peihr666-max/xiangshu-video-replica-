from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.generation import GenerationBatchRequest
from app.h3_prompts import GenerationContext, analysis_prompt_result, prompt_issues


def test_final_text_and_legacy_version_are_exclusive() -> None:
    base = dict(
        quantity=1,
        first_frame_asset_id="frame",
        output_duration_seconds=15,
        idempotency_key="click",
    )
    for extra in ({}, {"prompt_text": " "}, {"prompt_text": "text", "prompt_version_id": "old"}):
        with pytest.raises(ValidationError):
            GenerationBatchRequest(**base, **extra)
    text = "🎥" * 7000
    assert GenerationBatchRequest(**base, prompt_text=text).prompt_text == text
    with pytest.raises(ValidationError):
        GenerationBatchRequest(**base, prompt_text=text + "x")


def test_modes_follow_real_frame_roles() -> None:
    assert GenerationContext(route="text_image").mode() == "T2VA"
    assert GenerationContext(route="text_image", last_frame_asset_id="tail").mode() == "L2VA"
    assert (
        GenerationContext(first_frame_asset_id="first", last_frame_asset_id="tail").mode()
        == "FL2VA"
    )
    assert GenerationContext(route="reference").mode() == "Ref2VA"
    with pytest.raises(ValidationError):
        GenerationContext(duration_seconds=4.5)


def test_manual_text_is_allowed_but_invented_reference_is_not() -> None:
    assert prompt_issues("人物挥手", mode="T2VA", duration=8, labels=[], strict=False) == []
    assert (
        prompt_issues("<Video 1> 人物挥手", mode="T2VA", duration=8, labels=[], strict=False)[
            0
        ].code
        == "REFERENCE_NOT_BOUND"
    )


def test_analysis_keeps_action_beats_in_one_shot_and_dialogue_once() -> None:
    context = {
        "mode": "T2VA",
        "duration_seconds": 8,
        "generation_assets": [],
        "context_hash": "hash",
    }
    analysis = {
        "duration_seconds": 8,
        "shots": [
            {"spoken_text": "你好", "segment_kind": "ACTION_BEAT"},
            {"spoken_text": "世界", "segment_kind": "ACTION_BEAT"},
        ],
    }
    text = (
        "integrated_multimodal_description: [Shot 1] (S1) <d>[Chinese] 你好世界</d>\n"
        "overall_soundscape: N/A\n"
        "non_diegetic_music: N/A"
    )
    assert (
        analysis_prompt_result({"prompt_text": text}, context=context, analysis=analysis)["status"]
        == "READY"
    )
    result = analysis_prompt_result(
        {"prompt_text": text.replace("你好世界", "你好")}, context=context, analysis=analysis
    )
    assert result["status"] == "NEEDS_REVIEW"
    assert result["issues"][0]["code"] == "DIALOGUE_MISMATCH"


def test_missing_context_preserves_analysis_without_false_ready() -> None:
    result = analysis_prompt_result(
        None,
        context={
            "mode": "I2VA",
            "context_hash": "hash",
            "issues": [{"code": "GENERATION_ASSET_REQUIRED", "message": "缺少首帧"}],
        },
        analysis={},
    )
    assert result["status"] == "NEEDS_CONTEXT"
    assert result["prompt_text"] is None


def test_analysis_one_call_keeps_facts_when_prompt_is_invalid() -> None:
    import json

    from app.analysis import ApilioGemini, FakeGemini, analyze_video

    facts = json.loads(FakeGemini().analyze(video_uri="fake", duration_seconds=8).text)

    class Transport:
        calls = 0

        def post(self, url, *, headers, body):
            self.calls += 1
            request = json.loads(body)
            assert "analysis-h3.v1" in request["messages"][0]["content"]
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "schema_version": "analysis-h3.v1",
                                        "analysis": facts,
                                        "generation_prompt": {
                                            "mode": "T2VA",
                                            "prompt_text": "bad",
                                            "issues": [],
                                        },
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode(), {}

    transport = Transport()
    result = analyze_video(
        video_uri="https://example.test/source.mp4",
        video_duration_seconds=8,
        provider=ApilioGemini(api_key="test", transport=transport),
        generation_context={
            "mode": "T2VA",
            "duration_seconds": 8,
            "generation_assets": [],
            "context_hash": "h",
            "issues": [],
            "media_info": {"fps": 25, "resolution": "720x1280", "aspect_ratio": "9:16"},
        },
    )
    assert transport.calls == 1
    assert result.analysis.shots
    assert result.analysis.fps == 25
    assert result.generation_prompt["status"] != "READY"


def test_bad_json_never_triggers_paid_repair() -> None:
    from app.analysis import AnalysisProviderFailed, FakeGemini, analyze_video

    provider = FakeGemini(analysis_json="bad")
    with pytest.raises(AnalysisProviderFailed):
        analyze_video(video_uri="fake", video_duration_seconds=8, provider=provider)
    assert provider.repair_calls == 0


def test_rule_fields_match_parser_enums() -> None:
    from app.analysis import ShotMotion

    motion = ShotMotion(
        subject_motion_state="UNKNOWN",
        subject_direction="unknown",
        subject_displacement="无法判断",
        hand_action="手部被遮挡",
        camera_motion="ORBIT",
        relative_motion="无法判断",
    )
    assert motion.camera_motion == "ORBIT"


@pytest.mark.parametrize("case", ["dialogue", "warning"])
def test_optimizer_never_auto_accepts_changed_dialogue_or_uncertainty(case: str) -> None:
    import json

    from app.prompt_optimizer import validate_result

    original = "integrated_multimodal_description: [Shot 1] <d>[Chinese] 原句</d>\n"
    original += "overall_soundscape: N/A\nnon_diegetic_music: N/A"
    output = original.replace("原句", "被改写的台词") if case == "dialogue" else original
    warnings = [{"code": "UNCERTAIN", "message": "需核对动作"}] if case == "warning" else []
    result, state = validate_result(
        json.dumps({"prompt_text": output, "warnings": warnings}),
        snapshot={
            "prompt_text": original,
            "context": {"mode": "T2VA", "duration_seconds": 8, "generation_assets": []},
        },
    )
    assert state == ("FAILED" if case == "dialogue" else "NEEDS_INPUT")
    assert result["validation_status"] != "valid"
    assert result["warnings"][0]["code"] == (
        "DIALOGUE_CHANGED" if case == "dialogue" else "UNCERTAIN"
    )
