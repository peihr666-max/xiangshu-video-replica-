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


@contextmanager
def billing_context(source_id: str) -> Iterator[None]:
    token = _source.set(source_id)
    try:
        yield
    finally:
        _source.reset(token)


@contextmanager
def meter_call(service: str, *, units: float | int = 1) -> Iterator[None]:
    source = _source.get()
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
                conn, service=service, source_id=str(uuid4())
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
                complete_attempt(conn, attempt_id=attempt, usage=usage)
                if platform_operation:
                    finish_operation(
                        conn,
                        operation_id=platform_operation,
                        units=units if usage is not None else 0,
                        succeeded=usage is not None,
                    )
