"""Shared H3 content rules and deterministic checks; no provider calls or billing."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

FORMATTER_VERSION = "h3-format.v1"
MAX_PROMPT_CHARS = 7000
Mode = Literal["T2VA", "I2VA", "FL2VA", "L2VA", "Ref2VA"]
RULES = Path(__file__).with_name("prompt_rules")


class Issue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    message: str


class Reference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str = Field(min_length=1, max_length=128)
    purpose: str = Field(min_length=1, max_length=200)


class GenerationContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    route: Literal["text_image", "reference", "replica"] = "replica"
    duration_seconds: int = Field(default=15, ge=4, le=15, strict=True)
    ratio: Literal["adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"] = "adaptive"
    project_id: str | None = None
    analysis_version_id: str | None = None
    shot_card_version_id: str | None = None
    script_version_id: str | None = None
    source_asset_id: str | None = None
    first_frame_asset_id: str | None = None
    last_frame_asset_id: str | None = None
    references: list[Reference] = Field(default_factory=list, max_length=12)
    instructions: str = Field(default="", max_length=2000)

    def mode(self) -> Mode:
        if self.route == "reference":
            return "Ref2VA"
        if self.first_frame_asset_id and self.last_frame_asset_id:
            return "FL2VA"
        if self.first_frame_asset_id or self.route == "replica":
            return "I2VA"
        return "L2VA" if self.last_frame_asset_id else "T2VA"


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def mode_rules(mode: Mode) -> str:
    return (RULES / f"{mode}.txt").read_text(encoding="utf-8")


def prompt_issues(
    text: str, *, mode: Mode, duration: int, labels: list[str], strict: bool = True
) -> list[Issue]:
    issues: list[Issue] = []

    def add(code: str, message: str) -> None:
        issues.append(Issue(code=code, message=message))

    if not text.strip() or len(text) > MAX_PROMPT_CHARS:
        add("PROMPT_LENGTH_INVALID", "提示词须为 1–7000 字，且不能全为空白。")
    for kind, number in re.findall(r"<(Picture|Video|Audio)\s+(\d+)>", text):
        if f"<{kind} {number}>" not in labels:
            add("REFERENCE_NOT_BOUND", f"{kind} {number} 未绑定当前素材，请重新选择。")
    if re.search(r"(?<![A-Za-z0-9_@])@\d+", text):
        add("REFERENCE_ALIAS_UNRESOLVED", "请在提交预览中将 @编号绑定为当前素材标签。")
    if not strict:
        return issues
    fields = (
        ("subject_definitions", "summary", "retention_analysis", "detailed_description")
        if mode == "Ref2VA"
        else ("integrated_multimodal_description",)
    ) + ("overall_soundscape", "non_diegetic_music")
    positions = [re.search(rf"(?m)^\s*{field}\s*:", text) for field in fields]
    if any(match is None for match in positions):
        add("H3_STRUCTURE_INVALID", "提示词缺少当前模式的必要段落。")
    elif [match.start() for match in positions if match] != sorted(
        match.start() for match in positions if match
    ):
        add("H3_STRUCTURE_INVALID", "提示词段落顺序不正确。")
    if "```" in text or "[Shot 1]" not in text:
        add("H3_STRUCTURE_INVALID", "请使用完整 H3 正文和镜头标记，不带代码围栏。")
    if mode in ("I2VA", "FL2VA", "L2VA"):
        first_line = text.splitlines()[0] if text else ""
        if "Picture 1" not in first_line or (mode == "FL2VA" and "Picture 2" not in first_line):
            add("FRAME_ALIGNMENT_REQUIRED", "缺少当前首尾帧的对齐说明。")
    # Ref2VA can mention shots in subject/retention sections; verify only narrative.
    narrative = text.split("detailed_description:", 1)[-1] if mode == "Ref2VA" else text
    shot_numbers = [int(value) for value in re.findall(r"\[Shot (\d+)\]", narrative)]
    if shot_numbers != list(range(1, len(shot_numbers) + 1)):
        add("SHOT_SEQUENCE_INVALID", "镜头编号应连续，动作阶段不能重复新增镜头。")
    times = [int(m) * 60 + float(s) for m, s in re.findall(r"At (\d+):(\d+(?:\.\d+)?)", narrative)]
    if any(t <= 0 or t >= duration for t in times) or times != sorted(set(times)):
        add("TIMELINE_CONFLICT", "镜头时间须递增且位于生成时长内。")
    if text.count("<d>") != text.count("</d>"):
        add("DIALOGUE_INVALID", "台词标签不完整。")
    if "听不清" in text or "无法辨识" in text:
        add("CONTENT_REVIEW_REQUIRED", "存在无法辨识的内容，请核对。")
    return issues


def dialogue(text: str) -> str:
    return "".join(
        re.sub(r"\[[^\]]+\]|<[^>]+>|\s", "", part)
        for part in re.findall(r"<d>(.*?)</d>", text, flags=re.S)
    )


def analysis_prompt_result(
    candidate: Any, *, context: dict[str, Any], analysis: dict[str, Any]
) -> dict[str, Any]:
    mode: Mode = context["mode"]
    issues = [Issue.model_validate(item) for item in context.get("issues", [])]
    status = "NEEDS_CONTEXT" if issues else "INVALID"
    text = candidate.get("prompt_text") if isinstance(candidate, dict) else None
    if isinstance(candidate, dict) and candidate.get("mode", mode) != mode:
        issues.append(Issue(code="MODE_MISMATCH", message="生成模式与当前素材不一致。"))
        status = "INVALID"
    if not issues and isinstance(text, str):
        issues.extend(
            prompt_issues(
                text,
                mode=mode,
                duration=context["duration_seconds"],
                labels=[a["label"] for a in context["generation_assets"]],
            )
        )
        status = "INVALID" if issues else "READY"
        source_text = "".join(str(shot.get("spoken_text", "")) for shot in analysis["shots"])
        if re.sub(r"\s", "", source_text) != dialogue(text):
            issues.append(Issue(code="DIALOGUE_MISMATCH", message="台词与分析不一致，请核对。"))
            if status == "READY":
                status = "NEEDS_REVIEW"
        cuts = 1 + sum(s.get("segment_kind") == "SHOT_CUT" for s in analysis["shots"][1:])
        narrative = text.split("detailed_description:", 1)[-1]
        if len(re.findall(r"\[Shot \d+\]", narrative)) != cuts:
            issues.append(Issue(code="SHOT_MISMATCH", message="切镜数与分析不一致，请核对。"))
            if status == "READY":
                status = "NEEDS_REVIEW"
        original = re.sub(r"\s", "", str(analysis.get("original_script", source_text)))
        if original != re.sub(r"\s", "", source_text):
            issues.append(
                Issue(code="SOURCE_DIALOGUE_CONFLICT", message="全片口播与分段台词不一致，请核对。")
            )
            if status == "READY":
                status = "NEEDS_REVIEW"
        cut_times = [
            float(s["start_time"])
            for s in analysis["shots"][1:]
            if s.get("segment_kind") == "SHOT_CUT" and "start_time" in s
        ]
        prompt_times = [
            int(m) * 60 + float(sec)
            for m, sec in re.findall(r"At (\d+):(\d+(?:\.\d+)?)", narrative)
        ]
        if cut_times and (
            len(cut_times) != len(prompt_times)
            or any(abs(a - b) > 0.05 for a, b in zip(cut_times, prompt_times, strict=False))
        ):
            issues.append(
                Issue(code="CUT_TIME_MISMATCH", message="切镜时间与源分析不一致，请核对。")
            )
            if status == "READY":
                status = "NEEDS_REVIEW"
        if analysis["duration_seconds"] > context["duration_seconds"]:
            issues.append(Issue(code="TIMELINE_CONFLICT", message="源视频超过目标时长，请调整。"))
            if status == "READY":
                status = "NEEDS_REVIEW"
        if isinstance(candidate, dict) and candidate.get("issues"):
            issues.extend(Issue.model_validate(item) for item in candidate["issues"])
            if status == "READY":
                status = "NEEDS_REVIEW"
    return {
        "mode": mode,
        "prompt_text": text if isinstance(text, str) else None,
        "status": status,
        "issues": [i.model_dump() for i in issues],
        "context_hash": context["context_hash"],
        "formatter_version": FORMATTER_VERSION,
    }
