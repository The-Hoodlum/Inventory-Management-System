"""Global search: a small, extensible registry over the platform's EXISTING entities.

Each module contributes a :class:`SearchProvider` (entity name, the permission that
gates it, and an async ``search``); the core endpoint fans a query out across every
registered provider the caller is allowed to see and returns grouped hits. New modules
add to global search by registering a provider — they never edit the core endpoint.
"""
from app.search.registry import SearchProvider, register, registry

__all__ = ["SearchProvider", "register", "registry"]
