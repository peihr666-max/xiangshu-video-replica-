from __future__ import annotations

from email.message import Message
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from app.remote_binary import (
    RemoteBinaryError,
    _SafeRedirectHandler,
    request_public_binary,
    require_public_https_url,
)


def _addresses(ip: str):
    return [(2, 1, 6, "", (ip, 443))]


class _Response:
    def __init__(
        self,
        content: bytes,
        *,
        status: int = 200,
        content_type: str = "video/mp4",
        location: str | None = None,
    ) -> None:
        self._content = content
        self.status = status
        self.reason = "test"
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        if location:
            self.headers["Location"] = location

    def read(self, size: int) -> bytes:
        return self._content[:size]


class _Connection:
    def __init__(self, response: _Response, *, peer_ip: str) -> None:
        self.response = response
        self.connected_peer_ip = peer_ip
        self.request_args = None

    def request(self, *args, **kwargs) -> None:
        self.request_args = (args, kwargs)

    def getresponse(self) -> _Response:
        return self.response

    def close(self) -> None:
        pass


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


def test_remote_binary_pins_tcp_connection_to_validated_ip_before_request(monkeypatch):
    monkeypatch.setattr(
        "app.remote_binary.socket.getaddrinfo", lambda *_a, **_kw: _addresses("93.184.216.34")
    )
    observed = {}
    connection = _Connection(_Response(b"video"), peer_ip="93.184.216.34")

    def open_connection(host, *, port, peer_ip, timeout):
        observed.update(host=host, port=port, peer_ip=peer_ip, timeout=timeout)
        return connection

    monkeypatch.setattr("app.remote_binary._open_pinned_connection", open_connection)
    assert (
        request_public_binary(
            "GET", "https://cdn.example/v.mp4", headers={}, timeout_seconds=1, max_bytes=100
        )
        == b"video"
    )
    assert observed == {
        "host": "cdn.example",
        "port": 443,
        "peer_ip": "93.184.216.34",
        "timeout": 1,
    }
    assert connection.request_args is not None


def test_remote_binary_stops_after_configured_size_limit(monkeypatch):
    monkeypatch.setattr(
        "app.remote_binary.socket.getaddrinfo", lambda *_a, **_kw: _addresses("93.184.216.34")
    )
    monkeypatch.setattr(
        "app.remote_binary._open_pinned_connection",
        lambda *_a, **_kw: _Connection(_Response(b"x" * 11), peer_ip="93.184.216.34"),
    )
    with pytest.raises(RemoteBinaryError, match="size"):
        request_public_binary(
            "GET", "https://cdn.example/v.mp4", headers={}, timeout_seconds=1, max_bytes=10
        )


def test_remote_binary_validates_peer_even_for_http_error(monkeypatch):
    monkeypatch.setattr(
        "app.remote_binary.socket.getaddrinfo", lambda *_a, **_kw: _addresses("93.184.216.34")
    )
    monkeypatch.setattr(
        "app.remote_binary._open_pinned_connection",
        lambda *_a, **_kw: _Connection(_Response(b"bad", status=503), peer_ip="10.0.0.8"),
    )
    with pytest.raises(RemoteBinaryError, match="peer"):
        request_public_binary(
            "GET", "https://cdn.example/v.mp4", headers={}, timeout_seconds=1, max_bytes=100
        )


def test_http_error_is_raised_only_after_public_peer_validation(monkeypatch):
    monkeypatch.setattr(
        "app.remote_binary.socket.getaddrinfo", lambda *_a, **_kw: _addresses("93.184.216.34")
    )
    monkeypatch.setattr(
        "app.remote_binary._open_pinned_connection",
        lambda *_a, **_kw: _Connection(_Response(b"busy", status=429), peer_ip="93.184.216.34"),
    )
    with pytest.raises(HTTPError) as excinfo:
        request_public_binary(
            "POST",
            "https://api.example/tasks",
            headers={"Authorization": "Bearer secret"},
            body=b"{}",
            timeout_seconds=1,
            max_bytes=100,
        )
    assert excinfo.value.code == 429


def test_sensitive_request_rejects_all_redirects(monkeypatch):
    monkeypatch.setattr(
        "app.remote_binary.socket.getaddrinfo", lambda *_a, **_kw: _addresses("93.184.216.34")
    )
    monkeypatch.setattr(
        "app.remote_binary._open_pinned_connection",
        lambda *_a, **_kw: _Connection(
            _Response(b"", status=307, location="https://api.example/next"),
            peer_ip="93.184.216.34",
        ),
    )
    with pytest.raises(RemoteBinaryError, match="cannot redirect"):
        request_public_binary(
            "POST",
            "https://api.example/tasks",
            headers={"Authorization": "Bearer secret"},
            body=b"{}",
            timeout_seconds=1,
            max_bytes=100,
        )


def test_authenticated_redirect_cannot_cross_origin(monkeypatch):
    monkeypatch.setattr(
        "app.remote_binary.socket.getaddrinfo", lambda *_a, **_kw: _addresses("93.184.216.34")
    )
    handler = _SafeRedirectHandler(origin=("https", "api.example", 443), has_authorization=True)
    with pytest.raises(RemoteBinaryError, match="origins"):
        handler.redirect_request(
            Request("https://api.example/start"),
            None,
            302,
            "Found",
            {},
            "https://cdn.example/result",
        )
