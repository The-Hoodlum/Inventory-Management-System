"""Build the configured intelligence ``ExternalSource`` from settings.

Returns ``NullSource`` (inert) unless a provider is credentialed, so the
intelligence layer runs unchanged until a real feed is configured. As more
vendors are added (Xeneta, SeaRates, carrier APIs), compose them here behind the
same ``ExternalSource`` interface — callers never change.
"""
from __future__ import annotations

from app.intelligence.providers.base import ExternalSource, NullSource
from app.intelligence.sources.freightos import FreightosSource


def build_external_source(settings) -> ExternalSource:
    if settings.freightos_configured:
        return FreightosSource.from_settings(settings)
    return NullSource()
