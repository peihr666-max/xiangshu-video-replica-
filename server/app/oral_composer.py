from __future__ import annotations

import importlib
import io
import logging
import os
import platform as platform_module
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from app.media_tools import (
    MediaToolUnavailable,
    MediaValidationFailed,
    inspect_media_bytes,
    resolve_media_binary,
)
from app.storage import StorageAdapter, StoredObject

logger = logging.getLogger(__name__)
Template = Literal["bottom_caption", "center_banner", "top_title"]
COMPOSE_TIMEOUT_SECONDS = 300
FONT_ENV = "VIDEO_REPLICA_COMPOSE_FONT_PATH"
ENCODER_ENV = "VIDEO_REPLICA_COMPOSE_H264_ENCODER"


@dataclass(frozen=True)
class TextLayout:
    lines: tuple[str, ...]
    font_size: int
    box: tuple[int, int, int, int]


@dataclass(frozen=True)
class CompositionCapabilities:
    available: bool
    pillow: bool
    font: bool
    ffmpeg_overlay: bool
    encoder: str | None
    reasons: tuple[str, ...]


class CommandRunner(Protocol):
    def __call__(
        self, command: list[str], *, timeout: int
    ) -> subprocess.CompletedProcess[bytes]: ...


def calculate_text_layout(text: str, *, template: Template, width: int, height: int) -> TextLayout:
    if template not in {"bottom_caption", "center_banner", "top_title"}:
        raise ValueError("Unsupported composition template")
    max_width = int(width * (0.90 if template != "center_banner" else 0.86))
    max_height = int(height * (0.24 if template != "center_banner" else 0.34))
    minimum_font_size = 8
    font_size = min(72, max(minimum_font_size, width // 14))
    while True:
        chars_per_line = max(1, int(max_width / (font_size * 1.05)))
        lines = tuple(
            text[index : index + chars_per_line] for index in range(0, len(text), chars_per_line)
        )
        rendered_height = max(1, len(lines)) * int(font_size * 1.35)
        if rendered_height <= max_height or font_size == minimum_font_size:
            break
        font_size -= 2
    box_height = min(max_height, max(int(font_size * 1.7), rendered_height + font_size))
    x0 = (width - max_width) // 2
    if template == "top_title":
        y0 = int(height * 0.07)
    elif template == "center_banner":
        y0 = (height - box_height) // 2
    else:
        y0 = height - box_height - int(height * 0.08)
    return TextLayout(
        lines=lines, font_size=font_size, box=(x0, y0, x0 + max_width, y0 + box_height)
    )


def _default_encoder(platform: str) -> str | None:
    if platform == "windows":
        return "h264_mf"
    if platform == "darwin":
        return "h264_videotoolbox"
    return None


def build_ffmpeg_command(
    *, source_path: Path, overlay_path: Path, output_path: Path, platform: str | None = None
) -> list[str]:
    encoder = os.environ.get(ENCODER_ENV, "").strip() or _default_encoder(
        platform or platform_module.system().lower()
    )
    if encoder is None:
        raise RuntimeError(f"Set {ENCODER_ENV} for this platform")
    return [
        resolve_media_binary("ffmpeg"),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source_path),
        "-i",
        str(overlay_path),
        "-filter_complex",
        "overlay=0:0",
        "-c:v",
        encoder,
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(output_path),
    ]


def composition_capabilities() -> CompositionCapabilities:
    reasons: list[str] = []
    try:
        importlib.import_module("PIL")

        pillow = True
    except Exception as exc:
        logger.warning("oral composition Pillow probe unavailable: %s", type(exc).__name__)
        pillow = False
        reasons.append("Pillow is not installed")
    font_path = Path(os.environ.get(FONT_ENV, "")) if os.environ.get(FONT_ENV) else None
    font = bool(font_path and font_path.is_file())
    if not font:
        reasons.append(f"{FONT_ENV} does not point to a readable font")
    try:
        ffmpeg = resolve_media_binary("ffmpeg")
    except (MediaToolUnavailable, OSError, ValueError) as exc:
        logger.warning("oral composition ffmpeg probe unavailable: %s", type(exc).__name__)
        ffmpeg = None
    overlay = False
    encoder: str | None = None
    if ffmpeg:
        try:
            filters = subprocess.run(
                [ffmpeg, "-hide_banner", "-filters"], capture_output=True, timeout=10
            )
            overlay = filters.returncode == 0 and b" overlay " in filters.stdout
            wanted = os.environ.get(ENCODER_ENV, "").strip() or _default_encoder(
                platform_module.system().lower()
            )
            encoders = subprocess.run(
                [ffmpeg, "-hide_banner", "-encoders"], capture_output=True, timeout=10
            )
            if wanted and encoders.returncode == 0 and wanted.encode() in encoders.stdout:
                encoder = wanted
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("oral composition capability probe failed: %s", type(exc).__name__)
    if not overlay:
        reasons.append("FFmpeg overlay filter is unavailable")
    if encoder is None:
        reasons.append("A supported hardware H.264 encoder is unavailable")
    return CompositionCapabilities(
        available=pillow and font and overlay and encoder is not None,
        pillow=pillow,
        font=font,
        ffmpeg_overlay=overlay,
        encoder=encoder,
        reasons=tuple(reasons),
    )


def render_text_overlay_png(
    text: str, *, template: Template, width: int, height: int, font_path: Path
) -> bytes:
    image_module = importlib.import_module("PIL.Image")
    draw_module = importlib.import_module("PIL.ImageDraw")
    font_module = importlib.import_module("PIL.ImageFont")

    layout = calculate_text_layout(text, template=template, width=width, height=height)
    image = image_module.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = draw_module.Draw(image)
    x0, y0, x1, y1 = layout.box
    if template == "center_banner":
        draw.rectangle(layout.box, fill=(12, 12, 12, 190))
    box_width = x1 - x0
    box_height = y1 - y0
    fitted: tuple[object, tuple[str, ...], int] | None = None
    for font_size in range(layout.font_size, 5, -1):
        candidate_font = font_module.truetype(str(font_path), font_size)
        lines: list[str] = []
        current = ""
        for character in text:
            proposed = current + character
            bounds = draw.textbbox((0, 0), proposed, font=candidate_font, stroke_width=2)
            if current and bounds[2] - bounds[0] > box_width:
                lines.append(current)
                current = character
            else:
                current = proposed
        if current:
            lines.append(current)
        sample = draw.textbbox((0, 0), "国Ag", font=candidate_font, stroke_width=2)
        line_height = sample[3] - sample[1] + max(4, font_size // 5)
        if len(lines) * line_height <= box_height:
            fitted = candidate_font, tuple(lines), line_height
            break
    if fitted is None:
        raise ValueError("Composition text cannot fit inside the template safe area")
    font, fitted_lines, line_height = fitted
    total_height = len(fitted_lines) * line_height
    y = y0 + max(0, (y1 - y0 - total_height) // 2)
    for line in fitted_lines:
        bounds = draw.textbbox((0, 0), line, font=font, stroke_width=2)
        line_width = bounds[2] - bounds[0]
        draw.text(
            ((width - line_width) // 2, y),
            line,
            font=font,
            fill="white",
            stroke_width=2,
            stroke_fill="black",
        )
        y += line_height
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def compose_video(
    *, source: bytes, text: str, template: Template, runner: CommandRunner | None = None
) -> bytes:
    capabilities = composition_capabilities()
    if not capabilities.available:
        raise RuntimeError("Composition runtime unavailable: " + "; ".join(capabilities.reasons))
    font_path = Path(os.environ[FONT_ENV])
    inspection = inspect_media_bytes(source, suffix=".mp4", expected_type="video")
    if inspection.width is None or inspection.height is None:
        raise RuntimeError("Source video dimensions are unavailable")
    try:
        inspect_media_bytes(source, suffix=".mp4", expected_type="audio")
        source_has_audio = True
    except MediaValidationFailed:
        source_has_audio = False
    command_runner = runner or _run_command
    with tempfile.TemporaryDirectory(prefix="oral-compose-") as temp_dir:
        root = Path(temp_dir)
        source_path = root / "source.mp4"
        overlay_path = root / "overlay.png"
        output_path = root / "output.mp4"
        source_path.write_bytes(source)
        overlay_path.write_bytes(
            render_text_overlay_png(
                text,
                template=template,
                width=inspection.width,
                height=inspection.height,
                font_path=font_path,
            )
        )
        completed = command_runner(
            build_ffmpeg_command(
                source_path=source_path, overlay_path=overlay_path, output_path=output_path
            ),
            timeout=COMPOSE_TIMEOUT_SECONDS,
        )
        if completed.returncode != 0:
            logger.error("oral composition ffmpeg failed: returncode=%s", completed.returncode)
            raise RuntimeError("FFmpeg composition failed")
        content = output_path.read_bytes()
    output = inspect_media_bytes(content, suffix=".mp4", expected_type="video")
    if output.width != inspection.width or output.height != inspection.height:
        raise RuntimeError("Composed video dimensions changed")
    if (
        inspection.duration_seconds is not None
        and output.duration_seconds is not None
        and abs(output.duration_seconds - inspection.duration_seconds) > 0.2
    ):
        raise RuntimeError("Composed video duration changed")
    if source_has_audio:
        inspect_media_bytes(content, suffix=".mp4", expected_type="audio")
    return content


def _run_command(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(command, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("oral composition process failed: %s", type(exc).__name__)
        raise RuntimeError("FFmpeg composition process failed") from exc


def store_composed_video(
    storage: StorageAdapter, *, composition_id: str, owner_user_id: str, content: bytes
) -> StoredObject:
    return storage.put_object(
        f"oral-compositions/{owner_user_id}/{composition_id}/result.mp4",
        content,
        content_type="video/mp4",
    )
