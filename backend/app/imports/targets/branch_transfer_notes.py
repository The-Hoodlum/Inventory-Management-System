"""The "branch_transfer_notes" import target: load HISTORICAL branch-to-branch transfer
notes for serialized bikes from a spreadsheet.

RECORD-ONLY history — like the other document imports, this documents a move that already
happened; it NEVER moves stock or changes where the unit currently sits. Each row becomes a
completed ``dispatch_notes`` row (status='received') with one motorcycle line: "this chassis
was transferred to <branch> on <date>". No inventory movement, no unit mutation.

Atomic target: the whole batch is validated up front and committed in one transaction.

Smart chassis matching: each row is matched to an EXISTING unit by chassis (trimmed,
case-insensitive); an unknown chassis is a row error. The SOURCE is taken from the unit (its
warehouse, else one in its branch); the DESTINATION is the sheet's "To Branch" (matched by
name → a warehouse in that branch). A bike may appear on several transfer notes (it moved
more than once), so rows are not de-duplicated.
"""
from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.imports.domain.atomic import AtomicImporter, ImportPlan, RowInput, RowPlan
from app.imports.domain.fields import (
    LEVEL_ADVANCED,
    LEVEL_BASIC,
    LEVEL_STANDARD,
    FieldKind,
    FieldSpec,
    RowResult,
)
from app.imports.domain.registry import register
from app.models import DispatchNote, DispatchNoteLine, MotorcycleUnit, Warehouse
from app.models.inventory import Branch

_ALL = (LEVEL_BASIC, LEVEL_STANDARD, LEVEL_ADVANCED)
_STD = (LEVEL_STANDARD, LEVEL_ADVANCED)
_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%m/%d/%Y")


def _parse_date(raw: Any) -> tuple[dt.date | None, bool]:
    if isinstance(raw, dt.datetime):
        return raw.date(), True
    if isinstance(raw, dt.date):
        return raw, True
    s = ("" if raw is None else str(raw)).strip()
    if not s:
        return None, False
    s = s.split(" ")[0].split("T")[0]
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(s, fmt).date(), True
        except ValueError:
            continue
    return None, False


_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("date", "Transfer Date", required=True, kind=FieldKind.STRING, levels=_ALL,
              aliases=("date", "transfer date", "dispatch date", "moved date")),
    FieldSpec("chassis_number", "Chassis Number", required=True, kind=FieldKind.STRING, levels=_ALL,
              aliases=("chassis", "chassis no", "chassis number", "vin", "frame number", "frame no")),
    FieldSpec("to_branch", "To Branch", required=True, kind=FieldKind.STRING, levels=_ALL,
              aliases=("to branch", "destination", "destination branch", "to", "received branch", "to location")),
    FieldSpec("received_by", "Received By", kind=FieldKind.STRING, levels=_STD,
              aliases=("received by", "receiver", "signed by")),
    FieldSpec("remarks", "Remarks", kind=FieldKind.STRING, levels=_STD,
              aliases=("remarks", "note", "notes", "comment", "reference")),
)


class _Repo:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.s = session
        self.tenant_id = tenant_id

    async def find_unit(self, chassis: str) -> MotorcycleUnit | None:
        return await self.s.scalar(
            select(MotorcycleUnit).where(
                func.lower(MotorcycleUnit.chassis_number) == chassis.strip().lower()
            ).limit(1)
        )

    async def find_branch(self, name: str) -> Branch | None:
        return await self.s.scalar(
            select(Branch).where(func.lower(Branch.name) == name.strip().lower()).limit(1)
        )

    async def warehouse_in_branch(self, branch_id: uuid.UUID | None) -> Warehouse | None:
        if branch_id is None:
            return None
        return await self.s.scalar(
            select(Warehouse).where(Warehouse.branch_id == branch_id)
            .order_by(Warehouse.is_active.desc(), Warehouse.name).limit(1)
        )

    async def warehouse_for_unit(self, unit: MotorcycleUnit) -> Warehouse | None:
        if unit.warehouse_id is not None:
            wh = await self.s.get(Warehouse, unit.warehouse_id)
            if wh is not None:
                return wh
        return await self.warehouse_in_branch(unit.branch_id)

    async def next_number(self) -> str:
        return await self.s.scalar(
            text("SELECT next_sales_number(CAST(:t AS uuid), :d, :p)"),
            {"t": str(self.tenant_id), "d": "dispatch_note", "p": "DN"},
        )


class BranchTransferNotesImporter(AtomicImporter):
    key = "branch_transfer_notes"
    label = "Branch transfer notes (history)"
    key_field = "chassis_number"

    @property
    def fields(self) -> Sequence[FieldSpec]:
        return _FIELDS

    async def plan(self, session: Any, *, tenant_id: Any, rows: list[RowInput], options: Any = None) -> ImportPlan:
        repo = _Repo(session, tenant_id)
        plan = ImportPlan()
        for row_number, clean, field_errors in rows:
            errors = list(field_errors)

            when, ok = _parse_date(clean.get("date"))
            if not ok:
                errors.append("Transfer Date is required and must be a valid date")

            chassis = clean.get("chassis_number")
            unit = await repo.find_unit(chassis) if chassis else None
            if chassis and unit is None:
                errors.append(f"Chassis '{chassis}' is not on record — import the unit first")

            from_wh = to_wh = to_branch_id = None
            if unit is not None:
                src = await repo.warehouse_for_unit(unit)
                if src is None:
                    errors.append(f"Chassis '{chassis}' has no branch/warehouse to transfer from")
                else:
                    from_wh = src.id

            to_branch_name = (clean.get("to_branch") or "").strip()
            if to_branch_name:
                dest = await repo.find_branch(to_branch_name)
                if dest is None:
                    errors.append(f"Destination branch '{to_branch_name}' was not found")
                else:
                    dest_wh = await repo.warehouse_in_branch(dest.id)
                    if dest_wh is None:
                        errors.append(f"Destination branch '{to_branch_name}' has no warehouse")
                    else:
                        to_wh, to_branch_id = dest_wh.id, dest.id

            data = None
            if not errors and unit is not None:
                data = {
                    "unit_id": unit.id, "chassis_number": unit.chassis_number,
                    "engine_number": unit.engine_number, "from_warehouse_id": from_wh,
                    "from_branch_id": unit.branch_id, "to_warehouse_id": to_wh,
                    "to_branch_id": to_branch_id, "when": when,
                    "received_by": (clean.get("received_by") or None),
                    "remarks": (clean.get("remarks") or None),
                }
            plan.rows.append(RowPlan(row_number=row_number, key=chassis, errors=errors, data=data))
        return plan

    async def commit(self, session: Any, *, tenant_id: Any, user_id: Any, job_id: Any, plan: ImportPlan) -> int:
        repo = _Repo(session, tenant_id)
        created = 0
        for rp in plan.rows:
            if rp.data is None:
                continue
            d = rp.data
            when = d["when"]
            moved_at = dt.datetime.combine(when, dt.time(12, 0), tzinfo=dt.UTC)
            audit = f"Imported transfer note (job {job_id})"
            note = DispatchNote(
                tenant_id=tenant_id, note_number=await repo.next_number(),
                dispatch_type="warehouse_branch_transfer", status="received",
                from_branch_id=d.get("from_branch_id"), from_warehouse_id=d["from_warehouse_id"],
                to_branch_id=d.get("to_branch_id"), to_warehouse_id=d["to_warehouse_id"],
                remarks=f"{d['remarks']} — {audit}" if d.get("remarks") else audit,
                dispatched_by=user_id, dispatched_at=moved_at,
                received_by=d.get("received_by"), received_by_user=user_id, received_at=moved_at,
                created_by=user_id,
            )
            note.lines = [DispatchNoteLine(
                tenant_id=tenant_id, line_kind="motorcycle", unit_id=d["unit_id"],
                chassis_number=d["chassis_number"], engine_number=d.get("engine_number"),
                dispatched_qty=1, received_qty=1,
            )]
            session.add(note)
            created += 1
        await session.flush()
        return created

    async def process_row(self, ctx: Any, clean: dict[str, Any]) -> RowResult:  # pragma: no cover
        raise NotImplementedError("branch_transfer_notes is an atomic target; use plan()/commit()")


register(BranchTransferNotesImporter())
