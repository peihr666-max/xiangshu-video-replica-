from __future__ import annotations

import base64
import json
import socket
from collections.abc import Mapping
from dataclasses import dataclass, field

import pytest

from app.first_frames import (
    ApilioImageProvider,
    ImageInput,
    ImageProviderFailed,
    image_aspect_ratio,
    require_safe_provider_download_url,
    valid_provider_output_url,
)


@dataclass
class RecordedRequest:
    url: str
    headers: Mapping[str, str]
    body: bytes


@dataclass
class FakeApilioTransport:
    response_body: bytes
    response_headers: Mapping[str, str] = field(
        default_factory=lambda: {"content-type": "application/json"}
    )
    requests: list[RecordedRequest] = field(default_factory=list)
    downloads: dict[str, tuple[bytes, str]] = field(default_factory=dict)

    def post(
        self, url: str, *, headers: Mapping[str, str], body: bytes
    ) -> tuple[bytes, Mapping[str, str]]:
        self.requests.append(RecordedRequest(url=url, headers=headers, body=body))
        return self.response_body, self.response_headers

    def get(self, url: str) -> tuple[bytes, Mapping[str, str]]:
        content, content_type = self.downloads[url]
        return content, {"content-type": content_type}

    def get_json(self, url: str, *, headers: Mapping[str, str]):
        self.requests.append(RecordedRequest(url=url, headers=headers, body=b""))
        return self.response_body, self.response_headers


def image(content: bytes, content_type: str, filename: str) -> ImageInput:
    return ImageInput(content=content, content_type=content_type, filename=filename)


def test_gpt_image_edit_uses_apilio_multipart_contract_and_downloads_url_response() -> None:
    transport = FakeApilioTransport(
        response_body=b'{"data":[{"url":"https://cdn.example/first.png"}]}'
    )
    generated_png = png_with_dimensions(940, 1672)
    transport.downloads["https://cdn.example/first.png"] = (generated_png, "image/png")
    provider = ApilioImageProvider(api_key="test-key", transport=transport)

    generated = provider.edit(
        model="gpt-image-2",
        prompt="replace the person",
        source_image=image(b"source", "image/jpeg", "source.jpg"),
        character_reference_images=[
            image(b"front", "image/png", "front.png"),
            image(b"side", "image/webp", "side.webp"),
        ],
        output_count=1,
    )

    assert generated == [type(generated[0])(content=generated_png, content_type="image/png")]
    request = transport.requests[0]
    assert request.url == "https://api.apilio.ai/v1/images/edits"
    assert request.headers["Authorization"] == "Bearer test-key"
    assert b'name="model"\r\n\r\ngpt-image-2' in request.body
    assert b'name="prompt"\r\n\r\nreplace the person' in request.body
    assert request.body.index(b'filename="source.jpg"') < request.body.index(
        b'filename="front.png"'
    )
    assert request.body.index(b'filename="front.png"') < request.body.index(b'filename="side.webp"')
    assert b'name="response_format"\r\n\r\nb64_json' in request.body
    assert b'name="size"\r\n\r\nauto' in request.body


def test_nano_banana_edit_uses_source_ratio_and_2k_defaults() -> None:
    banana_result = png_with_dimensions(940, 1672)
    encoded = base64.b64encode(banana_result).decode("ascii")
    transport = FakeApilioTransport(
        response_body=(f'{{"data":[{{"b64_json":"{encoded}"}}]}}').encode()
    )
    provider = ApilioImageProvider(api_key="test-key", transport=transport)

    generated = provider.edit(
        model="nano-banana-pro-2k",
        prompt="replace the person",
        source_image=image(png_with_dimensions(576, 1024), "image/png", "source.png"),
        character_reference_images=[image(b"front", "image/png", "front.png")],
        output_count=1,
    )

    assert generated[0].content == banana_result
    assert generated[0].content_type == "image/png"
    body = transport.requests[0].body
    assert b'name="model"\r\n\r\nnano-banana-pro-2k' in body
    assert b'name="aspect_ratio"\r\n\r\n9:16' in body
    assert b'name="image_size"\r\n\r\n2K' in body


def test_provider_rejects_malformed_or_unsupported_image_responses() -> None:
    transport = FakeApilioTransport(response_body=b'{"data":[{}]}')
    provider = ApilioImageProvider(api_key="test-key", transport=transport)

    with pytest.raises(ImageProviderFailed, match="missing image output"):
        provider.edit(
            model="gpt-image-2",
            prompt="replace the person",
            source_image=image(b"source", "image/jpeg", "source.jpg"),
            character_reference_images=[],
            output_count=1,
        )


def test_provider_rejects_image_bytes_that_do_not_match_the_reported_type() -> None:
    transport = FakeApilioTransport(
        response_body=b'{"data":[{"url":"https://cdn.example/first.png"}]}'
    )
    transport.downloads["https://cdn.example/first.png"] = (b"not-a-png", "image/png")
    provider = ApilioImageProvider(api_key="test-key", transport=transport)

    with pytest.raises(ImageProviderFailed, match="do not match"):
        provider.edit(
            model="gpt-image-2",
            prompt="replace the person",
            source_image=image(b"source", "image/jpeg", "source.jpg"),
            character_reference_images=[],
            output_count=1,
        )


def test_provider_rejects_a_response_with_the_wrong_candidate_count() -> None:
    result = base64.b64encode(png_with_dimensions(940, 1672)).decode("ascii")
    transport = FakeApilioTransport(
        response_body=(f'{{"data":[{{"b64_json":"{result}"}},{{"b64_json":"{result}"}}]}}').encode()
    )
    provider = ApilioImageProvider(api_key="test-key", transport=transport)

    with pytest.raises(ImageProviderFailed, match="unexpected number"):
        provider.edit(
            model="gpt-image-2",
            prompt="replace the person",
            source_image=image(b"source", "image/jpeg", "source.jpg"),
            character_reference_images=[],
            output_count=1,
        )


def test_provider_output_urls_require_https_and_jpeg_source_ratio_is_preserved() -> None:
    assert valid_provider_output_url("http://cdn.example/first.png") is False
    assert valid_provider_output_url("https://cdn.example/first.png") is True
    assert (
        image_aspect_ratio(image(jpeg_with_dimensions(1024, 576), "image/jpeg", "source.jpg"))
        == "16:9"
    )


def test_apilio_output_host_allows_proxy_fake_ip_without_weakening_other_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.18.0.95", 443))
        ],
    )

    require_safe_provider_download_url("https://files.closeai.fans/filesystem/output/generated.png")
    with pytest.raises(ImageProviderFailed, match="public address"):
        require_safe_provider_download_url("https://untrusted.example/generated.png")


def png_with_dimensions(width: int, height: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
    )


def test_w20_download_uses_validated_ip_and_never_the_urllib_get_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import first_frames

    resolved: list[str] = []
    connections: list[tuple[object, ...]] = []
    requests: list[tuple[object, ...]] = []
    closed: list[str] = []

    def dns(host: str, *_args, **_kwargs):
        resolved.append(host)
        ip = "93.184.216.34" if len(resolved) == 1 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]

    class Response:
        status = 200
        headers = {"Content-Type": "image/png", "Content-Length": "5"}

        def read(self, size: int) -> bytes:
            assert size == first_frames.MAX_PROVIDER_IMAGE_BYTES + 1
            return b"image"

        def close(self):
            closed.append("response")

    class Connection:
        def connect(self):
            pass

        def request(self, *args, **kwargs):
            requests.append((args, kwargs))

        def getresponse(self):
            return Response()

        def close(self):
            closed.append("connection")

    def connection_factory(*args):
        connections.append(args)
        return Connection()

    monkeypatch.setattr(socket, "getaddrinfo", dns)
    monkeypatch.setattr(first_frames, "_pinned_connection", connection_factory, raising=False)
    monkeypatch.setattr(
        first_frames.UrllibApilioTransport,
        "_open",
        lambda *_: pytest.fail("unsafe domain reconnect"),
    )
    result = first_frames.UrllibApilioTransport(timeout_seconds=7).get(
        "https://cdn.example/image.png?sig=synthetic"
    )
    assert result[0] == b"image"
    assert resolved == ["cdn.example"]
    assert connections == [("https", "cdn.example", 443, "93.184.216.34", 7)]
    assert requests[0][0] == ("GET", "/image.png?sig=synthetic")
    assert requests[0][1]["headers"]["Host"] == "cdn.example"
    assert closed == ["response", "connection"]


@pytest.mark.parametrize(
    "url", ["https://name:password@cdn.example/a.png", "https://cdn.example:8443/a.png"]
)
def test_w20_download_rejects_credentials_and_nonstandard_ports(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *_a, **_k: pytest.fail("reject URL before DNS")
    )
    with pytest.raises(ImageProviderFailed):
        require_safe_provider_download_url(url)


def test_w20_rejects_unexpected_socket_peer_before_sending(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import first_frames

    closed: list[bool] = []

    class Socket:
        def getpeername(self):
            return ("127.0.0.1", 443)

        def close(self):
            closed.append(True)

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    monkeypatch.setattr(socket, "create_connection", lambda *_a, **_k: Socket())
    with pytest.raises(ImageProviderFailed, match="not verified"):
        first_frames.UrllibApilioTransport().get("https://cdn.example/image.png")
    assert closed == [True]


@pytest.mark.parametrize(
    "addresses", [["127.0.0.1"], ["10.0.0.1"], ["169.254.169.254"], ["93.184.216.34", "127.0.0.1"]]
)
def test_w20_private_and_mixed_dns_answers_never_connect(
    addresses: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import first_frames

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in addresses
        ],
    )
    monkeypatch.setattr(
        first_frames, "_pinned_connection", lambda *_a: pytest.fail("must not connect")
    )
    with pytest.raises(ImageProviderFailed, match="public address"):
        first_frames.UrllibApilioTransport().get("https://cdn.example/image.png")


@pytest.mark.parametrize(
    "response_case", ["ok", "redirect", "declared_too_large", "body_too_large"]
)
def test_w20_address_fallback_preserves_download_guards(
    response_case: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import first_frames

    dns_calls: list[bool] = []
    connected: list[str] = []
    closed: list[str] = []
    read_sizes: list[int] = []
    monkeypatch.setattr(first_frames, "MAX_PROVIDER_IMAGE_BYTES", 4)

    def dns(*_a, **_k):
        dns_calls.append(True)
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))
            for ip in ["93.184.216.34", "93.184.216.35"]
        ]

    class Response:
        status = 302 if response_case == "redirect" else 200
        headers = {
            "Content-Length": "5" if response_case == "declared_too_large" else "4",
            "Location": "https://127.0.0.1/internal",
        }

        def read(self, size):
            read_sizes.append(size)
            return b"abcde" if response_case == "body_too_large" else b"abcd"

        def close(self):
            closed.append("response")

    class Connection:
        def __init__(self, ip):
            self.ip = ip

        def connect(self):
            connected.append(self.ip)
            if self.ip.endswith("34"):
                raise OSError("synthetic unreachable address")

        def request(self, *_a, **_k):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            closed.append(self.ip)

    monkeypatch.setattr(socket, "getaddrinfo", dns)
    monkeypatch.setattr(
        first_frames, "_pinned_connection", lambda _s, _h, _p, ip, _t: Connection(ip)
    )
    transport = first_frames.UrllibApilioTransport()
    if response_case == "ok":
        assert transport.get("https://cdn.example/image.png")[0] == b"abcd"
    else:
        with pytest.raises(ImageProviderFailed):
            transport.get("https://cdn.example/image.png")
    assert dns_calls == [True]
    assert connected == ["93.184.216.34", "93.184.216.35"]
    assert closed == ["93.184.216.34", "response", "93.184.216.35"]
    assert read_sizes == ([] if response_case in {"redirect", "declared_too_large"} else [5])


def jpeg_with_dimensions(width: int, height: int) -> bytes:
    return (
        b"\xff\xd8"
        + b"\xff\xc0\x00\x11\x08"
        + height.to_bytes(2, "big")
        + width.to_bytes(2, "big")
        + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00\xff\xd9"
    )


@pytest.mark.parametrize("resuming", [False, True])
def test_first_frame_quality_timeout_delivers_paid_checkpoint_without_regeneration(resuming):
    from types import SimpleNamespace

    from app.first_frames import (
        FakeFirstFrameQualityInspector,
        FirstFrameQualityInspectorFailed,
        GeneratedImage,
        perform_first_frame_generation,
    )

    class Inspector(FakeFirstFrameQualityInspector):
        def inspect_source(self, source_image):
            assert not resuming, "do not repeat the completed source inspection"
            return super().inspect_source(source_image)

        def inspect_candidate(self, **kwargs):
            raise FirstFrameQualityInspectorFailed("timed out")

    class Provider:
        calls = 0

        def edit(self, **kwargs):
            self.calls += 1
            return [GeneratedImage(content=b"paid-image", content_type="image/png")]

    provider = Provider()
    work = SimpleNamespace(
        source_image=image(b"source", "image/png", "source.png"),
        reference_images=[image(b"reference", "image/png", "ref.png")],
        quantity=1,
        model="gpt-image-2",
        effective_prompt="replace person",
        project_appearance=SimpleNamespace(
            outfit_description="workwear", appearance_source="VIDEO_ANALYSIS"
        ),
    )
    checkpoints = []
    result = perform_first_frame_generation(
        work,
        provider=provider,
        quality_inspector=Inspector(),
        resumed_candidates=[
            GeneratedImage(content=b"paid-image", content_type="image/png", quality_attempt=1)
        ]
        if resuming
        else None,
        checkpoint_candidates=lambda values: checkpoints.append(list(values)),
    )
    assert provider.calls == (0 if resuming else 1)
    assert len(result) == 1 and result[0].content == b"paid-image"
    assert result[0].quality is None
    if not resuming:
        assert checkpoints[-1][0].content == b"paid-image"


def test_first_frame_quality_has_separate_single_attempt_budget():
    from app.first_frames import (
        ApilioFirstFrameQualityInspector,
        bounded_first_frame_quality_inspector,
    )

    original = ApilioFirstFrameQualityInspector(api_key="test-key")
    bounded = bounded_first_frame_quality_inspector(original)
    assert bounded.transport.timeout_seconds == 60
    assert bounded.max_attempts == 1
    assert original.transport.timeout_seconds == 240
    assert original.max_attempts == 2


@pytest.mark.parametrize("resuming", [False, True])
def test_scene_replacement_has_no_ai_review_or_automatic_regeneration(resuming):
    from types import SimpleNamespace

    from app.first_frames import GeneratedImage, perform_first_frame_generation

    class Inspector:
        def inspect_source(self, *args, **kwargs):
            pytest.fail("scene workflow must reuse validated source selection")

        def inspect_candidate(self, *args, **kwargs):
            pytest.fail("scene output is reviewed by its user")

    class Provider:
        calls = 0

        def edit(self, **kwargs):
            self.calls += 1
            return [GeneratedImage(content=b"scene-result", content_type="image/png")]

    provider = Provider()
    work = SimpleNamespace(
        source_image=image(b"source", "image/png", "source.png"),
        reference_images=[image(b"scene", "image/png", "scene.png")],
        quantity=1,
        model="gpt-image-2",
        effective_prompt="replace person",
        project_appearance=SimpleNamespace(appearance_source="SCENE_LOOK"),
    )
    checkpoints = []
    result = perform_first_frame_generation(
        work,
        provider=provider,
        quality_inspector=Inspector(),
        resumed_candidates=[
            GeneratedImage(content=b"scene-result", content_type="image/png", quality_attempt=1)
        ]
        if resuming
        else None,
        checkpoint_candidates=lambda values: checkpoints.append(list(values)),
    )
    assert provider.calls == (0 if resuming else 1)
    assert len(result) == 1 and result[0].quality is None
    if not resuming:
        assert checkpoints[-1] == result


def test_scene_reference_never_adds_identity_original_photo():
    import json
    from types import SimpleNamespace

    from app.first_frames import effective_reference_asset_ids

    conn = SimpleNamespace(
        execute=lambda *args: SimpleNamespace(
            fetchone=lambda: {
                "snapshot_json": json.dumps({"contact_sheet_asset_id": "scene-sheet"}),
                "persona_snapshot_json": json.dumps(
                    {"appearance_constraints_json": {"appearance_type": "scene"}}
                ),
                "source_asset_id": "original-identity-photo",
            }
        )
    )
    assert effective_reference_asset_ids(
        conn, character_version_id="scene-version", legacy_selected=["scene-front"]
    ) == (["scene-sheet"], ["scene_image"])


def test_scene_prompt_uses_images_even_without_scene_text():
    from app.first_frames import (
        _apply_scene_look_snapshot,
        derive_project_appearance_spec,
        normalize_prompt,
    )

    appearance = _apply_scene_look_snapshot(
        derive_project_appearance_spec(
            analysis_payload={}, source_analysis_version_id=None, source_timestamp_seconds=None
        ),
        character_snapshot={
            "persona_snapshot_json": {
                "name": "selected scene",
                "appearance_constraints_json": {"appearance_type": "scene"},
            }
        },
        character_version_id="scene-version",
    )
    assert appearance.appearance_source == "SCENE_LOOK"
    prompt = normalize_prompt(
        None,
        character_name="selected scene",
        reference_roles=["scene_image"],
        project_appearance=appearance,
    )
    assert "唯一外观依据" in prompt
    assert "禁止模糊补边" in prompt
    assert "原有字幕、文字和标识保持原样" in prompt
    assert "原始照片" not in prompt
    assert "后台自动匹配" not in prompt


def test_scene_provider_timeout_does_not_resubmit_paid_generation():
    from types import SimpleNamespace

    from fastapi import HTTPException

    from app.first_frames import RetryableImageProviderFailed, perform_first_frame_generation

    calls = []
    completed = []

    class Provider:
        def edit(self, **kwargs):
            calls.append(kwargs)
            raise RetryableImageProviderFailed("response timed out")

    work = SimpleNamespace(
        source_image=image(b"source", "image/png", "source.png"),
        reference_images=[image(b"scene", "image/png", "scene.png")],
        quantity=1,
        model="gpt-image-2",
        effective_prompt="replace person",
        project_appearance=SimpleNamespace(appearance_source="SCENE_LOOK"),
    )
    with pytest.raises(HTTPException):
        perform_first_frame_generation(
            work, provider=Provider(), after_provider_call=lambda: completed.append(True)
        )
    assert len(calls) == 1
    assert completed == [], "an unanswered submission must remain uncertain"


def test_async_edit_receipt_precedes_poll_and_uses_separate_authenticated_get():
    transport = FakeApilioTransport(response_body=b'{"task_id":"task-123"}')
    provider = ApilioImageProvider(api_key="test-key", transport=transport)
    task_id = provider.submit_edit(
        model="gpt-image-2",
        prompt="replace person",
        source_image=image(b"source", "image/png", "source.png"),
        character_reference_images=[image(b"scene", "image/png", "scene.png")],
        output_count=1,
    )
    assert task_id == "task-123"
    assert transport.requests[0].url.endswith("/v1/images/edits?async=true")
    output = png_with_dimensions(940, 1672)
    transport.response_body = json.dumps(
        {
            "code": "success",
            "data": {
                "task_id": task_id,
                "status": "SUCCESS",
                "data": {"data": [{"url": "https://cdn.example/async.png"}]},
            },
        }
    ).encode()
    transport.downloads["https://cdn.example/async.png"] = (output, "image/png")
    assert provider.poll_edit(task_id, output_count=1)[0].content == output
    request = transport.requests[-1]
    assert request.url == "https://api.apilio.ai/v1/images/tasks/task-123"
    assert request.headers["Authorization"] == "Bearer test-key"
    assert request.body == b""


@pytest.mark.parametrize("task_id", ["../tokens", "https://other.example/x", "a?x=y", ""])
def test_async_edit_rejects_unsafe_task_ids_before_network(task_id):
    transport = FakeApilioTransport(response_body=b"{}")
    provider = ApilioImageProvider(api_key="test-key", transport=transport)
    with pytest.raises(ImageProviderFailed):
        provider.poll_edit(task_id, output_count=1)
    assert transport.requests == []


def test_async_edit_pending_failure_and_mismatched_receipt():
    from fastapi import HTTPException

    transport = FakeApilioTransport(response_body=b"{}")
    provider = ApilioImageProvider(api_key="test-key", transport=transport)
    transport.response_body = b'{"code":"success","data":{"task_id":"t1","status":"IN_PROGRESS"}}'
    assert provider.poll_edit("t1", output_count=1) is None
    transport.response_body = b'{"code":"success","data":{"task_id":"other","status":"SUCCESS"}}'
    with pytest.raises(ImageProviderFailed):
        provider.poll_edit("t1", output_count=1)
    transport.response_body = (
        b'{"code":"success","data":{"task_id":"t1","status":"FAILURE","fail_reason":"secret"}}'
    )
    with pytest.raises(HTTPException) as failed:
        provider.poll_edit("t1", output_count=1)
    assert failed.value.status_code == 422
    assert "secret" not in str(failed.value.detail)


def test_async_scene_persists_receipt_before_poll_and_resume_never_posts(monkeypatch):
    from types import SimpleNamespace

    from app.first_frames import generate_scene_async

    transport = FakeApilioTransport(response_body=b'{"task_id":"scene-task"}')
    provider = ApilioImageProvider(api_key="test-key", transport=transport)
    work = SimpleNamespace(
        model="gpt-image-2",
        effective_prompt="replace person",
        source_image=image(b"source", "image/png", "source.png"),
        reference_images=[image(b"scene", "image/png", "scene.png")],
        quantity=1,
    )
    receipt = {}
    events = []

    def save(value):
        receipt.update(value)
        events.append("save")

    def poll(task_id, *, output_count):
        assert receipt["task_id"] == task_id
        events.append("poll")
        return [object()]

    monkeypatch.setattr(provider, "poll_edit", poll)
    for saved in (None, receipt):
        generate_scene_async(
            work,
            provider=provider,
            submission=saved,
            save_submission=save,
            before_paid_call=lambda: events.append("post"),
            heartbeat=lambda: None,
        )
    assert events == ["post", "save", "poll", "poll"]
    assert len(transport.requests) == 1


def test_async_scene_failed_receipt_write_never_polls(monkeypatch):
    from types import SimpleNamespace

    from app.first_frames import generate_scene_async

    provider = ApilioImageProvider(api_key="test-key")
    monkeypatch.setattr(provider, "submit_edit", lambda **kwargs: "scene-task")
    monkeypatch.setattr(
        provider, "poll_edit", lambda *args, **kwargs: pytest.fail("uncommitted receipt polled")
    )
    work = SimpleNamespace(
        model="gpt-image-2",
        effective_prompt="replace",
        source_image=image(b"source", "image/png", "source.png"),
        reference_images=[],
        quantity=1,
    )

    def save(value):
        raise RuntimeError("lease lost")

    with pytest.raises(RuntimeError, match="lease lost"):
        generate_scene_async(
            work,
            provider=provider,
            submission=None,
            save_submission=save,
            before_paid_call=lambda: None,
            heartbeat=None,
        )


def test_apilio_accepts_typed_data_uri_in_b64_json():
    output = png_with_dimensions(940, 1672)
    transport = FakeApilioTransport(
        response_body=json.dumps(
            {"data": [{"b64_json": "data:image/png;base64," + base64.b64encode(output).decode()}]}
        ).encode()
    )
    provider = ApilioImageProvider(api_key="test-key", transport=transport)
    assert provider._parse_response(transport.response_body, output_count=1)[0].content == output


@pytest.mark.parametrize(
    "header",
    [
        "data:text/html;base64,",
        "data:image/svg+xml;base64,",
        "data:image/png,",
        "data:image/jpeg;base64,",
    ],
)
def test_apilio_data_uri_rejects_unsupported_or_mismatched_type(header):
    output = png_with_dimensions(940, 1672)
    transport = FakeApilioTransport(response_body=b"{}")
    provider = ApilioImageProvider(api_key="test-key", transport=transport)
    with pytest.raises(ImageProviderFailed):
        provider._parse_image({"b64_json": header + base64.b64encode(output).decode()})


@pytest.mark.parametrize(
    "ratio,size",
    [
        ("9:16", "1008x1792"),
        ("16:9", "1792x1008"),
        ("1:1", "1024x1024"),
        ("3:4", "1152x1536"),
        ("4:3", "1536x1152"),
    ],
)
def test_selected_aspect_ratio_is_sent_to_provider_and_validated_by_api(ratio, size):
    from app.first_frame_routes import GenerateFirstFramesRequest

    assert GenerateFirstFramesRequest(aspect_ratio=ratio).aspect_ratio == ratio
    transport = FakeApilioTransport(response_body=b'{"task_id":"ratio-task"}')
    provider = ApilioImageProvider(api_key="test-key", transport=transport)
    for model in ("gpt-image-2", "nano-banana-pro-2k"):
        provider.submit_edit(
            model=model,
            prompt="replace",
            source_image=image(b"x", "image/png", "x.png"),
            character_reference_images=[],
            output_count=1,
            aspect_ratio=ratio,
        )
        body = transport.requests[-1].body
        field = (
            f'name="size"\r\n\r\n{size}'
            if model == "gpt-image-2"
            else f'name="aspect_ratio"\r\n\r\n{ratio}'
        )
        assert field.encode() in body


def test_aspect_ratio_api_rejects_arbitrary_dimensions():
    from pydantic import ValidationError

    from app.first_frame_routes import GenerateFirstFramesRequest

    with pytest.raises(ValidationError):
        GenerateFirstFramesRequest(aspect_ratio="9999:1")
