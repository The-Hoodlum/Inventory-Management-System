"""Motorcycle module orchestration.

Two responsibilities:

1. Reference catalog CRUD (models / variants / colours) so admins configure the
   module — nothing is hard-coded.
2. The per-unit lifecycle. Every accepted transition is validated against the ONE
   explicit state machine (``domain/lifecycle.py``), written to the unit's immutable
   event ledger (from/to/user), and recorded in ``audit_logs`` — illegal transitions
   are rejected. Selling reuses the EXISTING sales documents (``reserve`` links a
   sales order, ``sell`` links an invoice and sets customer + price); there is no
   parallel sales path. A branch move is a serialized transfer recorded on the unit's
   ledger (both sides visible) with the same lock/audit discipline as the fungible
   engine, applied to one specific chassis.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.models import (
    MotorcycleColour,
    MotorcycleModel,
    MotorcycleUnit,
    MotorcycleVariant,
)
from app.motorcycles.domain import lifecycle as L
from app.motorcycles.repository import MotorcycleRepository
from app.motorcycles.schemas import (
    ColourCreate,
    ColourOut,
    ColourUpdate,
    ModelCreate,
    ModelOut,
    ModelUpdate,
    ReserveIn,
    SellIn,
    TransferIn,
    TransitionIn,
    UnitCreate,
    UnitEventOut,
    UnitOut,
    UnitUpdate,
    VariantCreate,
    VariantOut,
    VariantUpdate,
)
from app.repositories.audit_repo import AuditRepository

# Invoice status -> the unit's convenience payment_status flag (future modules own the logic).
_INVOICE_TO_PAYMENT = {"paid": "paid", "partially_paid": "partial"}


def _d(v) -> Decimal | None:
    return Decimal(str(v)) if v is not None else None


def _f(v) -> float | None:
    return float(v) if v is not None else None


class MotorcycleService:
    def __init__(self, repo: MotorcycleRepository, audit: AuditRepository) -> None:
        self.repo = repo
        self.audit = audit

    # ==================================================================== #
    # Layer 1: reference catalog
    # ==================================================================== #
    async def create_model(self, *, tenant_id, user_id, payload: ModelCreate) -> ModelOut:
        if payload.brand and payload.brand.strip():
            brand_id = (await self.repo.get_or_create_brand(tenant_id, payload.brand)).id
        elif payload.brand_id is not None:
            if not await self.repo.brand_exists(payload.brand_id):
                raise NotFoundError("Brand not found")
            brand_id = payload.brand_id
        else:
            raise BusinessRuleError("A brand (brand_id or brand name) is required.")
        if payload.category_id and not await self.repo.category_exists(payload.category_id):
            raise NotFoundError("Category not found")
        if await self.repo.model_name_conflict(brand_id, payload.name):
            raise ConflictError(f"A model named '{payload.name}' already exists for this brand.")
        obj = MotorcycleModel(
            tenant_id=tenant_id, brand_id=brand_id, name=payload.name.strip(),
            category_id=payload.category_id, engine_cc=payload.engine_cc,
            default_selling_price=_d(payload.default_selling_price), specs=payload.specs,
            is_active=payload.is_active,
        )
        self.repo.session.add(obj)
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, "model", obj.id, "created")
        return await self._model_out(obj)

    async def update_model(self, *, tenant_id, user_id, model_id, payload: ModelUpdate) -> ModelOut:
        obj = await self._require(await self.repo.get_model(model_id), "Model")
        fields = payload.model_dump(exclude_unset=True)
        brand_id = fields.get("brand_id", obj.brand_id)
        if "brand_id" in fields and not await self.repo.brand_exists(brand_id):
            raise NotFoundError("Brand not found")
        if fields.get("category_id") and not await self.repo.category_exists(fields["category_id"]):
            raise NotFoundError("Category not found")
        if "name" in fields or "brand_id" in fields:
            if await self.repo.model_name_conflict(brand_id, fields.get("name", obj.name), exclude_id=obj.id):
                raise ConflictError("A model with that name already exists for this brand.")
        for key, value in fields.items():
            setattr(obj, key, _d(value) if key == "default_selling_price" else value)
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, "model", obj.id, "updated", extra={"fields": sorted(fields)})
        return await self._model_out(obj)

    async def list_models(self, **f) -> tuple[list[ModelOut], int]:
        rows, total = await self.repo.list_models(**f)
        brands = await self.repo.brand_names([m.brand_id for m in rows])
        return [await self._model_out(m, brands) for m in rows], total

    async def create_variant(self, *, tenant_id, user_id, payload: VariantCreate) -> VariantOut:
        if await self.repo.get_model(payload.model_id) is None:
            raise NotFoundError("Model not found")
        if await self.repo.variant_name_conflict(payload.model_id, payload.name):
            raise ConflictError(f"A variant named '{payload.name}' already exists for this model.")
        obj = MotorcycleVariant(
            tenant_id=tenant_id, model_id=payload.model_id, name=payload.name.strip(),
            specs=payload.specs, is_active=payload.is_active,
        )
        self.repo.session.add(obj)
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, "variant", obj.id, "created")
        return await self._variant_out(obj)

    async def update_variant(self, *, tenant_id, user_id, variant_id, payload: VariantUpdate) -> VariantOut:
        obj = await self._require(await self.repo.get_variant(variant_id), "Variant")
        fields = payload.model_dump(exclude_unset=True)
        if "name" in fields and await self.repo.variant_name_conflict(obj.model_id, fields["name"], exclude_id=obj.id):
            raise ConflictError("A variant with that name already exists for this model.")
        for key, value in fields.items():
            setattr(obj, key, value)
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, "variant", obj.id, "updated", extra={"fields": sorted(fields)})
        return await self._variant_out(obj)

    async def list_variants(self, **f) -> tuple[list[VariantOut], int]:
        rows, total = await self.repo.list_variants(**f)
        models = await self.repo.model_names([v.model_id for v in rows])
        return [await self._variant_out(v, models) for v in rows], total

    async def create_colour(self, *, tenant_id, user_id, payload: ColourCreate) -> ColourOut:
        if await self.repo.colour_name_conflict(payload.name):
            raise ConflictError(f"A colour named '{payload.name}' already exists.")
        obj = MotorcycleColour(
            tenant_id=tenant_id, name=payload.name.strip(), hex_code=payload.hex_code,
            is_active=payload.is_active,
        )
        self.repo.session.add(obj)
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, "colour", obj.id, "created")
        return ColourOut.model_validate(obj)

    async def update_colour(self, *, tenant_id, user_id, colour_id, payload: ColourUpdate) -> ColourOut:
        obj = await self._require(await self.repo.get_colour(colour_id), "Colour")
        fields = payload.model_dump(exclude_unset=True)
        if "name" in fields and await self.repo.colour_name_conflict(fields["name"], exclude_id=obj.id):
            raise ConflictError("A colour with that name already exists.")
        for key, value in fields.items():
            setattr(obj, key, value)
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, "colour", obj.id, "updated", extra={"fields": sorted(fields)})
        return ColourOut.model_validate(obj)

    async def list_colours(self, **f) -> tuple[list[ColourOut], int]:
        rows, total = await self.repo.list_colours(**f)
        return [ColourOut.model_validate(c) for c in rows], total

    # ==================================================================== #
    # Layer 2: unit registry + lifecycle
    # ==================================================================== #
    async def create_unit(self, *, tenant_id, user_id, payload: UnitCreate) -> UnitOut:
        if await self.repo.get_model(payload.model_id) is None:
            raise NotFoundError("Model not found")
        if await self.repo.get_unit_by_chassis(payload.chassis_number) is not None:
            raise ConflictError(f"Chassis number '{payload.chassis_number}' already exists.")
        if payload.variant_id:
            variant = await self.repo.get_variant(payload.variant_id)
            if variant is None or variant.model_id != payload.model_id:
                raise BusinessRuleError("Variant does not belong to the chosen model.")
        if payload.colour_id and await self.repo.get_colour(payload.colour_id) is None:
            raise NotFoundError("Colour not found")
        if payload.supplier_id and not await self.repo.supplier_exists(payload.supplier_id):
            raise NotFoundError("Supplier not found")
        unit = MotorcycleUnit(
            tenant_id=tenant_id, chassis_number=payload.chassis_number.strip(),
            engine_number=payload.engine_number, model_id=payload.model_id,
            variant_id=payload.variant_id, colour_id=payload.colour_id, year=payload.year,
            supplier_id=payload.supplier_id, container_ref=payload.container_ref,
            date_received=payload.date_received, branch_id=payload.branch_id,
            warehouse_id=payload.warehouse_id, internal_location=payload.internal_location,
            status=L.RECEIVED, assembly_status="required" if payload.assembly_required else "not_required",
            selling_price=_d(payload.selling_price),
        )
        self.repo.session.add(unit)
        await self.repo.session.flush()
        await self.repo.add_event(
            tenant_id=tenant_id, unit_id=unit.id, event_type="created",
            to_status=L.RECEIVED, user_id=user_id, note=payload.notes or "Unit received",
        )
        await self._audit(tenant_id, user_id, "unit", unit.id, "created", old=None, new=L.RECEIVED)
        return await self._unit_out(unit, with_events=True)

    async def update_unit(self, *, tenant_id, user_id, unit_id, payload: UnitUpdate) -> UnitOut:
        unit = await self._require(await self.repo.get_unit(unit_id, lock=True), "Motorcycle unit")
        self._check_version(unit, payload.version)
        fields = payload.model_dump(exclude_unset=True, exclude={"version"})
        if "variant_id" in fields and fields["variant_id"] is not None:
            variant = await self.repo.get_variant(fields["variant_id"])
            if variant is None or variant.model_id != unit.model_id:
                raise BusinessRuleError("Variant does not belong to this unit's model.")
        if fields.get("colour_id") and await self.repo.get_colour(fields["colour_id"]) is None:
            raise NotFoundError("Colour not found")
        if fields.get("supplier_id") and not await self.repo.supplier_exists(fields["supplier_id"]):
            raise NotFoundError("Supplier not found")
        for key, value in fields.items():
            setattr(unit, key, _d(value) if key == "selling_price" else value)
        unit.version += 1
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, "unit", unit.id, "updated", old=unit.status, new=unit.status,
                          extra={"fields": sorted(fields)})
        return await self._unit_out(unit, with_events=True)

    async def transition(self, *, tenant_id, user_id, unit_id, payload: TransitionIn) -> UnitOut:
        unit = await self._require(await self.repo.get_unit(unit_id, lock=True), "Motorcycle unit")
        new = payload.to_status
        if new in (L.RESERVED, L.SOLD):
            raise BusinessRuleError(
                "Use the reserve / sell action to set the customer and sales-document linkage."
            )
        if new not in L.STATUSES:
            raise BusinessRuleError(f"Unknown status '{new}'.")
        if not L.can_transition(unit.status, new):
            raise BusinessRuleError(f"Cannot move unit from {unit.status} to {new}.")
        old = unit.status
        unit.status = new
        self._apply_side_effects(unit, new)
        unit.version += 1
        await self.repo.session.flush()
        await self.repo.add_event(
            tenant_id=tenant_id, unit_id=unit.id, event_type="status_change",
            from_status=old, to_status=new, user_id=user_id, note=payload.note,
        )
        await self._audit(tenant_id, user_id, "unit", unit.id, f"status:{new}", old=old, new=new)
        return await self._unit_out(unit, with_events=True)

    @staticmethod
    def _apply_side_effects(unit: MotorcycleUnit, new: str) -> None:
        """Keep the convenience fields consistent with the lifecycle position."""
        if new == L.INSPECTED:
            if unit.inspection_status == "pending":
                unit.inspection_status = "passed"
            # reserved -> inspected releases the serialized hold
            unit.reserved_ref = None
        elif new == L.IN_ASSEMBLY:
            unit.assembly_status = "in_progress"
        elif new == L.ASSEMBLED:
            unit.assembly_status = "assembled"
        elif new == L.REGISTERED:
            unit.registration_status = "registered"
        elif new == L.WARRANTY_ACTIVE and unit.warranty_start is None:
            unit.warranty_start = dt.date.today()

    async def reserve(self, *, tenant_id, user_id, unit_id, payload: ReserveIn) -> UnitOut:
        """Hold ONE specific chassis for one customer — a serialized hold mirroring the
        reservation engine's lock/audit discipline (SELECT FOR UPDATE + immutable event),
        NOT the fungible qty_reserved counter (a unit is not a fungible product row)."""
        unit = await self._require(await self.repo.get_unit(unit_id, lock=True), "Motorcycle unit")
        if unit.status not in L.RESERVABLE_FROM:
            raise BusinessRuleError(f"A unit in status {unit.status} cannot be reserved.")
        if not await self.repo.customer_exists(payload.customer_id):
            raise NotFoundError("Customer not found")
        if payload.sales_order_id and await self.repo.get_sales_order(payload.sales_order_id) is None:
            raise NotFoundError("Sales order not found")
        old = unit.status
        unit.status = L.RESERVED
        unit.reserved_ref = payload.sales_order_id
        unit.customer_id = payload.customer_id
        unit.version += 1
        await self.repo.session.flush()
        await self.repo.add_event(
            tenant_id=tenant_id, unit_id=unit.id, event_type="reserved", from_status=old,
            to_status=L.RESERVED, user_id=user_id, reference_type="sales_order",
            reference_id=payload.sales_order_id, note=payload.note,
        )
        await self._audit(tenant_id, user_id, "unit", unit.id, "reserved", old=old, new=L.RESERVED)
        return await self._unit_out(unit, with_events=True)

    async def sell(self, *, tenant_id, user_id, unit_id, payload: SellIn) -> UnitOut:
        """Mark the unit sold against an EXISTING invoice. The invoice is the system of
        record for the money; here we only link the unit to it and copy the convenience
        fields (customer, price, payment flag)."""
        unit = await self._require(await self.repo.get_unit(unit_id, lock=True), "Motorcycle unit")
        if unit.status not in L.SELLABLE_FROM:
            raise BusinessRuleError(f"A unit in status {unit.status} cannot be sold.")
        invoice = await self.repo.get_invoice(payload.invoice_id)
        if invoice is None:
            raise NotFoundError("Invoice not found")
        old = unit.status
        unit.status = L.SOLD
        unit.sold_ref = invoice.id
        unit.reserved_ref = None
        unit.customer_id = payload.customer_id or invoice.customer_id
        unit.price_charged = _d(payload.price_charged) if payload.price_charged is not None else unit.selling_price
        unit.payment_status = _INVOICE_TO_PAYMENT.get(invoice.status, "unpaid")
        unit.version += 1
        await self.repo.session.flush()
        await self.repo.add_event(
            tenant_id=tenant_id, unit_id=unit.id, event_type="sold", from_status=old,
            to_status=L.SOLD, user_id=user_id, reference_type="invoice",
            reference_id=invoice.id, note=payload.note,
        )
        await self._audit(tenant_id, user_id, "unit", unit.id, "sold", old=old, new=L.SOLD)
        return await self._unit_out(unit, with_events=True)

    async def transfer(self, *, tenant_id, user_id, unit_id, payload: TransferIn) -> UnitOut:
        """Serialized branch move: this exact chassis moves to another branch/location,
        recorded as a `transfer` event with from/to branch (both sides visible), audited.
        Reuses the transfer CONCEPT on the unit's own ledger — the fungible stock-transfer
        engine cannot represent a single serialized unit."""
        unit = await self._require(await self.repo.get_unit(unit_id, lock=True), "Motorcycle unit")
        if unit.status == L.CANCELLED:
            raise BusinessRuleError("A cancelled unit cannot be transferred.")
        if payload.to_branch_id == unit.branch_id and payload.to_warehouse_id == unit.warehouse_id:
            raise BusinessRuleError("Destination is the same as the current location.")
        from_branch = unit.branch_id
        unit.branch_id = payload.to_branch_id
        if payload.to_warehouse_id is not None:
            unit.warehouse_id = payload.to_warehouse_id
        if payload.internal_location is not None:
            unit.internal_location = payload.internal_location
        unit.version += 1
        await self.repo.session.flush()
        await self.repo.add_event(
            tenant_id=tenant_id, unit_id=unit.id, event_type="transfer", user_id=user_id,
            from_branch_id=from_branch, to_branch_id=payload.to_branch_id, note=payload.note,
        )
        await self._audit(tenant_id, user_id, "unit", unit.id, "transferred", old=unit.status, new=unit.status,
                          extra={"from_branch": str(from_branch), "to_branch": str(payload.to_branch_id)})
        return await self._unit_out(unit, with_events=True)

    async def get_unit(self, unit_id: uuid.UUID) -> UnitOut:
        return await self._unit_out(
            await self._require(await self.repo.get_unit(unit_id), "Motorcycle unit"), with_events=True
        )

    async def list_units(self, **f) -> tuple[list[UnitOut], int]:
        rows, total = await self.repo.list_units(**f)
        names = (
            await self.repo.model_names([u.model_id for u in rows]),
            await self.repo.variant_names([u.variant_id for u in rows]),
            await self.repo.colour_names([u.colour_id for u in rows]),
            await self.repo.branch_names([u.branch_id for u in rows]),
            await self.repo.warehouse_names([u.warehouse_id for u in rows]),
            await self.repo.customer_names([u.customer_id for u in rows]),
        )
        return [await self._unit_out(u, with_events=False, names=names) for u in rows], total

    # =============================== helpers ============================= #
    @staticmethod
    async def _require(obj, label: str):
        if obj is None:
            raise NotFoundError(f"{label} not found")
        return obj

    @staticmethod
    def _check_version(unit: MotorcycleUnit, version: int | None) -> None:
        if version is not None and version != unit.version:
            raise ConflictError(
                "This unit was changed by someone else since you loaded it; reload and retry."
            )

    async def _audit(self, tenant_id, user_id, kind, entity_id, action, *, old="", new="", extra=None) -> None:
        changes = {"old_status": old, "new_status": new} if (old or new) else {}
        if extra:
            changes.update(extra)
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action=f"motorcycle_{kind}.{action}",
            entity_type=f"motorcycle_{kind}", entity_id=entity_id, changes=changes,
        )

    async def _model_out(self, m: MotorcycleModel, brands=None) -> ModelOut:
        brand_name = (brands or await self.repo.brand_names([m.brand_id])).get(m.brand_id)
        return ModelOut(
            id=m.id, tenant_id=m.tenant_id, brand_id=m.brand_id, brand_name=brand_name, name=m.name,
            category_id=m.category_id, engine_cc=m.engine_cc,
            default_selling_price=_f(m.default_selling_price), specs=m.specs or {}, is_active=m.is_active,
            created_at=m.created_at, updated_at=m.updated_at,
        )

    async def _variant_out(self, v: MotorcycleVariant, models=None) -> VariantOut:
        model_name = (models or await self.repo.model_names([v.model_id])).get(v.model_id)
        return VariantOut(
            id=v.id, tenant_id=v.tenant_id, model_id=v.model_id, model_name=model_name, name=v.name,
            specs=v.specs or {}, is_active=v.is_active, created_at=v.created_at, updated_at=v.updated_at,
        )

    async def _unit_out(self, unit: MotorcycleUnit, *, with_events: bool, names=None) -> UnitOut:
        if names is None:
            models = await self.repo.model_names([unit.model_id])
            variants = await self.repo.variant_names([unit.variant_id])
            colours = await self.repo.colour_names([unit.colour_id])
            branches = await self.repo.branch_names([unit.branch_id])
            warehouses = await self.repo.warehouse_names([unit.warehouse_id])
            customers = await self.repo.customer_names([unit.customer_id])
            suppliers = await self.repo.supplier_names([unit.supplier_id])
        else:
            models, variants, colours, branches, warehouses, customers = names
            suppliers = await self.repo.supplier_names([unit.supplier_id])
        events: list[UnitEventOut] = []
        if with_events:
            ledger = await self.repo.events_for(unit.id)
            ev_branches = await self.repo.branch_names(
                [e.from_branch_id for e in ledger] + [e.to_branch_id for e in ledger]
            )
            events = [
                UnitEventOut(
                    id=e.id, event_type=e.event_type, from_status=e.from_status, to_status=e.to_status,
                    from_branch_id=e.from_branch_id, from_branch_name=ev_branches.get(e.from_branch_id),
                    to_branch_id=e.to_branch_id, to_branch_name=ev_branches.get(e.to_branch_id),
                    reference_type=e.reference_type, reference_id=e.reference_id, note=e.note,
                    user_id=e.user_id, created_at=e.created_at,
                )
                for e in ledger
            ]
        return UnitOut(
            id=unit.id, chassis_number=unit.chassis_number, engine_number=unit.engine_number,
            model_id=unit.model_id, model_name=models.get(unit.model_id),
            variant_id=unit.variant_id, variant_name=variants.get(unit.variant_id),
            colour_id=unit.colour_id, colour_name=colours.get(unit.colour_id), year=unit.year,
            supplier_id=unit.supplier_id, supplier_name=suppliers.get(unit.supplier_id),
            container_ref=unit.container_ref, date_received=unit.date_received,
            branch_id=unit.branch_id, branch_name=branches.get(unit.branch_id),
            warehouse_id=unit.warehouse_id, warehouse_name=warehouses.get(unit.warehouse_id),
            internal_location=unit.internal_location, status=unit.status,
            inspection_status=unit.inspection_status, assembly_status=unit.assembly_status,
            reserved_ref=unit.reserved_ref, reserved_so_number=await self.repo.so_number(unit.reserved_ref),
            sold_ref=unit.sold_ref, sold_invoice_number=await self.repo.invoice_number(unit.sold_ref),
            customer_id=unit.customer_id, customer_name=customers.get(unit.customer_id),
            selling_price=_f(unit.selling_price), price_charged=_f(unit.price_charged),
            payment_status=unit.payment_status, registration_status=unit.registration_status,
            registration_number=unit.registration_number,
            registration_papers_received=unit.registration_papers_received,
            warranty_start=unit.warranty_start, warranty_end=unit.warranty_end,
            version=unit.version, created_at=unit.created_at, updated_at=unit.updated_at,
            allowed_next=L.allowed_next(unit.status), events=events,
        )
