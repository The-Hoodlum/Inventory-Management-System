"""Auth schemas."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str = Field(min_length=1)
    password: str = Field(min_length=1)
    # Optional: disambiguates the tenant when the same email exists in several
    # tenants. Not needed for single-tenant deployments / the demo.
    tenant_slug: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # access-token lifetime in seconds


class RefreshRequest(BaseModel):
    refresh_token: str


class MeResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    email: str
    full_name: str
    roles: list[str]
    permissions: list[str]
    accessible_warehouse_ids: list[uuid.UUID] = []  # explicit branch grants; empty = all branches
