"""Branch -> customer/reseller delivery orchestration (sale | consignment).

Writes NO stock directly. Sale mode is proof of a handover the sale already deducted
for. Consignment mode HOLDS parts (reservation: available down, on_hand unchanged) and
CONSIGNS bikes (out, not sellable, not deducted) on dispatch; SETTLE turns sold portions
into a real deduction / bike sale, and RETURN releases the unsold holds.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from app.core.exceptions import BusinessRuleError, NotFoundError
from app.customer_delivery.domain import status as S
from app.customer_delivery.repository import CustomerDeliveryRepository
from app.customer_delivery.schemas import (
    CustomerDeliveryCreate,
    CustomerDeliveryLineOut,
    CustomerDeliveryOut,
    CustomerDeliverySettle,
)
from app.models import CustomerDelivery, CustomerDeliveryLine, MotorcycleUnitEvent
from app.motorcycles.domain import lifecycle as L
from app.repositories.audit_repo import AuditRepository
from app.services.inventory_service import InventoryService, _available

_LINE_REF = "customer_consignment_line"


def _d(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal("0")


def _f(v) -> float:
    return float(v) if v is not None else 0.0


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class CustomerDeliveryService:
    def __init__(self, repo: CustomerDeliveryRepository, inventory: InventoryService, audit: AuditRepository) -> None:
        self.repo = repo
        self.inventory = inventory
        self.audit = audit

    # ------------------------------- create ---------------------------------- #
    async def create(self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, payload: CustomerDeliveryCreate) -> CustomerDeliveryOut:
        wh = await self.repo.get_warehouse(payload.from_warehouse_id)
        if wh is None:
            raise NotFoundError("Source warehouse not found")
        lines: list[CustomerDeliveryLine] = []

        if payload.delivery_mode == S.SALE:
            invoice = await self.repo.get_invoice(payload.invoice_id)
            if invoice is None:
                raise NotFoundError("Invoice not found")
            customer_id = invoice.customer_id
            # Proof of the sale's handover: list the invoice's parts + the bikes it sold.
            for product_id, qty in await self.repo.invoice_part_lines(invoice.id):
                lines.append(CustomerDeliveryLine(tenant_id=tenant_id, line_kind="part", product_id=product_id, qty=_d(qty)))
            for unit in await self.repo.units_on_invoice(invoice.id):
                lines.append(CustomerDeliveryLine(
                    tenant_id=tenant_id, line_kind="motorcycle", unit_id=unit.id,
                    chassis_number=unit.chassis_number, engine_number=unit.engine_number, qty=Decimal("1"),
                ))
            if not lines:
                raise BusinessRuleError("This invoice has no deliverable lines (no parts or linked bikes).")
            invoice_id = invoice.id
        else:  # consignment
            if await self.repo.get_customer(payload.customer_id) is None:
                raise NotFoundError("Customer not found")
            customer_id = payload.customer_id
            invoice_id = None
            for pl in payload.part_lines:
                if await self.repo.get_product(pl.product_id) is None:
                    raise NotFoundError("Product not found")
                lines.append(CustomerDeliveryLine(tenant_id=tenant_id, line_kind="part", product_id=pl.product_id, qty=_d(pl.qty)))
            seen: set[uuid.UUID] = set()
            for bl in payload.bike_lines:
                unit = await self.repo.get_unit(bl.unit_id)
                if unit is None:
                    raise NotFoundError("Motorcycle unit not found")
                if unit.id in seen:
                    raise BusinessRuleError(f"Unit {unit.chassis_number} is listed more than once.")
                seen.add(unit.id)
                if unit.status == L.SOLD:
                    raise BusinessRuleError(f"Unit {unit.chassis_number} is already sold.")
                if await self.repo.unit_on_open_consignment(unit.id):
                    raise BusinessRuleError(f"Unit {unit.chassis_number} is already out on consignment.")
                lines.append(CustomerDeliveryLine(
                    tenant_id=tenant_id, line_kind="motorcycle", unit_id=unit.id,
                    chassis_number=unit.chassis_number, engine_number=unit.engine_number, qty=Decimal("1"),
                ))

        cd = CustomerDelivery(
            tenant_id=tenant_id, delivery_number=await self.repo.number(tenant_id),
            delivery_mode=payload.delivery_mode, status=S.DRAFT, branch_id=wh.branch_id,
            from_warehouse_id=wh.id, customer_id=customer_id, invoice_id=invoice_id,
            remarks=payload.remarks, created_by=user_id,
        )
        cd.lines = lines
        self.repo.session.add(cd)
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, cd.id, "created", {"mode": cd.delivery_mode, "lines": len(lines)})
        return await self._out(cd)

    # ------------------------------- deliver --------------------------------- #
    async def deliver(self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, delivery_id: uuid.UUID, received_by: str | None) -> CustomerDeliveryOut:
        cd = await self._require(await self.repo.get(delivery_id, lock=True))
        if cd.status != S.DRAFT:
            raise BusinessRuleError(f"Only a draft delivery can be dispatched (status={cd.status}).")
        if cd.delivery_mode == S.SALE:
            # Proof of handover — the sale already deducted; nothing moves here.
            cd.status = S.DELIVERED
        else:  # consignment — hold parts + consign bikes, no deduction
            for ln in cd.lines:
                if ln.line_kind == "part":
                    inv = await self.inventory.inventory.get_for_update(ln.product_id, cd.from_warehouse_id)
                    avail = _available(inv) if inv is not None else Decimal("0")
                    if inv is None or avail < _d(ln.qty):
                        raise BusinessRuleError(
                            "Insufficient available stock to consign",
                            details={"product_id": str(ln.product_id), "available": str(avail), "requested": str(ln.qty)},
                        )
                    await self.inventory.reservations.reserve(
                        tenant_id=tenant_id, inv=inv, qty=_d(ln.qty), reference_id=ln.id,
                        reference_type=_LINE_REF, user_id=user_id,
                    )
                else:
                    unit = await self.repo.get_unit(ln.unit_id, lock=True)
                    unit.version += 1
                    self.repo.session.add(MotorcycleUnitEvent(
                        tenant_id=tenant_id, unit_id=unit.id, event_type="consigned",
                        reference_type="customer_delivery", reference_id=cd.id,
                        note=f"Out on consignment — {cd.delivery_number}", user_id=user_id,
                    ))
            cd.status = S.OUT_AT_RESELLER
        cd.dispatched_by = user_id
        cd.dispatched_at = _now()
        cd.received_by = received_by
        cd.received_at = _now()
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, cd.id, "delivered", {"status": cd.status})
        return await self._out(cd)

    # -------------------------------- settle --------------------------------- #
    async def settle(self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, delivery_id: uuid.UUID, payload: CustomerDeliverySettle) -> CustomerDeliveryOut:
        cd = await self._require(await self.repo.get(delivery_id, lock=True))
        if cd.delivery_mode != S.CONSIGNMENT or cd.status not in S.RECONCILABLE:
            raise BusinessRuleError("Only an open consignment can be settled.")
        part_map = {p.line_id: p for p in payload.part_lines}
        bike_map = {b.line_id: b for b in payload.bike_lines}

        for ln in cd.lines:
            done = _f(ln.settled_qty) + _f(ln.returned_qty)
            if done + 1e-9 >= _f(ln.qty):
                continue  # already reconciled
            if ln.line_kind == "part":
                p = part_map.get(ln.id)
                if p is None:
                    continue
                remaining = _f(ln.qty) - done
                settled = min(max(0.0, p.settled_qty), remaining)
                returned = min(max(0.0, p.returned_qty), remaining - settled)
                await self._reconcile_part(tenant_id, user_id, ln, cd.from_warehouse_id, _d(settled), _d(returned))
                ln.settled_qty = _d(_f(ln.settled_qty) + settled)
                ln.returned_qty = _d(_f(ln.returned_qty) + returned)
            else:
                b = bike_map.get(ln.id)
                if b is None:
                    continue
                unit = await self.repo.get_unit(ln.unit_id, lock=True)
                if b.outcome == "sold":
                    invoice = await self.repo.get_invoice(b.invoice_id) if b.invoice_id else None
                    if invoice is None:
                        raise BusinessRuleError(f"A sold consignment bike ({ln.chassis_number}) needs a sales invoice_id.")
                    unit.status = L.SOLD
                    unit.sold_ref = invoice.id
                    unit.customer_id = cd.customer_id
                    unit.version += 1
                    ln.settled_qty = Decimal("1")
                    ln.sold_invoice_id = invoice.id
                    self.repo.session.add(MotorcycleUnitEvent(
                        tenant_id=tenant_id, unit_id=unit.id, event_type="sold", to_status=L.SOLD,
                        reference_type="invoice", reference_id=invoice.id,
                        note=f"Consignment sold — {cd.delivery_number}", user_id=user_id,
                    ))
                else:  # returned unsold
                    unit.version += 1
                    ln.returned_qty = Decimal("1")
                    self.repo.session.add(MotorcycleUnitEvent(
                        tenant_id=tenant_id, unit_id=unit.id, event_type="returned",
                        reference_type="customer_delivery", reference_id=cd.id,
                        note=f"Consignment returned unsold — {cd.delivery_number}", user_id=user_id,
                    ))

        cd.status = S.reconcile_outcome([(_f(ln.qty), _f(ln.settled_qty), _f(ln.returned_qty)) for ln in cd.lines])
        if payload.remarks:
            cd.remarks = payload.remarks
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, cd.id, "settled", {"status": cd.status})
        return await self._out(cd)

    async def _reconcile_part(self, tenant_id, user_id, line, warehouse_id, settled: Decimal, returned: Decimal) -> None:
        """Sold portion -> a real deduction (issue from the hold); unsold portion ->
        release the hold back to available."""
        if settled > 0:
            await self.inventory.issue_against_reservation(
                tenant_id=tenant_id, user_id=user_id, product_id=line.product_id,
                warehouse_id=warehouse_id, quantity=settled, reference_type="consignment_sale",
                reference_id=line.id, reason=f"Consignment sale {line.id}",
                reservation_ref=line.id, reservation_ref_type=_LINE_REF, demand_source="sale",
            )
        if returned > 0:
            reservation = await self.inventory.reservations.active_for(line.id, _LINE_REF)
            if reservation is not None and reservation.qty > 0:
                inv = await self.inventory.inventory.get_for_update(line.product_id, warehouse_id)
                # Release only the returned portion (partial), keeping any remainder held.
                await self.inventory.reservations.consume(
                    tenant_id=tenant_id, inv=inv, reservation=reservation, qty=returned, user_id=user_id,
                )

    async def cancel(self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, delivery_id: uuid.UUID, reason: str | None) -> CustomerDeliveryOut:
        cd = await self._require(await self.repo.get(delivery_id, lock=True))
        if cd.status not in S.CANCELLABLE:
            raise BusinessRuleError(f"Only a draft delivery can be cancelled (status={cd.status}).")
        cd.status = S.CANCELLED
        if reason:
            cd.remarks = reason
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, cd.id, "cancelled", {"reason": reason})
        return await self._out(cd)

    # -------------------------------- reads ---------------------------------- #
    async def get(self, delivery_id: uuid.UUID) -> CustomerDeliveryOut:
        return await self._out(await self._require(await self.repo.get(delivery_id)))

    async def list_deliveries(self, **f) -> list[CustomerDeliveryOut]:
        return [await self._out(c) for c in await self.repo.list_deliveries(**f)]

    # ------------------------------- helpers --------------------------------- #
    @staticmethod
    async def _require(cd: CustomerDelivery | None) -> CustomerDelivery:
        if cd is None:
            raise NotFoundError("Customer delivery not found")
        return cd

    async def _audit(self, tenant_id, user_id, did, action, changes) -> None:
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action=f"customer_delivery.{action}",
            entity_type="customer_delivery", entity_id=did, changes=changes,
        )

    async def _out(self, cd: CustomerDelivery) -> CustomerDeliveryOut:
        branches = await self.repo.branch_names([cd.branch_id])
        warehouses = await self.repo.warehouse_names([cd.from_warehouse_id])
        customers = await self.repo.customer_names([cd.customer_id])
        prod = await self.repo.product_index([ln.product_id for ln in cd.lines])
        unit_models = await self.repo.unit_model_ids([ln.unit_id for ln in cd.lines])
        model_names = await self.repo.model_names(list(unit_models.values()))
        lines = []
        for ln in cd.lines:
            sku, name = prod.get(ln.product_id, (None, None))
            model_name = model_names.get(unit_models.get(ln.unit_id)) if ln.unit_id else None
            lines.append(CustomerDeliveryLineOut(
                id=ln.id, line_kind=ln.line_kind, product_id=ln.product_id, sku=sku, name=name,
                unit_id=ln.unit_id, chassis_number=ln.chassis_number, engine_number=ln.engine_number,
                model_name=model_name, qty=_f(ln.qty), settled_qty=_f(ln.settled_qty),
                returned_qty=_f(ln.returned_qty), sold_invoice_id=ln.sold_invoice_id, remarks=ln.remarks,
            ))
        return CustomerDeliveryOut(
            id=cd.id, delivery_number=cd.delivery_number, delivery_mode=cd.delivery_mode, status=cd.status,
            branch_id=cd.branch_id, branch_name=branches.get(cd.branch_id),
            from_warehouse_id=cd.from_warehouse_id, from_warehouse_name=warehouses.get(cd.from_warehouse_id),
            customer_id=cd.customer_id, customer_name=customers.get(cd.customer_id),
            invoice_id=cd.invoice_id, invoice_number=await self.repo.invoice_number(cd.invoice_id),
            remarks=cd.remarks, dispatched_at=cd.dispatched_at, received_by=cd.received_by,
            received_at=cd.received_at, created_at=cd.created_at, lines=lines,
        )
