"""Data access for the service follow-up module.

Read side: sold units joined to their model / colour / customer / branch names, plus a
per-unit aggregate of the service log (how many done + the last date). Write side: append
a service record, set a unit's usage profile, and CRUD the per-model schedule. All
tenant-scoped by RLS; the write paths touch only follow-up tables (never stock).
"""
from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Customer,
    MotorcycleColour,
    MotorcycleModel,
    MotorcycleServicePlan,
    MotorcycleServiceRecord,
    MotorcycleUnit,
)
from app.models.inventory import Branch
from app.motorcycles.domain import lifecycle as L


@dataclass(frozen=True)
class SoldUnitRow:
    unit_id: uuid.UUID
    chassis_number: str
    model_id: uuid.UUID
    model_name: str | None
    colour_name: str | None
    branch_id: uuid.UUID | None
    branch_name: str | None
    customer_id: uuid.UUID | None
    customer_name: str | None
    customer_phone: str | None
    date_sold: dt.date | None
    service_usage: str
    services_done: int
    last_service_date: dt.date | None


class ServiceFollowUpRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------- read ------------------------------------ #
    async def list_sold_units(
        self,
        *,
        branch_ids: Sequence[uuid.UUID] | None = None,
        model_id: uuid.UUID | None = None,
        search: str | None = None,
    ) -> list[SoldUnitRow]:
        """Every sold unit (with a sale date) plus its service-log aggregate. The due
        status is computed in the service layer, so this returns the full set to bucket."""
        done = func.count(MotorcycleServiceRecord.id)
        last = func.max(MotorcycleServiceRecord.service_date)
        stmt = (
            select(
                MotorcycleUnit.id,
                MotorcycleUnit.chassis_number,
                MotorcycleUnit.model_id,
                MotorcycleModel.name,
                MotorcycleColour.name,
                MotorcycleUnit.branch_id,
                Branch.name,
                MotorcycleUnit.customer_id,
                Customer.name,
                Customer.phone,
                MotorcycleUnit.date_sold,
                MotorcycleUnit.service_usage,
                done,
                last,
            )
            .select_from(MotorcycleUnit)
            .join(MotorcycleModel, MotorcycleModel.id == MotorcycleUnit.model_id)
            .outerjoin(MotorcycleColour, MotorcycleColour.id == MotorcycleUnit.colour_id)
            .outerjoin(Branch, Branch.id == MotorcycleUnit.branch_id)
            .outerjoin(Customer, Customer.id == MotorcycleUnit.customer_id)
            .outerjoin(MotorcycleServiceRecord, MotorcycleServiceRecord.unit_id == MotorcycleUnit.id)
            .where(MotorcycleUnit.status == L.SOLD, MotorcycleUnit.date_sold.isnot(None))
            .group_by(
                MotorcycleUnit.id, MotorcycleModel.name, MotorcycleColour.name,
                Branch.name, Customer.name, Customer.phone,
            )
        )
        if branch_ids is not None:
            stmt = stmt.where(MotorcycleUnit.branch_id.in_(list(branch_ids)))
        if model_id is not None:
            stmt = stmt.where(MotorcycleUnit.model_id == model_id)
        if search:
            like = f"%{search.strip().lower()}%"
            stmt = stmt.where(
                func.lower(MotorcycleUnit.chassis_number).like(like)
                | func.lower(func.coalesce(Customer.name, "")).like(like)
                | func.lower(func.coalesce(Customer.phone, "")).like(like)
                | func.lower(func.coalesce(MotorcycleUnit.registration_number, "")).like(like)
            )
        rows = await self.session.execute(stmt)
        return [
            SoldUnitRow(
                unit_id=r[0], chassis_number=r[1], model_id=r[2], model_name=r[3],
                colour_name=r[4], branch_id=r[5], branch_name=r[6], customer_id=r[7],
                customer_name=r[8], customer_phone=r[9], date_sold=r[10],
                service_usage=r[11], services_done=int(r[12] or 0), last_service_date=r[13],
            )
            for r in rows.all()
        ]

    async def get_unit(self, unit_id: uuid.UUID) -> MotorcycleUnit | None:
        return await self.session.scalar(select(MotorcycleUnit).where(MotorcycleUnit.id == unit_id))

    async def list_records(self, unit_id: uuid.UUID) -> list[MotorcycleServiceRecord]:
        rows = await self.session.scalars(
            select(MotorcycleServiceRecord)
            .where(MotorcycleServiceRecord.unit_id == unit_id)
            .order_by(MotorcycleServiceRecord.service_date, MotorcycleServiceRecord.created_at)
        )
        return list(rows)

    async def count_records(self, unit_id: uuid.UUID) -> int:
        return int(
            await self.session.scalar(
                select(func.count(MotorcycleServiceRecord.id)).where(
                    MotorcycleServiceRecord.unit_id == unit_id
                )
            )
            or 0
        )

    # ------------------------------- write ----------------------------------- #
    async def add_record(self, record: MotorcycleServiceRecord) -> MotorcycleServiceRecord:
        self.session.add(record)
        await self.session.flush()
        return record

    async def model_name(self, model_id: uuid.UUID) -> str | None:
        return await self.session.scalar(
            select(MotorcycleModel.name).where(MotorcycleModel.id == model_id)
        )

    # ------------------------------- plans ----------------------------------- #
    async def list_plans(self) -> list[MotorcycleServicePlan]:
        rows = await self.session.scalars(
            select(MotorcycleServicePlan).order_by(MotorcycleServicePlan.model_id.nullsfirst())
        )
        return list(rows)

    async def get_plan(self, plan_id: uuid.UUID) -> MotorcycleServicePlan | None:
        return await self.session.scalar(
            select(MotorcycleServicePlan).where(MotorcycleServicePlan.id == plan_id)
        )

    async def get_plan_by_model(self, model_id: uuid.UUID | None) -> MotorcycleServicePlan | None:
        stmt = select(MotorcycleServicePlan)
        stmt = stmt.where(
            MotorcycleServicePlan.model_id == model_id if model_id is not None
            else MotorcycleServicePlan.model_id.is_(None)
        )
        return await self.session.scalar(stmt)

    async def add_plan(self, plan: MotorcycleServicePlan) -> MotorcycleServicePlan:
        self.session.add(plan)
        await self.session.flush()
        return plan

    async def delete_plan(self, plan: MotorcycleServicePlan) -> None:
        await self.session.delete(plan)
        await self.session.flush()

    async def model_exists(self, model_id: uuid.UUID) -> bool:
        return (
            await self.session.scalar(select(MotorcycleModel.id).where(MotorcycleModel.id == model_id))
            is not None
        )

    async def model_names(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
        wanted = [v for v in {*ids} if v is not None]
        if not wanted:
            return {}
        rows = await self.session.execute(
            select(MotorcycleModel.id, MotorcycleModel.name).where(MotorcycleModel.id.in_(wanted))
        )
        return {r.id: r.name for r in rows}
