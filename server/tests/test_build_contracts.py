from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _bash_path() -> str | None:
    # Resolve the interpreter explicitly: Windows' CreateProcess searches
    # System32 before PATH, so a bare "bash" argument can silently resolve
    # to the WSL launcher stub (System32\bash.exe / WindowsApps\bash.exe)
    # even when git-bash is first on PATH. The stub's exit status drifts
    # with the WSL service state and its UTF-16 diagnostics kill text-mode
    # output readers mid-decode, so the POSIX launcher tests need a native
    # Windows POSIX shell (git-bash) or a real POSIX system, probed once at
    # import time.
    bash = shutil.which("bash")
    if bash is None:
        return None
    if sys.platform == "win32":
        lowered = {part.lower() for part in Path(bash).parts}
        if "system32" in lowered or "windowsapps" in lowered:
            return None
    probe = subprocess.run(
        [bash, "-c", "exit 0"],
        check=False,
        capture_output=True,
        timeout=30,
    )
    return bash if probe.returncode == 0 else None


BASH = _bash_path()


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


def test_local_start_commands_upgrade_the_database_before_api_or_worker() -> None:
    package = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    posix_launcher = (REPO_ROOT / "client/src-tauri/resources/start-backend.sh").read_text(
        encoding="utf-8"
    )
    windows_launcher = (REPO_ROOT / "client/src-tauri/resources/start-backend.bat").read_text(
        encoding="utf-8"
    )

    server_command = package["scripts"]["dev:server"]
    worker_command = package["scripts"]["dev:worker"]
    assert server_command.index("python -m app.bootstrap") < server_command.index(
        "python -m uvicorn"
    )
    assert worker_command.index("python -m app.bootstrap") < worker_command.index(
        "python -m app.generation_worker"
    )
    assert "--no-proxy-headers" in server_command
    assert "--no-proxy-headers" in posix_launcher
    assert "--no-proxy-headers" in windows_launcher
    assert posix_launcher.index("python -m app.bootstrap") < posix_launcher.index("start_server")
    assert windows_launcher.index("python -m app.bootstrap") < windows_launcher.index(
        'start "video-replica-api"'
    )


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
    assert workflow.count("persist-credentials: false") == 3
    assert "secret-scan:" in workflow
    assert "name: Secret scan" in workflow
    assert "quality-linux:" in workflow
    assert "name: Linux quality gate" in workflow
    assert "windows-nsis:" in workflow
    assert "name: Windows Tauri and NSIS" in workflow
    assert workflow.count(f"if: {fork_pr_guard}") == 3
    assert workflow.count("runs-on: ubuntu-24.04") == 2
    assert workflow.count("runs-on: windows-2025") == 1
    assert "npm run check:security" in workflow
    assert "run: npm run check\n" in workflow
    assert "npm run build" in workflow
    assert "npm audit --audit-level=high" in workflow
    assert "cargo test --manifest-path client/src-tauri/Cargo.toml --locked" in workflow
    assert "npm run check:tauri" in workflow
    assert "npm run check:tauri:customer" in workflow
    assert "npm run tauri:build -- --bundles nsis --no-sign --ci" in workflow
    assert "npm run tauri:build:customer" in workflow
    assert "VITE_API_BASE_URL: https://staging.example.invalid" in workflow
    windows_job = workflow.split("\n  windows-nsis:\n", 1)[1]
    job_config, windows_steps = windows_job.split("\n    steps:\n", 1)
    assert "runner.temp" not in job_config
    assert "LOCAL_ARTIFACT_ROOT" not in job_config
    for step_name in (
        "Archive unsigned internal NSIS installer locally",
        "Archive unsigned customer cloud NSIS installer locally",
    ):
        step = windows_steps.split(f"      - name: {step_name}\n", 1)[1].split(
            "\n      - name:", 1
        )[0]
        assert (
            "\n        env:\n"
            "          LOCAL_ARTIFACT_ROOT: ${{ runner.temp }}/video-replica-artifacts\n"
        ) in step
    assert workflow.count("LOCAL_ARTIFACT_ROOT") == 8
    assert workflow.count("Set-Content -LiteralPath (Join-Path $destination 'SHA256SUMS.txt')") == 2
    assert "Verify customer installer excludes local launchers" in workflow
    assert "7-Zip\\7z.exe" in workflow
    assert "start-backend.bat" in workflow
    assert "start-backend.sh" in workflow
    assert workflow.count("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1") == 3
    assert workflow.count("actions/setup-node@820762786026740c76f36085b0efc47a31fe5020") == 3
    assert "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97" in workflow
    assert "actions/upload-artifact@" not in workflow
    assert "actions/download-artifact@" not in workflow
    assert "msys2/setup-msys2@66cd2cce69caa17b53920067426061ca1de3a884" in workflow
    assert "Download and verify FFmpeg source" in workflow
    assert "Set up MSYS2 build toolchain" in workflow
    assert "Build LGPL Windows ffmpeg tools" in workflow
    assert "Verify Windows media tools" in workflow
    assert "Verify internal installer contains Windows media tools" in workflow
    assert "ffmpeg-7.1.5.tar.xz" in workflow
    assert "COPYING.LGPLv3" in workflow
    assert "SOURCE-NOTICE.md" in workflow
    assert "ffmpeg-smoke.wav" in workflow
    assert "ffmpeg-smoke.m4a" in workflow
    assert "ffmpeg-smoke.mp3" in workflow
    assert "h264-valid.mp4" in workflow
    assert "h264-truncated.mp4" in workflow
    assert "progress=end" in workflow
    assert "valid audio stream failed full decode" in workflow
    assert "valid H.264 video stream failed full decode" in workflow
    assert "truncated H.264 video unexpectedly passed full decode" in workflow
    assert "$truncatedStatus = $LASTEXITCODE" in workflow
    assert "if ($truncatedStatus -eq 0)" in workflow
    assert "exit 0" in workflow.split("truncated H.264 video unexpectedly passed", 1)[1]
    assert "payload hash mismatch" in workflow
    assert ".cargo-target/release/bundle/nsis/*.exe" in workflow


def test_windows_ffmpeg_builder_targets_pe_executables_and_tauri_bundles_directory() -> None:
    dockerfile = (REPO_ROOT / "scripts/ffmpeg-minimal/Dockerfile").read_text(encoding="utf-8")
    build_script = (REPO_ROOT / "scripts/ffmpeg-minimal/build.sh").read_text(encoding="utf-8")
    msys2_script = (REPO_ROOT / "scripts/ffmpeg-minimal/build-windows-msys2.sh").read_text(
        encoding="utf-8"
    )
    configure_script = (REPO_ROOT / "scripts/ffmpeg-minimal/configure.sh").read_text(
        encoding="utf-8"
    )
    tauri_config = json.loads(
        (REPO_ROOT / "client/src-tauri/tauri.conf.json").read_text(encoding="utf-8")
    )
    customer_config = json.loads(
        (REPO_ROOT / "client/src-tauri/tauri.customer.conf.json").read_text(encoding="utf-8")
    )
    license_text = (REPO_ROOT / "client/src-tauri/resources/ffmpeg/COPYING.LGPLv3").read_text(
        encoding="utf-8"
    )
    source_notice = (REPO_ROOT / "client/src-tauri/resources/ffmpeg/SOURCE-NOTICE.md").read_text(
        encoding="utf-8"
    )

    assert "gcc-mingw-w64-x86-64" in dockerfile
    assert (
        "FROM debian:bookworm-slim@sha256:"
        "88200866dfff7ea7f5cbcb6ec7c8a701889efe6fe859fe64d6990e4b07ea4171"
    ) in dockerfile
    assert "ARG FFMPEG_VERSION=7.1.5" in dockerfile
    assert "de668509caf9e35e3cd162473441fdb29538c6d96ed080292b3cf9e6fc5d558f" in dockerfile
    assert "FFMPEG_CROSS_PREFIX=x86_64-w64-mingw32-" in dockerfile
    assert "--target-os=mingw32" in configure_script
    assert '"--cross-prefix=${FFMPEG_CROSS_PREFIX}"' in configure_script
    assert "--disable-everything" in configure_script
    assert "--enable-version3" in configure_script
    assert "--enable-protocol=file,pipe" in configure_script
    assert "--enable-parser=" in configure_script
    assert "h264" in configure_script
    assert "--enable-decoder=" in configure_script
    assert "hevc" in configure_script
    assert "mpeg4" in configure_script
    assert "vp8" in configure_script
    assert "vp9" in configure_script
    assert "--enable-encoder=" in configure_script
    assert "wrapped_avframe" in configure_script
    assert "--enable-muxer=" in configure_script
    assert "null" in configure_script
    assert "COPY --from=build /src/ffmpeg.exe /ffmpeg.exe" in dockerfile
    assert "COPY --from=build /src/ffprobe.exe /ffprobe.exe" in dockerfile
    assert "COPY --from=build /tmp/ffmpeg-source.tar.xz /ffmpeg-7.1.5.tar.xz" in dockerfile
    assert "COPY --from=build /tmp/BUILD-PACKAGES.txt /BUILD-PACKAGES.txt" in dockerfile
    assert "x86_64-linux-musl" not in dockerfile
    assert "ffmpeg.exe" in build_script
    assert "ffprobe.exe" in build_script
    assert "ffmpeg-7.1.5.tar.xz" in build_script
    assert "configure.sh" in msys2_script
    assert "pacman -Q" in msys2_script
    assert "SHA256SUMS.txt" in msys2_script
    assert "de668509caf9e35e3cd162473441fdb29538c6d96ed080292b3cf9e6fc5d558f" in msys2_script
    assert tauri_config["bundle"]["resources"] == ["resources/"]
    assert customer_config["bundle"]["resources"] == []
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in license_text
    assert "Version 3" in license_text
    assert "FFmpeg 7.1.5" in source_notice
    assert "Source modifications: none" in source_notice
    assert "--disable-everything" in source_notice
    assert "--enable-version3" in source_notice
    assert "--enable-protocol=file,pipe" in source_notice
    assert "wrapped_avframe" in source_notice
    assert "--enable-muxer=mp4,ipod,adts,flac,wav,null" in source_notice
    assert "de668509caf9e35e3cd162473441fdb29538c6d96ed080292b3cf9e6fc5d558f" in source_notice


def test_windows_ffmpeg_validation_fixtures_are_stable_synthetic_media() -> None:
    fixture_root = REPO_ROOT / "scripts" / "ffmpeg-minimal" / "fixtures"
    expected = {
        "ffmpeg-smoke.mp3.b64": (
            4941,
            "d77ea9bd333a27ab042154cdfbf96ff8c3fd3e58a7be0cd2fbba48f9dd051c56",
        ),
        "h264-valid.mp4.b64": (
            1831,
            "c778f7ac74d7fb2e3f6bc0c019fd1a6dd1f382a958aaa7a48451ceba6b72f15e",
        ),
    }

    for name, (expected_size, expected_sha256) in expected.items():
        encoded = (fixture_root / name).read_text(encoding="ascii").strip()
        decoded = base64.b64decode(encoded, validate=True)
        assert len(decoded) == expected_size
        assert hashlib.sha256(decoded).hexdigest() == expected_sha256


def test_posix_backend_launcher_executes_default_commands(tmp_path: Path) -> None:
    if BASH is None:
        pytest.skip("a functional bash is required for the POSIX launcher flow")
    assert BASH is not None
    launcher = tmp_path / "start-backend.sh"
    shutil.copy2(REPO_ROOT / "client/src-tauri/resources/start-backend.sh", launcher)
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        """#!/bin/sh
case "$*" in
  *app.bootstrap*) printf '%s' "$*" > "$TEST_BOOTSTRAP_MARKER" ;;
  *uvicorn*) printf '%s' "$*" > "$TEST_SERVER_MARKER" ;;
  *generation_worker*) printf '%s' "$*" > "$TEST_WORKER_MARKER" ;;
  *) exit 64 ;;
esac
""",
        encoding="utf-8",
    )
    fake_uv.chmod(fake_uv.stat().st_mode | stat.S_IXUSR)

    server_marker = tmp_path / "server.args"
    worker_marker = tmp_path / "worker.args"
    bootstrap_marker = tmp_path / "bootstrap.args"
    env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "TEST_SERVER_MARKER": str(server_marker),
        "TEST_WORKER_MARKER": str(worker_marker),
        "TEST_BOOTSTRAP_MARKER": str(bootstrap_marker),
        "VIDEO_REPLICA_DB_PATH": str(tmp_path / "app.db"),
        "VIDEO_REPLICA_SETTINGS_KEY": "test-settings-key",
        "VIDEO_REPLICA_DESKTOP_USER_ID": "employee_1",
    }

    result = subprocess.run(
        [BASH, str(launcher)],
        check=False,
        capture_output=True,
        env=env,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "python -m app.bootstrap" in bootstrap_marker.read_text(encoding="utf-8")
    assert "python -m uvicorn app.main:app" in server_marker.read_text(encoding="utf-8")
    assert "python -m app.generation_worker" in worker_marker.read_text(encoding="utf-8")


def test_packaged_launchers_reject_partial_command_overrides(tmp_path: Path) -> None:
    launcher = tmp_path / "start-backend.sh"
    shutil.copy2(REPO_ROOT / "client/src-tauri/resources/start-backend.sh", launcher)
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR)

    partial_overrides = (
        {
            "VIDEO_REPLICA_SERVER_CMD": "/usr/bin/true",
            "VIDEO_REPLICA_WORKER_CMD": "/usr/bin/true",
        },
        {
            "VIDEO_REPLICA_BOOTSTRAP_CMD": "/usr/bin/true",
            "VIDEO_REPLICA_SERVER_CMD": "/usr/bin/true",
        },
        {
            "VIDEO_REPLICA_BOOTSTRAP_CMD": "/usr/bin/true",
            "VIDEO_REPLICA_WORKER_CMD": "/usr/bin/true",
        },
    )
    expected_error = "packaged bootstrap, server, and worker commands must be set together"
    if BASH is not None:
        for overrides in partial_overrides:
            env = {
                **os.environ,
                "VIDEO_REPLICA_DB_PATH": str(tmp_path / "app.db"),
                "VIDEO_REPLICA_DESKTOP_USER_ID": "employee_1",
                **overrides,
            }
            result = subprocess.run(
                [BASH, str(launcher)],
                check=False,
                capture_output=True,
                env=env,
                text=True,
                timeout=10,
            )

            assert result.returncode != 0
            assert expected_error in str(result.stderr)

    windows_launcher = (REPO_ROOT / "client/src-tauri/resources/start-backend.bat").read_text(
        encoding="utf-8"
    )
    distribution_plan = (REPO_ROOT / "docs/服务端分发与自动拉起方案.md").read_text(encoding="utf-8")
    assert expected_error in windows_launcher
    assert "VIDEO_REPLICA_BOOTSTRAP_CMD" in distribution_plan


def test_posix_packaged_launcher_runs_without_uv_or_server_sources(tmp_path: Path) -> None:
    if BASH is None:
        pytest.skip("a functional bash is required for the POSIX launcher flow")
    assert BASH is not None
    launcher = tmp_path / "start-backend.sh"
    shutil.copy2(REPO_ROOT / "client/src-tauri/resources/start-backend.sh", launcher)
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR)

    marker_dir = tmp_path / "markers"
    marker_dir.mkdir()
    commands: dict[str, str] = {}
    for name in ("bootstrap", "server", "worker"):
        command = tmp_path / name
        # as_posix(): the launcher hands the override commands to
        # ``sh -c``, where Windows backslash separators would be eaten as
        # escape characters (identical to str() on POSIX).
        command_path = command.as_posix()
        marker_path = (marker_dir / name).as_posix()
        command.write_text(
            f"#!/bin/sh\nprintf '%s' '{name}' > '{marker_path}'\n",
            encoding="utf-8",
        )
        command.chmod(command.stat().st_mode | stat.S_IXUSR)
        commands[name] = command_path

    env = {
        **os.environ,
        "PATH": "/usr/bin:/bin",
        "VIDEO_REPLICA_DB_PATH": str(tmp_path / "app.db"),
        "VIDEO_REPLICA_DESKTOP_USER_ID": "employee_1",
        "VIDEO_REPLICA_BOOTSTRAP_CMD": commands["bootstrap"],
        "VIDEO_REPLICA_SERVER_CMD": commands["server"],
        "VIDEO_REPLICA_WORKER_CMD": commands["worker"],
    }
    result = subprocess.run(
        [BASH, str(launcher)],
        check=False,
        capture_output=True,
        env=env,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert {path.name for path in marker_dir.iterdir()} == {"bootstrap", "server", "worker"}
