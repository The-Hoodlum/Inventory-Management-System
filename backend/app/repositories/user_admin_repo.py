"""Tenant-scoped user + role lookups for the admin/user-management API.

Identity and RBAC tables are intentionally NOT under row-level security, so
every query here filters by ``tenant_id`` explicitly. Kept separate from the
auth-critical ``UserRepository`` to avoid coupling admin CRUD to login.
"""
from __future__ import annotations

import uuid

from sqlalchemy import delete, func, insert, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Branch, Role, User, UserBranchAccess, UserRole


class UserAdminRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_users(
        self,
        *,
        tenant_id: uuid.UUID,
        search: str | None = None,
        is_active: bool | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[User], int]:
        cond = [User.tenant_id == tenant_id]
        if is_active is not None:
            cond.append(User.is_active.is_(is_active))
        if search:
            like = f"%{search}%"
            cond.append(or_(User.email.ilike(like), User.full_name.ilike(like)))

        total = await self.session.scalar(
            select(func.count()).select_from(User).where(*cond)
        )
        rows = (
            await self.session.execute(
                select(User).where(*cond).order_by(User.created_at.desc()).offset(offset).limit(limit)
            )
        ).scalars().all()
        return list(rows), int(total or 0)

    async def get_in_tenant(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User | None:
        res = await self.session.execute(
            select(User).where(User.id == user_id, User.tenant_id == tenant_id)
        )
        return res.scalar_one_or_none()

    async def email_exists(self, tenant_id: uuid.UUID, email: str) -> bool:
        res = await self.session.execute(
            select(User.id).where(User.tenant_id == tenant_id, User.email == email)
        )
        return res.first() is not None

    async def add(self, user: User) -> None:
        self.session.add(user)
        await self.session.flush()

    async def role_ids_for(self, user_id: uuid.UUID) -> list[uuid.UUID]:
        res = await self.session.execute(
            select(UserRole.role_id).where(UserRole.user_id == user_id)
        )
        return [r[0] for r in res.all()]

    async def roles_for_users(
        self, user_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[tuple[uuid.UUID, str]]]:
        if not user_ids:
            return {}
        stmt = (
            select(UserRole.user_id, Role.id, Role.name)
            .join(Role, Role.id == UserRole.role_id)
            .where(UserRole.user_id.in_(user_ids))
        )
        out: dict[uuid.UUID, list[tuple[uuid.UUID, str]]] = {}
        for uid, rid, rname in (await self.session.execute(stmt)).all():
            out.setdefault(uid, []).append((rid, rname))
        return out

    # ------------------------------ branches ----------------------------- #
    async def branches_for_users(
        self, user_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[uuid.UUID]]:
        if not user_ids:
            return {}
        rows = await self.session.execute(
            select(UserBranchAccess.user_id, UserBranchAccess.branch_id)
            .where(UserBranchAccess.user_id.in_(user_ids))
        )
        out: dict[uuid.UUID, list[uuid.UUID]] = {}
        for uid, bid in rows.all():
            out.setdefault(uid, []).append(bid)
        return out

    async def valid_branch_ids(self, tenant_id: uuid.UUID) -> set[uuid.UUID]:
        rows = await self.session.execute(select(Branch.id).where(Branch.tenant_id == tenant_id))
        return {r[0] for r in rows.all()}

    async def set_branches(
        self, user_id: uuid.UUID, branch_ids: list[uuid.UUID], tenant_id: uuid.UUID
    ) -> None:
        await self.session.execute(delete(UserBranchAccess).where(UserBranchAccess.user_id == user_id))
        for bid in branch_ids:
            await self.session.execute(
                insert(UserBranchAccess).values(user_id=user_id, branch_id=bid, tenant_id=tenant_id)
            )
        await self.session.flush()

    async def set_roles(self, user_id: uuid.UUID, role_ids: list[uuid.UUID]) -> None:
        await self.session.execute(delete(UserRole).where(UserRole.user_id == user_id))
        for rid in role_ids:
            await self.session.execute(
                insert(UserRole).values(user_id=user_id, role_id=rid)
            )
        await self.session.flush()

    async def assignable_roles(self, tenant_id: uuid.UUID) -> list[Role]:
        stmt = (
            select(Role)
            .where(or_(Role.tenant_id == tenant_id, Role.tenant_id.is_(None)))
            .order_by(Role.name)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def assignable_role_ids(self, tenant_id: uuid.UUID) -> set[uuid.UUID]:
        stmt = select(Role.id).where(
            or_(Role.tenant_id == tenant_id, Role.tenant_id.is_(None))
        )
        return {r[0] for r in (await self.session.execute(stmt)).all()}
