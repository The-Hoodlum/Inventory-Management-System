"""Domain-level errors for the reorder engine.

This package is intentionally free of any framework, database, or I/O imports so
the calculation core can be reasoned about and unit-tested in complete isolation.
"""
from __future__ import annotations


class ReorderDomainError(Exception):
    """Base class for reorder-engine domain errors."""


class InvalidPolicyError(ReorderDomainError):
    """A reorder policy is internally inconsistent (e.g. units_per_carton < 1)."""
