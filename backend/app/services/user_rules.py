"""Pure user-management rules — standard library only (no pydantic / SQLAlchemy).

Isolated here so the validation logic is unit-testable without a database or web
stack. The service layer calls these helpers and raises the appropriate
application errors.
"""
from __future__ import annotations

import re
import uuid

MIN_PASSWORD_LENGTH = 10


def normalize_email(email: str) -> str:
    """Trim and lower-case an email for consistent storage/lookup (the DB column
    is CITEXT, but normalising here keeps comparisons predictable everywhere)."""
    return email.strip().lower()


def password_problems(password: str) -> list[str]:
    """Return a list of unmet password requirements (empty == acceptable)."""
    problems: list[str] = []
    if len(password) < MIN_PASSWORD_LENGTH:
        problems.append(f"at least {MIN_PASSWORD_LENGTH} characters")
    if not re.search(r"[A-Za-z]", password):
        problems.append("at least one letter")
    if not re.search(r"\d", password):
        problems.append("at least one digit")
    return problems


def role_changes(
    current: set[uuid.UUID], desired: set[uuid.UUID]
) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    """(to_add, to_remove) when moving from ``current`` to ``desired`` roles."""
    return (desired - current, current - desired)


def invalid_role_ids(
    desired: set[uuid.UUID], valid: set[uuid.UUID]
) -> set[uuid.UUID]:
    """Role ids in ``desired`` that aren't assignable for the tenant."""
    return set(desired) - set(valid)


def dedupe_preserving_order(items: list[uuid.UUID]) -> list[uuid.UUID]:
    return list(dict.fromkeys(items))
