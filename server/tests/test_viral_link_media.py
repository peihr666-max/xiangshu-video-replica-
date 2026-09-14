"""Media preflight regressions: M4A, Windows decoder access and safe DNS errors."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from app import media, viral_import_routes
from app.media import VideoMetadata
from app.viral_import_routes import validate_resolved_media_content
from app.viral_link import (
    DouyidouHttpTransport,
    DouyidouLinkClient,
    ResolvedViralLink,
    ViralLinkError,
)
from app.viral_media import ViralMediaDNSUnavailable, ViralMediaResult


def test_link_preflight_accepts_mp4_container_audio() -> None:
    names: list[str] = []

    class Probe:
        def probe(self, content: bytes, *, filename: str) -> VideoMetadata:
            names.append(filename)
            return VideoMetadata(duration_seconds=30)

    validate_resolved_media_content(
        b"\x00\x00\x00\x18ftypM4A ",
        kind="audio",
        content_type="audio/mp4",
        probe=Probe(),
    )
    assert names == ["source.m4a"]


def test_ffprobe_input_is_readable_by_an_external_process_and_cleaned(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(media.shutil, "which", lambda _: sys.executable)
    monkeypatch.setattr(media.tempfile, "tempdir", str(tmp_path))
    run = subprocess.run
    source_paths: list[Path] = []

    def decoder(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        source = Path(command[-1])
        source_paths.append(source)
        child = run(
            [
                sys.executable,
                "-c",
                "import pathlib,sys; "
                "assert pathlib.Path(sys.argv[1]).read_bytes() == b'media-bytes'",
                str(source),
            ],
            **kwargs,
        )
        assert child.returncode == 0, "decoder could not read its input while probing"
        return subprocess.CompletedProcess(
            command, 0, json.dumps({"format": {"duration": "12.5"}}), ""
        )

    monkeypatch.setattr(media.subprocess, "run", decoder)
    assert (
        media.FFprobeVideoProbe().probe(b"media-bytes", filename="source.mp4").duration_seconds
        == 12.5
    )
    assert source_paths and all(not path.exists() for path in source_paths)


def test_preflight_dns_failure_has_actionable_redacted_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Pipeline:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def fetch(self, *args: Any, **kwargs: Any) -> None:
            raise ViralMediaDNSUnavailable("private-url?token=do-not-disclose")

    monkeypatch.setattr(viral_import_routes, "ViralMediaPipeline", Pipeline)
    resolved = ResolvedViralLink(
        platform="douyin",
        video_id="7672703482771972081",
        title="test",
        author="",
        cover_url=None,
        video_url="https://cdn.example/video.mp4",
        audio_url=None,
        duration_ms=0,
        source_description="",
    )
    with pytest.raises(ViralLinkError) as result:
        viral_import_routes.preflight_resolved_media(resolved, purpose="copy", storage=None)
    assert result.value.status_code == 503
    assert result.value.code == "VIRAL_LINK_MEDIA_DNS_UNAVAILABLE"
    assert "DNS" in result.value.message
    assert "token" not in result.value.message


def test_copy_preflight_uses_video_audio_track_instead_of_resolver_music(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preferences: list[str | None] = []

    class Pipeline:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def fetch(self, video: Any, *, prefer: str | None = None) -> ViralMediaResult:
            preferences.append(prefer)
            return ViralMediaResult(
                kind="video",
                storage_uri="cos://media/video.mp4",
                url="https://media.example/video.mp4",
                size=100,
                content_type="video/mp4",
                cache_hit=False,
                sha256="hash",
            )

    monkeypatch.setattr(viral_import_routes, "ViralMediaPipeline", Pipeline)
    resolved = ResolvedViralLink(
        platform="douyin",
        video_id="7672703482771972081",
        title="spoken video",
        author="",
        cover_url=None,
        video_url="https://media.example/video.mp4",
        audio_url="https://media.example/background-music.m4a",
        duration_ms=10_000,
        source_description="",
    )
    viral_import_routes.preflight_resolved_media(
        resolved,
        purpose="copy",
        storage=None,  # type: ignore[arg-type]
    )
    assert preferences == ["video"]


def test_copy_resolution_rejects_audio_only_media() -> None:
    class Transport(DouyidouHttpTransport):
        def request(self, url: str, *, headers: Any) -> bytes:
            return json.dumps(
                {
                    "code": 0,
                    "data": {
                        "aweme_id": "7672703482771972081",
                        "audio": ["https://media.example/background-music.m4a"],
                    },
                }
            ).encode()

    resolver = DouyidouLinkClient(app_id="test", app_secret="test", transport=Transport())
    with pytest.raises(ViralLinkError) as result:
        resolver.resolve(
            "https://www.douyin.com/jingxuan?modal_id=7672703482771972081",
            purpose="copy",
        )
    assert result.value.status_code == 422
    assert result.value.code == "VIRAL_LINK_MEDIA_MISSING"
