"""T21 / SES-04 — the portable business-database translation (frozen name).

Fail-first tests for ``server/app/db_portable.py`` (the single-implementation
foundation): the fail-closed SQLite translator over the bounded dialect set,
and the ``BusinessConnection`` facade surface the business services see. The
existing SQLite test suite is the runtime oracle for the translation — these
tests lock the *rules* so a regression in the translator cannot silently
change what the desktop lane executes.

CW-054 adds the two contracts that need no PostgreSQL server to pin down:

- ``_NamedRow`` (the PG lane's row class) measured against a live
  ``sqlite3.Row``, which is the oracle the customer lane must not drift from;
- ``IntegrityConstraintError`` / ``_map_integrity_error``, whose dual base makes
  one constraint failure catchable by both lanes' handlers.

The parts that *do* need a real server — actual batch persistence, SQLSTATE
round-trips, ``constraint_name`` from the server's ``Diagnostic`` — live in
``test_cw054_pg_portable_contract.py`` (TEST-PG).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

import psycopg
import pytest

from app.db_portable import (
    BusinessConnection,
    IntegrityConstraintError,
    _map_integrity_error,
    _NamedRow,
    translate_to_sqlite,
)

# ---------------------------------------------------------------------------
# translate_to_sqlite — placeholders
# ---------------------------------------------------------------------------


def test_placeholder_becomes_question_mark() -> None:
    assert (
        translate_to_sqlite("INSERT INTO projects (id, owner_user_id, name) VALUES (%s, %s, %s)")
        == "INSERT INTO projects (id, owner_user_id, name) VALUES (?, ?, ?)"
    )


def test_placeholder_inside_a_string_literal_is_untouched() -> None:
    assert (
        translate_to_sqlite("SELECT * FROM t WHERE note = '100% savings' AND id = %s")
        == "SELECT * FROM t WHERE note = '100% savings' AND id = ?"
    )


def test_placeholder_inside_a_comment_is_untouched() -> None:
    assert (
        translate_to_sqlite("SELECT %s FROM t -- %s stays a comment\nWHERE id = %s")
        == "SELECT ? FROM t -- %s stays a comment\nWHERE id = ?"
    )
    assert (
        translate_to_sqlite("SELECT %s /* %s block */ FROM t WHERE id = %s")
        == "SELECT ? /* %s block */ FROM t WHERE id = ?"
    )


def test_placeholder_inside_a_double_quoted_identifier_is_untouched() -> None:
    assert (
        translate_to_sqlite('SELECT "%s" FROM t WHERE id = %s') == 'SELECT "%s" FROM t WHERE id = ?'
    )


def test_unknown_placeholder_style_fails_closed() -> None:
    with pytest.raises(ValueError, match="placeholder"):
        translate_to_sqlite("SELECT %d FROM t")


def test_unterminated_quote_or_comment_fails_closed() -> None:
    with pytest.raises(ValueError, match="unterminated"):
        translate_to_sqlite("SELECT 'oops")
    with pytest.raises(ValueError, match="unterminated"):
        translate_to_sqlite("SELECT /* oops")


# ---------------------------------------------------------------------------
# translate_to_sqlite — row-lock, interval, casts
# ---------------------------------------------------------------------------


def test_for_update_is_removed() -> None:
    assert (
        translate_to_sqlite("SELECT id FROM customer_session_state WHERE id = %s FOR UPDATE")
        == "SELECT id FROM customer_session_state WHERE id = ?"
    )
    assert (
        translate_to_sqlite("SELECT id FROM queue WHERE worker = %s FOR UPDATE SKIP LOCKED")
        == "SELECT id FROM queue WHERE worker = ?"
    )


def test_interval_is_translated() -> None:
    assert (
        translate_to_sqlite("SET lease_until = now() + interval '60 seconds'")
        == "SET lease_until = datetime('now', '+60 seconds')"
    )
    assert (
        translate_to_sqlite("WHERE now() - interval '30 minutes' <= updated_at")
        == "WHERE datetime('now', '-30 minutes') <= updated_at"
    )


def test_pg_cast_is_stripped() -> None:
    assert (
        translate_to_sqlite("SELECT lease_until::text FROM customer_session_state")
        == "SELECT lease_until FROM customer_session_state"
    )
    assert translate_to_sqlite("WHERE created_at::timestamptz >= %s") == (
        "WHERE datetime(created_at) >= ?"
    )


def test_timestamptz_identifier_becomes_datetime_parse() -> None:
    """T25: a bare ``ident::timestamptz`` comparison parses the TEXT column
    with datetime() on SQLite — format-independent, matching the PG cast."""
    assert (
        translate_to_sqlite("WHERE locked_until::timestamptz <= now()")
        == "WHERE datetime(locked_until) <= datetime('now')"
    )
    assert (
        translate_to_sqlite("WHERE next_poll_at::timestamptz <= now() - interval '60 seconds'")
        == "WHERE datetime(next_poll_at) <= datetime('now', '-60 seconds')"
    )
    assert (
        translate_to_sqlite("WHERE task.updated_at::timestamptz >= %s::timestamptz")
        == "WHERE datetime(task.updated_at) >= datetime(?)"
    )


def test_timestamptz_parameter_cast_stays_stripped() -> None:
    """A ``%s::timestamptz`` parameter is parsed with datetime() on the SQLite
    lane (``datetime(?)`` accepts the ISO-8601 parameter) so both sides of a
    comparison are parsed — the same semantics as the PG cast."""
    assert (
        translate_to_sqlite("WHERE recovery_expires_at::timestamptz <= %s::timestamptz")
        == "WHERE datetime(recovery_expires_at) <= datetime(?)"
    )
    assert (
        translate_to_sqlite(
            "SET lease_until = GREATEST(%s::timestamptz, "
            "created_at::timestamptz + interval '1 microsecond')"
        )
        == "SET lease_until = GREATEST(datetime(?), datetime(created_at) "
        "+ interval '1 microsecond')"
    )


def test_bare_now_becomes_datetime_now() -> None:
    """T25: a bare ``now()`` (no interval) must not reach SQLite as an
    undefined function; datetime('now') is the UTC wall-clock text."""
    assert (
        translate_to_sqlite(
            "UPDATE user_queue_cursors SET last_dispatched_at = now() WHERE user_id = %s"
        )
        == "UPDATE user_queue_cursors SET last_dispatched_at = datetime('now') "
        "WHERE user_id = ?"
    )


def test_unhandled_cast_fails_closed() -> None:
    with pytest.raises(ValueError, match="cast"):
        translate_to_sqlite("SELECT x::numeric(10,2) FROM t")


def test_upsert_and_returning_pass_through() -> None:
    # SQLite >= 3.24 / 3.35 supports both natively; the translator leaves them.
    sql = "INSERT INTO t (id, v) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING RETURNING id"
    assert (
        translate_to_sqlite(sql) == "INSERT INTO t (id, v) VALUES (?, ?) "
        "ON CONFLICT (id) DO NOTHING RETURNING id"
    )


# ---------------------------------------------------------------------------
# BusinessConnection — the sqlite3-shaped facade
# ---------------------------------------------------------------------------


@pytest.fixture()
def sqlite_business() -> BusinessConnection:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE items (id TEXT PRIMARY KEY, owner TEXT, note TEXT)")
    return BusinessConnection.sqlite(conn)


def test_execute_translates_and_commits_through_with(sqlite_business: BusinessConnection) -> None:
    with sqlite_business:
        sqlite_business.execute(
            "INSERT INTO items (id, owner, note) VALUES (%s, %s, %s)",
            ("a", "u1", "100% done"),
        )
    row = sqlite_business.execute(
        "SELECT note FROM items WHERE id = %s AND owner = %s", ("a", "u1")
    ).fetchone()
    assert row[0] == "100% done"


def test_with_rolls_back_on_exception(sqlite_business: BusinessConnection) -> None:
    try:
        with sqlite_business:
            sqlite_business.execute("INSERT INTO items (id, owner) VALUES (%s, %s)", ("b", "u2"))
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    count = sqlite_business.execute("SELECT count(*) FROM items").fetchone()[0]
    assert count == 0


def test_explicit_transaction_begin_immediate(sqlite_business: BusinessConnection) -> None:
    with sqlite_business.transaction():
        sqlite_business.execute("INSERT INTO items (id, owner) VALUES (%s, %s)", ("c", "u3"))
    count = sqlite_business.execute("SELECT count(*) FROM items").fetchone()[0]
    assert count == 1


def test_postgres_commit_and_rollback_are_no_ops() -> None:
    calls: list[str] = []

    class _StubBackend:  # the PostgresBackend contract
        def __init__(self) -> None:
            self._stub = _Stub()

        def execute(self, *args: object, **kwargs: object) -> None: ...

        def executemany(self, *args: object, **kwargs: object) -> None: ...

        @property
        def raw(self) -> _Stub:
            return self._stub

    class _Stub:
        def commit(self) -> None:
            calls.append("commit")

        def rollback(self) -> None:
            calls.append("rollback")

    conn = BusinessConnection(_StubBackend())  # type: ignore[arg-type]
    conn.commit()
    conn.rollback()
    assert calls == []  # no-op on the PG backend: commit authority stays with the fenced tx


def test_postgres_backend_swallows_begin_immediate() -> None:
    """PR #56 P1: migrated write services still spell their write lock as
    BEGIN IMMEDIATE; on the PG lane the fenced transaction is already open so
    the statement must be a no-op (forwarding it to psycopg is a syntax error)."""
    calls: list[str] = []

    class _Result:
        def fetchone(self) -> None:
            return None

        def fetchall(self) -> list[object]:
            return []

        @property
        def rowcount(self) -> int:
            return -1

    class _StubPsycopg:
        row_factory: object = None

        def execute(self, sql: str, params: object = ()) -> _Result:
            calls.append(sql)
            return _Result()

    from app.db_portable import BusinessConnection, PostgresBackend

    conn = BusinessConnection(PostgresBackend(_StubPsycopg()))  # type: ignore[arg-type]
    result = conn.execute("BEGIN IMMEDIATE")
    assert calls == []  # swallowed on the PG lane
    assert result.fetchone() is None
    conn.execute("SELECT 1")
    assert calls == ["SELECT 1"]


# ---------------------------------------------------------------------------
# _NamedRow — parity with a real sqlite3.Row (CW-054)
# ---------------------------------------------------------------------------

_PARITY_SQL = "SELECT 'alice' AS owner, 7 AS amount, NULL AS note"


def _outcome(call: Callable[[], Any]) -> tuple[str, Any]:
    """Normalise a row access to ``(kind, payload)`` so a raise is comparable.

    The exception type *and* message are part of the observable contract: a
    caller guarding an optional column with ``except IndexError`` needs the
    same type on both lanes, and sqlite3.Row's messages are what a developer
    sees when the guard is wrong.
    """
    try:
        return ("value", call())
    except Exception as exc:  # noqa: BLE001 - the type/message IS the assertion
        return (type(exc).__name__, str(exc))


def _both_rows(sql: str) -> tuple[sqlite3.Row, _NamedRow]:
    """The same result set as a live ``sqlite3.Row`` and as a PG-lane ``_NamedRow``.

    The ``_NamedRow`` is built from sqlite's own cursor description and values,
    so the row *class* is the only difference. That is exactly the comparison
    the customer lane needs and it requires no PostgreSQL server — a
    ``sqlite3.Row`` is a standalone value object that outlives its connection.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(sql)
        real = cursor.fetchone()
        assert real is not None
        names = tuple(column[0] for column in cursor.description or ())
    finally:
        conn.close()
    return real, _NamedRow(tuple(real), names)


PARITY_CASES: list[tuple[str, str, Callable[[Any], Any]]] = [
    ("by-position", _PARITY_SQL, lambda row: row[0]),
    ("by-position-null-column", _PARITY_SQL, lambda row: row[2]),
    ("negative-index", _PARITY_SQL, lambda row: row[-1]),
    ("index-out-of-range", _PARITY_SQL, lambda row: row[3]),
    ("slice", _PARITY_SQL, lambda row: row[0:2]),
    ("by-name", _PARITY_SQL, lambda row: row["owner"]),
    ("by-name-null-column", _PARITY_SQL, lambda row: row["note"]),
    ("unknown-name", _PARITY_SQL, lambda row: row["missing"]),
    ("upper-case-name", _PARITY_SQL, lambda row: row["OWNER"]),
    ("mixed-case-name", _PARITY_SQL, lambda row: row["Owner"]),
    ("folded-camel-name", "SELECT 7 AS ownerUserId", lambda row: row["owneruserid"]),
    ("exact-camel-name", "SELECT 7 AS ownerUserId", lambda row: row["ownerUserId"]),
    ("upper-camel-name", "SELECT 7 AS ownerUserId", lambda row: row["OWNERUSERID"]),
    ("duplicate-case-first-wins", "SELECT 1 AS owner, 2 AS OWNER", lambda row: row["OWNER"]),
    ("duplicate-case-exact", "SELECT 1 AS owner, 2 AS OWNER", lambda row: row["owner"]),
    ("keys", _PARITY_SQL, lambda row: row.keys()),
    ("keys-container-type", _PARITY_SQL, lambda row: type(row.keys()).__name__),
    ("len", _PARITY_SQL, lambda row: len(row)),
    ("iteration", _PARITY_SQL, lambda row: list(row)),
    ("tuple", _PARITY_SQL, lambda row: tuple(row)),
    ("dict", _PARITY_SQL, lambda row: dict(row)),
    ("equals-plain-tuple", _PARITY_SQL, lambda row: row == ("alice", 7, None)),
    ("contains-column-name", _PARITY_SQL, lambda row: "owner" in row),
    ("contains-value", _PARITY_SQL, lambda row: "alice" in row),
    ("float-key", _PARITY_SQL, lambda row: row[1.0]),
    ("bytes-key", _PARITY_SQL, lambda row: row[b"owner"]),
    ("none-key", _PARITY_SQL, lambda row: row[None]),
]


@pytest.mark.parametrize(
    ("sql", "access"),
    [(case[1], case[2]) for case in PARITY_CASES],
    ids=[case[0] for case in PARITY_CASES],
)
def test_named_row_matches_a_real_sqlite_row(sql: str, access: Callable[[Any], Any]) -> None:
    """Every observable row access behaves identically on both lanes.

    One SQL source means one row contract (PG-02): the PG lane hands the
    business services a ``_NamedRow`` where the desktop lane hands them a
    ``sqlite3.Row``, and a service must not have to know which. The matrix is
    measured against the live stdlib class rather than written from the docs —
    which do not mention the case folding, the first-match rule or the
    ``IndexError`` for a non-index key at all.
    """
    real, named = _both_rows(sql)
    assert _outcome(lambda: access(real)) == _outcome(lambda: access(named))


def test_named_row_folds_case_and_the_first_match_wins() -> None:
    """The rule the matrix can only show as a difference of *values*.

    PostgreSQL lower-cases an unquoted identifier, so the customer lane
    describes ``SELECT 1 AS owner, 2 AS OWNER`` differently from the desktop
    lane. ``sqlite3.Row`` answers ``row["OWNER"]`` with the first column whose
    name matches case-insensitively — not the exact-case one — and picking the
    exact match instead would silently return a different column.
    """
    _, named = _both_rows("SELECT 1 AS owner, 2 AS OWNER")
    assert named.keys() == ["owner", "OWNER"]
    assert named["OWNER"] == 1
    assert named["owner"] == 1
    assert named[1] == 2  # the second column is still reachable by position


def test_named_row_rejects_a_non_index_key_with_index_error() -> None:
    """``sqlite3.Row`` says ``Index must be int or string``; a bare tuple
    subscript would raise ``TypeError``, so a caller's ``except IndexError``
    would not fire on the customer lane."""
    _, named = _both_rows(_PARITY_SQL)
    for bad_key in (1.0, b"owner", None):
        with pytest.raises(IndexError, match="Index must be int or string"):
            _ = named[bad_key]


def test_named_row_keys_is_a_fresh_mutable_list() -> None:
    """``rbac_routes.project_response`` probes optional columns with
    ``x not in row.keys()``; sqlite3.Row returns a new list each call, so a
    caller mutating it must not corrupt the row."""
    _, named = _both_rows(_PARITY_SQL)
    keys = named.keys()
    assert keys == ["owner", "amount", "note"]
    assert named.keys() is not keys
    keys.append("injected")
    assert named.keys() == ["owner", "amount", "note"]


def test_neither_row_class_offers_a_mapping_get() -> None:
    """The one axis where the two cannot be byte-identical: both raise
    ``AttributeError`` for ``.get``, but the message names the class. Recorded so
    the parity matrix is not read as claiming more than it proves — and so a
    caller cannot start relying on ``row.get(...)`` on either lane.

    Asserted with ``hasattr`` rather than ``pytest.raises`` because the attribute
    genuinely does not exist on either type, which a strict type checker would
    otherwise (correctly) reject at the access site.
    """
    real, named = _both_rows(_PARITY_SQL)
    assert not hasattr(real, "get")
    assert not hasattr(named, "get")


# ---------------------------------------------------------------------------
# IntegrityConstraintError — one constraint failure, both lanes (CW-054)
# ---------------------------------------------------------------------------


def test_constraint_error_is_catchable_by_either_lanes_handler() -> None:
    """The dual base is the entire point of the class.

    ``app/source_frames.py`` catches ``sqlite3.Error`` around its writes and
    ``app/zpay_payments.py`` catches ``sqlite3.IntegrityError``; before CW-054 a
    PostgreSQL constraint failure reached neither handler, so the customer lane
    turned a mapped business result into an unhandled 500 while the desktop lane
    behaved correctly.
    """
    error = IntegrityConstraintError("duplicate key", sqlstate="23505")
    for handler in (
        sqlite3.Error,
        sqlite3.IntegrityError,
        psycopg.Error,
        psycopg.IntegrityError,
    ):
        with pytest.raises(handler):
            raise error


@pytest.mark.parametrize(
    ("raised", "sqlstate"),
    [
        (psycopg.errors.UniqueViolation, "23505"),
        (psycopg.errors.ForeignKeyViolation, "23503"),
        (psycopg.errors.CheckViolation, "23514"),
        (psycopg.errors.NotNullViolation, "23502"),
    ],
    ids=["unique", "foreign-key", "check", "not-null"],
)
def test_mapper_keeps_the_sqlstate_of_each_constraint_class(
    raised: type[psycopg.Error], sqlstate: str
) -> None:
    """A caller maps each violation to its own business result, so the SQLSTATE
    must survive the translation instead of collapsing into one opaque error.

    psycopg's SQLSTATE subclasses carry ``sqlstate`` as a class attribute, which
    is why the four-way mapping is testable with no server. ``constraint_name``
    comes from the server-side ``Diagnostic`` — a read-only property that cannot
    be stubbed — so it is asserted against a live PG in
    ``test_cw054_pg_portable_contract.py``.
    """
    mapped = _map_integrity_error(raised("boom"))
    assert isinstance(mapped, IntegrityConstraintError)
    assert mapped.sqlstate == sqlstate
    assert str(mapped) == "boom"


def test_mapper_survives_an_error_with_no_server_diagnostic() -> None:
    """A client-side psycopg error has an empty ``Diagnostic``; the mapper must
    not raise on top of the failure it is translating."""
    mapped = _map_integrity_error(psycopg.IntegrityError("no server"))
    assert mapped.sqlstate is None
    assert mapped.constraint_name is None


def test_constraint_error_carries_no_sqlstate_on_the_sqlite_lane() -> None:
    """SQLite reports no SQLSTATE, so the attributes default to ``None`` rather
    than to a made-up code a caller might branch on."""
    error = IntegrityConstraintError("sqlite says no")
    assert error.sqlstate is None
    assert error.constraint_name is None
    assert error.args == ("sqlite says no",)
