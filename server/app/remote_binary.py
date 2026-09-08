from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from collections.abc import Mapping
from contextlib import closing
from io import BytesIO
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler


class RemoteBinaryError(RuntimeError):
    pass


def require_public_https_url(url: str) -> frozenset[str]:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise RemoteBinaryError("remote URL must be public HTTPS")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise RemoteBinaryError("remote hostname could not be resolved") from exc
    resolved = frozenset(str(item[4][0]) for item in addresses)
    if not resolved or any(not ipaddress.ip_address(address).is_global for address in resolved):
        raise RemoteBinaryError("remote hostname must resolve only to public addresses")
    return resolved


class _SafeRedirectHandler(HTTPRedirectHandler):
    """Compatibility seam; production redirects are handled by the pinned client below."""

    def __init__(self, *, origin: tuple[str, str, int], has_authorization: bool) -> None:
        super().__init__()
        self._origin = origin
        self._has_authorization = has_authorization

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        require_public_https_url(newurl)
        if self._has_authorization and _origin(newurl) != self._origin:
            raise RemoteBinaryError("authenticated requests cannot redirect across origins")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _origin(url: str) -> tuple[str, str, int]:
    parsed = urlsplit(url)
    return parsed.scheme, parsed.hostname or "", parsed.port or 443


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """TLS connection pinned to a public DNS answer before sensitive bytes are sent."""

    def __init__(self, host: str, *, port: int, peer_ip: str, timeout: float) -> None:
        self._tls_context = ssl.create_default_context()
        super().__init__(host, port=port, timeout=timeout, context=self._tls_context)
        self._peer_ip = peer_ip
        self.connected_peer_ip: str | None = None

    def connect(self) -> None:
        sock = socket.create_connection((self._peer_ip, self.port), self.timeout)
        try:
            self.sock = self._tls_context.wrap_socket(sock, server_hostname=self.host)
            actual_peer = str(self.sock.getpeername()[0])
            if actual_peer != self._peer_ip or not ipaddress.ip_address(actual_peer).is_global:
                raise RemoteBinaryError("remote peer does not match validated public DNS")
            self.connected_peer_ip = actual_peer
        except BaseException:
            if self.sock is not None:
                self.sock.close()
            else:
                sock.close()
            raise


def _open_pinned_connection(
    host: str, *, port: int, peer_ip: str, timeout: float
) -> _PinnedHTTPSConnection:
    return _PinnedHTTPSConnection(host, port=port, peer_ip=peer_ip, timeout=timeout)


def _read_bounded(response: http.client.HTTPResponse, max_bytes: int) -> bytes:
    content_length = response.headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise RemoteBinaryError("remote body exceeds size limit")
        except ValueError as exc:
            raise RemoteBinaryError("remote content length is invalid") from exc
    content = response.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise RemoteBinaryError("remote body exceeds size limit")
    return bytes(content)


def request_public_binary(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str],
    body: bytes | None = None,
    timeout_seconds: float,
    max_bytes: int,
    allowed_content_prefixes: tuple[str, ...] = (),
) -> bytes:
    current_url = url
    original_origin = _origin(url)
    has_authorization = any(key.lower() == "authorization" for key in headers)
    for redirect_count in range(6):
        parsed = urlsplit(current_url)
        addresses = require_public_https_url(current_url)
        peer_ip = sorted(addresses)[0]
        host = parsed.hostname or ""
        port = parsed.port or 443
        path = parsed.path or "/"
        if parsed.query:
            path += f"?{parsed.query}"
        connection = _open_pinned_connection(
            host, port=port, peer_ip=peer_ip, timeout=timeout_seconds
        )
        with closing(connection):
            request_headers = dict(headers)
            request_headers.setdefault("Host", host if port == 443 else f"{host}:{port}")
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            actual_peer = connection.connected_peer_ip or ""
            if actual_peer != peer_ip or not ipaddress.ip_address(actual_peer).is_global:
                raise RemoteBinaryError("remote peer does not match validated public DNS")
            if response.status in {301, 302, 303, 307, 308}:
                if has_authorization or body is not None or method not in {"GET", "HEAD"}:
                    raise RemoteBinaryError("sensitive remote requests cannot redirect")
                location = response.headers.get("Location")
                if not location or redirect_count == 5:
                    raise RemoteBinaryError("remote redirect is invalid or too deep")
                redirected = urljoin(current_url, location)
                require_public_https_url(redirected)
                if _origin(redirected) != original_origin:
                    raise RemoteBinaryError("remote requests cannot redirect across origins")
                current_url = redirected
                if response.status == 303:
                    method, body = "GET", None
                continue
            if response.status >= 400:
                content = _read_bounded(response, min(max_bytes, 1_000_000))
                raise HTTPError(
                    current_url,
                    response.status,
                    response.reason,
                    response.headers,
                    BytesIO(content),
                )
            content_type = response.headers.get_content_type().lower()
            if allowed_content_prefixes and not any(
                content_type.startswith(prefix) for prefix in allowed_content_prefixes
            ):
                raise RemoteBinaryError("remote content type is not allowed")
            return _read_bounded(response, max_bytes)
    raise RemoteBinaryError("remote redirect is too deep")
