"""CW-025: 桌面制品不注入 PG DSN 断言（CW-020 三配置布局）。

账本要求："验证桌面制品不接收 PG DSN，API 与 Worker 只连接同一登记 PG"。

CW-020 将客户配置提升为唯一默认后，桌面端由三份 Tauri 配置构成：
- base ``tauri.conf.json``：客户 foundation（唯一默认），承载 identifier
  ``com.xiangshu.video-replica.customer``、version、窗口 url="customer"、
  resources=[]、HTTPS-only CSP、longDescription"不包含本地 API 或 Worker 启动器"。
- customer overlay ``tauri.customer.conf.json``：仅追加发行专属 installerHooks。
- internal overlay ``tauri.internal.conf.json``：内部 opt-in（仅经
  ``--features local-sidecar`` 显式触发），identifier ``com.internal.video-replica``、
  CSP 含 loopback、resources 打包本地启动器（归 CW-021 退役）。

客户制品 = base + customer overlay 合并，是纯 UI 壳，连接云端 HTTPS API，
不包含本地后端启动器，也不应该接收 PG DSN 环境变量。

本文件验证：
1. 客户制品配置（base + customer overlay）不含 VIDEO_REPLICA_DATABASE_URL / DB_PATH。
2. base（客户 foundation）resources=[] 不打包 start-backend.sh，描述明确不含本地启动器。
3. 唯一默认客户构建脚本（tauri:build）不注入 PG DSN，内部构建须显式 opt-in。
4. 内部 opt-in 制品（tauri.internal.conf.json）与客户制品 identifier 隔离。

注意：start-backend.sh / local-sidecar 源码本身归 CW-021/CW-040 处理，
本测试只验证客户制品不引用它、且任何桌面制品都不接收 PG DSN。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_TAURI = REPO_ROOT / "client" / "src-tauri"
# CW-020：base = 客户 foundation（唯一默认）；customer overlay 仅追加 installerHooks；
# internal overlay = 内部 opt-in（--features local-sidecar 显式触发）。
TAURI_BASE_CONF = SRC_TAURI / "tauri.conf.json"
TAURI_CUSTOMER_OVERLAY_CONF = SRC_TAURI / "tauri.customer.conf.json"
TAURI_INTERNAL_OVERLAY_CONF = SRC_TAURI / "tauri.internal.conf.json"
PACKAGE_JSON = REPO_ROOT / "package.json"
REQUIRE_CUSTOMER_API_BASE = REPO_ROOT / "scripts" / "require_customer_api_base.mjs"


def test_customer_tauri_config_exists() -> None:
    """前置检查：CW-020 三份桌面制品配置（base + customer overlay + internal overlay）均存在。"""
    for conf in (TAURI_BASE_CONF, TAURI_CUSTOMER_OVERLAY_CONF, TAURI_INTERNAL_OVERLAY_CONF):
        assert conf.exists(), f"桌面制品配置不存在: {conf}"


def test_customer_tauri_config_has_no_database_url_env() -> None:
    """CW-025: 客户制品配置（base + customer overlay）不含 VIDEO_REPLICA_DATABASE_URL。

    客户制品是纯 UI 壳，通过 HTTPS 连接云端 API，不应该接收 PG DSN。CW-020 后
    客户 foundation（identifier/resources/CSP）在 base tauri.conf.json，customer
    overlay 仅追加 installerHooks——两者都不得注入 PG DSN 或 DB_PATH。
    """
    for conf in (TAURI_BASE_CONF, TAURI_CUSTOMER_OVERLAY_CONF):
        config_text = conf.read_text(encoding="utf-8")
        config = json.loads(config_text)

        # 检查整个配置文件不含 DATABASE_URL / DB_PATH 相关字符串
        assert "VIDEO_REPLICA_DATABASE_URL" not in config_text, (
            f"{conf.name} 不得含 VIDEO_REPLICA_DATABASE_URL"
        )
        assert "DATABASE_URL" not in config_text, f"{conf.name} 不得含任何 DATABASE_URL 引用"
        assert "VIDEO_REPLICA_DB_PATH" not in config_text, (
            f"{conf.name} 不得含 VIDEO_REPLICA_DB_PATH"
        )

        # 检查 env 字段（如果存在）不含 PG DSN
        if "env" in config:
            env_vars = config["env"]
            assert "VIDEO_REPLICA_DATABASE_URL" not in env_vars, (
                f"{conf.name} env 不得注入 VIDEO_REPLICA_DATABASE_URL"
            )


def test_customer_tauri_config_has_no_backend_resources() -> None:
    """CW-025: base（客户 foundation）resources=[] 不打包 start-backend.sh。

    客户制品描述明确："不包含本地 API 或 Worker 启动器"。CW-020 后 resources 与
    longDescription 由 base tauri.conf.json 承载（不再在瘦 customer overlay）。
    """
    config = json.loads(TAURI_BASE_CONF.read_text(encoding="utf-8"))

    # 检查 bundle.resources 为空
    bundle = config.get("bundle", {})
    resources = bundle.get("resources", [])
    assert resources == [], f"客户 base resources 必须为空（不打包后端启动器），实际: {resources}"

    # 检查描述明确说不含本地启动器
    long_description = bundle.get("longDescription", "")
    assert "不包含本地 API" in long_description or "不含本地" in long_description, (
        f"客户 base 描述应明确不含本地启动器，实际: {long_description}"
    )

    # base 即客户 foundation：identifier 含 customer、CSP 为 HTTPS-only（无本地 loopback 回退）
    assert "customer" in config.get("identifier", "").lower(), (
        f"客户 base identifier 应含 'customer': {config.get('identifier', '')}"
    )
    csp = config.get("app", {}).get("security", {}).get("csp", "")
    assert "127.0.0.1:8000" not in csp, f"客户 base CSP 不得含本地 loopback API 回退: {csp}"


def test_customer_tauri_config_does_not_reference_start_backend() -> None:
    """CW-025: 客户制品（base + customer overlay）不引用 start-backend.sh。"""
    for conf in (TAURI_BASE_CONF, TAURI_CUSTOMER_OVERLAY_CONF):
        config_text = conf.read_text(encoding="utf-8")

        assert "start-backend" not in config_text, (
            f"{conf.name} 不得引用 start-backend.sh（内部遗留物，归 CW-021/CW-040）"
        )
        assert "start_backend" not in config_text, f"{conf.name} 不得引用 start_backend"


def test_internal_tauri_config_is_separate_from_customer() -> None:
    """CW-025: 内部 opt-in 制品（tauri.internal.conf.json）与客户制品隔离。

    CW-020 后内部制品迁入独立 overlay，仅经 ``--features local-sidecar`` 显式触发；
    其 identifier 必须与客户 base 不同，确保内部发行不能冒充客户包（CW-020 DoD ②）。
    """
    assert TAURI_INTERNAL_OVERLAY_CONF.exists(), (
        f"内部制品配置不存在: {TAURI_INTERNAL_OVERLAY_CONF}"
    )
    assert TAURI_INTERNAL_OVERLAY_CONF != TAURI_BASE_CONF, (
        "内部制品和客户 base 必须是不同的配置文件"
    )

    internal_config = json.loads(TAURI_INTERNAL_OVERLAY_CONF.read_text(encoding="utf-8"))
    customer_config = json.loads(TAURI_BASE_CONF.read_text(encoding="utf-8"))

    # 检查 identifier 不同
    internal_id = internal_config.get("identifier", "")
    customer_id = customer_config.get("identifier", "")
    assert internal_id != customer_id, (
        f"内部制品和客户制品 identifier 必须不同: {internal_id} vs {customer_id}"
    )

    # 客户 base identifier 应含 "customer"，内部 overlay identifier 应含 "internal"
    assert "customer" in customer_id.lower(), f"客户制品 identifier 应含 'customer': {customer_id}"
    assert "internal" in internal_id.lower(), f"内部制品 identifier 应含 'internal': {internal_id}"

    # 客户 overlay 不重复承载 identifier（identifier 单一真源在 base foundation）
    overlay_config = json.loads(TAURI_CUSTOMER_OVERLAY_CONF.read_text(encoding="utf-8"))
    assert "identifier" not in overlay_config, (
        "客户 overlay 不应重复承载 identifier（由 base foundation 单一提供）"
    )


def test_package_json_customer_build_script_does_not_inject_pg_dsn() -> None:
    """CW-025: package.json 唯一默认客户构建脚本不注入 PG DSN。

    CW-020 后 ``tauri:build``（无后缀）即客户唯一默认，应使用 tauri.customer.conf.json
    + --no-default-features + origin guard，不注入 VIDEO_REPLICA_DATABASE_URL；
    ``tauri:build:customer`` 保留为别名。内部构建 ``tauri:build:internal`` 必须显式
    --features local-sidecar，同样不注入 PG DSN。
    """
    package = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    scripts = package.get("scripts", {})

    default_build = scripts.get("tauri:build", "")
    assert default_build, "package.json 缺少 tauri:build 脚本（唯一默认客户构建）"

    # 唯一默认构建不注入任何 PG DSN / DB_PATH
    assert "VIDEO_REPLICA_DATABASE_URL" not in default_build, (
        f"唯一默认客户构建脚本不得注入 VIDEO_REPLICA_DATABASE_URL: {default_build}"
    )
    assert "DATABASE_URL" not in default_build, (
        f"唯一默认客户构建脚本不得含任何 DATABASE_URL 引用: {default_build}"
    )
    assert "VIDEO_REPLICA_DB_PATH" not in default_build, (
        f"唯一默认客户构建脚本不得注入 VIDEO_REPLICA_DB_PATH: {default_build}"
    )

    # 唯一默认构建使用 customer overlay + --no-default-features（编译期排除 local-sidecar）
    assert "tauri.customer.conf.json" in default_build, (
        f"唯一默认客户构建脚本必须使用 tauri.customer.conf.json: {default_build}"
    )
    assert "--no-default-features" in default_build, (
        f"唯一默认客户构建脚本必须 --no-default-features（不打进 local-sidecar）: {default_build}"
    )

    # tauri:build:customer 保留为唯一默认的别名，同样不注入 PG DSN
    customer_alias = scripts.get("tauri:build:customer", "")
    assert customer_alias, "package.json 缺少 tauri:build:customer 别名脚本"
    assert "VIDEO_REPLICA_DATABASE_URL" not in customer_alias, (
        f"客户构建别名不得注入 VIDEO_REPLICA_DATABASE_URL: {customer_alias}"
    )

    # 内部构建脚本必须显式 opt-in（--features local-sidecar），且不注入 PG DSN
    internal_build = scripts.get("tauri:build:internal", "")
    assert internal_build, "package.json 缺少 tauri:build:internal 脚本（内部 opt-in）"
    assert "local-sidecar" in internal_build, (
        f"内部构建脚本必须显式 --features local-sidecar: {internal_build}"
    )
    assert "VIDEO_REPLICA_DATABASE_URL" not in internal_build, (
        f"内部构建脚本不得注入 VIDEO_REPLICA_DATABASE_URL: {internal_build}"
    )


def test_require_customer_api_base_script_does_not_inject_pg_dsn() -> None:
    """CW-025: require_customer_api_base.mjs 不注入 PG DSN。

    这个脚本只验证客户 API base URL 配置，不应该涉及数据库配置。
    """
    if not REQUIRE_CUSTOMER_API_BASE.exists():
        pytest.skip(f"脚本不存在: {REQUIRE_CUSTOMER_API_BASE}")

    script_text = REQUIRE_CUSTOMER_API_BASE.read_text(encoding="utf-8")

    # 检查脚本不含 DATABASE_URL 注入
    assert "VIDEO_REPLICA_DATABASE_URL" not in script_text, (
        "require_customer_api_base.mjs 不得注入 VIDEO_REPLICA_DATABASE_URL"
    )
    assert "DATABASE_URL" not in script_text, (
        "require_customer_api_base.mjs 不得含任何 DATABASE_URL 引用"
    )

    # 检查脚本不含 DB_PATH 注入
    assert "VIDEO_REPLICA_DB_PATH" not in script_text, (
        "require_customer_api_base.mjs 不得注入 VIDEO_REPLICA_DB_PATH"
    )


def test_customer_artifact_env_isolation_summary() -> None:
    """CW-025: 桌面制品环境隔离总结断言。

    综合验证：客户制品构建链路（package.json tauri:build →
    require_customer_api_base.mjs → base tauri.conf.json + customer overlay）
    全程不接触 PG DSN 或 DB_PATH，客户 foundation resources 为空；且内部 opt-in
    overlay 同样不接收 PG DSN（CW-025 不变量适用于全部桌面制品）。

    这是账本"验证桌面制品不接收 PG DSN"的最终验收断言。
    """
    # 1. 配置层面：三份桌面制品均不含 PG DSN / DB_PATH
    for conf in (TAURI_BASE_CONF, TAURI_CUSTOMER_OVERLAY_CONF, TAURI_INTERNAL_OVERLAY_CONF):
        conf_text = conf.read_text(encoding="utf-8")
        assert "VIDEO_REPLICA_DATABASE_URL" not in conf_text, f"{conf.name} 含 PG DSN"
        assert "VIDEO_REPLICA_DB_PATH" not in conf_text, f"{conf.name} 含 DB_PATH"

    # 2. 构建脚本层面（唯一默认 tauri:build + 内部 opt-in tauri:build:internal）
    package = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    scripts = package.get("scripts", {})
    for script_name in ("tauri:build", "tauri:build:internal"):
        build_script = scripts.get(script_name, "")
        assert "VIDEO_REPLICA_DATABASE_URL" not in build_script, f"{script_name} 注入 PG DSN"
        assert "VIDEO_REPLICA_DB_PATH" not in build_script, f"{script_name} 注入 DB_PATH"

    # 3. 辅助脚本层面
    if REQUIRE_CUSTOMER_API_BASE.exists():
        helper_text = REQUIRE_CUSTOMER_API_BASE.read_text(encoding="utf-8")
        assert "VIDEO_REPLICA_DATABASE_URL" not in helper_text
        assert "VIDEO_REPLICA_DB_PATH" not in helper_text

    # 4. 客户 foundation resources 为空（不打包任何后端启动器）
    base_conf = json.loads(TAURI_BASE_CONF.read_text(encoding="utf-8"))
    assert base_conf.get("bundle", {}).get("resources", []) == []
