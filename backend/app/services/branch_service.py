"""Branch service: create / update / delete / get / list, with audit.

Branches have no soft-delete column; deletion is a hard delete, but the FK
(RESTRICT from warehouses.branch_id) prevents removing a branch that still owns
locations — that surfaces here as a 409 with a clear message.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError, NotFoundError
from app.models import Branch
from app.repositories.audit_repo import AuditRepository
from app.repositories.branch_repo import BranchRepository
from app.schemas.branch import BranchCreate, BranchUpdate

_AUDITED_FIELDS = ("code", "name", "is_active")


def _snapshot(b: Branch) -> dict[str, Any]:
    return {f: getattr(b, f) for f in _AUDITED_FIELDS}


class BranchService:
    def __init__(self, branches: BranchRepository, audit: AuditRepository) -> None:
        self.branches = branches
        self.audit = audit

    async def create(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, data: BranchCreate, ip: str | None = None
    ) -> Branch:
        if await self.branches.get_by_code(data.code):
            raise ConflictError(f"A branch with code '{data.code}' already exists")
        branch = Branch(tenant_id=tenant_id, **data.model_dump())
        await self.branches.add(branch)
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action="create", entity_type="branch",
            entity_id=branch.id, changes={"after": _snapshot(branch)}, ip_address=ip,
        )
        return branch

    async def get(self, branch_id: uuid.UUID) -> Branch:
        branch = await self.branches.get(branch_id)
        if branch is None:
            raise NotFoundError("Branch not found")
        return branch

    async def update(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, branch_id: uuid.UUID,
        data: BranchUpdate, ip: str | None = None,
    ) -> Branch:
        branch = await self.get(branch_id)
        changes = data.model_dump(exclude_unset=True)
        if "code" in changes and changes["code"] != branch.code:
            if await self.branches.get_by_code(changes["code"]):
                raise ConflictError(f"A branch with code '{changes['code']}' already exists")
        before = _snapshot(branch)
        for field, value in changes.items():
            setattr(branch, field, value)
        await self.branches.session.flush()
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action="update", entity_type="branch",
            entity_id=branch.id, changes={"before": before, "after": _snapshot(branch)}, ip_address=ip,
        )
        return branch

    async def delete(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, branch_id: uuid.UUID, ip: str | None = None
    ) -> None:
        branch = await self.get(branch_id)
        bid = branch.id
        name = branch.name  # capture now: a failed delete aborts the txn, so ORM attribute
        #                     access afterwards would raise instead of returning the name.
        # Refuse (and say what to move first) if ANYTHING still references the branch —
        # locations, units, documents, user assignments — so nothing is orphaned or
        # silently un-linked. Deletion stays the user's own explicit action; no data wipe.
        blockers = await self.branches.reference_blockers(branch_id)
        if blockers:
            summary = ", ".join(f"{count} {label}" for label, count in blockers)
            raise ConflictError(
                f"Cannot delete branch '{name}' — it is still referenced by {summary}. "
                "Move or reassign these first, or deactivate the branch instead (set it inactive)."
            )
        try:
            await self.branches.delete(branch)
        except IntegrityError as exc:  # backstop for any reference not caught above
            raise ConflictError(
                f"Cannot delete branch '{name}'; something still references it. "
                "Reassign or remove those first, or deactivate it instead."
            ) from exc
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action="delete", entity_type="branch",
            entity_id=bid, changes={"deleted": True}, ip_address=ip,
        )

    async def list(
        self, *, active_only: bool = False, page: int = 1, page_size: int = 100
    ) -> tuple[list[Branch], int]:
        return await self.branches.list(active_only=active_only, page=page, page_size=page_size)
