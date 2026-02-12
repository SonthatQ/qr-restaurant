from __future__ import annotations

import base64
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

from app.settings import settings


@dataclass
class SCBToken:
    access_token: str
    expires_at: float


class SCBClient:
    """
    Configurable SCB client (sandbox & production).
    - Uses OAuth Client Credentials to fetch token (no hardcode).
    - Uses SCB headers commonly required in SCB Open API examples:
      Authorization: Bearer <token>
      ResourceOwnerId: <api_key>
      RequestUId: <uuid>
      Channel: scbeasy
    """

    def __init__(self) -> None:
        self._token: Optional[SCBToken] = None
        self._timeout = httpx.Timeout(20.0, connect=10.0)

    def _base_url(self) -> str:
        return settings.SCB_API_BASE.rstrip("/")

    async def _get_token(self) -> str:
        if settings.SCB_MOCK:
            return "mock-token"

        now = time.time()
        if self._token and self._token.expires_at - 30 > now:
            return self._token.access_token

        url = self._base_url() + settings.SCB_OAUTH_TOKEN_PATH
        auth = (settings.SCB_CLIENT_ID, settings.SCB_CLIENT_SECRET)

        data = {"grant_type": "client_credentials"}  # typical for server-to-server

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(url, data=data, auth=auth)
            r.raise_for_status()
            j = r.json()

        access_token = j.get("access_token", "")
        expires_in = float(j.get("expires_in", 3600))
        if not access_token:
            raise RuntimeError(f"SCB token missing. Response: {j}")

        self._token = SCBToken(access_token=access_token, expires_at=now + expires_in)
        return access_token

    def _headers(self, token: str, request_uid: Optional[str] = None) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "ResourceOwnerId": settings.SCB_API_KEY,
            "RequestUId": request_uid or str(uuid.uuid4()),
            "Channel": settings.SCB_CHANNEL,
        }

    async def post_json(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if settings.SCB_MOCK:
            # Return a payload compatible with our app usage
            # We'll store qr_raw (string) and qr_image_base64
            fake_qr_payload = f"MOCK_SCB_QR::{payload.get('billPayment', payload)}"
            qr_png_b64 = self._fake_qr_png_base64(fake_qr_payload)
            return {
                "status": "SUCCESS",
                "data": {
                    "transactionId": f"MOCKTXN-{uuid.uuid4().hex[:10]}",
                    "qrPayload": fake_qr_payload,
                    "qrImageBase64": qr_png_b64,
                },
            }

        token = await self._get_token()
        url = self._base_url() + path
        headers = self._headers(token)

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            return r.json()

    async def get_json(self, path: str) -> Dict[str, Any]:
        if settings.SCB_MOCK:
            return {"status": "SUCCESS", "data": {"paymentStatus": "PENDING"}}

        token = await self._get_token()
        url = self._base_url() + path
        headers = self._headers(token)

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            return r.json()

    def _fake_qr_png_base64(self, text: str) -> str:
        # Local fallback for mock mode only (not production)
        import qrcode
        from io import BytesIO

        img = qrcode.make(text)
        bio = BytesIO()
        img.save(bio, format="PNG")
        return base64.b64encode(bio.getvalue()).decode("utf-8")


scb_client = SCBClient()
