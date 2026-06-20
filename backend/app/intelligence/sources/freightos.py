"""Freightos external source — a real, credential-gated ``ExternalSource``.

A Freightos developer app issues an **API key and a secret**; both are required.
Credentials come from the environment (``FREIGHTOS_API_KEY`` /
``FREIGHTOS_API_SECRET``) — never hard-coded, never logged, never returned by any
API. The source is inert unless ``settings.freightos_configured`` (enabled + key
+ secret); when inert it returns no data and makes no network call.

Authentication flow (``FREIGHTOS_AUTH_MODE``):

  basic   (default)  Authorization: Basic base64("<key>:<secret>")
                     One request, no token round-trip — use when Freightos
                     accepts HTTP Basic with the key as username and secret as
                     password.

  oauth2             OAuth 2.0 client-credentials grant. POST to
                     ``FREIGHTOS_TOKEN_URL`` with
                     {grant_type: client_credentials, client_id: <key>,
                      client_secret: <secret>} -> {access_token, expires_in};
                     the token is cached in-memory until just before expiry and
                     sent as ``Authorization: Bearer <token>`` on data calls.

  headers            x-api-key: <key> + x-api-secret: <secret> request headers.

Confirm the exact mode, token URL, and index path against your Freightos plan
(Terminal / FBX). The parser is defensive — unrecognised response shapes yield
``[]`` rather than fabricated data — and any error logs a redacted warning and
returns ``[]`` so a feed problem can never break a reorder run.
"""
from __future__ import annotations

import base64
import datetime as dt
from decimal import Decimal, InvalidOperation

from app.core.logging import get_logger
from app.intelligence.providers.base import RawMetric

logger = get_logger(__name__)

_TOKEN_SAFETY_WINDOW_S = 30  # refresh slightly before the token actually expires


def credential_problems(*, enabled: bool, api_key: str | None, api_secret: str | None) -> list[str]:
    """Names of the env vars that must be set when Freightos is enabled (pure;
    returns field NAMES only — never the values). Used by startup validation."""
    if not enabled:
        return []
    missing: list[str] = []
    if not api_key:
        missing.append("FREIGHTOS_API_KEY")
    if not api_secret:
        missing.append("FREIGHTOS_API_SECRET")
    return missing


def _to_decimal(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _origin_country(item: dict, lane: str | None) -> str | None:
    explicit = item.get("origin_country") or item.get("origin")
    if isinstance(explicit, str) and len(explicit) >= 2:
        return explicit[:2].upper()
    if isinstance(lane, str) and len(lane) >= 2:
        return lane[:2].upper()  # UN/LOCODE prefix is the ISO-2 country
    return None


class FreightosSource:
    """Implements the ``ExternalSource`` protocol for category 'freight'."""

    def __init__(
        self,
        *,
        api_key: str | None,
        api_secret: str | None,
        base_url: str = "https://api.freightos.com",
        index_path: str = "/api/v2/indices",
        auth_mode: str = "basic",
        token_url: str = "https://api.freightos.com/oauth/token",
        timeout_seconds: float = 20.0,
        lanes: list[str] | None = None,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url
        self.index_path = index_path
        self.auth_mode = auth_mode
        self.token_url = token_url
        self.timeout_seconds = timeout_seconds
        self.lanes = list(lanes or [])
        self._token: str | None = None
        self._token_expiry: dt.datetime | None = None

    @classmethod
    def from_settings(cls, settings) -> FreightosSource:
        return cls(
            api_key=settings.freightos_api_key,
            api_secret=settings.freightos_api_secret,
            base_url=settings.freightos_base_url,
            index_path=settings.freightos_index_path,
            auth_mode=settings.freightos_auth_mode,
            token_url=settings.freightos_token_url,
            timeout_seconds=settings.freightos_timeout_seconds,
            lanes=list(settings.freightos_lanes or []),
        )

    # Redacted repr so the key/secret never leak via logs, tracebacks, or repr().
    def __repr__(self) -> str:
        return (
            f"FreightosSource(auth_mode={self.auth_mode!r}, "
            f"configured={bool(self.api_key and self.api_secret)})"
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    # ------------------------------ auth ------------------------------- #
    @staticmethod
    def _basic_header(api_key: str, api_secret: str) -> dict[str, str]:
        token = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode("ascii")
        return {"Authorization": f"Basic {token}"}

    @staticmethod
    def _header_pair(api_key: str, api_secret: str) -> dict[str, str]:
        return {"x-api-key": api_key, "x-api-secret": api_secret}

    async def _access_token(self, client) -> str:
        """OAuth2 client-credentials token, cached until just before expiry."""
        now = dt.datetime.now(dt.UTC)
        if self._token and self._token_expiry and now < self._token_expiry:
            return self._token
        resp = await client.post(
            self.token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self.api_key,
                "client_secret": self.api_secret,
            },
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        payload = resp.json()
        self._token = payload["access_token"]
        ttl = int(payload.get("expires_in", 3600)) - _TOKEN_SAFETY_WINDOW_S
        self._token_expiry = now + dt.timedelta(seconds=max(ttl, 0))
        return self._token

    async def _auth_headers(self, client) -> dict[str, str]:
        if self.auth_mode == "headers":
            return self._header_pair(self.api_key, self.api_secret)
        if self.auth_mode == "oauth2":
            return {"Authorization": f"Bearer {await self._access_token(client)}"}
        return self._basic_header(self.api_key, self.api_secret)  # default: basic

    # ------------------------------ fetch ------------------------------ #
    async def fetch(self, category: str, keys: list[str]) -> list[RawMetric]:
        # Only serves freight; inert unless BOTH credentials are present.
        if category != "freight" or not self.configured:
            return []

        import httpx  # lazy: keeps the module importable without the dependency

        lanes = list(keys) or self.lanes
        url = self.base_url.rstrip("/") + self.index_path
        params = {"lanes": ",".join(lanes)} if lanes else {}
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                headers = {"Accept": "application/json", **(await self._auth_headers(client))}
                resp = await client.get(url, headers=headers, params=params)
                resp.raise_for_status()
                payload = resp.json()
        except Exception as exc:  # noqa: BLE001 - never break a reorder run on a feed error
            # Log the error TYPE only — never the message/headers, which could
            # echo credentials or signed URLs.
            logger.warning("freightos_fetch_failed", error_type=type(exc).__name__)
            return []
        return self._parse(payload)

    def _parse(self, payload) -> list[RawMetric]:
        """Map a Freightos rate-index response to RawMetric (origin-country keyed)."""
        if isinstance(payload, dict):
            items = payload.get("indices") or payload.get("data") or payload.get("results") or []
        elif isinstance(payload, list):
            items = payload
        else:
            items = []
        if not isinstance(items, list):
            return []

        out: list[RawMetric] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            lane = item.get("lane") or item.get("route") or item.get("id")
            origin = _origin_country(item, lane if isinstance(lane, str) else None)
            if not origin:
                continue
            pct = item.get("change_pct", item.get("pct_change", item.get("change")))
            value = item.get("value", item.get("index", item.get("rate")))
            out.append(
                RawMetric(
                    key=origin,
                    label=str(lane or origin),
                    value=_to_decimal(value),
                    pct_change=_to_decimal(pct),
                    trend=item.get("trend"),
                    detail={"lane": lane} if lane else None,
                )
            )
        return out
