"""Schemas for user administration (list/create/update) and role listing."""
from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None = None
    is_system: bool


class UserCreate(BaseModel):
    email: str = Field(min_length=1)
    full_name: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=1)
    role_ids: list[uuid.UUID] = Field(default_factory=list)
    is_active: bool = True


class UserUpdate(BaseModel):
    """Partial update. ``password`` resets the password; ``role_ids`` replaces
    the full set of assigned roles."""

    full_name: str | None = Field(default=None, min_length=1, max_length=256)
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=1)
    role_ids: list[uuid.UUID] | None = None


class UserOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    email: str
    full_name: str
    is_active: bool
    last_login_at: dt.datetime | None
    created_at: dt.datetime
    roles: list[str]          # role names, for display
    role_ids: list[uuid.UUID]  # for editing
