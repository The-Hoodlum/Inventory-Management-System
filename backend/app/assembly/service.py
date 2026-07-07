"""Assembly-planner orchestration.

Turns current unit counts (assembled vs unassembled per model/colour/variant) plus the
tenant's optional per model/colour targets into a deterministic plan: what to assemble now
(capped by buildable stock) and what is thin with nothing to build from. It drives the
pure planner (``domain/planner.py``); it reads NO sales or demand data and predicts
nothing. The planner recommends — assembling is the user performing the existing
unassembled->assembled lifecycle transition in the Motorcycle module.
"""
from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence

from app.assembly.domain import planner as P
from app.assembly.repository import AssemblyRepository, ComboCount
from app.assembly.schemas import (
    AssemblyLineOut,
    AssemblyPlanOut,
    AssemblyTargetIn,
    AssemblyTargetOut,
)
from app.core.exceptions import NotFoundError
from app.models import AssemblyTarget
from app.repositories.audit_repo import AuditRepository


class AssemblyPlannerService:
    def __init__(self, repo: AssemblyRepository, audit: AuditRepository) -> None:
        self.repo = repo
        self.audit = audit

    # -------------------------------- plan ----------------------------------- #
    async def plan(
        self, *, branch_ids: Sequence[uuid.UUID] | None = None, model_id: uuid.UUID | None = None
    ) -> AssemblyPlanOut:
        counts = await self.repo.assembly_counts(branch_ids=branch_ids, model_id=model_id)
        config = self._config_index(await self.repo.list_targets())
        names = await self._names(counts)

        recommendations: list[AssemblyLineOut] = []
        gaps: list[AssemblyLineOut] = []
        for c in counts:
            target, threshold = self._resolve(config, c.model_id, c.colour_id)
            outcome = P.plan_combo(P.ComboInput(
                assembled=c.assembled, unassembled=c.unassembled, target=target, threshold=threshold,
            ))
            if not (outcome.is_recommendation or outcome.is_gap):
                continue
            line = self._line(c, target, threshold, outcome, names)
            (recommendations if outcome.is_recommendation else gaps).append(line)

        # Deterministic ranking: thinnest first, then the bigger build, then a stable name
        # order. A future demand-weighted layer can re-rank recommendations here.
        recommendations.sort(key=lambda r: (r.current_assembled, -r.recommended_qty, r.model_name or "", r.colour_name or ""))
        gaps.sort(key=lambda r: (r.current_assembled, r.model_name or "", r.colour_name or ""))
        return AssemblyPlanOut(
            generated_at=dt.datetime.now(dt.UTC),
            default_target_assembled=P.DEFAULT_TARGET_ASSEMBLED,
            default_threshold=P.DEFAULT_THRESHOLD,
            recommendations=recommendations,
            gaps=gaps,
        )

    # ------------------------------- targets --------------------------------- #
    async def list_targets(self) -> list[AssemblyTargetOut]:
        targets = await self.repo.list_targets()
        models = await self.repo.model_names([t.model_id for t in targets])
        colours = await self.repo.colour_names([t.colour_id for t in targets])
        return [self._target_out(t, models, colours) for t in targets]

    async def upsert_target(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, payload: AssemblyTargetIn
    ) -> AssemblyTargetOut:
        if not await self.repo.model_exists(payload.model_id):
            raise NotFoundError("Model not found")
        if payload.colour_id is not None and not await self.repo.colour_exists(payload.colour_id):
            raise NotFoundError("Colour not found")
        existing = await self.repo.get_target_by_combo(payload.model_id, payload.colour_id)
        if existing is not None:
            existing.target_assembled = payload.target_assembled
            existing.threshold = payload.threshold
            target = existing
            action = "target_updated"
        else:
            target = await self.repo.add_target(AssemblyTarget(
                tenant_id=tenant_id, model_id=payload.model_id, colour_id=payload.colour_id,
                target_assembled=payload.target_assembled, threshold=payload.threshold,
            ))
            action = "target_set"
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, target.id, action, {
            "model_id": str(payload.model_id),
            "colour_id": str(payload.colour_id) if payload.colour_id else None,
            "target_assembled": payload.target_assembled, "threshold": payload.threshold,
        })
        models = await self.repo.model_names([target.model_id])
        colours = await self.repo.colour_names([target.colour_id])
        return self._target_out(target, models, colours)

    async def delete_target(self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, target_id: uuid.UUID) -> None:
        target = await self.repo.get_target(target_id)
        if target is None:
            raise NotFoundError("Assembly target not found")
        await self.repo.delete_target(target)
        await self._audit(tenant_id, user_id, target_id, "target_removed", {})

    # ------------------------------- helpers --------------------------------- #
    @staticmethod
    def _config_index(targets: list[AssemblyTarget]) -> dict[tuple[uuid.UUID, uuid.UUID | None], tuple[int, int]]:
        return {(t.model_id, t.colour_id): (t.target_assembled, t.threshold) for t in targets}

    @staticmethod
    def _resolve(config, model_id, colour_id) -> tuple[int, int]:
        """Most-specific-wins: exact (model, colour) -> model-wide (model, None) -> defaults."""
        if colour_id is not None and (model_id, colour_id) in config:
            return config[(model_id, colour_id)]
        if (model_id, None) in config:
            return config[(model_id, None)]
        return (P.DEFAULT_TARGET_ASSEMBLED, P.DEFAULT_THRESHOLD)

    async def _names(self, counts: list[ComboCount]):
        return (
            await self.repo.model_names([c.model_id for c in counts]),
            await self.repo.variant_names([c.variant_id for c in counts]),
            await self.repo.colour_names([c.colour_id for c in counts]),
        )

    @staticmethod
    def _line(c: ComboCount, target, threshold, outcome, names) -> AssemblyLineOut:
        models, variants, colours = names
        return AssemblyLineOut(
            model_id=c.model_id, model_name=models.get(c.model_id),
            variant_id=c.variant_id, variant_name=variants.get(c.variant_id),
            colour_id=c.colour_id, colour_name=colours.get(c.colour_id),
            current_assembled=c.assembled, unassembled_available=c.unassembled,
            target_assembled=target, threshold=threshold,
            recommended_qty=outcome.recommended_qty, reason=outcome.reason,
        )

    @staticmethod
    def _target_out(t: AssemblyTarget, models, colours) -> AssemblyTargetOut:
        return AssemblyTargetOut(
            id=t.id, model_id=t.model_id, model_name=models.get(t.model_id),
            colour_id=t.colour_id, colour_name=colours.get(t.colour_id),
            target_assembled=t.target_assembled, threshold=t.threshold,
        )

    async def _audit(self, tenant_id, user_id, entity_id, action, changes) -> None:
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action=f"assembly.{action}",
            entity_type="assembly_target", entity_id=entity_id, changes=changes,
        )
