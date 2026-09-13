"""Cost context for auxiliary provider calls outside database transactions."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import uuid4

from app.db_pg import pg_transaction
from app.db_portable import BusinessConnection
from app.usage_billing import (
    accept_platform_operation,
    begin_attempt,
    begin_source_attempt,
    complete_attempt,
    finish_operation,
)

_source: ContextVar[str | None] = ContextVar("billing_source", default=None)
_collection: ContextVar[str | None] = ContextVar("billing_collection", default=None)


@contextmanager
def collection_billing_context(batch_id: str) -> Iterator[None]:
    """Each physical request owns its cost; a batch only groups shared customer charges."""
    token = _collection.set(batch_id)
    try:
        yield
    finally:
        _collection.reset(token)


@contextmanager
def billing_context(source_id: str) -> Iterator[None]:
    token = _source.set(source_id)
    try:
        yield
    finally:
        _source.reset(token)


@contextmanager
def meter_call(service: str, *, units: float | int = 1) -> Iterator[None]:
    source = None if service == "viral_data" and _collection.get() else _source.get()
    attempt = None
    platform_operation = None
    if source:
        with pg_transaction() as raw:
            attempt = begin_source_attempt(
                BusinessConnection.postgres(raw), source, service=service
            )
    elif service == "viral_data" and os.environ.get("VIDEO_REPLICA_DATABASE_URL"):
        with pg_transaction() as raw:
            conn = BusinessConnection.postgres(raw)
            platform_operation = accept_platform_operation(
                conn, service=service, source_id=str(uuid4()), collection_batch_id=_collection.get()
            )
            attempt = begin_attempt(conn, operation_id=platform_operation, attempt_key="request")
    usage = None
    try:
        yield
        usage = units
    finally:
        if attempt:
            with pg_transaction() as raw:
                conn = BusinessConnection.postgres(raw)
                if platform_operation:
                    operation = conn.execute(
                        "SELECT state FROM billing_operations WHERE id=%s FOR UPDATE",
                        (platform_operation,),
                    ).fetchone()
                    if operation[0] != "PENDING":
                        raise RuntimeError("采集接口计量已超时，迟到结果保留待核对")
                complete_attempt(conn, attempt_id=attempt, usage=usage)
                if platform_operation:
                    finish_operation(
                        conn,
                        operation_id=platform_operation,
                        units=units if usage is not None else 0,
                        succeeded=usage is not None,
                    )
