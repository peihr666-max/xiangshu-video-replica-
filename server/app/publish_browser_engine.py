"""QR selectors adapted from social-auto-upload; see publishers/vendor/social_auto_upload.

Use stock Playwright and platform-provided QR images. Never bypass verification.
Each login has a fresh, non-persistent browser context; only encrypted state survives.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlparse

from playwright.async_api import (
    BrowserContext,
    Locator,
    Page,
    Response,
    StorageState,
    async_playwright,
)

from app.publish_browser import Platform

ORIGINS = {
    "douyin": "https://creator.douyin.com",
    "wechat_channels": "https://channels.weixin.qq.com",
    "xiaohongshu": "https://creator.xiaohongshu.com",
}
ENDPOINTS = {
    "douyin": "/web/api/media/user/info/",
    "wechat_channels": "/auth/auth_data",
    "xiaohongshu": "/api/galaxy/user/info",
}
DOUYIN_IDENTITY_URL = "https://creator.douyin.com/web/api/media/user/info/?aid=1128"
DOUYIN_PROBE_INTERVAL_SECONDS = 3.0

logger = logging.getLogger(__name__)


@dataclass
class BrowserEvent:
    phase: str
    image: str | None = None
    identity: dict[str, str] | None = None
    storage: dict[str, Any] | None = None


def parse_identity(platform: Platform, body: Any) -> dict[str, str] | None:
    if not isinstance(body, dict):
        return None
    try:
        status_code = body.get("status_code")
        if platform == "douyin" and (
            (type(status_code) is int and status_code == 0)
            or (type(status_code) is str and status_code == "0")
        ):
            user = body.get("user", {})
            uid, name = user.get("uid") or user.get("user_id"), user.get("nickname")
        elif platform == "wechat_channels" and body.get("errCode", body.get("errcode")) == 0:
            data = body.get("data", {})
            user = (
                data.get("finderUser")
                or data.get("userAttr")
                or (data.get("finderList") or [{}])[0]
            )
            uid, name = user.get("finderUsername"), user.get("nickname", user.get("nickName"))
        elif platform == "xiaohongshu" and (
            body.get("success") is True or ("success" not in body and body.get("code") == 0)
        ):
            user = body.get("data", {})
            uid, name = user.get("userId"), user.get("userName")
        else:
            return None
        if isinstance(uid, bool) or not isinstance(uid, str | int) or not isinstance(name, str):
            return None
        if not str(uid).strip() or not name.strip() or len(str(uid)) > 256 or len(name) > 256:
            return None
        return {"platform_user_id": str(uid).strip(), "username": name.strip()}
    except (AttributeError, TypeError, IndexError):
        return None


def _is_douyin_creator_page(url: str) -> bool:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}" == ORIGINS["douyin"] and (
        parsed.path == "/creator-micro" or parsed.path.startswith("/creator-micro/")
    )


async def _probe_douyin_identity(context: BrowserContext) -> dict[str, str] | None:
    response = None
    try:
        response = await context.request.get(
            DOUYIN_IDENTITY_URL,
            timeout=5000,
            max_redirects=0,
        )
        if not response.ok:
            logger.warning(
                "douyin identity probe rejected at creator backend: http_status=%s",
                response.status,
            )
            return None
        return parse_identity("douyin", await response.json())
    except Exception as exc:
        logger.warning("douyin identity probe failed at creator backend: %s", type(exc).__name__)
        return None
    finally:
        if response is not None:
            try:
                await response.dispose()
            except Exception as exc:
                logger.warning(
                    "douyin identity probe cleanup failed at creator backend: %s",
                    type(exc).__name__,
                )


async def qr_locator(page: Page, platform: Platform) -> Locator | None:
    # Selectors and XHS scan-panel switch ported from pinned MIT upstream.
    candidates: list[Locator] = []
    if platform == "douyin":
        candidates = [
            page.locator(selector).first
            for selector in (
                'div#animate_qrcode_container img[src^="data:image"]',
                'div[class*="animate_qrcode_container"] img[src^="data:image"]',
                'div[class*="scan_qrcode_login_content"] img[src^="data:image"]',
                'img[aria-label="二维码"]',
            )
        ]
    elif platform == "xiaohongshu":
        box = page.locator("div[class*='login-box']").first
        if await box.count() and not await box.get_by_text("扫一扫", exact=False).count():
            toggle = box.locator("img.css-wemwzq").first
            if await toggle.is_visible():
                await toggle.click(timeout=1500)
        candidates = [
            page.locator(".login-box-container")
            .get_by_text("APP扫一扫登录")
            .first.locator("xpath=..//following-sibling::div//img")
            .first,
            box.locator('img[src^="data:image"]').first,
        ]
    else:
        # Both legacy and July-2026 qrconnect frames; screenshot resolves relative URLs.
        for frame in page.frames:
            url = urlparse(frame.url)
            if (
                url.scheme == "https"
                and url.netloc == "open.weixin.qq.com"
                and url.path == "/connect/qrconnect"
            ) or (
                url.scheme == "https"
                and url.netloc == "channels.weixin.qq.com"
                and "login-for-iframe" in url.path
            ):
                candidates.extend(await frame.locator("img.qrcode, img.js_qrcode_img").all())
        candidates.extend(
            page.locator(selector).first
            for selector in (
                "div.login-qrcode-wrap img.qrcode",
                "div.qrcode-wrap img.qrcode",
                "img.qrcode",
                "img.js_qrcode_img",
            )
        )
    for candidate in candidates:
        if await candidate.is_visible():
            bounds = await candidate.bounding_box()
            if bounds and bounds["width"] >= 100 and bounds["height"] >= 100:
                return candidate
    return None


async def login_events(
    platform: Platform,
    storage: dict[str, Any] | None = None,
) -> AsyncGenerator[BrowserEvent, None]:
    identity: dict[str, str] | None = None
    last_douyin_probe_at: float | None = None
    tasks: set[asyncio.Task[None]] = set()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                storage_state=cast(StorageState | None, storage),
                viewport={"width": 1080, "height": 780},
            )
            page = await context.new_page()

            async def capture(response: Response) -> None:
                nonlocal identity
                parsed = urlparse(response.url)
                if f"{parsed.scheme}://{parsed.netloc}" != ORIGINS[
                    platform
                ] or not parsed.path.endswith(ENDPOINTS[platform]):
                    return
                try:
                    parsed_identity = parse_identity(platform, await response.json())
                    if platform != "douyin" or parsed_identity is not None:
                        identity = parsed_identity
                except Exception:
                    pass

            def on_response(response: Response) -> None:
                task = asyncio.create_task(capture(response))
                tasks.add(task)
                task.add_done_callback(tasks.discard)

            page.on("response", on_response)
            # The login shell may keep loading optional scripts while its QR is ready.
            # Start observing after the response commits; each locator tolerates loading DOM.
            await page.goto(ORIGINS[platform], wait_until="commit", timeout=45000)
            deadline = time.monotonic() + 280
            while time.monotonic() < deadline:
                on_douyin_creator_page = platform == "douyin" and _is_douyin_creator_page(page.url)
                now = time.monotonic()
                if (
                    on_douyin_creator_page
                    and identity is None
                    and (
                        last_douyin_probe_at is None
                        or now - last_douyin_probe_at >= DOUYIN_PROBE_INTERVAL_SECONDS
                    )
                ):
                    last_douyin_probe_at = now
                    probed_identity = await _probe_douyin_identity(context)
                    if probed_identity is not None:
                        identity = probed_identity
                current = urlparse(page.url)
                on_douyin_creator_page = platform == "douyin" and _is_douyin_creator_page(page.url)
                if (
                    identity is not None
                    and f"{current.scheme}://{current.netloc}" == ORIGINS[platform]
                ):
                    state = dict(await context.storage_state(indexed_db=True))
                    yield BrowserEvent("connected", identity=identity, storage=state)
                    return
                if on_douyin_creator_page:
                    yield BrowserEvent("confirming")
                    await asyncio.sleep(1.5)
                    continue
                try:
                    for frame in page.frames:
                        parsed = urlparse(frame.url)
                        if parsed.netloc not in {
                            urlparse(ORIGINS[platform]).netloc,
                            "open.weixin.qq.com",
                        }:
                            continue
                        expired = (
                            frame.get_by_text("二维码已过期", exact=False)
                            .or_(frame.get_by_text("二维码已失效", exact=False))
                            .first
                        )
                        if await expired.is_visible():
                            yield BrowserEvent("expired")
                            return
                    qr = await qr_locator(page, platform)
                    if qr is not None:
                        png = await qr.screenshot(type="png", timeout=3000)
                        image = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
                        yield (
                            BrowserEvent("qr_ready", image=image)
                            if len(image) <= 600000
                            else BrowserEvent("action_required")
                        )
                    else:
                        yield BrowserEvent("loading")
                except Exception:
                    yield BrowserEvent("action_required")
                await asyncio.sleep(1.5)
            if platform == "douyin":
                logger.warning(
                    "douyin login expired: creator_backend=%s identity_captured=%s",
                    _is_douyin_creator_page(page.url),
                    identity is not None,
                )
            yield BrowserEvent("expired")
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await browser.close()
