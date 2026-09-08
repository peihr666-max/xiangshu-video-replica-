from __future__ import annotations

import ipaddress
import socket
from collections.abc import Mapping
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


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


def _peer_ip(response: object) -> str:
    explicit = getattr(response, "peer_ip", None)
    if isinstance(explicit, str):
        return explicit
    try:
        peer = response.fp.raw._sock.getpeername()  # type: ignore[attr-defined]
    except (AttributeError, OSError) as exc:
        raise RemoteBinaryError("remote peer address is unavailable") from exc
    if not isinstance(peer, tuple) or not peer or not isinstance(peer[0], str):
        raise RemoteBinaryError("remote peer address is unavailable")
    return peer[0]


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
    require_public_https_url(url)
    request = Request(url, data=body, headers=dict(headers), method=method)
    has_authorization = any(key.lower() == "authorization" for key in headers)
    handler = _SafeRedirectHandler(origin=_origin(url), has_authorization=has_authorization)
    with build_opener(handler).open(request, timeout=timeout_seconds) as response:
        final_addresses = require_public_https_url(response.geturl())
        peer_ip = _peer_ip(response)
        if peer_ip not in final_addresses or not ipaddress.ip_address(peer_ip).is_global:
            raise RemoteBinaryError("remote peer does not match validated public DNS")
        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                if int(content_length) > max_bytes:
                    raise RemoteBinaryError("remote body exceeds size limit")
            except ValueError as exc:
                raise RemoteBinaryError("remote content length is invalid") from exc
        content_type = response.headers.get_content_type().lower()
        if allowed_content_prefixes and not any(
            content_type.startswith(prefix) for prefix in allowed_content_prefixes
        ):
            raise RemoteBinaryError("remote content type is not allowed")
        content = response.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise RemoteBinaryError("remote body exceeds size limit")
        return bytes(content)
