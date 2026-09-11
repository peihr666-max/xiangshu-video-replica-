"""CW-032 — the customer delivery package is a registered, rebuildable unit.

TEST-LOGIC (offline). The single default package lives in
``deploy/customer/``: ``compose.yaml`` (topology), ``README.md`` (rebuild
manual) and ``bootstrap-base-image.sh`` (first image on a blank host), with
``deploy/customer-git-rollout.sh`` consuming the in-repo compose instead of
an unregistered host file. The machine-checked contracts here:

1. **Topology** — the compose declares exactly the rollout's service set,
   adds the one-shot ``migrate`` role, and never lets api/worker execute
   schema DDL (single-migration execution; no multi-instance DDL races).
2. **Pool budget** — 2 API + 4 worker processes against the compose
   ``max_connections`` leaves the documented headroom, computed from the
   live defaults in ``app.db_pg`` (the numbers cannot drift silently).
3. **Wiring** — nginx upstreams, health checks and the rollout's image-bump
   service names stay consistent with the compose.
4. **Exclusions** — the formal package references no internal-P0/SQLite
   backup unit and no historical operator tooling (PG-08/PG-09); the
   registered package file list is closed.
5. **Fail-fast matrix** — every required dependency (PG DSN, root keys,
   private COS, ffmpeg/ffprobe) maps to the executable acceptance that
   fails fast, and those targets actually exist.

Blank-host rebuild execution itself needs a real Docker host; the command
contracts are pinned here and the real topology acceptance is CW-047.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "deploy" / "customer"
COMPOSE = PACKAGE_DIR / "compose.yaml"
README = PACKAGE_DIR / "README.md"
BOOTSTRAP = PACKAGE_DIR / "bootstrap-base-image.sh"
ROLLOUT = REPO_ROOT / "deploy" / "customer-git-rollout.sh"
NGINX = REPO_ROOT / "deploy" / "nginx" / "customer.conf.example"

# The closed inventory of the formal delivery package.
PACKAGE_FILES = ("compose.yaml", "README.md", "bootstrap-base-image.sh")

ROLLOUT_SERVICES = ("api-1", "api-2", "worker-1", "worker-2", "worker-3", "worker-4")

# Fail-fast matrix: dependency -> (executable acceptance target, marker).
FAIL_FAST_MATRIX = {
    "missing-or-invalid-pg-dsn": (
        "server/tests/test_bootstrap_all_env_pg_gate.py",
        "resolve_database_config",
    ),
    "missing-root-keys-production-security-gate": (
        "server/tests/test_customer_ha_smoke.py",
        "assert_customer_production_security",
    ),
    "missing-private-cos": (
        "server/tests/test_customer_ha_smoke.py",
        "check_customer_production_runtime_dependencies",
    ),
    "missing-ffprobe-media-probe": (
        "server/tests/test_customer_ha_smoke.py",
        "customer_runtime_dependency_gate_requires_ffprobe",
    ),
    "ffmpeg-unavailable-media-tools": (
        "server/tests/test_script_from_audio.py",
        "MediaToolUnavailable",
    ),
}


def _compose_text() -> str:
    return COMPOSE.read_text(encoding="utf-8")


def _service_block(service: str) -> str:
    """Return the raw YAML block of one top-level service (heuristic split)."""

    text = _compose_text()
    match = re.search(rf"(?ms)^  {re.escape(service)}:\n(.*?)(?=^  \S|\Z)", text)
    assert match is not None, f"service {service} missing from compose.yaml"
    return match.group(1)


def test_compose_declares_exactly_the_rollout_topology() -> None:
    section = _compose_text().split("services:")[1].split("\nvolumes:")[0]
    services = set(re.findall(r"(?m)^  ([a-z0-9-]+):\s*$", section))
    assert services == {*ROLLOUT_SERVICES, "db", "migrate"}
    rollout = ROLLOUT.read_text(encoding="utf-8")
    services_line = re.search(r"(?m)^SERVICES=\(([^)]*)\)", rollout)
    assert services_line is not None
    assert services_line.group(1).split() == list(ROLLOUT_SERVICES)


def test_migrate_is_the_only_schema_ddl_role() -> None:
    migrate_block = _service_block("migrate")
    assert "python -m alembic upgrade head" in migrate_block
    assert 'restart: "no"' in migrate_block
    for service in ROLLOUT_SERVICES:
        block = _service_block(service)
        assert "alembic" not in block, f"{service} must not execute schema DDL"
        assert "condition: service_completed_successfully" in block, (
            f"{service} must wait for the one-shot migrate role"
        )


def test_connection_pool_budget_fits_the_database_limit() -> None:
    text = (REPO_ROOT / "server" / "app" / "db_pg.py").read_text(encoding="utf-8")
    default_max = int(re.search(r"DEFAULT_POOL_MAX = (\d+)", text).group(1))
    assert default_max == 8
    processes = sum(1 for service in ROLLOUT_SERVICES if service.startswith(("api", "worker")))
    assert processes == 6
    budget = processes * default_max
    compose = _compose_text()
    max_connections = int(re.search(r"max_connections=(\d+)", compose).group(1))
    reserved = int(re.search(r"superuser_reserved_connections=(\d+)", compose).group(1))
    # 48 + 1 transient migrate + 3 reserved <= declared limit (README §3).
    assert budget + 1 + reserved <= max_connections, (budget, max_connections)
    assert "VIDEO_REPLICA_PG_POOL_MAX" in compose


def test_api_wiring_matches_nginx_and_health_contract() -> None:
    compose = _compose_text()
    nginx = NGINX.read_text(encoding="utf-8")
    assert "127.0.0.1:8001:8000" in compose and "127.0.0.1:8002:8000" in compose
    assert "127.0.0.1:8001" in nginx and "127.0.0.1:8002" in nginx
    # Health checks: db pg_isready; api /health via the in-image python.
    assert "pg_isready" in compose
    assert compose.count("urllib.request.urlopen('http://127.0.0.1:8000/health'") == 2
    # The health route itself exists (release VERIFY curls it through nginx).
    main_py = (REPO_ROOT / "server" / "app" / "main.py").read_text(encoding="utf-8")
    assert '@app.get("/health"' in main_py


def test_rollout_consumes_the_registered_package() -> None:
    rollout = ROLLOUT.read_text(encoding="utf-8")
    assert 'COMPOSE="${CUSTOMER_COMPOSE:-$SOURCE/deploy/customer/compose.yaml}"' in rollout
    assert 'sha256sum "$COMPOSE" > "$BACKUP/compose.sha256"' in rollout
    bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
    assert "uv sync --locked --no-dev" in bootstrap
    assert "python -m compileall -q app migrations" in bootstrap
    assert (
        "import app.main, app.admin_customer_routes, app.customer_fence, app.generation_worker"
        in bootstrap
    )
    assert "historical SQLite tooling in the customer image" in bootstrap


def test_formal_package_excludes_internal_and_sqlite_backup_surface() -> None:
    exclusion_markers = (
        "不属于本包",
        "排除",
        "never enters",
        "! test -e",
        "historical SQLite tooling in the customer image",
    )
    for name in PACKAGE_FILES:
        assert (PACKAGE_DIR / name).is_file(), name
        text = (PACKAGE_DIR / name).read_text(encoding="utf-8")
        for token in (
            "video-replica-backup",
            "internal-p0",
            "app.backup",
            "sqlite_to_postgres",
            "reconcile_customer_billing",
        ):
            for line in text.splitlines():
                if token in line:
                    # Only the documented exclusion statement may name them.
                    assert any(marker in line for marker in exclusion_markers), (
                        name,
                        token,
                        line.strip(),
                    )
    # The formal package directory inventory is closed.
    package_names = {path.name for path in PACKAGE_DIR.iterdir()}
    assert package_names == set(PACKAGE_FILES)


def test_readme_documents_rebuild_admin_backup_and_hashes() -> None:
    readme = README.read_text(encoding="utf-8")
    assert "bootstrap-base-image.sh" in readme
    assert "provision-empty-customer" in readme and "--confirm-empty-database" in readme
    assert "pitr-backup.sh" in readme and "pitr-restore-drill.sh" in readme
    assert "max_connections=120" in readme
    assert "BACKUP-SHA256SUMS" in readme and "compose.sha256" in readme
    assert "service_completed_successfully" in readme


def test_fail_fast_matrix_targets_exist() -> None:
    for dependency, (test_file, marker) in FAIL_FAST_MATRIX.items():
        path = REPO_ROOT / test_file
        assert path.is_file(), (dependency, test_file)
        assert marker in path.read_text(encoding="utf-8"), (dependency, marker)
