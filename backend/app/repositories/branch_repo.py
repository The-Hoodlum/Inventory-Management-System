"""Branch repository: get, list, create (via base), delete."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select, text

from app.models import Branch
from app.repositories.base import BaseRepository

# Every table (+ its branch column[s]) that represents real data / documents / assignments
# tied to a branch, with a human label — checked before a branch delete so nothing is
# orphaned or silently un-linked. Pinned from pg_catalog (2026-07) rather than discovered at
# runtime: information_schema.constraint_column_usage is privilege-filtered and returns
# NOTHING for the non-superuser app_user, which would silently skip the guard. The immutable
# motorcycle_unit_events ledger is intentionally omitted (append-only history; SET NULL).
_BRANCH_REFERENCES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("warehouses", ("branch_id",), "locations"),
    ("motorcycle_units", ("branch_id",), "motorcycle units"),
    ("dispatch_notes", ("from_branch_id", "to_branch_id"), "dispatch notes"),
    ("delivery_notes", ("branch_id",), "delivery notes"),
    ("customer_deliveries", ("branch_id",), "customer deliveries"),
    ("issuances", ("branch_id",), "issuances"),
    ("bike_issues", ("branch_id",), "bike repair jobs"),
    ("parts_sales", ("branch_id",), "parts-sales records"),
    ("quotations", ("branch_id",), "quotations"),
    ("sales_orders", ("branch_id",), "sales orders"),
    ("invoices", ("branch_id",), "invoices"),
    ("receipts", ("branch_id",), "receipts"),
    ("payments", ("branch_id",), "payments"),
    ("returns", ("branch_id",), "returns"),
    ("credit_notes", ("branch_id",), "credit notes"),
    ("user_branch_access", ("branch_id",), "user assignments"),
)


class BranchRepository(BaseRepository[Branch]):
    model = Branch

    async def get(self, branch_id: uuid.UUID) -> Branch | None:
        return await self.session.get(Branch, branch_id)

    async def get_by_code(self, code: str) -> Branch | None:
        res = await self.session.execute(select(Branch).where(Branch.code == code))
        return res.scalar_one_or_none()

    async def list(
        self, *, active_only: bool = False, page: int = 1, page_size: int = 100
    ) -> tuple[list[Branch], int]:
        base = select(Branch)
        if active_only:
            base = base.where(Branch.is_active.is_(True))
        total = await self.session.scalar(select(func.count()).select_from(base.subquery()))
        stmt = base.order_by(Branch.name).limit(page_size).offset((page - 1) * page_size)
        res = await self.session.execute(stmt)
        return list(res.scalars().all()), int(total or 0)

    async def delete(self, branch: Branch) -> None:
        await self.session.delete(branch)
        await self.session.flush()

    async def reference_blockers(self, branch_id: uuid.UUID) -> list[tuple[str, int]]:
        """``(label, count)`` for every table that still references this branch, so a delete
        can refuse and say exactly what to move first — covering FKs whose ``ON DELETE`` is
        SET NULL/CASCADE (which would otherwise orphan data silently). Counts are tenant-
        scoped by RLS; branch ids are globally unique anyway. Table/column names are the
        pinned constants above (never user input), so the f-string is safe."""
        out: list[tuple[str, int]] = []
        for table, cols, label in _BRANCH_REFERENCES:
            where = " OR ".join(f'"{c}" = :bid' for c in cols)
            n = await self.session.scalar(
                text(f'SELECT count(*) FROM "{table}" WHERE {where}'), {"bid": str(branch_id)}
            )
            if n:
                out.append((label, int(n)))
        return out
