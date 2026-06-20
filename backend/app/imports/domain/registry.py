"""Tiny registry of import targets, keyed by ``importer.key``."""
from __future__ import annotations

from app.imports.domain.base import ResourceImporter

_REGISTRY: dict[str, ResourceImporter] = {}


def register(importer: ResourceImporter) -> ResourceImporter:
    _REGISTRY[importer.key] = importer
    return importer


def get_importer(key: str) -> ResourceImporter:
    importer = _REGISTRY.get(key)
    if importer is None:
        raise KeyError(key)
    return importer


def all_importers() -> list[ResourceImporter]:
    return list(_REGISTRY.values())
