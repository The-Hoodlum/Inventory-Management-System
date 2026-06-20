"""Domain errors for purchase-order management and goods receiving.

This package is pure: no FastAPI, SQLAlchemy, or I/O imports, so the state
machine and receiving logic can be unit-tested in isolation.
"""
from __future__ import annotations


class ProcurementDomainError(Exception):
    """Base class for procurement domain errors."""


class InvalidTransitionError(ProcurementDomainError):
    """A requested status transition is not allowed from the current status."""


class ReceiptError(ProcurementDomainError):
    """A goods receipt is invalid (unknown line, non-positive qty, over-receipt)."""
