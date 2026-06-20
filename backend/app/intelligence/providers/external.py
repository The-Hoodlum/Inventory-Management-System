"""Free/public external intelligence providers (production feeds).

Each maps a public API onto ``Observation`` records in the *existing* signal
categories, scoped so the existing matching (supplier country / product
commodity+origin) and scoring consume them with **no core change**. All are inert
until enabled in settings; network/parse errors yield ``[]`` (see
``HttpIntelligenceProvider``) so a feed can never break ingest.

Integrated here (free): ExchangeRate.host, World Bank. (IMF, UN Comtrade, GDELT,
OpenWeather follow the same pattern.) Paid providers (Freightos/Xeneta/Trading
Economics) implement the same ``IntelligenceProvider`` contract and register in
``providers.registry`` later — the engine never changes.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation

from app.intelligence.providers.base import (
    ONE,
    ZERO,
    HttpIntelligenceProvider,
    Observation,
    _clamp01,
)

# Currency -> representative ISO-2 country, so FX risk matches suppliers by country.
_CCY_COUNTRY = {
    "CNY": "CN", "JPY": "JP", "INR": "IN", "KRW": "KR", "TWD": "TW", "VND": "VN",
    "THB": "TH", "IDR": "ID", "MYR": "MY", "EUR": "DE", "GBP": "GB", "TRY": "TR",
    "MXN": "MX", "BRL": "BR", "ZAR": "ZA", "PLN": "PL",
}

# M49 numeric -> ISO-2 for the major economies (UN Comtrade uses M49 codes).
_M49_ISO2 = {
    "156": "CN", "842": "US", "392": "JP", "276": "DE", "699": "IN", "410": "KR",
    "704": "VN", "764": "TH", "360": "ID", "458": "MY", "826": "GB", "792": "TR",
    "484": "MX", "76": "BR",
}

# ISO-3 -> ISO-2 for the major sourcing economies (IMF/World Bank use ISO-3 codes).
_ISO3_ISO2 = {
    "CHN": "CN", "USA": "US", "JPN": "JP", "DEU": "DE", "IND": "IN", "KOR": "KR",
    "TWN": "TW", "VNM": "VN", "THA": "TH", "IDN": "ID", "MYS": "MY", "GBR": "GB",
    "TUR": "TR", "MEX": "MX", "BRA": "BR", "ZAF": "ZA", "POL": "PL", "ITA": "IT",
    "FRA": "FR", "ESP": "ES", "NLD": "NL",
}


def _dec(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _fx_fraction(info: dict) -> Decimal | None:
    """Fractional change for one currency (e.g. 0.03 = +3%) from a fluctuation row,
    preferring an explicit percent and falling back to start/end rates."""
    cp = _dec(info.get("change_pct"))
    if cp is not None:
        return cp / Decimal("100")
    start, end = _dec(info.get("start_rate")), _dec(info.get("end_rate"))
    if start and end and start != 0:
        return (end - start) / start
    return None


class ExchangeRateHostProvider(HttpIntelligenceProvider):
    """FX volatility (ExchangeRate.host) → currency/cost risk per supplier country.
    A large 30-day move in a sourcing currency raises landed-cost risk for suppliers
    invoicing in it. Scoped by country (mapped from the currency)."""

    category = "trade"
    key = "exchangerate_host"
    # A 10% swing over the window ≈ maximum severity.
    severity_cap = Decimal("0.10")
    symbols = list(_CCY_COUNTRY.keys())

    async def _fetch(self):
        end = dt.date.today()
        start = end - dt.timedelta(days=30)
        params = {
            "base": "USD",
            "symbols": ",".join(self.symbols),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        }
        if self.api_key:
            params["access_key"] = self.api_key
        return await self._get_json("/fluctuation", params=params)

    def parse(self, payload) -> list[Observation]:
        rates = (payload or {}).get("rates") if isinstance(payload, dict) else None
        if not isinstance(rates, dict):
            return []
        out: list[Observation] = []
        for sym, info in rates.items():
            country = _CCY_COUNTRY.get(sym)
            if not country or not isinstance(info, dict):
                continue
            frac = _fx_fraction(info)
            if frac is None:
                continue
            severity = _clamp01(abs(frac) / self.severity_cap) if self.severity_cap > 0 else ZERO
            pct = (frac * Decimal("100")).quantize(Decimal("0.1"))
            out.append(
                Observation(
                    category=self.category,
                    scope_type="country",
                    scope_key=country,
                    severity=severity,
                    demand_factor=ONE,
                    confidence=Decimal("0.6"),
                    headline=f"FX USD/{sym} {pct}% over 30d",
                    source=self.key,
                    value=_dec(info.get("end_rate")),
                    unit=sym,
                    trend="up" if frac > 0 else ("down" if frac < 0 else None),
                    detail={"symbol": sym, "fraction": str(frac)},
                )
            )
        return out


class WorldBankProvider(HttpIntelligenceProvider):
    """Country economic-stress risk (World Bank WDI: GDP growth, annual %, indicator
    NY.GDP.MKTP.KD.ZG). Slow or contracting growth raises a country's supply/demand
    risk; healthy economies are skipped (severity floor). Scoped by country."""

    category = "geopolitical"
    key = "worldbank"
    indicator = "NY.GDP.MKTP.KD.ZG"

    async def _fetch(self):
        # Most-recent non-empty value per country, all countries.
        return await self._get_json(
            f"/country/all/indicator/{self.indicator}",
            params={"format": "json", "mrnev": "1", "per_page": "400"},
        )

    def parse(self, payload) -> list[Observation]:
        # World Bank returns [ <metadata>, [ <rows> ] ].
        if not (isinstance(payload, list) and len(payload) >= 2 and isinstance(payload[1], list)):
            return []
        out: list[Observation] = []
        for row in payload[1]:
            if not isinstance(row, dict):
                continue
            val = _dec(row.get("value"))
            country = (row.get("country") or {}).get("id") if isinstance(row.get("country"), dict) else None
            if val is None or not country:
                continue
            # GDP growth -> risk: +3% ⇒ 0, contraction ⇒ high; (3 - growth) / 15, clamped.
            risk = _clamp01((Decimal("3") - val) / Decimal("15"))
            if risk < Decimal("0.1"):  # healthy economy — not a risk signal
                continue
            iso = str(country)[:2].upper()
            out.append(
                Observation(
                    category=self.category,
                    scope_type="country",
                    scope_key=iso,
                    severity=risk,
                    demand_factor=ONE,
                    confidence=Decimal("0.7"),
                    headline=f"GDP growth ({row.get('countryiso3code') or iso}): {val}%",
                    source=self.key,
                    value=val,
                    unit="%",
                    trend=None,
                    detail={"indicator": self.indicator, "date": row.get("date")},
                )
            )
        return out


class ImfProvider(HttpIntelligenceProvider):
    """Macro risk (IMF DataMapper: inflation, average consumer prices, % change,
    indicator PCPIPCH). High inflation in a sourcing country raises cost/supply risk.
    Scoped by country (ISO-3 → ISO-2)."""

    category = "trade"
    key = "imf"
    indicator = "PCPIPCH"
    severity_cap = Decimal("25")  # ~25% annual inflation ≈ maximum severity

    async def _fetch(self):
        return await self._get_json(f"/{self.indicator}")

    def parse(self, payload) -> list[Observation]:
        values = None
        if isinstance(payload, dict) and isinstance(payload.get("values"), dict):
            values = payload["values"].get(self.indicator)
        if not isinstance(values, dict):
            return []
        out: list[Observation] = []
        current_year = dt.date.today().year
        for iso3, series in values.items():
            iso2 = _ISO3_ISO2.get(str(iso3).upper())
            if not iso2 or not isinstance(series, dict) or not series:
                continue
            # Prefer the latest actual/estimate year, not IMF's out-year projections.
            actual = [y for y in series if str(y).isdigit() and int(y) <= current_year]
            year = max(actual) if actual else max(series.keys())
            val = _dec(series.get(year))
            if val is None:
                continue
            severity = _clamp01(abs(val) / self.severity_cap) if self.severity_cap > 0 else ZERO
            out.append(
                Observation(
                    category=self.category,
                    scope_type="country",
                    scope_key=iso2,
                    severity=severity,
                    demand_factor=ONE,
                    confidence=Decimal("0.6"),
                    headline=f"Inflation ({iso3}) {val}% ({year})",
                    source=self.key,
                    value=val,
                    unit="%",
                    trend=None,
                    detail={"indicator": self.indicator, "year": year},
                )
            )
        return out


class GdeltProvider(HttpIntelligenceProvider):
    """Global supply-disruption news intensity (GDELT DOC 2.0 timeline volume). A
    rising share of global coverage about disruptions lifts a baseline geopolitical
    risk. Scoped global (matches every context); per-country refinement later."""

    category = "geopolitical"
    key = "gdelt"
    query = "(supply chain OR port closure OR factory shutdown OR export ban OR sanctions OR strike)"
    severity_cap = Decimal("3")  # ~3% of global coverage volume ≈ maximum severity

    async def _fetch(self):
        return await self._get_json(
            "/doc/doc",
            params={"query": self.query, "mode": "timelinevol", "timespan": "14d", "format": "json"},
        )

    def parse(self, payload) -> list[Observation]:
        timeline = payload.get("timeline") if isinstance(payload, dict) else None
        if not (isinstance(timeline, list) and timeline and isinstance(timeline[0], dict)):
            return []
        data = timeline[0].get("data")
        if not isinstance(data, list) or not data:
            return []
        vals = [d for d in (_dec(p.get("value")) for p in data if isinstance(p, dict)) if d is not None]
        if not vals:
            return []
        recent = vals[-1]
        severity = _clamp01(recent / self.severity_cap) if self.severity_cap > 0 else ZERO
        return [
            Observation(
                category=self.category,
                scope_type="global",
                scope_key=None,
                severity=severity,
                demand_factor=ONE,
                confidence=Decimal("0.5"),
                headline=f"Global supply-disruption news volume at {recent}% of coverage",
                source=self.key,
                value=recent,
                unit="%",
                trend="up" if len(vals) > 1 and vals[-1] > vals[0] else None,
                detail={"query": self.query, "points": len(vals)},
            )
        ]


# Major container ports monitored for weather disruption (city, ISO-2 country).
_OW_PORTS = [
    ("Shanghai", "CN"), ("Shenzhen", "CN"), ("Ningbo", "CN"), ("Singapore", "SG"),
    ("Busan", "KR"), ("Rotterdam", "NL"), ("Los Angeles", "US"), ("Hamburg", "DE"),
]
_OW_SEVERE = {"Thunderstorm", "Tornado", "Hurricane", "Squall"}


class OpenWeatherProvider(HttpIntelligenceProvider):
    """Severe weather at major ports (OpenWeather current conditions) → port-disruption
    risk, scoped by the port's country. Needs an API key. One request per port; a
    failed port is skipped, never failing the whole pull."""

    category = "port"
    key = "openweather"
    wind_cap = Decimal("25")  # m/s; storm-force ≈ maximum severity

    async def _fetch(self):
        results = []
        for city, country in _OW_PORTS:
            try:
                data = await self._get_json(
                    "/weather", params={"q": city, "appid": self.api_key, "units": "metric"}
                )
                results.append({"city": city, "country": country, "data": data})
            except Exception:  # noqa: BLE001 — per-port resilience
                continue
        return results

    def parse(self, payload) -> list[Observation]:
        if not isinstance(payload, list):
            return []
        out: list[Observation] = []
        for entry in payload:
            data = entry.get("data") if isinstance(entry, dict) else None
            if not isinstance(data, dict):
                continue
            wind = _dec((data.get("wind") or {}).get("speed"))
            weather = data.get("weather") or []
            main = weather[0].get("main") if weather and isinstance(weather[0], dict) else None
            severity = ZERO
            if wind is not None and self.wind_cap > 0:
                severity = _clamp01(wind / self.wind_cap)
            if main in _OW_SEVERE:
                severity = max(severity, Decimal("0.7"))
            if severity < Decimal("0.15"):  # skip calm ports — not a disruption signal
                continue
            out.append(
                Observation(
                    category=self.category,
                    scope_type="country",
                    scope_key=entry.get("country"),
                    severity=severity,
                    demand_factor=ONE,
                    confidence=Decimal("0.6"),
                    headline=f"Weather at {entry.get('city')}: {main or 'wind'} ({wind} m/s)",
                    source=self.key,
                    value=wind,
                    unit="m/s",
                    trend=None,
                    detail={"city": entry.get("city"), "condition": main},
                )
            )
        return out


class ComtradeProvider(HttpIntelligenceProvider):
    """UN Comtrade trade flows → trade signals by reporter country. Needs a
    subscription key. Severity is taken from a year-over-year change when the
    response carries one (a sharp drop in a sourcing country's trade is a
    disruption signal); otherwise the row is surfaced as informational context
    (severity 0) — no fabricated risk. Refine to partner-concentration risk later."""

    category = "trade"
    key = "comtrade"
    severity_cap = Decimal("0.5")  # a 50% YoY swing ≈ maximum severity

    async def _fetch(self):
        return await self._get_json(
            "/data/v1/get/C/A/HS",
            params={
                "reporterCode": ",".join(_M49_ISO2.keys()),
                "flowCode": "M",
                "period": str(dt.date.today().year - 1),
                "subscription-key": self.api_key,
            },
        )

    def parse(self, payload) -> list[Observation]:
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return []
        # Aggregate to ONE signal per reporter country — the raw response is one row
        # per HS commodity (can be 100k+), which is meaningless granularity for a risk
        # signal and would bloat the table.
        agg: dict[str, dict] = {}
        for r in rows:
            if not isinstance(r, dict):
                continue
            iso2 = _M49_ISO2.get(str(r.get("reporterCode")))
            if not iso2:
                continue
            bucket = agg.setdefault(iso2, {"total": ZERO, "change": None})
            val = _dec(r.get("primaryValue"))
            if val is not None:
                bucket["total"] += val
            if bucket["change"] is None:
                bucket["change"] = _dec(
                    r.get("pctChange") if r.get("pctChange") is not None else r.get("change_pct")
                )
        out: list[Observation] = []
        for iso2, bucket in agg.items():
            change = bucket["change"]
            severity = ZERO
            if change is not None and self.severity_cap > 0:
                severity = _clamp01((abs(change) / Decimal("100")) / self.severity_cap)
            out.append(
                Observation(
                    category=self.category,
                    scope_type="country",
                    scope_key=iso2,
                    severity=severity,
                    demand_factor=ONE,
                    confidence=Decimal("0.4"),
                    headline=f"Trade flow {iso2}: {bucket['total']}",
                    source=self.key,
                    value=bucket["total"],
                    trend="down" if (change is not None and change < 0) else None,
                    detail={"aggregated_reporter": iso2},
                )
            )
        return out
