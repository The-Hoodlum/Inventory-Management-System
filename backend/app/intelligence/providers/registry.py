"""Registry of external intelligence providers, built from settings.

Returns only providers that are enabled (and credentialed where required), so the
default build is inert. Adding a provider — free or paid — is one entry here plus its
class; the ingest engine (``IntelligenceService``) never changes.
"""
from __future__ import annotations

from app.intelligence.providers.base import IntelligenceProvider
from app.intelligence.providers.external import (
    ComtradeProvider,
    ExchangeRateHostProvider,
    GdeltProvider,
    ImfProvider,
    OpenWeatherProvider,
    WorldBankProvider,
)


def build_free_providers(settings) -> list[IntelligenceProvider]:
    """The enabled public/free HTTP providers. Empty when none are enabled."""
    providers: list[IntelligenceProvider] = []
    t = settings.intel_http_timeout_seconds

    if settings.intel_exchangerate_enabled:
        providers.append(
            ExchangeRateHostProvider(
                enabled=True,
                base_url=settings.intel_exchangerate_base_url,
                api_key=settings.intel_exchangerate_api_key,
                timeout_seconds=t,
            )
        )
    if settings.intel_worldbank_enabled:
        providers.append(
            WorldBankProvider(
                enabled=True,
                base_url=settings.intel_worldbank_base_url,
                timeout_seconds=t,
            )
        )
    if settings.intel_imf_enabled:
        providers.append(
            ImfProvider(enabled=True, base_url=settings.intel_imf_base_url, timeout_seconds=t)
        )
    if settings.intel_gdelt_enabled:
        providers.append(
            GdeltProvider(enabled=True, base_url=settings.intel_gdelt_base_url, timeout_seconds=t)
        )
    # UN Comtrade needs a subscription key — register only when enabled and keyed.
    if settings.intel_comtrade_enabled and settings.intel_comtrade_api_key:
        providers.append(
            ComtradeProvider(
                enabled=True,
                base_url=settings.intel_comtrade_base_url,
                api_key=settings.intel_comtrade_api_key,
                timeout_seconds=t,
            )
        )
    # OpenWeather needs an API key — only register when both enabled and keyed.
    if settings.intel_openweather_enabled and settings.intel_openweather_api_key:
        providers.append(
            OpenWeatherProvider(
                enabled=True,
                base_url=settings.intel_openweather_base_url,
                api_key=settings.intel_openweather_api_key,
                timeout_seconds=t,
            )
        )
    return providers
