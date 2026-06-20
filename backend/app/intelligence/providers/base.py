"""Intelligence ingestion providers — the data-layer seam.

A *provider* produces normalised ``Observation`` records for one category, which
the ``IntelligenceService`` persists into ``intelligence_signals``. There are two
kinds:

  * computed  — derives observations from internal data (e.g. supplier risk from
                purchase-order history). Fully functional today.
  * feed      — normalises data from an external ``ExternalSource`` adapter
                (Freightos, Xeneta, a commodity-price API, a customs/tariff feed).
                The adapter is where vendor-specific API code lives; until one is
                configured the provider simply yields nothing, and analysts can
                enter observations manually instead.

Adding a real feed = implement ``ExternalSource`` for the vendor and inject it.
No other code changes.
"""
from __future__ import annotations

import abc
import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import ClassVar, Protocol

from app.core.logging import get_logger

logger = get_logger(__name__)

ZERO = Decimal("0")
ONE = Decimal("1")


@dataclass(frozen=True)
class Observation:
    """A normalised intelligence record, ready to persist."""

    category: str
    scope_type: str               # global | country | supplier | commodity | route | port
    scope_key: str | None
    severity: Decimal             # 0..1 risk contribution
    demand_factor: Decimal        # multiplicative demand effect (1 = none)
    confidence: Decimal           # 0..1
    headline: str
    source: str
    value: Decimal | None = None
    unit: str | None = None
    trend: str | None = None
    expires_at: dt.datetime | None = None
    detail: dict | None = None


@dataclass(frozen=True)
class RawMetric:
    """Raw input from an external source before category normalisation."""

    key: str                      # e.g. 'CN' (country), 'steel', 'Shanghai', 'CN-US'
    label: str
    value: Decimal | None = None
    pct_change: Decimal | None = None   # fractional change, e.g. 0.30 = +30%
    level: Decimal | None = None        # pre-scored 0..1 severity, if the source gives one
    trend: str | None = None
    detail: dict | None = None


class ExternalSource(Protocol):
    """Vendor adapter. Implementations: FreightosSource, XenetaSource, ...
    (not built yet — they require API credentials)."""

    async def fetch(self, category: str, keys: list[str]) -> list[RawMetric]:
        ...


class NullSource:
    """Default source: no external feed configured, so nothing is ingested."""

    async def fetch(self, category: str, keys: list[str]) -> list[RawMetric]:
        return []


class IntelligenceProvider(abc.ABC):
    category: ClassVar[str]
    key: ClassVar[str]

    @abc.abstractmethod
    async def collect(self) -> list[Observation]:
        """Produce observations to persist."""


# --------------------------------------------------------------------------- #
# HTTP provider base (public/free production feeds)
# --------------------------------------------------------------------------- #
class HttpIntelligenceProvider(IntelligenceProvider):
    """Base for providers that fetch a public/free API over HTTP and normalise the
    payload into ``Observation`` records.

    Inert (no network) unless ``enabled``. Both the network call and the parse are
    wrapped: any error is logged with the *type* only (never the message/URL, which
    could echo a key) and yields ``[]`` — so a feed problem can never break ingest
    or a reorder run. Subclasses implement the async ``_fetch`` (vendor request) and
    a pure ``parse(payload)`` (unit-tested without a network)."""

    def __init__(
        self,
        *,
        enabled: bool,
        base_url: str,
        api_key: str | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.enabled = enabled
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def __repr__(self) -> str:  # never leak the key
        return f"{type(self).__name__}(enabled={self.enabled}, key={'set' if self.api_key else 'none'})"

    async def collect(self) -> list[Observation]:
        if not self.enabled:
            return []
        try:
            payload = await self._fetch()
        except Exception as exc:  # noqa: BLE001 — a feed error must never break ingest
            logger.warning("intel_fetch_failed", provider=self.key, error_type=type(exc).__name__)
            return []
        try:
            return self.parse(payload)
        except Exception as exc:  # noqa: BLE001 — unexpected response shape -> nothing
            logger.warning("intel_parse_failed", provider=self.key, error_type=type(exc).__name__)
            return []

    async def _get_json(self, path: str, *, params=None, headers=None):
        """GET JSON from ``path`` (absolute, or relative to ``base_url``)."""
        import httpx  # lazy: keeps the module importable without the dependency

        url = path if path.startswith("http") else f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def _fetch(self):
        raise NotImplementedError

    def parse(self, payload) -> list[Observation]:
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Feed providers (external-source backed)
# --------------------------------------------------------------------------- #
def _clamp01(v: Decimal) -> Decimal:
    return max(ZERO, min(ONE, v))


class FeedIntelligenceProvider(IntelligenceProvider):
    """Base for externally-fed categories. Subclasses set ``category``, the
    ``scope_type``/``tracked_keys`` they monitor, and the severity normalisation.
    """

    scope_type: ClassVar[str] = "global"
    tracked_keys: ClassVar[list[str]] = []
    # Fractional change treated as maximum severity (e.g. 0.5 => +50% = risk 1.0).
    severity_cap: ClassVar[Decimal] = Decimal("0.5")

    def __init__(self, source: ExternalSource | None = None) -> None:
        self.source = source or NullSource()

    async def collect(self) -> list[Observation]:
        raws = await self.source.fetch(self.category, list(self.tracked_keys))
        return [self._normalise(r) for r in raws]

    def _severity(self, raw: RawMetric) -> Decimal:
        if raw.level is not None:
            return _clamp01(raw.level)
        if raw.pct_change is not None and self.severity_cap > 0:
            return _clamp01(abs(raw.pct_change) / self.severity_cap)
        return ZERO

    def _headline(self, raw: RawMetric, severity: Decimal) -> str:
        if raw.pct_change is not None:
            pct = (raw.pct_change * Decimal("100")).quantize(Decimal("0.1"))
            return f"{self.category.title()} — {raw.label}: {pct}% ({raw.trend or 'change'})"
        return f"{self.category.title()} — {raw.label}"

    def _normalise(self, raw: RawMetric) -> Observation:
        severity = self._severity(raw)
        return Observation(
            category=self.category,
            scope_type=self.scope_type,
            scope_key=raw.key,
            severity=severity,
            demand_factor=ONE,  # cost/risk signals don't shift demand magnitude
            confidence=Decimal("0.7"),
            headline=self._headline(raw, severity),
            source=self.key,
            value=raw.value,
            trend=raw.trend,
            detail=raw.detail,
        )
