from __future__ import annotations

import ipaddress
import socket
from collections.abc import Mapping
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class RemoteBinaryError(RuntimeError):
    pass


def require_public_https_url(url: str) -> None:
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
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise RemoteBinaryError("remote hostname must resolve only to public addresses")


class _SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        require_public_https_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


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
    with build_opener(_SafeRedirectHandler()).open(request, timeout=timeout_seconds) as response:
        require_public_https_url(response.geturl())
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
