"""The "internal_issuance_notes" import target: load HISTORICAL internal issuance/handover
notes for serialized bikes from a spreadsheet.

RECORD-ONLY history — documents a completed internal handout (loaned to a requestor /
department and since returned) that already happened; it NEVER moves stock or changes the
unit's current state. Each row becomes a CLOSED ``issuances`` row (status='returned', the
line fully returned) with one motorcycle line — so a bike's past internal use is on record
without affecting whether it's currently sellable.

Atomic target: validated up front, committed in one transaction.

Smart chassis matching: matched to an EXISTING unit by chassis; an unknown chassis is a row
error. The source warehouse is taken from the unit. A bike may appear on several issuance
notes over time, so rows are not de-duplicated.
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
from app.models import Issuance, IssuanceLine, MotorcycleUnit, Warehouse

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
    FieldSpec("date", "Issue Date", required=True, kind=FieldKind.STRING, levels=_ALL,
              aliases=("date", "issue date", "issued date", "handover date")),
    FieldSpec("chassis_number", "Chassis Number", required=True, kind=FieldKind.STRING, levels=_ALL,
              aliases=("chassis", "chassis no", "chassis number", "vin", "frame number", "frame no")),
    FieldSpec("requestor", "Requestor", required=True, kind=FieldKind.STRING, levels=_ALL,
              aliases=("requestor", "requested by", "issued to", "person", "staff", "name")),
    FieldSpec("department", "Department", kind=FieldKind.STRING, levels=_STD,
              aliases=("department", "dept", "team", "section")),
    FieldSpec("purpose", "Purpose", kind=FieldKind.STRING, levels=_STD,
              aliases=("purpose", "reason", "use", "for")),
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

    async def warehouse_for_unit(self, unit: MotorcycleUnit) -> Warehouse | None:
        if unit.warehouse_id is not None:
            wh = await self.s.get(Warehouse, unit.warehouse_id)
            if wh is not None:
                return wh
        if unit.branch_id is not None:
            return await self.s.scalar(
                select(Warehouse).where(Warehouse.branch_id == unit.branch_id)
                .order_by(Warehouse.is_active.desc(), Warehouse.name).limit(1)
            )
        return None

    async def next_number(self) -> str:
        return await self.s.scalar(
            text("SELECT next_sales_number(CAST(:t AS uuid), :d, :p)"),
            {"t": str(self.tenant_id), "d": "issuance", "p": "ISS"},
        )


class InternalIssuanceNotesImporter(AtomicImporter):
    key = "internal_issuance_notes"
    label = "Internal issuance notes (history)"
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
                errors.append("Issue Date is required and must be a valid date")

            if not (clean.get("requestor") or "").strip():
                errors.append("Requestor is required")

            chassis = clean.get("chassis_number")
            unit = await repo.find_unit(chassis) if chassis else None
            if chassis and unit is None:
                errors.append(f"Chassis '{chassis}' is not on record — import the unit first")

            warehouse_id = None
            if unit is not None:
                wh = await repo.warehouse_for_unit(unit)
                if wh is None:
                    errors.append(f"Chassis '{chassis}' has no branch/warehouse to issue from")
                else:
                    warehouse_id = wh.id

            data = None
            if not errors and unit is not None:
                data = {
                    "unit_id": unit.id, "chassis_number": unit.chassis_number,
                    "engine_number": unit.engine_number, "warehouse_id": warehouse_id,
                    "branch_id": unit.branch_id, "when": when,
                    "requestor": clean.get("requestor").strip(),
                    "department": (clean.get("department") or None),
                    "purpose": (clean.get("purpose") or None),
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
            at = dt.datetime.combine(when, dt.time(12, 0), tzinfo=dt.UTC)
            audit = f"Imported issuance note (job {job_id})"
            iss = Issuance(
                tenant_id=tenant_id, issuance_number=await repo.next_number(), status="returned",
                branch_id=d.get("branch_id"), warehouse_id=d["warehouse_id"],
                requestor=d["requestor"], department=d.get("department"), purpose=d.get("purpose"),
                remarks=f"{d['remarks']} — {audit}" if d.get("remarks") else audit,
                issued_by=user_id, issued_at=at, closed_at=at, created_by=user_id,
            )
            iss.lines = [IssuanceLine(
                tenant_id=tenant_id, line_kind="motorcycle", unit_id=d["unit_id"],
                chassis_number=d["chassis_number"], engine_number=d.get("engine_number"),
                qty=1, returnable=True, returned_qty=1, returned_at=at,
            )]
            session.add(iss)
            created += 1
        await session.flush()
        return created

    async def process_row(self, ctx: Any, clean: dict[str, Any]) -> RowResult:  # pragma: no cover
        raise NotImplementedError("internal_issuance_notes is an atomic target; use plan()/commit()")


register(InternalIssuanceNotesImporter())
