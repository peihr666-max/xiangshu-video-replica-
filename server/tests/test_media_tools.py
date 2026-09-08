from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.media_tools import MediaToolFailed, require_media_stream


def test_require_media_stream_accepts_the_expected_decodable_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        media_path = Path(command[-1])
        if "-progress" in command:
            media_path = Path(command[command.index("-i") + 1])
        observed["content"] = media_path.read_bytes()
        observed["suffix"] = media_path.suffix
        observed["kwargs"] = kwargs
        if "-progress" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=b"frame=1\nout_time_us=1000\nprogress=end\n",
                stderr=b"",
            )
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"streams": [{"codec_type": "video"}]}).encode(),
            stderr=b"",
        )

    monkeypatch.setattr("app.media_tools.resolve_media_binary", lambda tool: f"/{tool}")
    monkeypatch.setattr("app.media_tools.subprocess.run", fake_run)

    require_media_stream(b"valid-video", extension="mp4", expected_stream="video")

    assert observed["content"] == b"valid-video"
    assert observed["suffix"] == ".mp4"
    assert observed["kwargs"] == {
        "capture_output": True,
        "timeout": 300,
    }


def test_require_media_stream_rejects_a_stream_that_cannot_be_fully_decoded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps({"streams": [{"codec_type": "video"}]}).encode(),
                stderr=b"",
            )
        return subprocess.CompletedProcess(command, 183, stdout=b"", stderr=b"damaged frame")

    monkeypatch.setattr("app.media_tools.resolve_media_binary", lambda tool: f"/{tool}")
    monkeypatch.setattr("app.media_tools.subprocess.run", fake_run)

    with pytest.raises(MediaToolFailed, match="媒体文件无法验证"):
        require_media_stream(b"damaged-video", extension="mp4", expected_stream="video")

    assert calls == 2


@pytest.mark.parametrize(
    ("result", "content"),
    [
        (subprocess.CompletedProcess([], 1, stdout=b"", stderr=b"bad"), b"bad-media"),
        (subprocess.CompletedProcess([], 0, stdout=b"not-json", stderr=b""), b"bad-json"),
        (
            subprocess.CompletedProcess(
                [],
                0,
                stdout=json.dumps({"streams": [{"codec_type": "video"}]}).encode(),
                stderr=b"",
            ),
            b"wrong-stream",
        ),
    ],
)
def test_require_media_stream_rejects_invalid_or_wrong_media(
    monkeypatch: pytest.MonkeyPatch,
    result: subprocess.CompletedProcess[bytes],
    content: bytes,
) -> None:
    monkeypatch.setattr("app.media_tools.resolve_media_binary", lambda _tool: "/ffprobe")
    monkeypatch.setattr("app.media_tools.subprocess.run", lambda *_args, **_kwargs: result)

    with pytest.raises(MediaToolFailed, match="媒体文件无法验证"):
        require_media_stream(content, extension="mp3", expected_stream="audio")


def test_require_media_stream_rejects_empty_content_before_starting_ffprobe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_run(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("ffprobe must not run for empty content")

    monkeypatch.setattr("app.media_tools.subprocess.run", fail_run)

    with pytest.raises(MediaToolFailed, match="媒体文件为空"):
        require_media_stream(b"", extension="mp4", expected_stream="video")


def test_require_media_stream_decodes_the_complete_video_before_accepting_it(
    tmp_path: Path,
) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("ffmpeg is required for the production media validation contract")
    valid_path = tmp_path / "valid.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=64x64:rate=10",
            "-t",
            "2",
            "-c:v",
            "mpeg4",
            "-q:v",
            "2",
            "-movflags",
            "+faststart",
            "-y",
            str(valid_path),
        ],
        check=True,
        capture_output=True,
    )
    valid = valid_path.read_bytes()

    require_media_stream(valid, extension="mp4", expected_stream="video")

    with pytest.raises(MediaToolFailed, match="媒体文件无法验证"):
        require_media_stream(valid[:-64], extension="mp4", expected_stream="video")
