from __future__ import annotations

from email.message import Message
from types import SimpleNamespace

import pytest

from app.remote_binary import RemoteBinaryError, request_public_binary, require_public_https_url


def _addresses(ip: str):
    return [(2, 1, 6, "", (ip, 443))]


class _Response:
    def __init__(self, url: str, content: bytes, *, content_type: str = "video/mp4") -> None:
        self._url = url
        self._content = content
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def geturl(self) -> str:
        return self._url

    def read(self, size: int) -> bytes:
        return self._content[:size]


@pytest.mark.parametrize(
    "url,ip",
    [
        ("http://cdn.example/v.mp4", "93.184.216.34"),
        ("https://127.0.0.1/v.mp4", "127.0.0.1"),
        ("https://cdn.example/v.mp4", "10.0.0.8"),
        ("https://cdn.example/v.mp4", "169.254.1.1"),
        ("https://cdn.example/v.mp4", "::1"),
    ],
)
def test_remote_binary_rejects_non_https_and_non_public_hosts(monkeypatch, url, ip):
    monkeypatch.setattr("app.remote_binary.socket.getaddrinfo", lambda *_a, **_kw: _addresses(ip))
    with pytest.raises(RemoteBinaryError):
        require_public_https_url(url)


def test_remote_binary_revalidates_final_destination_against_dns_change(monkeypatch):
    answers = iter((_addresses("93.184.216.34"), _addresses("10.0.0.8")))
    monkeypatch.setattr("app.remote_binary.socket.getaddrinfo", lambda *_a, **_kw: next(answers))
    response = _Response("https://cdn.example/v.mp4", b"video")
    monkeypatch.setattr(
        "app.remote_binary.build_opener",
        lambda *_a: SimpleNamespace(open=lambda *_a, **_kw: response),
    )

    with pytest.raises(RemoteBinaryError, match="public"):
        request_public_binary(
            "GET",
            "https://cdn.example/v.mp4",
            headers={},
            timeout_seconds=1,
            max_bytes=100,
        )


def test_remote_binary_stops_after_configured_size_limit(monkeypatch):
    monkeypatch.setattr(
        "app.remote_binary.socket.getaddrinfo",
        lambda *_a, **_kw: _addresses("93.184.216.34"),
    )
    response = _Response("https://cdn.example/v.mp4", b"x" * 11)
    monkeypatch.setattr(
        "app.remote_binary.build_opener",
        lambda *_a: SimpleNamespace(open=lambda *_a, **_kw: response),
    )

    with pytest.raises(RemoteBinaryError, match="size"):
        request_public_binary(
            "GET",
            "https://cdn.example/v.mp4",
            headers={},
            timeout_seconds=1,
            max_bytes=10,
        )
