"""User, tenant, and RBAC lookups.

The identity/RBAC tables are intentionally NOT under RLS (see database README),
so these queries run without a tenant GUC — which is required because login must
resolve the user before any tenant context exists.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Permission,
    Role,
    RolePermission,
    Tenant,
    User,
    UserBranchAccess,
    UserRole,
)


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_tenant_by_slug(self, slug: str) -> Tenant | None:
        res = await self.session.execute(select(Tenant).where(Tenant.slug == slug))
        return res.scalar_one_or_none()

    async def find_by_email(
        self, email: str, tenant_id: uuid.UUID | None = None
    ) -> list[User]:
        stmt = select(User).where(User.email == email)
        if tenant_id is not None:
            stmt = stmt.where(User.tenant_id == tenant_id)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_permission_codes(self, user_id: uuid.UUID) -> set[str]:
        stmt = (
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .where(UserRole.user_id == user_id)
        )
        res = await self.session.execute(stmt)
        return {row[0] for row in res.all()}

    async def get_role_names(self, user_id: uuid.UUID) -> list[str]:
        stmt = (
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
            .order_by(Role.name)
        )
        res = await self.session.execute(stmt)
        return [row[0] for row in res.all()]

    async def get_branch_ids(self, user_id: uuid.UUID) -> set[uuid.UUID]:
        """Branches a user is scoped to. Empty set = unrestricted (all branches).

        Reads the RLS-protected user_branch_access, so the tenant GUC must already be set.
        """
        res = await self.session.execute(
            select(UserBranchAccess.branch_id).where(UserBranchAccess.user_id == user_id)
        )
        return {row[0] for row in res.all()}

    async def touch_last_login(self, user: User) -> None:
        from sqlalchemy import func

        user.last_login_at = func.now()
