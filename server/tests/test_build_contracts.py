from __future__ import annotations

import json
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_cargo_build_uses_workspace_isolated_target_directory() -> None:
    config_path = REPO_ROOT / ".cargo" / "config.toml"

    assert config_path.exists()
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert config["build"]["target-dir"] == ".cargo-target"
    assert ".cargo-target/" in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")


def test_python_quality_commands_survive_a_relocated_virtualenv() -> None:
    package = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    scripts = package["scripts"]

    assert "python -m mypy" in scripts["check"]
    assert "python -m pytest" in scripts["check"]
    assert "python -m pytest" in scripts["test"]
    assert "python -m pytest" in scripts["test:e2e"]
    assert "--locked mypy" not in scripts["check"]
    assert "--locked pytest" not in scripts["check"]
    assert "--locked pytest" not in scripts["test"]
    assert "--locked pytest" not in scripts["test:e2e"]


def test_api_uses_the_project_interpreter_instead_of_a_global_uvicorn() -> None:
    package = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    customer_e2e_launcher = (REPO_ROOT / "e2e/customer/setup-backend.mjs").read_text(
        encoding="utf-8"
    )

    assert "python -m uvicorn" in package["scripts"]["dev:server"]
    assert "--no-proxy-headers" in package["scripts"]["dev:server"]
    assert '"--no-proxy-headers"' in customer_e2e_launcher


def test_dev_start_commands_upgrade_the_database_before_api_or_worker() -> None:
    # CW-021 removed the packaged start-backend launchers from the desktop
    # bundle; only the development commands (which target a registered PG and
    # are never shipped) keep a bootstrapping order worth locking.
    package = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))

    server_command = package["scripts"]["dev:server"]
    worker_command = package["scripts"]["dev:worker"]
    assert server_command.index("python -m app.bootstrap") < server_command.index(
        "python -m uvicorn"
    )
    assert worker_command.index("python -m app.bootstrap") < worker_command.index(
        "python -m app.generation_worker"
    )
    assert "--no-proxy-headers" in server_command


def test_pull_requests_run_linux_quality_and_windows_nsis_gates() -> None:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    fork_pr_guard = (
        "github.event_name != 'pull_request' || "
        "github.event.pull_request.head.repo.full_name == github.repository"
    )

    assert workflow_path.exists()
    workflow = workflow_path.read_text(encoding="utf-8")
    assert "pull_request:" in workflow
    assert "push:" in workflow
    assert workflow.count("branches: [main]") == 2
    assert "pull_request_target:" not in workflow
    assert "permissions:\n  contents: read" in workflow
    # 4 checkouts (changes, secret-scan, quality-linux, windows-nsis); select-runner
    # runs github-script only and checks out nothing.
    assert workflow.count("persist-credentials: false") == 4
    assert "secret-scan:" in workflow
    assert "name: Secret scan" in workflow
    assert "quality-linux:" in workflow
    assert "name: Linux quality gate" in workflow
    assert "windows-nsis:" in workflow
    assert "name: Windows Tauri and NSIS" in workflow
    # Supporting jobs added by the CI-localization change: `changes` (path
    # filtering) and `select-runner` (dual-path Linux gate: a self-hosted
    # `video-replica` runner when one is online, else GitHub-hosted). The pinned
    # actions and the arch-agnostic runner label are contract-checked so a future
    # edit cannot silently drop the dual path or unpin an action.
    assert "changes:" in workflow
    assert "name: Detect changes" in workflow
    assert "select-runner:" in workflow
    assert "name: Select runner" in workflow
    assert "dorny/paths-filter@ceb8a2b8f2d89434be7ff52d3de7ec3738c5cc9d" in workflow
    assert "actions/github-script@3a2844b7e9c422d3c10d287c895573f7108da1b3" in workflow
    assert '["self-hosted","linux","video-replica"]' in workflow
    assert "fromJSON(needs.select-runner.outputs.runner)" in workflow
    # Every job (changes, select-runner, secret-scan, quality-linux, windows-nsis)
    # carries the same-repo fork-PR guard, so a fork PR never runs untrusted code.
    assert workflow.count(f"if: {fork_pr_guard}") == 5
    assert workflow.count("runs-on: ubuntu-24.04") == 2
    assert workflow.count("runs-on: windows-2025") == 1
    assert "npm run check:security" in workflow
    # The Linux gate splits the former single `npm run check` into static checks
    # plus sharded pytest (each shard against its own isolated PostgreSQL
    # container); `npm run check` is no longer invoked verbatim in ci.yml.
    assert "run: npm run check:static\n" in workflow
    assert "run: bash scripts/ci/run-pytest-shards.sh\n" in workflow
    assert "npm run build" in workflow
    assert "npm audit --audit-level=high" in workflow
    assert "cargo test --manifest-path client/src-tauri/Cargo.toml --locked" in workflow
    assert "npm run check:tauri" in workflow
    # CW-021: the local sidecar feature and the internal edition are gone, so
    # CI only ever builds the customer cloud bundle.
    assert "check:tauri:internal" not in workflow
    assert "tauri:build:internal" not in workflow
    assert "internal NSIS" not in workflow
    assert "npm run tauri:build:customer" in workflow
    assert "VITE_API_BASE_URL: https://staging.example.invalid" in workflow
    windows_job = workflow.split("\n  windows-nsis:\n", 1)[1]
    job_config, windows_steps = windows_job.split("\n    steps:\n", 1)
    assert "runner.temp" not in job_config
    assert "LOCAL_ARTIFACT_ROOT" not in job_config
    step = windows_steps.split(
        "      - name: Archive unsigned customer cloud NSIS installer locally\n", 1
    )[1].split("\n      - name:", 1)[0]
    assert (
        "\n        env:\n"
        "          LOCAL_ARTIFACT_ROOT: ${{ runner.temp }}/video-replica-artifacts\n"
    ) in step
    assert workflow.count("LOCAL_ARTIFACT_ROOT") == 4
    assert workflow.count("SHA256SUMS.txt") == 1
    # CW-021 widened payload detection: beyond the launcher scripts the
    # customer installer must not carry an embedded server/Python runtime,
    # FFmpeg distribution, SQLite business database, or boot/port markers.
    assert "Verify customer installer excludes local backend distribution" in workflow
    assert "pyvenv.cfg" in workflow
    assert "ffmpeg.exe" in workflow
    assert "'.db', '.sqlite', '.sqlite3', '.pyd'" in workflow
    assert "[\\\\/](server|\\.venv|ffmpeg)[\\\\/]" in workflow
    assert "VIDEO_REPLICA_BOOT_COMMAND" in workflow
    assert "127.0.0.1:8000" in workflow
    assert "7-Zip\\7z.exe" in workflow
    # The launcher names may only appear inside the payload gate's forbidden
    # list; no build/check/archive step may reference them.
    workflow_before_payload_gate = workflow.split(
        "Verify customer installer excludes local backend distribution", 1
    )[0]
    assert "start-backend" not in workflow_before_payload_gate
    assert "start-backend.bat" in workflow
    assert "start-backend.sh" in workflow
    assert workflow.count("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1") == 4
    assert workflow.count("actions/setup-node@820762786026740c76f36085b0efc47a31fe5020") == 3
    assert "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97" in workflow
    assert "actions/upload-artifact@" not in workflow
    assert ".cargo-target/release/bundle/nsis/*.exe" in workflow


def test_packaged_local_backend_launchers_are_removed() -> None:
    # CW-021: the desktop bundle must not ship any local backend launcher. The
    # packaged start scripts, the local-sidecar Cargo feature, the internal
    # overlay config, and the sidecar startup code in lib.rs are retired.
    for launcher in (
        "client/src-tauri/resources/start-backend.sh",
        "client/src-tauri/resources/start-backend.bat",
        "client/src-tauri/tauri.internal.conf.json",
    ):
        assert not (REPO_ROOT / launcher).exists(), f"{launcher} must be removed (CW-021)"
    package = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    for script in ("check:tauri:internal", "tauri:build:internal", "tauri:dev:internal"):
        assert script not in package["scripts"], f"{script} must be removed (CW-021)"
    assert "local-sidecar" not in json.dumps(package)
    cargo_toml = (REPO_ROOT / "client/src-tauri/Cargo.toml").read_text(encoding="utf-8")
    assert "local-sidecar" not in cargo_toml
    lib_rs = (REPO_ROOT / "client/src-tauri/src/lib.rs").read_text(encoding="utf-8")
    for marker in (
        "BackendProcess",
        "BOOT_COMMAND",
        "local_api_ready",
        "start_local_services",
        "127.0.0.1:8000",
    ):
        assert marker not in lib_rs, f"lib.rs must not keep local sidecar code: {marker}"
