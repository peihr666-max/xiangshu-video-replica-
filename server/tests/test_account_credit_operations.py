"""Account operations use real administrator sessions and a PostgreSQL ledger."""

# ruff: noqa: F811
from uuid import uuid4

import psycopg
import pytest
from test_customer_pricing import (  # noqa: F401
    account,
    admin_login,
    client,
    mutation,
    pricing_client,
    registration_client,
    registration_dsn,
    route_state,
    token_headers,
)


@pytest.fixture()
def operations_client(pricing_client):
    from app.account_admin_routes import router as account_router
    from app.admin_customer_routes import router

    pricing_client.app.include_router(router)
    pricing_client.app.include_router(account_router)
    from app.account_migration_routes import router as migration_router

    pricing_client.app.include_router(migration_router)
    from app.credit_conversion import router as conversion_router

    pricing_client.app.include_router(conversion_router)
    return pricing_client


def test_registered_account_is_listed_and_exported(operations_client, route_state):
    client = operations_client
    _, uid = account(client)
    admin_login(client, route_state)
    result = client.get("/api/control/customers", params={"username": "center_user"})
    assert result.status_code == 200, result.text
    assert result.json()["total"] == 1
    row = result.json()["items"][0]
    assert row["user_id"] == uid and row["activation_code"] == "账号注册"
    exported = client.get("/api/control/customers.csv", params={"username": "center_user"})
    assert exported.status_code == 200 and "center_user" in exported.text


@pytest.mark.parametrize("source", ["FREE_GRANT", "CREDIT_COMPENSATION"])
def test_gift_and_compensation_are_zero_revenue_and_replay(operations_client, route_state, source):
    client = operations_client
    customer, uid = account(client)
    headers = {**admin_login(client, route_state), "Idempotency-Key": str(uuid4())}
    payload = {
        "confirm": True,
        "reason": "Internal approval only",
        "credits": 123,
        "source_document_type": source,
        "source_document_ref": "LOCAL-APPROVAL",
    }
    path = f"/api/control/customers/{uid}/adjustments"
    first = client.post(path, headers=headers, json=payload)
    assert first.status_code == 201, first.text
    assert client.post(path, headers=headers, json=payload).json() == first.json()
    with psycopg.connect(route_state) as conn:
        assert (
            conn.execute(
                "SELECT available_credits FROM wallets WHERE user_id = %s", (uid,)
            ).fetchone()[0]
            == 123
        )
        order = conn.execute(
            "SELECT amount_fen, pricing_scope FROM recharge_orders WHERE user_id = %s", (uid,)
        ).fetchone()
        assert order == (0, "CUSTOMER_STANDARD")
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM admin_adjustments WHERE target_user_id = %s", (uid,)
            ).fetchone()[0]
            == 1
        )
    ledger = client.get("/api/customer/wallet/transactions", headers=customer)
    assert ledger.status_code == 200, ledger.text
    assert ledger.json()["items"][0]["credit_source"] == source
    assert "Internal approval" not in ledger.text and "LOCAL-APPROVAL" not in ledger.text


def test_native_payment_settings_work_with_admin_cookie(operations_client, route_state):
    client = operations_client
    admin = admin_login(client, route_state)
    path = "/api/control/settings/customer-payments"
    loaded = client.get(path)
    assert loaded.status_code == 200, loaded.text
    assert set(loaded.json()) == {"billing", "zpay"}
    payload = {
        "confirm": True,
        "reason": "local billing setup",
        "internal_base_unit_price_fen": 1000,
        "oral_unit_price_fen": 100,
        "min_recharge_fen": 20000,
        "recharge_step_fen": 1000,
    }
    updated = client.patch(
        path + "/billing", json=payload, headers={**admin, "Idempotency-Key": str(uuid4())}
    )
    assert updated.status_code == 200, updated.text
    assert client.get(path).json()["billing"]["min_recharge_fen"] == 20000


def test_admin_summary_never_exposes_secrets(operations_client, route_state):
    client = operations_client
    customer, uid = account(client)
    key = mutation(client, "", customer, {"label": "team-script"}).json()
    admin_login(client, route_state)
    response = client.get(f"/api/control/customers/{uid}/account-summary")
    assert response.status_code == 200, response.text
    assert response.json()["tokens"][0]["label"] == "team-script"
    assert key["plaintext"] not in response.text and "key_digest" not in response.text
    assert "password_hash" not in response.text


@pytest.mark.parametrize("receipt", ["valid", "unpaid", "mismatch", "revoked_admin"])
def test_original_order_reconcile_then_callback_credits_once(
    operations_client, route_state, monkeypatch, receipt
):
    from app import account_admin_routes
    from app.db_portable import BusinessConnection
    from app.payment_provider import DeploymentConfig, MerchantConfig, OrderQueryResult
    from app.zpay_payments import confirm_recharge_payment

    client = operations_client
    _, uid = account(client)
    admin = admin_login(client, route_state)
    with psycopg.connect(route_state) as conn:
        conn.execute(
            "INSERT INTO recharge_orders (id, user_id, merchant_order_no, provider, status, "
            "pricing_scope, base_unit_price_fen_snapshot, charged_unit_price_fen_snapshot, "
            "min_recharge_fen_snapshot, recharge_step_fen_snapshot, amount_fen, credits) "
            "VALUES ('uc4-order', %s, 'UC4-ORDER', 'zpay', 'PENDING', 'CUSTOMER_STANDARD', "
            "1000, 1000, 10000, 1000, 20000, 20)",
            (uid,),
        )

    class Gateway:
        def load_merchant_config(self, conn):
            return MerchantConfig("zpay", {}, ("alipay",))

        def load_deployment_config(self):
            return DeploymentConfig("", "")

        def query_order(self, **kwargs):
            if receipt == "revoked_admin":
                with psycopg.connect(route_state) as raw:
                    raw.execute("UPDATE admin_sessions SET revoked_at = CURRENT_TIMESTAMP")
            return OrderQueryResult(
                receipt != "unpaid",
                "UC4-ORDER",
                "UC4-TRADE",
                19999 if receipt == "mismatch" else 20000,
                "alipay",
                "verified-local",
            )

    monkeypatch.setattr(account_admin_routes, "get_payment_provider", lambda name: Gateway())
    path = f"/api/control/customers/{uid}/recharge-orders/UC4-ORDER/reconcile"
    result = client.post(
        path,
        headers={**admin, "Idempotency-Key": str(uuid4())},
        json={"confirm": True, "reason": "original receipt check"},
    )
    if receipt != "valid":
        assert result.status_code in (401, 403, 409), result.text
        with psycopg.connect(route_state) as raw:
            assert (
                raw.execute(
                    "SELECT available_credits FROM wallets WHERE user_id = %s", (uid,)
                ).fetchone()[0]
                == 0
            )
            assert (
                raw.execute("SELECT status FROM recharge_orders WHERE id = 'uc4-order'").fetchone()[
                    0
                ]
                == "PENDING"
            )
        return
    assert result.status_code == 200, result.text
    with psycopg.connect(route_state) as raw:
        confirm_recharge_payment(
            BusinessConnection.postgres(raw),
            merchant_order_no="UC4-ORDER",
            provider_trade_no="UC4-TRADE",
            amount_fen=20000,
            channel="alipay",
            source_digest="callback",
            allowed_channels=("alipay",),
        )
        assert (
            raw.execute(
                "SELECT available_credits FROM wallets WHERE user_id = %s", (uid,)
            ).fetchone()[0]
            == 20
        )
        assert (
            raw.execute(
                "SELECT COUNT(*) FROM wallet_transactions WHERE recharge_order_id = 'uc4-order'"
            ).fetchone()[0]
            == 1
        )


@pytest.mark.parametrize("role", ["customer", "auditor"])
def test_non_writers_cannot_mutate_account_credits(operations_client, route_state, role):
    client = operations_client
    customer, uid = account(client)
    admin = admin_login(client, route_state)
    with psycopg.connect(route_state) as conn:
        conn.execute("UPDATE users SET role = %s WHERE username = 'price_admin'", (role,))
    response = client.post(
        f"/api/control/customers/{uid}/adjustments",
        headers={**admin, "Idempotency-Key": str(uuid4())},
        json={
            "confirm": True,
            "reason": "must deny",
            "credits": 10,
            "source_document_type": "FREE_GRANT",
            "source_document_ref": "denied",
        },
    )
    assert response.status_code in (401, 403), response.text
    assert client.get("/api/customer/wallet", headers=customer).json()["available_credits"] == 0


@pytest.mark.parametrize("credits", [1.5, True, 0, -1])
def test_admin_credit_input_is_strict_positive_integer(operations_client, route_state, credits):
    client = operations_client
    _, uid = account(client)
    admin = admin_login(client, route_state)
    response = client.post(
        f"/api/control/customers/{uid}/adjustments",
        headers={**admin, "Idempotency-Key": str(uuid4())},
        json={
            "confirm": True,
            "reason": "integer check",
            "credits": credits,
            "source_document_type": "FREE_GRANT",
            "source_document_ref": "input",
        },
    )
    assert response.status_code in (400, 422), response.text


@pytest.mark.parametrize("suffix", ["recharge-orders", "wallet-transactions"])
def test_native_account_ledger_reads_without_control_proxy(operations_client, route_state, suffix):
    client = operations_client
    _, uid = account(client)
    admin = admin_login(client, route_state)
    grant = client.post(
        f"/api/control/customers/{uid}/adjustments",
        headers={**admin, "Idempotency-Key": str(uuid4())},
        json={
            "confirm": True,
            "reason": "native account ledger",
            "credits": 25,
            "source_document_type": "FREE_GRANT",
            "source_document_ref": "native-read",
        },
    )
    assert grant.status_code == 201, grant.text
    result = client.get(f"/api/control/customers/{uid}/{suffix}", params={"limit": 3, "offset": 0})
    assert result.status_code == 200, result.text
    assert result.json()["total"] == 1
    assert result.json()["items"][0]["user_id"] == uid
    assert "password_hash" not in result.text


def test_concurrent_grant_payment_and_token_consumption_conserve_account_ledger(
    operations_client, route_state
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from test_customer_pricing import reserve, seed_tasks

    from app.db_portable import BusinessConnection
    from app.internal_billing import finalize_internal_billing
    from app.zpay_payments import confirm_recharge_payment

    client = operations_client
    customer, uid = account(client)
    key = mutation(client, "", customer, {"label": "concurrent worker"}).json()
    admin = admin_login(client, route_state)
    seed_tasks(route_state, uid, ["concurrent-credit-task"], balance=0)

    def grant(credits, reference):
        result = client.post(
            f"/api/control/customers/{uid}/adjustments",
            headers={**admin, "Idempotency-Key": str(uuid4())},
            json={
                "confirm": True,
                "reason": "concurrent account accounting",
                "credits": credits,
                "source_document_type": "FREE_GRANT",
                "source_document_ref": reference,
            },
        )
        assert result.status_code == 201, result.text

    grant(100, "opening-balance")
    with psycopg.connect(route_state) as raw:
        raw.execute(
            "INSERT INTO recharge_orders (id, user_id, merchant_order_no, provider, status, "
            "pricing_scope, base_unit_price_fen_snapshot, charged_unit_price_fen_snapshot, "
            "min_recharge_fen_snapshot, recharge_step_fen_snapshot, amount_fen, credits) "
            "VALUES ('concurrent-order', %s, 'CONCURRENT-ORDER', 'zpay', 'PENDING', "
            "'CUSTOMER_STANDARD', 1000, 1000, 10000, 1000, 20000, 20)",
            (uid,),
        )

    barrier = Barrier(3, timeout=15)

    def change(kind):
        barrier.wait()
        if kind == "gift":
            grant(25, "concurrent-gift")
        elif kind == "payment":
            with psycopg.connect(route_state) as raw:
                confirm_recharge_payment(
                    BusinessConnection.postgres(raw),
                    merchant_order_no="CONCURRENT-ORDER",
                    provider_trade_no="CONCURRENT-TRADE",
                    amount_fen=20000,
                    channel="alipay",
                    source_digest="local-verified-callback",
                    allowed_channels=("alipay",),
                )
        else:
            reserve(route_state, uid, key["id"], "concurrent-credit-task", 20)
            with psycopg.connect(route_state) as raw:
                raw.execute(
                    "UPDATE generation_tasks SET status = 'SUCCEEDED', archive_status = "
                    "'DIRECT', provider_result_url = 'https://example.com/test.mp4' "
                    "WHERE id = 'concurrent-credit-task'"
                )
                finalize_internal_billing(
                    BusinessConnection.postgres(raw),
                    task_id="concurrent-credit-task",
                    outcome="success",
                )

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(change, ("gift", "payment", "token")))
    with psycopg.connect(route_state) as raw:
        assert raw.execute(
            "SELECT available_credits, reserved_credits FROM wallets WHERE user_id = %s", (uid,)
        ).fetchone() == (85, 0)
        assert raw.execute(
            "SELECT SUM(available_delta), SUM(reserved_delta) FROM wallet_transactions "
            "WHERE user_id = %s",
            (uid,),
        ).fetchone() == (85, 0)
        assert (
            raw.execute(
                "SELECT COUNT(*) FROM wallet_transactions WHERE user_id = %s AND type = 'CHARGE'",
                (uid,),
            ).fetchone()[0]
            == 3
        )
    listed = client.get("/api/customer/api-keys", headers=customer).json()["items"]
    assert next(item for item in listed if item["id"] == key["id"])["total_consumed_credits"] == 60
