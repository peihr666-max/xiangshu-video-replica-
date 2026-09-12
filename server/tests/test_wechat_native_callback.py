"""CW-070: WeChat Pay V3 Native callback wiring — crypto + route (non-settlement).

TDD red suite for the WeChat Native notification callback. Covers the two parts
that never touch a wechat_native recharge_order (those are PostgreSQL-only and
live in test_wechat_native_callback_pg.py):

1. ``WeChatNativeProvider.verify_notification_raw`` — raw-body signature
   verification over the exact bytes plus AES-256-GCM resource decryption, using
   a self-generated test platform key/certificate and a stub certificate manager.
   No network, no database, no real WeChat credentials.
2. The ``POST /api/payments/wechat_native/notify`` route's non-settlement paths
   (forged → FAIL, authentic-but-unpaid → SUCCESS ACK, missing config → FAIL) on
   the SQLite lane, asserting ``confirm_recharge_payment`` is never reached.

The ZPay byte-identical regression stays in test_payments.py (unchanged).
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient

from app.db import initialize_database
from app.db_portable import BusinessConnection
from app.main import app
from app.payment_provider import MerchantConfig
from app.payment_routes import get_wechat_provider
from app.wechat_native_client import (
    PlatformCertificateManager,
    WeChatMerchantConfig,
    WeChatNativeError,
    WeChatPlatformCertificate,
    build_response_verify_message,
)
from app.wechat_native_provider import (
    WECHAT_CALLBACK_BODY_INVALID,
    WECHAT_CALLBACK_CERT_UNAVAILABLE,
    WECHAT_CALLBACK_DECRYPT_FAILED,
    WECHAT_CALLBACK_MISSING_HEADERS,
    WECHAT_CALLBACK_PAYLOAD_INVALID,
    WECHAT_CALLBACK_SIGNATURE_INVALID,
    WeChatNativeProvider,
    WeChatNotificationResult,
)

API_V3_KEY = "0123456789abcdef0123456789abcdef"
NOTIFY_PATH = "/api/payments/wechat_native/notify"
OUT_TRADE_NO = "202609120000000000000000000000w1"
TRANSACTION_ID = "4200001234202609120000000001"


# ---------------------------------------------------------------------------
# Test platform key / self-signed certificate fixtures (no real WeChat material)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def platform_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def platform_cert(platform_key: rsa.RSAPrivateKey) -> x509.Certificate:
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "WeChat Pay Test Platform")])
    now = dt.datetime.now(dt.UTC)
    return (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(platform_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=365))
        .sign(platform_key, hashes.SHA256())
    )


@pytest.fixture(scope="module")
def platform_serial(platform_cert: x509.Certificate) -> str:
    return format(platform_cert.serial_number, "X")


@pytest.fixture(scope="module")
def platform_certificate(
    platform_cert: x509.Certificate, platform_serial: str
) -> WeChatPlatformCertificate:
    return WeChatPlatformCertificate(
        serial_no=platform_serial,
        public_key=cast(RSAPublicKey, platform_cert.public_key()),
        not_after=platform_cert.not_valid_after_utc,
    )


@pytest.fixture(scope="module")
def wrong_key() -> rsa.RSAPrivateKey:
    """A second key that is NOT the platform key — signs forged callbacks."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _StubCertManager(PlatformCertificateManager):
    """Returns one canned platform certificate; raises for any other serial.

    Subclasses the real manager so the provider's ``cert_manager`` type holds,
    but overrides ``get_certificate`` so no network fetch ever happens.
    """

    def __init__(self, certificate: WeChatPlatformCertificate) -> None:
        super().__init__()
        self._certificate = certificate

    def get_certificate(
        self, merchant: WeChatMerchantConfig, serial_no: str
    ) -> WeChatPlatformCertificate:
        if serial_no != self._certificate.serial_no:
            raise WeChatNativeError("WeChat platform certificate serial not found")
        return self._certificate


def _merchant_config() -> MerchantConfig:
    return MerchantConfig(
        provider="wechat_native",
        raw={
            "appid": "wx8123456789",
            "mchid": "1900000001",
            "serial_no": "MERCHANTSERIAL0001",
            "api_v3_key": API_V3_KEY,
            "private_key": "-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----",
        },
        allowed_channels=("wxpay",),
    )


def _encrypt_resource(
    plaintext: bytes, *, api_v3_key: str, nonce: str, associated_data: str
) -> str:
    ciphertext = AESGCM(api_v3_key.encode()).encrypt(
        nonce.encode(), plaintext, associated_data.encode()
    )
    return base64.b64encode(ciphertext).decode("ascii")


def _success_resource_plaintext(
    *,
    out_trade_no: str = OUT_TRADE_NO,
    transaction_id: str | None = TRANSACTION_ID,
    trade_state: str = "SUCCESS",
    amount_total: int = 10000,
) -> bytes:
    payload: dict[str, object] = {
        "appid": "wx8123456789",
        "mchid": "1900000001",
        "out_trade_no": out_trade_no,
        "trade_state": trade_state,
        "amount": {"total": amount_total, "payer_total": amount_total, "currency": "CNY"},
    }
    if transaction_id is not None:
        payload["transaction_id"] = transaction_id
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def build_callback(
    *,
    signing_key: rsa.RSAPrivateKey,
    serial: str,
    resource_plaintext: bytes,
    api_v3_key: str = API_V3_KEY,
    resource_nonce: str = "resnonce123456",
    associated_data: str = "transaction",
    timestamp: str = "1700000000",
    header_nonce: str = "hdrnonce1234567",
    encrypt_key: str | None = None,
) -> tuple[bytes, dict[str, str]]:
    """Build a raw callback body plus its Wechatpay-* headers, signed by signing_key."""
    ciphertext = _encrypt_resource(
        resource_plaintext,
        api_v3_key=encrypt_key or api_v3_key,
        nonce=resource_nonce,
        associated_data=associated_data,
    )
    body = json.dumps(
        {
            "id": "evt-cw070-1",
            "create_time": "2026-09-12T12:00:00+08:00",
            "event_type": "TRANSACTION.SUCCESS",
            "resource_type": "encrypt-resource",
            "resource": {
                "algorithm": "AEAD_AES_256_GCM",
                "ciphertext": ciphertext,
                "associated_data": associated_data,
                "nonce": resource_nonce,
                "original_type": "transaction",
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")
    message = build_response_verify_message(
        timestamp=timestamp, nonce=header_nonce, body=body.decode("utf-8")
    )
    signature = signing_key.sign(message.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    headers = {
        "Wechatpay-Timestamp": timestamp,
        "Wechatpay-Nonce": header_nonce,
        "Wechatpay-Signature": base64.b64encode(signature).decode("ascii"),
        "Wechatpay-Serial": serial,
        "Content-Type": "application/json",
    }
    return body, headers


def _provider(platform_certificate: WeChatPlatformCertificate) -> WeChatNativeProvider:
    return WeChatNativeProvider(cert_manager=_StubCertManager(platform_certificate))


def _verify(
    provider: WeChatNativeProvider,
    *,
    body: bytes,
    headers: dict[str, str],
    merchant: MerchantConfig | None = None,
) -> WeChatNotificationResult:
    return provider.verify_notification_raw(
        raw_body=body,
        timestamp=headers.get("Wechatpay-Timestamp"),
        nonce=headers.get("Wechatpay-Nonce"),
        signature=headers.get("Wechatpay-Signature"),
        serial=headers.get("Wechatpay-Serial"),
        merchant=merchant or _merchant_config(),
    )


# ---------------------------------------------------------------------------
# verify_notification_raw — pure crypto (no DB, no network)
# ---------------------------------------------------------------------------


def test_verify_notification_raw_accepts_valid_success(
    platform_key: rsa.RSAPrivateKey,
    platform_serial: str,
    platform_certificate: WeChatPlatformCertificate,
) -> None:
    body, headers = build_callback(
        signing_key=platform_key,
        serial=platform_serial,
        resource_plaintext=_success_resource_plaintext(),
    )
    result = _verify(_provider(platform_certificate), body=body, headers=headers)
    assert result.authenticated is True
    assert result.error_code is None
    assert result.trade_state == "SUCCESS"
    assert result.merchant_order_no == OUT_TRADE_NO
    assert result.provider_trade_no == TRANSACTION_ID
    assert result.amount_fen == 10000
    assert result.channel == "wxpay"
    assert result.source_digest == hashlib.sha256(body).hexdigest()


def test_verify_notification_raw_rejects_forged_signature(
    wrong_key: rsa.RSAPrivateKey,
    platform_serial: str,
    platform_certificate: WeChatPlatformCertificate,
) -> None:
    body, headers = build_callback(
        signing_key=wrong_key,
        serial=platform_serial,
        resource_plaintext=_success_resource_plaintext(),
    )
    result = _verify(_provider(platform_certificate), body=body, headers=headers)
    assert result.authenticated is False
    assert result.error_code == WECHAT_CALLBACK_SIGNATURE_INVALID
    assert result.merchant_order_no is None


def test_verify_notification_raw_rejects_unknown_serial(
    platform_key: rsa.RSAPrivateKey,
    platform_certificate: WeChatPlatformCertificate,
) -> None:
    body, headers = build_callback(
        signing_key=platform_key,
        serial="UNKNOWNSERIAL999",
        resource_plaintext=_success_resource_plaintext(),
    )
    result = _verify(_provider(platform_certificate), body=body, headers=headers)
    assert result.authenticated is False
    assert result.error_code == WECHAT_CALLBACK_CERT_UNAVAILABLE


@pytest.mark.parametrize(
    "missing",
    ["Wechatpay-Timestamp", "Wechatpay-Nonce", "Wechatpay-Signature", "Wechatpay-Serial"],
)
def test_verify_notification_raw_rejects_missing_header(
    platform_key: rsa.RSAPrivateKey,
    platform_serial: str,
    platform_certificate: WeChatPlatformCertificate,
    missing: str,
) -> None:
    body, headers = build_callback(
        signing_key=platform_key,
        serial=platform_serial,
        resource_plaintext=_success_resource_plaintext(),
    )
    headers.pop(missing)
    result = _verify(_provider(platform_certificate), body=body, headers=headers)
    assert result.authenticated is False
    assert result.error_code == WECHAT_CALLBACK_MISSING_HEADERS


def test_verify_notification_raw_acknowledges_non_success_trade_state(
    platform_key: rsa.RSAPrivateKey,
    platform_serial: str,
    platform_certificate: WeChatPlatformCertificate,
) -> None:
    body, headers = build_callback(
        signing_key=platform_key,
        serial=platform_serial,
        resource_plaintext=_success_resource_plaintext(trade_state="NOTPAY", transaction_id=None),
    )
    result = _verify(_provider(platform_certificate), body=body, headers=headers)
    assert result.authenticated is True
    assert result.error_code is None
    assert result.trade_state == "NOTPAY"
    assert result.provider_trade_no is None


def test_verify_notification_raw_rejects_malformed_body(
    platform_key: rsa.RSAPrivateKey,
    platform_serial: str,
    platform_certificate: WeChatPlatformCertificate,
) -> None:
    garbage = b"this-is-not-json"
    message = build_response_verify_message(
        timestamp="1700000000", nonce="hdrnonce1234567", body=garbage.decode("utf-8")
    )
    signature = platform_key.sign(message.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    headers = {
        "Wechatpay-Timestamp": "1700000000",
        "Wechatpay-Nonce": "hdrnonce1234567",
        "Wechatpay-Signature": base64.b64encode(signature).decode("ascii"),
        "Wechatpay-Serial": platform_serial,
    }
    result = _verify(_provider(platform_certificate), body=garbage, headers=headers)
    assert result.authenticated is False
    assert result.error_code == WECHAT_CALLBACK_BODY_INVALID


def test_verify_notification_raw_rejects_tampered_resource(
    platform_key: rsa.RSAPrivateKey,
    platform_serial: str,
    platform_certificate: WeChatPlatformCertificate,
) -> None:
    # Signed correctly, but the resource was encrypted under a different key so
    # the AES-256-GCM auth tag will not match the merchant api_v3_key.
    body, headers = build_callback(
        signing_key=platform_key,
        serial=platform_serial,
        resource_plaintext=_success_resource_plaintext(),
        encrypt_key="ffffffffffffffffffffffffffffffff",
    )
    result = _verify(_provider(platform_certificate), body=body, headers=headers)
    assert result.authenticated is False
    assert result.error_code == WECHAT_CALLBACK_DECRYPT_FAILED


def test_verify_notification_raw_rejects_incomplete_success_payload(
    platform_key: rsa.RSAPrivateKey,
    platform_serial: str,
    platform_certificate: WeChatPlatformCertificate,
) -> None:
    # trade_state SUCCESS but no transaction_id → cannot settle.
    body, headers = build_callback(
        signing_key=platform_key,
        serial=platform_serial,
        resource_plaintext=_success_resource_plaintext(transaction_id=None),
    )
    result = _verify(_provider(platform_certificate), body=body, headers=headers)
    assert result.authenticated is True
    assert result.error_code == WECHAT_CALLBACK_PAYLOAD_INVALID


# ---------------------------------------------------------------------------
# Route non-settlement paths (SQLite lane; confirm_recharge_payment never runs)
# ---------------------------------------------------------------------------


class _CallbackRouteProvider(WeChatNativeProvider):
    """Real verify_notification_raw, canned merchant config (no provider_settings)."""

    def __init__(self, certificate: WeChatPlatformCertificate) -> None:
        super().__init__(cert_manager=_StubCertManager(certificate))
        self._merchant = _merchant_config()

    def load_merchant_config(self, conn: BusinessConnection) -> MerchantConfig:
        return self._merchant


class _UnconfiguredProvider(WeChatNativeProvider):
    def load_merchant_config(self, conn: BusinessConnection) -> MerchantConfig:
        raise ValueError("WeChat Native merchant settings are incomplete")


@pytest.fixture()
def callback_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, list[tuple[str, object]]]]:
    db_path = tmp_path / "callback.db"
    monkeypatch.setenv("VIDEO_REPLICA_AUTH_MODE", "internal")
    monkeypatch.setenv("VIDEO_REPLICA_DB_PATH", str(db_path))
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://video.example")
    with initialize_database(db_path):
        pass
    confirm_calls: list[tuple[str, object]] = []

    def _record_confirm(*args: object, **kwargs: object) -> object:
        confirm_calls.append((str(kwargs.get("merchant_order_no")), kwargs.get("provider_spec")))
        raise AssertionError("confirm_recharge_payment must not run on this path")

    monkeypatch.setattr("app.payment_routes.confirm_recharge_payment", _record_confirm)
    try:
        with TestClient(app) as client:
            yield client, confirm_calls
    finally:
        app.dependency_overrides.clear()


def test_route_forged_callback_returns_fail(
    callback_env: tuple[TestClient, list[tuple[str, object]]],
    wrong_key: rsa.RSAPrivateKey,
    platform_serial: str,
    platform_certificate: WeChatPlatformCertificate,
) -> None:
    client, confirm_calls = callback_env
    app.dependency_overrides[get_wechat_provider] = lambda: _CallbackRouteProvider(
        platform_certificate
    )
    body, headers = build_callback(
        signing_key=wrong_key,
        serial=platform_serial,
        resource_plaintext=_success_resource_plaintext(),
    )
    response = client.post(NOTIFY_PATH, content=body, headers=headers)
    assert response.status_code == 400
    assert response.json()["code"] == "FAIL"
    assert confirm_calls == []


def test_route_non_success_callback_acks_without_settling(
    callback_env: tuple[TestClient, list[tuple[str, object]]],
    platform_key: rsa.RSAPrivateKey,
    platform_serial: str,
    platform_certificate: WeChatPlatformCertificate,
) -> None:
    client, confirm_calls = callback_env
    app.dependency_overrides[get_wechat_provider] = lambda: _CallbackRouteProvider(
        platform_certificate
    )
    body, headers = build_callback(
        signing_key=platform_key,
        serial=platform_serial,
        resource_plaintext=_success_resource_plaintext(trade_state="NOTPAY", transaction_id=None),
    )
    response = client.post(NOTIFY_PATH, content=body, headers=headers)
    assert response.status_code == 200
    assert response.json() == {"code": "SUCCESS", "message": "OK"}
    assert confirm_calls == []


def test_route_missing_config_returns_fail_503(
    callback_env: tuple[TestClient, list[tuple[str, object]]],
    platform_key: rsa.RSAPrivateKey,
    platform_serial: str,
    platform_certificate: WeChatPlatformCertificate,
) -> None:
    client, confirm_calls = callback_env
    app.dependency_overrides[get_wechat_provider] = lambda: _UnconfiguredProvider(
        cert_manager=_StubCertManager(platform_certificate)
    )
    body, headers = build_callback(
        signing_key=platform_key,
        serial=platform_serial,
        resource_plaintext=_success_resource_plaintext(),
    )
    response = client.post(NOTIFY_PATH, content=body, headers=headers)
    assert response.status_code == 503
    assert response.json()["code"] == "FAIL"
    assert confirm_calls == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
