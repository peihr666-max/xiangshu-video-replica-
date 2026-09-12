"""CW-041 (pre-GA scope, CW-001 §6 P1): internal identity entries fail closed.

CW-041's full scope is "退出内部身份及无合法消费者的入口"; the owner-signed P1
decision scopes the pre-GA slice to ENTRY fail-closed — the internal-identity
surface must be unreachable in customer production, while the physical module
retirement (``app/internal_accounts.py`` / ``app/internal_billing.py``) stays
in the deferred cleanup batch.

Layered guards pinned here (existing ones referenced, new ones asserted):

- CW-026 already proves the request-level fencing: X-Dev-User-Id and internal
  Bearer tokens are refused on the customer PG lane in every environment,
  including with the customer-production flag set
  (``test_customer_production_flag_still_refuses_internal_bearer``).
- test_admin_auth.py already proves the CW-025 lifespan guard: customer
  production refuses the internal SQLite lane at startup.
- NEW here: the internal-accounts CLI (``python -m app.internal_accounts``)
  never runs a lifespan, so it rides the CW-042-a choke point in ``app/db.py``
  — customer production refuses it before any file is touched, while the
  internal lane keeps full CLI functionality.
- NEW here: structural pin that ``app.internal_accounts`` remains a CLI-only
  surface (zero route-module importers), so no customer-facing HTTP entry can
  appear without tripping this contract.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from app.db import CUSTOMER_PRODUCTION_ENV
from app.internal_accounts import build_parser
from app.internal_accounts import main as internal_accounts_main

_REFUSAL_SNIPPET = "customer production is PostgreSQL-only"


@contextmanager
def _cli_argv(*argv: str) -> Iterator[None]:
    saved = sys.argv
    sys.argv = ["internal_accounts", *argv]
    try:
        yield
    finally:
        sys.argv = saved


# ---------------------------------------------------------------------------
# Process-level entry: the internal-accounts CLI rides the CW-042-a choke point
# ---------------------------------------------------------------------------


def test_internal_accounts_cli_refuses_in_customer_production(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "prod-internal.db"
    monkeypatch.setenv(CUSTOMER_PRODUCTION_ENV, "true")
    with _cli_argv(
        "--db-path",
        str(db_path),
        "create-user",
        "--username",
        "op",
        "--display-name",
        "Op",
    ):
        with pytest.raises(RuntimeError, match=_REFUSAL_SNIPPET):
            internal_accounts_main()
    assert not db_path.exists()


def test_internal_accounts_cli_still_serves_the_internal_lane(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.Capsys
) -> None:
    """Scope guard: the P1 slice must not break the internal lane's own tool."""
    db_path = tmp_path / "internal.db"
    monkeypatch.delenv(CUSTOMER_PRODUCTION_ENV, raising=False)
    with _cli_argv(
        "--db-path", str(db_path), "create-user", "--username", "operator", "--display-name", "Op"
    ):
        internal_accounts_main()
    created = json.loads(capsys.readouterr().out)
    assert created["username"] == "operator"

    with _cli_argv("--db-path", str(db_path), "issue-token", "--user-id", created["user_id"]):
        internal_accounts_main()
    issued = json.loads(capsys.readouterr().out)
    assert issued["user_id"] == created["user_id"]
    assert issued["token"]


# ---------------------------------------------------------------------------
# Structural pin: the internal-identity module stays CLI-only
# ---------------------------------------------------------------------------


def test_internal_accounts_has_no_route_module_importers() -> None:
    """``app.internal_accounts`` must remain a CLI-only surface (zero app
    importers today). If a route module ever imports it, the internal-identity
    surface would gain an HTTP entry — exactly what CW-041's exit forbids
    without an owner decision."""
    app_dir = Path(__file__).resolve().parent.parent / "app"
    offenders = [
        path.name
        for path in app_dir.glob("*.py")
        if path.name != "internal_accounts.py"
        and "internal_accounts" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], (
        f"app.internal_accounts gained app-level consumers: {offenders} "
        "(CW-041 内部身份入口退出 — 需 owner 决策才能挂载)"
    )


def test_internal_accounts_parser_requires_db_path() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["create-user", "--username", "op"])
