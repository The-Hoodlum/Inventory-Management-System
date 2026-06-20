"""Declarative base for all ORM models."""
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Common base. Tables themselves are created by the Alembic migrations in
    the ``database/`` package; these ORM classes map onto that existing schema.
    """
