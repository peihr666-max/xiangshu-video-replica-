from __future__ import annotations

import base64
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
