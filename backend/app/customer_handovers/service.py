"""Customer Handover orchestration.

A handover is created against an existing invoice + serialized unit; the customer,
motorcycle, branch, salesperson and invoice amounts are pulled FROM those records (never
re-typed) and the customer block is SNAPSHOT so later edits to the customer master don't
change the signed document. It writes NO stock. Completing it:

  * validates the record is signable (payment settled, QC + manager signed, customer
    signed, delivery dated — see domain.status.completion_errors);
  * marks the unit an INDEPENDENT 'delivered' fact (delivered + delivered_at) and stamps
    warranty_start — WITHOUT touching the terminal 'sold' sale status;
  * writes a 'delivered' row to the unit's immutable event ledger;
  * locks the handover (DRAFT -> COMPLETED).
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from app.core.exceptions import BusinessRuleError, NotFoundError, PermissionDeniedError
from app.customer_handovers.domain import status as S
from app.customer_handovers.repository import CustomerHandoverRepository
from app.customer_handovers.schemas import (
    APPROVAL_ROLES,
    ApprovalOut,
    HandoverComplete,
    HandoverCreate,
    HandoverLookupOut,
    HandoverOut,
    HandoverUpdate,
)
from app.models import CustomerHandover, MotorcycleUnitEvent
from app.motorcycles.domain import lifecycle as L
from app.repositories.audit_repo import AuditRepository


def _d(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal("0")


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _today() -> dt.date:
    return _now().date()


class CustomerHandoverService:
    def __init__(self, repo: CustomerHandoverRepository, audit: AuditRepository) -> None:
        self.repo = repo
        self.audit = audit

    # ------------------------------- create ---------------------------------- #
    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        payload: HandoverCreate,
        allowed_branch_ids: frozenset[uuid.UUID] | None = None,
    ) -> HandoverOut:
        unit = await self.repo.get_unit(payload.unit_id)
        if unit is None:
            raise NotFoundError("Motorcycle unit not found")

        # The bike must be SOLD (the unit's sale status) — that, not an invoice link, is
        # what "ready to hand over" means. Bulk-imported historical sales are sold but carry
        # no invoice, so we do NOT require ``sold_ref``.
        if unit.status != L.SOLD:
            raise BusinessRuleError(
                f"Bike {unit.chassis_number} is {unit.status} and hasn't been sold yet — nothing to hand over."
            )

        # Resolve the source invoice: an explicit one, else the unit's linked invoice
        # (absent for historically-imported sales — that is allowed).
        invoice = None
        invoice_id = payload.invoice_id or unit.sold_ref
        if invoice_id is not None:
            invoice = await self.repo.get_invoice(invoice_id)
            if invoice is None:
                raise NotFoundError("Invoice not found")
            if unit.sold_ref is not None and unit.sold_ref != invoice.id:
                raise BusinessRuleError(f"Bike {unit.chassis_number} is not linked to invoice {invoice.invoice_number}.")

        # Branch isolation — both the unit's branch and the invoice's branch must be in scope.
        self._assert_branch(allowed_branch_ids, unit.branch_id, invoice.branch_id if invoice else None)

        # One handover per unit (friendly error before the DB unique constraint).
        if await self.repo.unit_handover(tenant_id, unit.id) is not None:
            raise BusinessRuleError(f"Bike {unit.chassis_number} already has a handover record.")

        customer_id = unit.customer_id or (invoice.customer_id if invoice else None)
        customer = await self.repo.get_customer(customer_id) if customer_id else None
        address = await self.repo.default_address(customer_id) if customer_id else None
        salesperson_id = payload.salesperson_id or (await self.repo.order_salesperson(invoice) if invoice else None)

        # Amounts come from the invoice when there is one; otherwise from the unit's own
        # sale price (a historical sale is treated as already settled — the user can adjust).
        if invoice is not None:
            invoice_amount = _d(invoice.grand_total_zmw)
            amount_paid = _d(invoice.amount_paid)
        else:
            invoice_amount = _d(unit.price_charged)
            amount_paid = _d(unit.price_charged)

        h = CustomerHandover(
            tenant_id=tenant_id,
            handover_no=await self.repo.number(tenant_id),
            status=S.DRAFT,
            invoice_id=invoice.id if invoice else None,
            sales_order_id=invoice.sales_order_id if invoice else None,
            unit_id=unit.id,
            branch_id=unit.branch_id or (invoice.branch_id if invoice else None),
            salesperson_id=salesperson_id,
            delivery_date=_today(),
            # Customer snapshot (frozen now).
            full_name=(customer.name if customer else None),
            nrc_passport_no=(customer.tax_number if customer else None),
            phone=(customer.phone if customer else None),
            whatsapp=(customer.phone if customer else None),
            email=(customer.email if customer else None),
            physical_address=self._format_address(address),
            # Payment reference (overridable).
            payment_method="Cash",
            invoice_amount_zmw=invoice_amount,
            amount_paid_zmw=amount_paid,
            balance_zmw=invoice_amount - amount_paid,
            salesperson_name=await self.repo.user_display(salesperson_id),
            created_by=user_id,
        )
        # Apply any initial values the caller supplied ON TOP of the autofill.
        self._apply_edits(h, payload)

        self.repo.session.add(h)
        await self.repo.session.flush()
        await self._audit(
            tenant_id, user_id, h.id, "created",
            {"unit_id": str(unit.id), "invoice": invoice.invoice_number if invoice else None},
        )
        return await self._out(h)

    # ------------------------------- update ---------------------------------- #
    async def update(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        handover_id: uuid.UUID,
        payload: HandoverUpdate,
        allowed_branch_ids: frozenset[uuid.UUID] | None = None,
    ) -> HandoverOut:
        h = await self._require(await self.repo.get(handover_id, lock=True))
        self._assert_branch(allowed_branch_ids, h.branch_id)
        if h.status == S.COMPLETED:
            raise BusinessRuleError("This handover is completed and can no longer be edited.")
        self._apply_edits(h, payload)
        if payload.salesperson_id is not None:
            h.salesperson_name = await self.repo.user_display(payload.salesperson_id) or h.salesperson_name
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, h.id, "updated", None)
        return await self._out(h)

    # ------------------------------ complete --------------------------------- #
    async def complete(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        handover_id: uuid.UUID,
        payload: HandoverComplete | None = None,
        allowed_branch_ids: frozenset[uuid.UUID] | None = None,
    ) -> HandoverOut:
        h = await self._require(await self.repo.get(handover_id, lock=True))
        self._assert_branch(allowed_branch_ids, h.branch_id)
        if h.status == S.COMPLETED:
            raise BusinessRuleError("This handover is already completed.")

        if payload is not None and payload.fields is not None:
            self._apply_edits(h, payload.fields)

        errors = S.completion_errors(h)
        if errors:
            raise BusinessRuleError(
                "This handover isn't ready to complete.",
                details={"reasons": errors},
            )

        # Lock the unit before mutating its lifecycle (parity with the stock-mutation rule).
        unit = await self.repo.get_unit(h.unit_id, lock=True)
        if unit is None:
            raise NotFoundError("Motorcycle unit not found")

        if h.warranty_start_date is None:
            h.warranty_start_date = h.delivery_date or _today()

        h.status = S.COMPLETED
        h.completed_at = _now()
        h.completed_by = user_id

        # INDEPENDENT delivered fact — the terminal 'sold' sale status is unchanged.
        unit.delivered = True
        unit.delivered_at = _now()
        if unit.warranty_start is None:
            unit.warranty_start = h.warranty_start_date
        unit.version = (unit.version or 0) + 1

        self.repo.session.add(
            MotorcycleUnitEvent(
                tenant_id=tenant_id,
                unit_id=unit.id,
                event_type="delivered",
                from_status=unit.status,
                to_status=unit.status,   # sale status intentionally unchanged (SOLD is terminal)
                reference_type="customer_handover",
                reference_id=h.id,
                note=f"Customer handover completed — {h.handover_no}",
                user_id=user_id,
            )
        )
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, h.id, "completed", {"unit_id": str(unit.id)})
        return await self._out(h)

    # -------------------------------- reads ---------------------------------- #
    async def get(
        self, handover_id: uuid.UUID, *, allowed_branch_ids: frozenset[uuid.UUID] | None = None
    ) -> HandoverOut:
        h = await self._require(await self.repo.get(handover_id))
        self._assert_branch(allowed_branch_ids, h.branch_id)
        return await self._out(h)

    async def list_handovers(self, **f) -> list[HandoverOut]:
        return [await self._out(h) for h in await self.repo.list_handovers(**f)]

    async def lookup_by_chassis(
        self, *, tenant_id: uuid.UUID, chassis: str, allowed_branch_ids: frozenset[uuid.UUID] | None = None
    ) -> HandoverLookupOut:
        """Resolve a chassis/VIN to the auto-fill preview for the New Handover form."""
        unit = await self.repo.find_sold_unit_by_chassis(tenant_id, chassis.strip())
        if unit is None:
            raise NotFoundError(f"No motorcycle found with chassis '{chassis}'.")
        self._assert_branch(allowed_branch_ids, unit.branch_id)
        if unit.status != L.SOLD:
            raise BusinessRuleError(
                f"Bike {unit.chassis_number} is {unit.status} and hasn't been sold yet — nothing to hand over."
            )

        # The invoice is optional — historically-imported sales have none.
        invoice = await self.repo.get_invoice(unit.sold_ref) if unit.sold_ref else None
        ctx = await self.repo.unit_context(unit.id)
        customer_id = unit.customer_id or (invoice.customer_id if invoice else None)
        customer = await self.repo.get_customer(customer_id) if customer_id else None
        existing = await self.repo.unit_handover(tenant_id, unit.id)
        salesperson_id = await self.repo.order_salesperson(invoice) if invoice else None

        # Amounts from the invoice when present, else the unit's own sale price.
        if invoice is not None:
            invoice_amount = _d(invoice.grand_total_zmw)
            amount_paid = _d(invoice.amount_paid)
        else:
            invoice_amount = _d(unit.price_charged)
            amount_paid = _d(unit.price_charged)
        return HandoverLookupOut(
            unit_id=unit.id,
            invoice_id=invoice.id if invoice else None,
            invoice_number=(invoice.invoice_number if invoice else None),
            chassis_number=ctx.get("chassis_number"),
            engine_number=ctx.get("engine_number"),
            model_name=ctx.get("model_name"),
            colour_name=ctx.get("colour_name"),
            customer_id=customer_id,
            customer_name=(customer.name if customer else None),
            phone=(customer.phone if customer else None),
            email=(customer.email if customer else None),
            branch_id=unit.branch_id or (invoice.branch_id if invoice else None),
            branch_name=await self.repo.branch_name(unit.branch_id or (invoice.branch_id if invoice else None)),
            salesperson_display=await self.repo.user_display(salesperson_id),
            invoice_amount_zmw=invoice_amount,
            amount_paid_zmw=amount_paid,
            balance_zmw=invoice_amount - amount_paid,
            existing_handover_id=existing.id if existing else None,
        )

    # ------------------------------- helpers --------------------------------- #
    @staticmethod
    def _assert_branch(allowed: frozenset[uuid.UUID] | None, *branch_ids: uuid.UUID | None) -> None:
        if allowed is None:
            return
        for b in branch_ids:
            if b is not None and b not in allowed:
                raise PermissionDeniedError("You are not assigned to that branch.")

    @staticmethod
    def _format_address(address) -> str | None:
        if address is None:
            return None
        parts = [address.line1, address.line2, address.city, address.region, address.country]
        joined = ", ".join(p for p in parts if p)
        return joined or None

    def _apply_edits(self, h: CustomerHandover, payload) -> None:
        """Apply only the fields the caller actually set, then reconcile derived columns
        (signature timestamps + payment balance)."""
        data = payload.model_dump(exclude_unset=True)
        # These are set on create/read paths, never patched directly here.
        data.pop("invoice_id", None)
        data.pop("unit_id", None)
        for key, value in data.items():
            setattr(h, key, value)

        # Recompute balance when either side of it changed and it wasn't set explicitly.
        if ("amount_paid_zmw" in data or "invoice_amount_zmw" in data) and "balance_zmw" not in data:
            h.balance_zmw = _d(h.invoice_amount_zmw) - _d(h.amount_paid_zmw)

        self._reconcile_signatures(h)

    @staticmethod
    def _reconcile_signatures(h: CustomerHandover) -> None:
        now = _now()
        # Approval grid: signed -> stamp time once; un-signed -> clear.
        for role in APPROVAL_ROLES:
            signed = getattr(h, f"{role}_signed")
            at_field = f"{role}_signed_at"
            if signed and getattr(h, at_field) is None:
                setattr(h, at_field, now)
            elif not signed and getattr(h, at_field) is not None:
                setattr(h, at_field, None)
        # Customer signature time tracks the captured name (the salesperson's time is the
        # approval-grid salesperson_signed_at).
        name = (h.customer_signature_name or "").strip()
        if name and h.customer_signed_at is None:
            h.customer_signed_at = now
        elif not name and h.customer_signed_at is not None:
            h.customer_signed_at = None

    @staticmethod
    async def _require(h: CustomerHandover | None) -> CustomerHandover:
        if h is None:
            raise NotFoundError("Handover not found")
        return h

    async def _audit(self, tenant_id, user_id, hid, action, changes) -> None:
        await self.audit.add(
            tenant_id=tenant_id,
            user_id=user_id,
            action=f"customer_handover.{action}",
            entity_type="customer_handover",
            entity_id=hid,
            changes=changes,
        )

    async def _out(self, h: CustomerHandover) -> HandoverOut:
        ctx = await self.repo.unit_context(h.unit_id)
        out = HandoverOut.model_validate(h)
        out.chassis_number = ctx.get("chassis_number")
        out.engine_number = ctx.get("engine_number")
        out.model_name = ctx.get("model_name")
        out.colour_name = ctx.get("colour_name")
        out.branch_name = await self.repo.branch_name(h.branch_id)
        out.salesperson_display = h.salesperson_name or await self.repo.user_display(h.salesperson_id)
        out.invoice_number = await self.repo.invoice_number(h.invoice_id)
        out.approvals = [
            ApprovalOut(
                role=role,
                name=getattr(h, f"{role}_name"),
                signed=getattr(h, f"{role}_signed"),
                signed_at=getattr(h, f"{role}_signed_at"),
            )
            for role in APPROVAL_ROLES
        ]
        return out
