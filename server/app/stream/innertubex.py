"""
آداپتور پایتونی کلاینت رزولور InnerTubeX در Music Bazi.
ارتباط با پروسه محلی JVM Bridge از طریق پروتکل سبک HTTP/JSON.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any
import uuid

import httpx

from .errors import (
    BridgeTimeoutError,
    BridgeUnavailableError,
    InvalidResponseError,
    map_bridge_error,
)
from .models import ResolvedStream

log = logging.getLogger(__name__)


class InnerTubeXResolver:
    """
    کلاینت آسنکرون جهت ارتباط با سرویس لوکال InnerTubeX JVM Bridge.
    پایتون هیچ وابستگی بومی به کاتلین یا بایت‌کد جاوا ندارد.
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        host = os.getenv("MUSICBAZI_INNERTUBEX_HOST", "127.0.0.1")
        port = os.getenv("MUSICBAZI_INNERTUBEX_PORT", "8765")
        self.base_url = (base_url or f"http://{host}:{port}").rstrip("/")

        default_timeout = float(os.getenv("MUSICBAZI_INNERTUBEX_TIMEOUT", "3.5"))
        self.timeout = timeout_seconds if timeout_seconds is not None else default_timeout
        self._external_client = client

    def _client(self) -> httpx.AsyncClient:
        if self._external_client is not None:
            return self._external_client
        return httpx.AsyncClient(timeout=self.timeout)

    async def is_ready(self) -> bool:
        """بررسی سلامت و آماده‌به‌کار بودن سرویس لوکال بریج."""
        try:
            if self._external_client is not None:
                resp = await self._external_client.get(f"{self.base_url}/health")
            else:
                async with httpx.AsyncClient(timeout=1.5) as client:
                    resp = await client.get(f"{self.base_url}/health")

            if resp.status_code == 200:
                data = resp.json()
                return bool(data.get("ok") and data.get("ready"))
            return False
        except Exception:
            return False

    async def refresh_visitor_data(self) -> bool:
        """
        ارسال درخواست صریح تازه‌سازی Visitor Data به Bridge لوکال (Phase 1).
        در صورت موفقیت و دریافت توکن جدید True برمی‌گرداند.
        """
        url = f"{self.base_url}/visitor/refresh"
        try:
            if self._external_client is not None:
                resp = await self._external_client.post(url)
            else:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(url)
            if resp.status_code == 200:
                data = resp.json()
                return bool(data.get("ok") and data.get("refreshed"))
            return False
        except Exception as exc:
            log.warning("InnerTubeX Bridge visitor refresh request failed: %s", exc)
            return False

    async def notify_session_changed(self) -> bool:
        """اطلاع‌رسانی تغییر نشست/کوکی به Bridge برای پاک‌سازی exclusion و minted."""
        url = f"{self.base_url}/session/changed"
        try:
            if self._external_client is not None:
                resp = await self._external_client.post(url)
            else:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    resp = await client.post(url)
            return resp.status_code == 200
        except Exception as exc:
            log.warning("InnerTubeX Bridge notify session changed failed: %s", exc)
            return False

    async def report_refusal(
        self,
        video_id: str,
        status_code: int,
        client_name: str | None = None,
        profile_id: str | None = None,
        url: str | None = None,
    ) -> bool:
        """
        ارسال بازخورد رد شدن استریم حین پخش (۴۰۳/۴۰۴/۴۱۰) به Bridge (فاز ۲).
        کلاینت متناظر جهت جلوگیری از انتخاب مجدد موقتاً کنار گذاشته می‌شود.
        """
        clean_vid = video_id.strip()
        if not clean_vid:
            return False

        payload = {
            "video_id": clean_vid,
            "status_code": status_code,
            "client_name": client_name,
            "profile_id": profile_id,
            "url": url,
        }
        refuse_url = f"{self.base_url}/refuse"
        try:
            if self._external_client is not None:
                resp = await self._external_client.post(refuse_url, json=payload)
            else:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    resp = await client.post(refuse_url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                return bool(data.get("ok") and data.get("handled"))
            return False
        except Exception as exc:
            log.warning("InnerTubeX Bridge report refusal failed on %s: %s", clean_vid, exc)
            return False

    async def resolve_stream(
        self,
        video_id: str,
        purpose: str = "playback",
        quality: str | None = None,
        refresh_visitor: bool = False,
    ) -> ResolvedStream:
        """
        استخراج آدرس استریم صوتی و مشخصات فنی از طریق InnerTubeX.
        پارامتر purpose می‌تواند 'playback' یا 'download' باشد.
        فلگ refresh_visitor برای درخواست تازه‌سازی شناسه بازدیدکننده در Bridge است.
        """
        clean_vid = video_id.strip()
        if not clean_vid:
            raise ValueError("video_id cannot be empty")

        req_id = f"itx_{uuid.uuid4().hex[:8]}"
        payload = {
            "request_id": req_id,
            "video_id": clean_vid,
            "purpose": purpose,
            "quality": quality,
            "refresh_visitor": refresh_visitor,
        }

        start_time = time.time()
        url = f"{self.base_url}/resolve"

        try:
            if self._external_client is not None:
                resp = await self._external_client.post(url, json=payload)
            else:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(url, json=payload)
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            log.warning("InnerTubeX Bridge connection refused on %s (%s)", self.base_url, exc)
            raise BridgeUnavailableError(
                f"InnerTubeX Bridge at {self.base_url} is unreachable: {exc}",
                video_id=clean_vid,
            ) from exc
        except httpx.TimeoutException as exc:
            log.warning("InnerTubeX Bridge timed out after %.2fs on %s", self.timeout, clean_vid)
            raise BridgeTimeoutError(
                f"InnerTubeX Bridge timed out after {self.timeout}s: {exc}",
                video_id=clean_vid,
            ) from exc
        except Exception as exc:
            raise BridgeUnavailableError(f"HTTP request failed: {exc}", video_id=clean_vid) from exc

        elapsed_ms = int((time.time() - start_time) * 1000)

        try:
            data = resp.json()
        except Exception as exc:
            raise InvalidResponseError(
                f"Bridge returned malformed JSON (status {resp.status_code})",
                video_id=clean_vid,
            ) from exc

        if not data.get("ok"):
            err_data = data.get("error") or {}
            err_code = str(err_data.get("code") or "UNKNOWN")
            err_msg = str(err_data.get("message") or f"Bridge resolution failed (HTTP {resp.status_code})")
            retryable = bool(err_data.get("retryable", False))

            log.warning(
                "InnerTubeX extraction rejected [vid=%s, code=%s, elapsed=%dms]: %s",
                clean_vid,
                err_code,
                elapsed_ms,
                err_msg,
            )
            raise map_bridge_error(
                code=err_code,
                message=err_msg,
                retryable=retryable,
                video_id=clean_vid,
            )

        stream_raw = data.get("stream")
        if not stream_raw or not isinstance(stream_raw, dict):
            raise InvalidResponseError("Bridge response missing 'stream' object", video_id=clean_vid)

        try:
            stream = ResolvedStream.from_dict(stream_raw)
        except Exception as exc:
            raise InvalidResponseError(
                f"Failed to validate ResolvedStream from Bridge: {exc}",
                video_id=clean_vid,
            ) from exc

        # لاگ امن بدون فاش‌کردن Signed URL
        client_name = stream.resolver_metadata.get("client_name") or "unknown"
        log.info(
            "InnerTubeX resolved [vid=%s, client=%s, codec=%s, bitrate=%s, elapsed=%dms]",
            clean_vid,
            client_name,
            stream.codec,
            stream.bitrate,
            elapsed_ms,
        )

        return stream
