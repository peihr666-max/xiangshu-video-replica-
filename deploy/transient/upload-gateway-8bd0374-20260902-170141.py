#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path("/opt/video-replica-candidate")
HOST = "0.0.0.0"
PORT = 39001
ALLOWED_IPS = {"103.85.74.27", "182.96.53.123"}
EXPIRES_AT = time.time() + 3 * 60 * 60
DEPLOY_SCRIPT = "deploy-v0.1.12-8bd0374-20260902-170141.sh"
RUN_LOG = ROOT / "gateway-run-v0.1.12-8bd0374-20260902-170141.log"
PID_FILE = ROOT / "gateway-run-v0.1.12-8bd0374-20260902-170141.pid"
STATUS_FILE = ROOT / "deploy-v0.1.12-20260902-170141.status"
DEPLOY_LOG = ROOT / "deploy-v0.1.12-20260902-170141.log"
EXPECTED = {
    "client-dist-v0.1.12-8bd0374-20260902-170141.tar.gz": {
        "size": 1683061,
        "sha256": "ec7b6f6ac70b205506d795ae387deee795266492b83b4eedf72d33713658ade3",
    },
    "deploy-v0.1.12-8bd0374-20260902-170141.sh": {
        "size": 10789,
        "sha256": "eba6bba59f66197b03933887787fe9bc665c6b39e42f766c012528cdfdf21b08",
    },
    "server-runtime-full-v0.1.12-8bd0374-20260902-170141.tar.gz": {
        "size": 459360,
        "sha256": "db6b1a7c755d7247e172f3d42bc451ee0c67a09a91a8ffa2743706953ca4b6a8",
    },
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_file(name: str) -> dict[str, object]:
    path = ROOT / name
    if not path.is_file():
        return {"present": False}
    spec = EXPECTED[name]
    size = path.stat().st_size
    sha256 = file_sha256(path)
    return {
        "present": True,
        "size": size,
        "sha256": sha256,
        "valid": size == spec["size"] and sha256 == spec["sha256"],
    }


def tail(path: Path, limit: int = 20000) -> str:
    if not path.is_file():
        return ""
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - limit))
        return handle.read().decode("utf-8", errors="replace")


def running_pid() -> int | None:
    if not PID_FILE.is_file():
        return None
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


class Handler(BaseHTTPRequestHandler):
    server_version = "VideoReplicaUpload/1.1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        if time.time() >= EXPIRES_AT:
            self._json(410, {"ok": False, "error": "gateway_expired"})
            return False
        if self.client_address[0] not in ALLOWED_IPS:
            self._json(
                403,
                {
                    "ok": False,
                    "error": "forbidden",
                    "source_ip": self.client_address[0],
                },
            )
            return False
        return True

    def do_GET(self) -> None:
        if not self._authorized():
            return
        path = urlsplit(self.path).path
        if path == "/inspect":
            self._json(
                200,
                {
                    "ok": True,
                    "expires_in_seconds": max(0, int(EXPIRES_AT - time.time())),
                    "files": {name: inspect_file(name) for name in EXPECTED},
                },
            )
            return
        if path == "/status":
            status = (
                STATUS_FILE.read_text(encoding="utf-8").strip()
                if STATUS_FILE.is_file()
                else "NOT_STARTED"
            )
            self._json(
                200,
                {
                    "ok": True,
                    "status": status,
                    "running_pid": running_pid(),
                    "deploy_log": tail(DEPLOY_LOG),
                    "run_log": tail(RUN_LOG),
                },
            )
            return
        self._json(404, {"ok": False, "error": "not_found"})

    def do_PUT(self) -> None:
        if not self._authorized():
            return
        name = unquote(urlsplit(self.path).path.lstrip("/"))
        if name not in EXPECTED or "/" in name or "\\" in name:
            self._json(404, {"ok": False, "error": "unknown_file"})
            return
        spec = EXPECTED[name]
        try:
            content_length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            content_length = -1
        if content_length != spec["size"]:
            self._json(400, {"ok": False, "error": "size_mismatch"})
            return

        ROOT.mkdir(parents=True, exist_ok=True)
        target = ROOT / name
        part = ROOT / f".{name}.part"
        digest = hashlib.sha256()
        remaining = content_length
        try:
            with part.open("wb") as handle:
                while remaining:
                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise OSError("unexpected end of upload")
                    handle.write(chunk)
                    digest.update(chunk)
                    remaining -= len(chunk)
            if digest.hexdigest() != spec["sha256"]:
                raise OSError("sha256 mismatch")
            os.replace(part, target)
        except OSError as exc:
            part.unlink(missing_ok=True)
            self._json(400, {"ok": False, "error": str(exc)})
            return
        self._json(200, {"ok": True, "file": name})

    def do_POST(self) -> None:
        if not self._authorized():
            return
        if urlsplit(self.path).path != "/run":
            self._json(404, {"ok": False, "error": "not_found"})
            return
        invalid = [name for name in EXPECTED if not inspect_file(name).get("valid")]
        if invalid:
            self._json(409, {"ok": False, "error": "files_invalid", "files": invalid})
            return
        pid = running_pid()
        if pid is not None:
            self._json(409, {"ok": False, "error": "already_running", "pid": pid})
            return
        STATUS_FILE.unlink(missing_ok=True)
        with RUN_LOG.open("ab", buffering=0) as output:
            process = subprocess.Popen(
                ["bash", str(ROOT / DEPLOY_SCRIPT)],
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        PID_FILE.write_text(str(process.pid), encoding="utf-8")
        self._json(202, {"ok": True, "pid": process.pid})


def shutdown_after_expiry(server: ThreadingHTTPServer) -> None:
    time.sleep(max(0, EXPIRES_AT - time.time()))
    server.shutdown()


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    threading.Thread(target=shutdown_after_expiry, args=(server,), daemon=True).start()

    def stop(_signum: int, _frame: object) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    server.serve_forever(poll_interval=0.5)
    server.server_close()


if __name__ == "__main__":
    main()

