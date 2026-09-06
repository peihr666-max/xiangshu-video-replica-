"""Standalone publish worker: drains queued publishes and account probes.

Delivering one video blocks for minutes (upload, platform transcode wait,
create), so publishing runs in its own process instead of the generation
worker's serial loop — a slow publish must never stall H3 polling or oral
tasks. The claim/finalize CAS pattern is shared with ``app.publish``; the
platform delivery I/O happens inside the adapters with no database
transaction open. The heavy vendor/adapters imports are function-local so
this module can also be imported for tests without Node/curl_cffi present.
"""

from __future__ import annotations

import argparse
import logging
import os
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

from app.db import connect_database
from app.db_pg import (
    DatabaseMode,
    check_pg_ready,
    resolve_database_config,
    validate_customer_production,
)
from app.db_portable import BusinessConnection
from app.media import storage_key_from_uri
from app.media_routes import get_media_storage
from app.publish import (
    PublishCredentialError,
    PublishLease,
    PublishLeaseLostError,
    claim_account_verify_work,
    claim_publish_work,
    finalize_account_verify,
    finalize_publish_work,
    prepare_publish_work,
)
from app.publishers.base import PublishResult
from app.settings import fernet_from_environment
from app.storage import StorageAdapter

logger = logging.getLogger(__name__)


def _write_temp(payload: bytes, suffix: str) -> Path:
    handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 - cleaned by caller
        prefix="publish-", suffix=suffix, delete=False
    )
    try:
        handle.write(payload)
    finally:
        handle.close()
    return Path(handle.name)


def _suffix_of(uri: str, default: str) -> str:
    name = uri.rsplit("/", 1)[-1]
    ext = Path(name).suffix.lower()
    return ext if ext else default


def _dispatch_probe(
    platform: str, cookie: str, security_sdk: str | None
) -> tuple[bool, str | None]:
    if platform == "douyin":
        from app.publishers import douyin_adapter

        return douyin_adapter.probe_douyin(cookie, security_sdk)
    from app.publishers import channels_adapter

    return channels_adapter.probe_channels(cookie)


def _dispatch_publish(
    platform: str,
    *,
    cookie: str,
    security_sdk: str | None,
    video_path: Path,
    title: str,
    description: str,
    tags: list[str],
    cover_path: Path | None,
) -> PublishResult:
    if platform == "douyin":
        from app.publishers import douyin_adapter

        return douyin_adapter.publish_to_douyin(
            cookie=cookie,
            security_sdk=security_sdk,
            video_path=video_path,
            title=title,
            description=description,
            tags=tags,
            cover_path=cover_path,
        )
    from app.publishers import channels_adapter

    return channels_adapter.publish_to_channels(
        cookie=cookie,
        video_path=video_path,
        title=title,
        description=description,
        tags=tags,
        cover_path=cover_path,
    )


def perform_publish_delivery(
    row: dict[str, object],
    *,
    storage: StorageAdapter,
) -> PublishResult:
    """Adapter I/O with no database transaction; owns temp-file lifecycle."""
    import json

    video_uri = str(row["video_storage_uri"])
    video_path = _write_temp(
        storage.get_object(storage_key_from_uri(video_uri)),
        _suffix_of(video_uri, ".mp4"),
    )
    cover_path: Path | None = None
    cover_uri = row.get("cover_storage_uri")
    if cover_uri:
        cover_path = _write_temp(
            storage.get_object(storage_key_from_uri(str(cover_uri))),
            _suffix_of(str(cover_uri), ".jpg"),
        )
    try:
        tags: list[str] = []
        try:
            parsed = json.loads(str(row.get("tags_json") or "[]"))
            if isinstance(parsed, list):
                tags = [str(tag) for tag in parsed]
        except json.JSONDecodeError:
            tags = []
        security_sdk_raw = row.get("security_sdk")
        return _dispatch_publish(
            str(row["platform"]),
            cookie=str(row["cookie"]),
            security_sdk=str(security_sdk_raw) if security_sdk_raw else None,
            video_path=video_path,
            title=str(row.get("title") or ""),
            description=str(row.get("description") or ""),
            tags=tags,
            cover_path=cover_path,
        )
    finally:
        for path in (video_path, cover_path):
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    logger.warning("failed to clean publish temp file %s", path)


def run_publish_round(
    open_txn: Callable[[], AbstractContextManager[BusinessConnection]],
    *,
    worker_id: str,
    storage: StorageAdapter,
    fernet: object = None,
) -> int:
    """Claim and process at most one verify probe and one publish.

    Every claim/prepare/finalize gets its own short transaction via
    ``open_txn`` (SQLite: a short-lived connection; PG: one
    ``pg_transaction`` block) — the minutes-long platform delivery I/O must
    never run inside an open transaction, or the claimed lease would not
    commit and per-account serialization would break across workers.
    """
    from cryptography.fernet import Fernet

    key = fernet if isinstance(fernet, Fernet) else fernet_from_environment()
    processed = 0

    with open_txn() as conn:
        lease = claim_account_verify_work(conn, worker_id=worker_id)
    if lease is not None:
        processed += 1
        row = lease.row
        try:
            cookie = key.decrypt(str(row["cookie_enc"]).encode("ascii")).decode("utf-8")
            sdk_enc = row.get("security_sdk_enc")
            security_sdk = (
                key.decrypt(str(sdk_enc).encode("ascii")).decode("utf-8") if sdk_enc else None
            )
            ok, message = _dispatch_probe(str(row["platform"]), cookie, security_sdk)
        except PublishLeaseLostError:
            return processed
        except Exception as exc:  # noqa: BLE001 - probe boundary
            logger.warning("account verify preparation failed: %s", type(exc).__name__)
            ok, message = False, "登录态材料无法读取，请重新连接账号"
        try:
            with open_txn() as conn:
                finalize_account_verify(conn, lease=lease, ok=ok, message=message)
        except PublishLeaseLostError:
            logger.warning("account verify finalize lost lease: %s", lease.record_id)

    with open_txn() as conn:
        publish_lease = claim_publish_work(conn, worker_id=worker_id)
    if publish_lease is not None:
        processed += 1
        prepared: PublishLease | None = None
        credential_failed = False
        try:
            with open_txn() as conn:
                prepared = prepare_publish_work(conn, publish_lease, fernet=key)
        except PublishLeaseLostError:
            return processed
        except PublishCredentialError:
            logger.error("publish credentials cannot be decrypted: %s", publish_lease.record_id)
            credential_failed = True
        if credential_failed and prepared is None:
            try:
                with open_txn() as conn:
                    finalize_publish_work(
                        conn,
                        lease=publish_lease,
                        result=PublishResult(
                            platform=str(publish_lease.row["platform"]),
                            status="failed",
                            message="发布凭据无法解密，请重新连接账号",
                        ),
                    )
            except PublishLeaseLostError:
                pass
            return processed
        assert prepared is not None
        try:
            result = perform_publish_delivery(prepared.row, storage=storage)
        except Exception as exc:  # noqa: BLE001 - delivery boundary
            logger.warning("publish delivery crashed: %s", type(exc).__name__)
            result = PublishResult(
                platform=str(prepared.row["platform"]),
                status="failed",
                message="发布执行异常，请重试",
            )
        try:
            with open_txn() as conn:
                finalize_publish_work(conn, lease=prepared, result=result)
        except PublishLeaseLostError:
            logger.warning("publish finalize lost lease: %s", prepared.record_id)
    return processed


@contextmanager
def _open_sqlite_txn(db_path: Path) -> Iterator[BusinessConnection]:
    with BusinessConnection.sqlite(connect_database(db_path)) as conn:
        yield conn


def _sqlite_round(db_path: Path, *, worker_id: str) -> int:
    with _open_sqlite_txn(db_path) as conn:
        storage = get_media_storage(conn)
    return run_publish_round(
        lambda: _open_sqlite_txn(db_path), worker_id=worker_id, storage=storage
    )


def run_sqlite_forever(
    *, db_path: Path, worker_id: str, idle_seconds: float
) -> None:  # pragma: no cover - process loop
    while True:
        try:
            processed = _sqlite_round(db_path, worker_id=worker_id)
        except Exception:
            logger.exception("publish worker iteration failed")
            processed = 0
        if processed == 0:
            time.sleep(idle_seconds)


def _pg_round(*, worker_id: str) -> int:  # pragma: no cover - process loop
    from app.db_pg import pg_transaction

    with pg_transaction() as raw_conn:
        storage = get_media_storage(BusinessConnection.postgres(raw_conn))

    @contextmanager
    def open_txn() -> Iterator[BusinessConnection]:
        with pg_transaction() as raw_conn:
            yield BusinessConnection.postgres(raw_conn)

    return run_publish_round(open_txn, worker_id=worker_id, storage=storage)


def run_pg_forever(
    *, worker_id: str, idle_seconds: float
) -> None:  # pragma: no cover - process loop
    from app.db_pg import pg_transaction

    with pg_transaction() as raw_conn:
        get_media_storage(BusinessConnection.postgres(raw_conn))
    if check_pg_ready() is None:
        raise RuntimeError("PostgreSQL publish worker readiness check returned no result")
    while True:
        try:
            processed = _pg_round(worker_id=worker_id)
        except Exception:
            logger.exception("publish worker iteration failed")
            processed = 0
        if processed == 0:
            time.sleep(idle_seconds)


def main() -> None:  # pragma: no cover - CLI entry
    parser = argparse.ArgumentParser(description="Run the platform publish worker")
    parser.add_argument("--idle-seconds", type=float, default=2.0)
    parser.add_argument("--worker-id", default=f"publish-worker-{os.getpid()}")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    config = resolve_database_config()
    validate_customer_production(config)
    if config.mode is DatabaseMode.POSTGRESQL:
        run_pg_forever(worker_id=args.worker_id, idle_seconds=args.idle_seconds)
    else:
        if config.sqlite_path is None:  # pragma: no cover - mode guarantees a path
            raise RuntimeError("SQLite mode resolved without a database path")
        run_sqlite_forever(
            db_path=Path(config.sqlite_path),
            worker_id=args.worker_id,
            idle_seconds=args.idle_seconds,
        )


if __name__ == "__main__":  # pragma: no cover
    main()
