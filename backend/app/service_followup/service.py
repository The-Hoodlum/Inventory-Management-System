"""Service follow-up orchestration.

Joins each sold unit to its schedule (per-model override -> tenant default -> module
default) and computes the next service due (time-only, usage-scaled). Also logs services
performed, sets a unit's usage profile, and edits the schedule. Writes only follow-up
tables + an audit row; never touches stock.
"""
from __future__ import annotations

import datetime as dt
import math
import uuid
from collections.abc import Sequence

from app.core.exceptions import BusinessRuleError, NotFoundError
from app.models import MotorcycleServicePlan, MotorcycleServiceRecord
from app.repositories.audit_repo import AuditRepository
from app.service_followup.domain import schedule as S
from app.service_followup.repository import ServiceFollowUpRepository, SoldUnitRow
from app.service_followup.schemas import (
    FollowUpKpis,
    FollowUpPage,
    FollowUpRow,
    ServicePlanIn,
    ServicePlanOut,
    ServicePlansOut,
    ServiceRecordCreate,
    ServiceRecordOut,
    StageOut,
    UsageUpdate,
)

_STATUS_ORDER = {S.OVERDUE: 0, S.DUE_SOON: 1, S.UPCOMING: 2}


class ServiceFollowUpService:
    def __init__(self, repo: ServiceFollowUpRepository, audit: AuditRepository) -> None:
        self.repo = repo
        self.audit = audit

    # ------------------------------ follow-up list --------------------------- #
    async def list_followups(
        self,
        *,
        branch_ids: Sequence[uuid.UUID] | None = None,
        model_id: uuid.UUID | None = None,
        search: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
        today: dt.date | None = None,
    ) -> FollowUpPage:
        today = today or dt.date.today()
        units = await self.repo.list_sold_units(branch_ids=branch_ids, model_id=model_id, search=search)
        stages_by_model = self._stage_index(await self.repo.list_plans())

        rows: list[FollowUpRow] = []
        kpis = FollowUpKpis()
        for u in units:
            row = self._row(u, stages_by_model, today)
            if row.status == S.OVERDUE:
                kpis.overdue += 1
            elif row.status == S.DUE_SOON:
                kpis.due_soon += 1
            elif row.status == S.UPCOMING:
                kpis.upcoming += 1
            rows.append(row)
        kpis.total = len(rows)

        if status in (S.OVERDUE, S.DUE_SOON, S.UPCOMING):
            rows = [r for r in rows if r.status == status]

        # Most-urgent first: overdue, then due-soon, then upcoming; within a bucket the
        # soonest due date. Rows with no computable due date sink to the bottom.
        rows.sort(key=lambda r: (
            _STATUS_ORDER.get(r.status or "", 9),
            r.next_due_date or dt.date.max,
        ))

        total = len(rows)
        start = (page - 1) * page_size
        page_items = rows[start:start + page_size]
        return FollowUpPage(
            items=page_items, page=page, page_size=page_size, total=total,
            total_pages=math.ceil(total / page_size) if total else 0, kpis=kpis,
        )

    def _row(self, u: SoldUnitRow, stages_by_model, today: dt.date) -> FollowUpRow:
        stages = stages_by_model.get(u.model_id) or stages_by_model.get(None) or list(S.DEFAULT_STAGES)
        nxt = S.compute_next_service(
            sale_date=u.date_sold, services_done=u.services_done,
            last_service_date=u.last_service_date, usage=u.service_usage,
            stages=stages, today=today,
        )
        return FollowUpRow(
            unit_id=u.unit_id, chassis_number=u.chassis_number, model_id=u.model_id,
            model_name=u.model_name, colour_name=u.colour_name, branch_id=u.branch_id,
            branch_name=u.branch_name, customer_id=u.customer_id, customer_name=u.customer_name,
            customer_phone=u.customer_phone, date_sold=u.date_sold,
            service_usage=S.normalise_usage(u.service_usage), services_done=u.services_done,
            last_service_date=u.last_service_date,
            next_sequence=nxt.sequence if nxt else None,
            next_label=nxt.label if nxt else None,
            next_due_date=nxt.due_date if nxt else None,
            days_until_due=nxt.days_until_due if nxt else None,
            status=nxt.status if nxt else None,
        )

    @staticmethod
    def _stage_index(plans: list[MotorcycleServicePlan]) -> dict[uuid.UUID | None, list[S.Stage]]:
        """model_id -> stages (None key = the tenant default row)."""
        return {p.model_id: S.stages_from_config(p.stages) for p in plans}

    # ------------------------------ records ---------------------------------- #
    async def list_records(self, unit_id: uuid.UUID) -> list[ServiceRecordOut]:
        records = await self.repo.list_records(unit_id)
        return [self._record_out(r) for r in records]

    async def log_service(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, unit_id: uuid.UUID,
        payload: ServiceRecordCreate,
    ) -> ServiceRecordOut:
        unit = await self.repo.get_unit(unit_id)
        if unit is None:
            raise NotFoundError("Motorcycle unit not found")
        if unit.date_sold is None:
            raise BusinessRuleError("Only a sold bike (with a sale date) can have services logged")
        done = await self.repo.count_records(unit_id)
        sequence = payload.sequence or (done + 1)
        stages = S.stages_from_config(await self._plan_stages_for(unit.model_id))
        label = S.stage_for(stages, sequence).label
        record = await self.repo.add_record(MotorcycleServiceRecord(
            tenant_id=tenant_id, unit_id=unit_id, sequence=sequence, label=label,
            service_date=payload.service_date, note=(payload.note or None), performed_by=user_id,
        ))
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action="service.logged",
            entity_type="motorcycle_service_record", entity_id=record.id,
            changes={"unit_id": str(unit_id), "sequence": sequence,
                     "service_date": payload.service_date.isoformat()},
        )
        return self._record_out(record)

    async def _plan_stages_for(self, model_id: uuid.UUID) -> object:
        plan = await self.repo.get_plan_by_model(model_id)
        if plan is None:
            plan = await self.repo.get_plan_by_model(None)
        return plan.stages if plan is not None else list(S.DEFAULT_STAGES)

    async def set_usage(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, unit_id: uuid.UUID, payload: UsageUpdate,
    ) -> FollowUpRow:
        usage = (payload.service_usage or "").strip().lower()
        if usage not in S.USAGE_PROFILES:
            raise BusinessRuleError(f"Usage must be one of {', '.join(S.USAGE_PROFILES)}")
        unit = await self.repo.get_unit(unit_id)
        if unit is None:
            raise NotFoundError("Motorcycle unit not found")
        unit.service_usage = usage
        await self.repo.session.flush()
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action="service.usage_set",
            entity_type="motorcycle_unit", entity_id=unit_id, changes={"service_usage": usage},
        )
        # Recompute this unit's row so the UI can update in place.
        stages_by_model = self._stage_index(await self.repo.list_plans())
        rows = await self.repo.list_sold_units()
        match = next((r for r in rows if r.unit_id == unit_id), None)
        if match is None:  # not sold yet — return a minimal echo
            return FollowUpRow(
                unit_id=unit_id, chassis_number=unit.chassis_number, model_id=unit.model_id,
                service_usage=usage, services_done=0,
            )
        return self._row(match, stages_by_model, dt.date.today())

    # ------------------------------ schedule --------------------------------- #
    async def list_plans(self) -> ServicePlansOut:
        plans = await self.repo.list_plans()
        model_ids = [p.model_id for p in plans if p.model_id is not None]
        names = await self.repo.model_names(model_ids)
        out: list[ServicePlanOut] = []
        for p in plans:
            out.append(self._plan_out(p, names))
        module_default = ServicePlanOut(
            is_default=True, is_module_default=True,
            stages=[StageOut(sequence=s.sequence, label=s.label, interval_days=s.interval_days)
                    for s in S.DEFAULT_STAGES],
        )
        return ServicePlansOut(
            plans=out, module_default=module_default,
            usage_multipliers=dict(S.USAGE_MULTIPLIERS),
        )

    async def upsert_plan(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, payload: ServicePlanIn,
    ) -> ServicePlanOut:
        if payload.model_id is not None and not await self.repo.model_exists(payload.model_id):
            raise NotFoundError("Model not found")
        stages_json = [
            {"sequence": i, "label": (s.label or f"Service {i}").strip() or f"Service {i}",
             "interval_days": s.interval_days}
            for i, s in enumerate(payload.stages, start=1)
        ]
        existing = await self.repo.get_plan_by_model(payload.model_id)
        if existing is not None:
            existing.stages = stages_json
            plan = existing
            action = "service.schedule_updated"
        else:
            plan = await self.repo.add_plan(MotorcycleServicePlan(
                tenant_id=tenant_id, model_id=payload.model_id, stages=stages_json,
            ))
            action = "service.schedule_set"
        await self.repo.session.flush()
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action=action,
            entity_type="motorcycle_service_plan", entity_id=plan.id,
            changes={"model_id": str(payload.model_id) if payload.model_id else None,
                     "stages": stages_json},
        )
        names = await self.repo.model_names([plan.model_id] if plan.model_id else [])
        return self._plan_out(plan, names)

    async def delete_plan(self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, plan_id: uuid.UUID) -> None:
        plan = await self.repo.get_plan(plan_id)
        if plan is None:
            raise NotFoundError("Service schedule not found")
        await self.repo.delete_plan(plan)
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action="service.schedule_removed",
            entity_type="motorcycle_service_plan", entity_id=plan_id, changes={},
        )

    # ------------------------------ mappers ---------------------------------- #
    @staticmethod
    def _plan_out(p: MotorcycleServicePlan, names: dict) -> ServicePlanOut:
        stages = S.stages_from_config(p.stages)
        return ServicePlanOut(
            id=p.id, model_id=p.model_id, model_name=names.get(p.model_id),
            is_default=p.model_id is None, is_module_default=False,
            stages=[StageOut(sequence=s.sequence, label=s.label, interval_days=s.interval_days)
                    for s in stages],
        )

    @staticmethod
    def _record_out(r: MotorcycleServiceRecord) -> ServiceRecordOut:
        return ServiceRecordOut(
            id=r.id, unit_id=r.unit_id, sequence=r.sequence, label=r.label,
            service_date=r.service_date, note=r.note, performed_by=r.performed_by,
            created_at=r.created_at,
        )
