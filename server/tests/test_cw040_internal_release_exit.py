"""CW-040 (pre-GA scope, CW-001 §6 P1): internal release/ops entries fail closed.

CW-040's full scope is "退出内部发行与专属运维入口"; the owner-signed P1
decision scopes the pre-GA slice to ENTRY fail-closed — the internal release
toolchain and ops units must be unreachable from every customer build/deploy
surface, while the physical deletion (``packaging_tools/``,
``deploy/internal-p0.*``, ``deploy/systemd/video-replica-backup.*``,
``scripts/p0_acceptance_evidence.py``) stays in the deferred post-GA cleanup
batch (retirement condition: 内部停写 CW-051 后归档).

Pinned contracts here:

- The customer NSIS payload scan in ``ci.yml`` keeps its forbidden-name /
  forbidden-extension / binary-marker lists (the CW-021/024 entry closure).
- ``packaging_tools/`` is referenced by CI only as a path-filter trigger, and
  never executed by any build/release step (root npm scripts, client scripts,
  the signed-release channel, deploy/customer templates).
- ``scripts/p0_acceptance_evidence.py`` (internal P0 leftover) has no
  customer-surface consumer either.
- The historical SQLite backup CLI (``python -m app.backup``, the ops entry
  that pairs with ``deploy/systemd/video-replica-backup.*``) rides the
  CW-042-a choke point: customer production refuses it before any file is
  touched, while the internal lane keeps it available until CW-051 stops
  writes.
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from app.backup import main as backup_main
from app.db import CUSTOMER_PRODUCTION_ENV

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_CI_YML = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_REFUSAL_SNIPPET = "customer production is PostgreSQL-only"

_NSIS_FORBIDDEN_NAMES = (
    "start-backend.bat', 'start-backend.sh', 'pyvenv.cfg', 'ffmpeg.exe', 'ffprobe.exe"
)
_NSIS_FORBIDDEN_EXTENSIONS = "'.db', '.sqlite', '.sqlite3', '.pyd'"
_NSIS_BINARY_MARKERS = "'start-backend', 'VIDEO_REPLICA_BOOT_COMMAND', '127.0.0.1:8000'"


# ---------------------------------------------------------------------------
# CI: the customer installer entry stays fail-closed
# ---------------------------------------------------------------------------


def test_nsis_payload_scan_keeps_all_forbidden_markers() -> None:
    ci = _CI_YML.read_text(encoding="utf-8")
    assert _NSIS_FORBIDDEN_NAMES in ci
    assert _NSIS_FORBIDDEN_EXTENSIONS in ci
    assert _NSIS_BINARY_MARKERS in ci
    assert "customer installer contains local backend distribution" in ci
    assert "contains local backend marker" in ci


def test_packaging_tools_is_never_executed_by_ci() -> None:
    """packaging_tools may appear ONLY as a path-filter trigger line; any
    other occurrence would mean a CI step runs the internal release
    toolchain."""
    offenders = [
        line.strip()
        for line in _CI_YML.read_text(encoding="utf-8").splitlines()
        if "packaging_tools" in line and "- 'packaging_tools/**'" not in line
    ]
    assert offenders == []


# ---------------------------------------------------------------------------
# Customer build/deploy surfaces never reach the internal toolchain
# ---------------------------------------------------------------------------


def test_npm_scripts_have_no_internal_toolchain_references() -> None:
    for manifest in (_REPO_ROOT / "package.json", _REPO_ROOT / "client" / "package.json"):
        text = manifest.read_text(encoding="utf-8")
        for marker in ("packaging_tools", "p0_acceptance", "internal-p0"):
            assert marker not in text, f"{manifest.name} references {marker}"


def test_signed_release_channel_has_no_internal_toolchain_references() -> None:
    channel = _REPO_ROOT / "scripts" / "release" / "build-customer-signed-release.ps1"
    text = channel.read_text(encoding="utf-8")
    for marker in ("packaging_tools", "p0_acceptance", "internal-p0", "video-replica-backup"):
        assert marker not in text, f"signed release channel references {marker}"


def test_customer_deploy_templates_have_no_internal_toolchain_references() -> None:
    deploy_customer = _REPO_ROOT / "deploy" / "customer"
    offenders: list[str] = []
    for path in deploy_customer.rglob("*"):
        if not path.is_file() or path.suffix not in {
            ".sh",
            ".md",
            ".example",
            ".service",
            ".timer",
        }:
            continue
        text = path.read_text(encoding="utf-8")
        for marker in ("packaging_tools", "p0_acceptance", "internal-p0.env", "nginx/internal-p0"):
            if marker in text:
                offenders.append(f"{path.name}:{marker}")
        if "systemctl" in text and "video-replica-backup" in text:
            offenders.append(f"{path.name}:video-replica-backup unit wired")
    assert offenders == [], (
        f"deploy/customer gained internal toolchain references: {offenders} "
        "(CW-040 内部发行/运维入口退出 — 物理删除延后，但客户面不得引用)"
    )


# ---------------------------------------------------------------------------
# Process-level entry: the historical backup CLI rides the CW-042-a choke point
# ---------------------------------------------------------------------------


def test_backup_cli_refuses_in_customer_production(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "prod.db"
    db_path.write_bytes(b"")  # backup_database checks source existence first
    monkeypatch.setenv(CUSTOMER_PRODUCTION_ENV, "true")
    saved_argv = sys.argv
    sys.argv = ["backup", "backup", str(db_path), str(tmp_path / "out.db")]
    try:
        with pytest.raises(RuntimeError, match=_REFUSAL_SNIPPET):
            backup_main()
    finally:
        sys.argv = saved_argv


def test_backup_cli_still_serves_the_internal_lane(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Scope guard: the deferred retirement must not break the internal lane
    before CW-051 stops internal writes (backup/restore stays available)."""
    monkeypatch.delenv(CUSTOMER_PRODUCTION_ENV, raising=False)
    # initialize a tiny internal database, then back it up through the CLI path.
    from app.db import initialize_database

    source = tmp_path / "internal.db"
    conn = initialize_database(source)
    conn.close()

    backup_target = tmp_path / "backup.db"
    buffer = io.StringIO()
    saved_argv = sys.argv
    sys.argv = ["backup", "backup", str(source), str(backup_target)]
    try:
        with redirect_stdout(buffer):
            backup_main()
    finally:
        sys.argv = saved_argv
    assert backup_target.exists(), "internal-lane backup CLI must keep working"
