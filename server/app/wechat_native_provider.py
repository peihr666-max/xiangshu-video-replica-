"""WeChat Pay V3 Native payment provider implementation.

Adapts the WeChatNativeClient (V3 Native HTTP client) to the generic
PaymentProvider Protocol so routes can select WeChat Native through the provider
registry without WeChat-specific branching.

CW-069: request signing, platform-certificate management, and response signature
verification live in wechat_native_client; this module only maps the generic data
types, translates errors, and registers the provider. WeChat Native is QR/code
based, so create_payment_code is the supported flow while create_payment_form
(gateway redirect) is intentionally unsupported.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.db_portable import BusinessConnection
from app.payment_provider import (
    DeploymentConfig,
    MerchantConfig,
    NotificationVerification,
    OrderQueryError,
    OrderQueryResult,
    PaymentCodeError,
    PaymentCodeResult,
    PaymentFormResult,
    PaymentProvider,
    PaymentProviderError,
    register_provider,
)
from app.settings import SettingsRepository
from app.wechat_native_client import (
    WeChatDeploymentConfig,
    WeChatNativeClient,
    WeChatNativeError,
    deployment_config_from_environment,
    merchant_config_from_settings,
)

WECHAT_NATIVE_PROVIDER_NAME = "wechat_native"
WECHAT_NATIVE_CHANNEL = "wxpay"
WECHAT_NATIVE_CALLBACK_UNSUPPORTED = "WECHAT_NATIVE_CALLBACK_UNSUPPORTED"


class WeChatNativeProvider(PaymentProvider):
    """WeChat Pay V3 Native provider conforming to the PaymentProvider Protocol.

    Delegates order placement and querying to WeChatNativeClient. The client may be
    injected for testing; when omitted (as when constructed by the registry) a
    default client using the real urllib opener is created lazily per call.
    """

    def __init__(self, *, client: WeChatNativeClient | None = None) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return WECHAT_NATIVE_PROVIDER_NAME

    def load_merchant_config(self, conn: BusinessConnection) -> MerchantConfig:
        """Load and validate WeChat Native merchant config from provider_settings."""
        raw = SettingsRepository(conn).load_provider_config(WECHAT_NATIVE_PROVIDER_NAME)
        # Validate eagerly so incomplete settings raise ValueError per the Protocol.
        merchant_config_from_settings(raw)
        return MerchantConfig(
            provider=WECHAT_NATIVE_PROVIDER_NAME,
            raw=raw,
            allowed_channels=(WECHAT_NATIVE_CHANNEL,),
        )

    def load_deployment_config(self) -> DeploymentConfig:
        """Derive deployment config from PUBLIC_BASE_URL (WeChat Native needs only notify_url)."""
        deployment = deployment_config_from_environment()
        return DeploymentConfig(
            notify_url=deployment.notify_url,
            return_url="",
            gateway_url="",
        )

    def create_payment_form(
        self,
        *,
        merchant_order_no: str,
        amount_fen: int,
        credits: int,
        merchant: MerchantConfig,
        deployment: DeploymentConfig,
    ) -> PaymentFormResult:
        """WeChat Native is code/QR based; the form-redirect flow is unsupported."""
        raise PaymentProviderError(
            "WeChat Native does not support form-based payment; use create_payment_code"
        )

    def create_payment_code(
        self,
        *,
        merchant: MerchantConfig,
        deployment: DeploymentConfig,
        merchant_order_no: str,
        amount_fen: int,
        credits: int,
        client_ip: str,
    ) -> PaymentCodeResult:
        """Place a Native order and surface the weixin:// code_url for QR rendering."""
        wechat_merchant = merchant_config_from_settings(merchant.raw)
        wechat_deployment = WeChatDeploymentConfig(notify_url=deployment.notify_url)
        client = self._client or WeChatNativeClient()
        try:
            result = client.create_native_order(
                merchant=wechat_merchant,
                deployment=wechat_deployment,
                out_trade_no=merchant_order_no,
                description=f"内部视频生成条数充值 {credits} 条",
                amount_fen=amount_fen,
                client_ip=client_ip,
            )
        except WeChatNativeError as exc:
            raise PaymentCodeError(str(exc), status_code=exc.status_code) from exc
        # WeChat returns only code_url (the QR content); there is no hosted image and
        # no order number at creation time, so both QR fields carry the code_url.
        return PaymentCodeResult(
            qr_image_url=result.code_url,
            payment_url=result.code_url,
            provider_order_no=None,
        )

    def query_order(
        self,
        *,
        merchant: MerchantConfig,
        deployment: DeploymentConfig,
        merchant_order_no: str,
    ) -> OrderQueryResult:
        """Query an order by out-trade-no and normalize it into the generic result."""
        wechat_merchant = merchant_config_from_settings(merchant.raw)
        client = self._client or WeChatNativeClient()
        try:
            result = client.query_order(merchant=wechat_merchant, out_trade_no=merchant_order_no)
        except WeChatNativeError as exc:
            raise OrderQueryError(str(exc), status_code=exc.status_code) from exc
        return OrderQueryResult(
            paid=result.paid,
            merchant_order_no=result.out_trade_no,
            provider_trade_no=result.transaction_id,
            amount_fen=result.amount_fen,
            channel=WECHAT_NATIVE_CHANNEL,
            response_digest=result.response_digest,
        )

    def verify_notification(
        self,
        params: Mapping[str, str],
        merchant: MerchantConfig,
    ) -> NotificationVerification:
        """Fail closed: WeChat callbacks need raw-body + header signature verification.

        A WeChat Native notification is a JSON body whose authenticity depends on the
        Wechatpay-Timestamp/Nonce/Signature/Serial headers verified over the exact raw
        bytes, plus AES-256-GCM decryption of the resource with the api_v3_key. That
        cannot be reconstructed from a flattened Mapping[str, str], so this params-based
        entry point never marks a notification valid. Raw-body callback verification is
        a route-level follow-up task.
        """
        return NotificationVerification(
            valid=False,
            merchant_order_no=None,
            provider_trade_no=None,
            amount_fen=None,
            channel=None,
            source_digest=None,
            error_code=WECHAT_NATIVE_CALLBACK_UNSUPPORTED,
        )


# Register WeChatNativeProvider at import time.
register_provider(WECHAT_NATIVE_PROVIDER_NAME, WeChatNativeProvider)
