"""User-administration service: create / list / get / update / deactivate users
and assign roles, with audit logging and self-lockout protection.

All mutations are tenant-scoped (the repository filters by tenant). Password and
role validation live in the pure ``user_rules`` module.
"""
from __future__ import annotations

import uuid

from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.core.security import hash_password
from app.models import User
from app.repositories.audit_repo import AuditRepository
from app.repositories.user_admin_repo import UserAdminRepository
from app.schemas.user import RoleOut, UserCreate, UserOut, UserUpdate
from app.services import user_rules


class UserAdminService:
    def __init__(self, users: UserAdminRepository, audit: AuditRepository) -> None:
        self.users = users
        self.audit = audit

    # ------------------------------ helpers ------------------------------ #
    async def _to_out(
        self, user: User, role_pairs: list[tuple[uuid.UUID, str]] | None = None
    ) -> UserOut:
        if role_pairs is None:
            mapping = await self.users.roles_for_users([user.id])
            role_pairs = mapping.get(user.id, [])
        names = sorted(name for _id, name in role_pairs)
        ids = [rid for rid, _name in role_pairs]
        return UserOut(
            id=user.id,
            tenant_id=user.tenant_id,
            email=user.email,
            full_name=user.full_name,
            is_active=user.is_active,
            last_login_at=user.last_login_at,
            created_at=user.created_at,
            roles=names,
            role_ids=ids,
        )

    async def _validate_roles(self, tenant_id: uuid.UUID, role_ids: list[uuid.UUID]) -> list[uuid.UUID]:
        desired = user_rules.dedupe_preserving_order(role_ids)
        if desired:
            valid = await self.users.assignable_role_ids(tenant_id)
            invalid = user_rules.invalid_role_ids(set(desired), valid)
            if invalid:
                raise BusinessRuleError(
                    "One or more roles are not assignable in this tenant",
                    details={"role_ids": sorted(str(r) for r in invalid)},
                )
        return desired

    @staticmethod
    def _check_password(password: str) -> None:
        problems = user_rules.password_problems(password)
        if problems:
            raise BusinessRuleError(
                "Password must contain " + ", ".join(problems),
                details={"password": problems},
            )

    # ------------------------------- reads ------------------------------- #
    async def list(
        self,
        *,
        tenant_id: uuid.UUID,
        search: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[UserOut], int]:
        is_active: bool | None = None
        if status == "active":
            is_active = True
        elif status == "inactive":
            is_active = False
        offset = (page - 1) * page_size
        users, total = await self.users.list_users(
            tenant_id=tenant_id, search=search, is_active=is_active, offset=offset, limit=page_size
        )
        role_map = await self.users.roles_for_users([u.id for u in users])
        out = [await self._to_out(u, role_map.get(u.id, [])) for u in users]
        return out, total

    async def get(self, *, tenant_id: uuid.UUID, user_id: uuid.UUID) -> UserOut:
        user = await self.users.get_in_tenant(tenant_id, user_id)
        if user is None:
            raise NotFoundError("User not found")
        return await self._to_out(user)

    async def list_roles(self, *, tenant_id: uuid.UUID) -> list[RoleOut]:
        roles = await self.users.assignable_roles(tenant_id)
        return [RoleOut.model_validate(r) for r in roles]

    # ----------------------------- mutations ----------------------------- #
    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_id: uuid.UUID,
        data: UserCreate,
        ip: str | None = None,
    ) -> UserOut:
        email = user_rules.normalize_email(data.email)
        self._check_password(data.password)
        if await self.users.email_exists(tenant_id, email):
            raise ConflictError(f"A user with email '{email}' already exists")
        desired = await self._validate_roles(tenant_id, data.role_ids)

        user = User(
            tenant_id=tenant_id,
            email=email,
            full_name=data.full_name,
            password_hash=hash_password(data.password),
            is_active=data.is_active,
        )
        await self.users.add(user)
        if desired:
            await self.users.set_roles(user.id, desired)

        await self.audit.add(
            tenant_id=tenant_id,
            user_id=actor_id,
            action="create",
            entity_type="user",
            entity_id=user.id,
            changes={
                "email": email,
                "full_name": data.full_name,
                "is_active": data.is_active,
                "role_ids": [str(r) for r in desired],
            },
            ip_address=ip,
        )
        return await self._to_out(user)

    async def update(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_id: uuid.UUID,
        user_id: uuid.UUID,
        data: UserUpdate,
        ip: str | None = None,
    ) -> UserOut:
        user = await self.users.get_in_tenant(tenant_id, user_id)
        if user is None:
            raise NotFoundError("User not found")

        changes: dict = {}
        if data.full_name is not None and data.full_name != user.full_name:
            user.full_name = data.full_name
            changes["full_name"] = data.full_name

        if data.is_active is not None and data.is_active != user.is_active:
            if not data.is_active and user_id == actor_id:
                raise BusinessRuleError("You cannot deactivate your own account")
            user.is_active = data.is_active
            changes["is_active"] = data.is_active

        if data.password is not None:
            self._check_password(data.password)
            user.password_hash = hash_password(data.password)
            changes["password_changed"] = True

        if data.role_ids is not None:
            desired = await self._validate_roles(tenant_id, data.role_ids)
            await self.users.set_roles(user_id, desired)
            changes["role_ids"] = [str(r) for r in desired]

        await self.users.session.flush()
        if changes:
            await self.audit.add(
                tenant_id=tenant_id,
                user_id=actor_id,
                action="update",
                entity_type="user",
                entity_id=user.id,
                changes=changes,
                ip_address=ip,
            )
        return await self._to_out(user)

    async def deactivate(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_id: uuid.UUID,
        user_id: uuid.UUID,
        ip: str | None = None,
    ) -> None:
        if user_id == actor_id:
            raise BusinessRuleError("You cannot deactivate your own account")
        user = await self.users.get_in_tenant(tenant_id, user_id)
        if user is None:
            raise NotFoundError("User not found")
        if user.is_active:
            user.is_active = False
            await self.users.session.flush()
            await self.audit.add(
                tenant_id=tenant_id,
                user_id=actor_id,
                action="deactivate",
                entity_type="user",
                entity_id=user.id,
                changes={"is_active": False},
                ip_address=ip,
            )
