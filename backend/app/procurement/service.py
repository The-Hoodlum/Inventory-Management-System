"""Application service for purchase-order management and goods receiving.

Orchestrates the pure domain (state machine + receiving math) with the data
layer, inventory updates, audit logging, and the lifecycle-event timeline. All
mutations run inside the request's single transaction (opened by ``get_db``),
so a receipt either fully applies — inventory, stock ledger, line balances, PO
status, audit, events — or rolls back together.
"""
from __future__ import annotations

import datetime as dt
import math
import uuid
from decimal import ROUND_HALF_UP, Decimal

from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.procurement.domain.exceptions import InvalidTransitionError, ReceiptError
from app.procurement.domain.receiving import LineState, apply_receipt
from app.procurement.domain.states import (
    POAction,
    POStatus,
    assert_transition,
    can_edit,
    target_status,
)
from app.procurement.email import EmailService
from app.procurement.pdf import build_purchase_order_pdf
from app.procurement.repository import ProcurementRepository
from app.procurement.schemas import (
    EmailPORequest,
    EmailResult,
    POCreate,
    POLineCreate,
    POLineOut,
    POOut,
    POUpdate,
    ReceiptResult,
    ReceiveRequest,
)

_QUANT = Decimal("0.0001")

# action -> (event label, audit action)
_ACTION_EVENT: dict[POAction, str] = {
    POAction.SUBMIT: "submitted",
    POAction.APPROVE: "approved",
    POAction.REJECT: "rejected",
    POAction.CANCEL: "cancelled",
    POAction.SEND: "sent",
}
_ACTION_AUDIT: dict[POAction, str] = {
    POAction.SUBMIT: "po.submitted",
    POAction.APPROVE: "po.approved",
    POAction.REJECT: "po.rejected",
    POAction.CANCEL: "po.cancelled",
    POAction.SEND: "po.sent",
}


class ProcurementService:
    def __init__(self, procurement_repo, inventory_repo, audit_repo, email_service=None, notifications=None) -> None:
        self.repo: ProcurementRepository = procurement_repo
        self.inventory = inventory_repo
        self.audit = audit_repo
        self.email: EmailService = email_service or EmailService.from_settings()
        self.notifications = notifications   # optional NotificationService; None -> no notifications

    # =============================== helpers =============================== #
    @staticmethod
    def _line_total(qty: Decimal, unit_cost: Decimal) -> Decimal:
        return (Decimal(qty) * Decimal(unit_cost)).quantize(_QUANT, rounding=ROUND_HALF_UP)

    @staticmethod
    def _cartons(line: POLineCreate) -> int | None:
        if line.ordered_cartons is not None:
            return line.ordered_cartons
        if line.units_per_carton:
            return int(math.ceil(Decimal(line.ordered_qty) / Decimal(line.units_per_carton)))
        return None

    async def _record_event(
        self, po, *, action: str, from_status, to_status, comment, actor, tenant, detail=None
    ) -> None:
        def _v(s):
            return s.value if isinstance(s, POStatus) else s

        await self.repo.add_event(
            tenant_id=tenant,
            po_id=po.id,
            action=action,
            from_status=_v(from_status),
            to_status=_v(to_status),
            comment=comment,
            detail=detail,
            actor_id=actor,
        )

    async def _audit(self, *, tenant, actor, action, entity_id, changes, ip) -> None:
        await self.audit.add(
            tenant_id=tenant,
            user_id=actor,
            action=action,
            entity_type="purchase_order",
            entity_id=entity_id,
            changes=changes,
            ip_address=ip,
        )

    def _po_out(self, po, lines) -> POOut:
        line_outs: list[POLineOut] = []
        for ln in lines:
            ordered = Decimal(ln.ordered_qty)
            received = Decimal(ln.received_qty or 0)
            line_outs.append(
                POLineOut(
                    id=ln.id,
                    product_id=ln.product_id,
                    ordered_qty=ordered,
                    ordered_cartons=ln.ordered_cartons,
                    unit_cost=Decimal(ln.unit_cost),
                    line_total=Decimal(ln.line_total),
                    received_qty=received,
                    remaining_qty=ordered - received,
                )
            )
        return POOut(
            id=po.id,
            po_number=po.po_number,
            supplier_id=po.supplier_id,
            warehouse_id=po.warehouse_id,
            status=po.status,
            currency=po.currency,
            fx_rate=Decimal(po.fx_rate),
            subtotal=Decimal(po.subtotal),
            tax=Decimal(po.tax),
            total=Decimal(po.total),
            notes=po.notes,
            order_date=po.created_at,
            expected_date=po.expected_date,
            created_by=po.created_by,
            approved_by=po.approved_by,
            approved_at=po.approved_at,
            version=po.version,
            created_at=po.created_at,
            updated_at=po.updated_at,
            lines=line_outs,
        )

    # =============================== create =============================== #
    async def create_po(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, data: POCreate, ip: str | None
    ) -> POOut:
        supplier = await self.repo.get_supplier(data.supplier_id)
        if supplier is None:
            raise NotFoundError("Supplier not found")
        warehouse = await self.repo.get_warehouse(data.warehouse_id)
        if warehouse is None:
            raise NotFoundError("Warehouse not found")

        currency = (data.currency or getattr(supplier, "currency", None) or "USD").upper()
        fx_rate = Decimal(data.fx_rate) if data.fx_rate is not None else Decimal(1)

        po_number = await self.repo.next_po_number(tenant_id)
        po = await self.repo.add_po(
            tenant_id=tenant_id,
            po_number=po_number,
            supplier_id=data.supplier_id,
            warehouse_id=data.warehouse_id,
            status=POStatus.DRAFT.value,
            currency=currency,
            fx_rate=fx_rate,
            subtotal=Decimal(0),
            tax=Decimal(0),
            total=Decimal(0),
            notes=data.notes,
            expected_date=data.expected_date,
            created_by=user_id,
        )

        subtotal = Decimal(0)
        line_models = []
        for ln in data.lines:
            line_total = self._line_total(ln.ordered_qty, ln.unit_cost)
            lm = await self.repo.add_line(
                tenant_id=tenant_id,
                po_id=po.id,
                product_id=ln.product_id,
                ordered_qty=Decimal(ln.ordered_qty),
                ordered_cartons=self._cartons(ln),
                unit_cost=Decimal(ln.unit_cost),
                line_total=line_total,
                received_qty=Decimal(0),
            )
            subtotal += line_total
            line_models.append(lm)

        po.subtotal = subtotal
        po.tax = Decimal(0)
        po.total = subtotal
        await self.repo.session.flush()

        await self._record_event(
            po, action="created", from_status=None, to_status=POStatus.DRAFT,
            comment=data.notes, actor=user_id, tenant=tenant_id,
            detail={"lines": len(line_models), "total": str(subtotal)},
        )
        await self._audit(
            tenant=tenant_id, actor=user_id, action="po.create", entity_id=po.id,
            changes={"po_number": po.po_number, "supplier_id": str(data.supplier_id),
                     "lines": len(line_models), "total": str(subtotal)}, ip=ip,
        )
        return self._po_out(po, line_models)

    # =============================== update =============================== #
    async def update_po(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, po_id: uuid.UUID,
        data: POUpdate, ip: str | None
    ) -> POOut:
        po = await self.repo.get_for_update(po_id)
        if po is None:
            raise NotFoundError("Purchase order not found")
        if not can_edit(po.status):
            raise BusinessRuleError(
                f"Only draft purchase orders can be edited (current status: {po.status})."
            )

        if data.currency is not None:
            po.currency = data.currency.upper()
        if data.fx_rate is not None:
            po.fx_rate = Decimal(data.fx_rate)
        if data.expected_date is not None:
            po.expected_date = data.expected_date
        if data.notes is not None:
            po.notes = data.notes

        if data.lines is not None:
            await self.repo.delete_lines(po.id)
            subtotal = Decimal(0)
            line_models = []
            for ln in data.lines:
                line_total = self._line_total(ln.ordered_qty, ln.unit_cost)
                lm = await self.repo.add_line(
                    tenant_id=tenant_id, po_id=po.id, product_id=ln.product_id,
                    ordered_qty=Decimal(ln.ordered_qty), ordered_cartons=self._cartons(ln),
                    unit_cost=Decimal(ln.unit_cost), line_total=line_total, received_qty=Decimal(0),
                )
                subtotal += line_total
                line_models.append(lm)
            po.subtotal = subtotal
            po.tax = Decimal(0)
            po.total = subtotal
        else:
            line_models = await self.repo.lines_for(po.id)

        po.version += 1
        await self.repo.session.flush()

        await self._record_event(
            po, action="updated", from_status=POStatus.DRAFT, to_status=POStatus.DRAFT,
            comment=None, actor=user_id, tenant=tenant_id,
            detail={"total": str(po.total)},
        )
        await self._audit(
            tenant=tenant_id, actor=user_id, action="po.update", entity_id=po.id,
            changes={"po_number": po.po_number, "total": str(po.total)}, ip=ip,
        )
        return self._po_out(po, line_models)

    # ========================== state transitions ========================= #
    async def _apply_action(
        self, *, po_id: uuid.UUID, action: POAction, comment: str | None,
        actor: uuid.UUID, tenant: uuid.UUID, ip: str | None
    ) -> POOut:
        po = await self.repo.get_for_update(po_id)
        if po is None:
            raise NotFoundError("Purchase order not found")

        from_status = po.status
        try:
            assert_transition(from_status, action)
        except InvalidTransitionError as exc:
            raise ConflictError(str(exc)) from exc

        target = target_status(from_status, action)
        po.status = target.value
        po.version += 1
        if action is POAction.APPROVE:
            po.approved_by = actor
            po.approved_at = dt.datetime.now(dt.UTC)
        await self.repo.session.flush()

        await self._record_event(
            po, action=_ACTION_EVENT[action], from_status=from_status, to_status=po.status,
            comment=comment, actor=actor, tenant=tenant, detail=None,
        )
        await self._audit(
            tenant=tenant, actor=actor, action=_ACTION_AUDIT[action], entity_id=po.id,
            changes={"po_number": po.po_number, "from": from_status, "to": po.status,
                     "comment": comment}, ip=ip,
        )
        # A PO that just entered the approval queue -> tell the approvers (po.approve).
        if po.status == POStatus.PENDING_APPROVAL.value and self.notifications is not None:
            from app.notifications import events as N_EVENTS
            await self.notifications.notify(
                tenant_id=tenant, event_type=N_EVENTS.PO_PENDING_APPROVAL, severity="info",
                title=f"Purchase order {po.po_number} awaits approval",
                href="/purchase-orders", entity_type="purchase_order", entity_id=po.id,
                actor_user_id=actor, permission="po.approve",
            )
        return self._po_out(po, await self.repo.lines_for(po.id))

    async def submit(self, **kw) -> POOut:
        return await self._apply_action(action=POAction.SUBMIT, **kw)

    async def approve(self, **kw) -> POOut:
        return await self._apply_action(action=POAction.APPROVE, **kw)

    async def reject(self, **kw) -> POOut:
        return await self._apply_action(action=POAction.REJECT, **kw)

    async def cancel(self, **kw) -> POOut:
        return await self._apply_action(action=POAction.CANCEL, **kw)

    async def send(self, **kw) -> POOut:
        return await self._apply_action(action=POAction.SEND, **kw)

    # ============================== receiving ============================= #
    async def receive(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, po_id: uuid.UUID,
        req: ReceiveRequest, ip: str | None
    ) -> ReceiptResult:
        po = await self.repo.get_for_update(po_id)
        if po is None:
            raise NotFoundError("Purchase order not found")

        try:
            assert_transition(po.status, POAction.RECEIVE)
        except InvalidTransitionError as exc:
            raise ConflictError(str(exc)) from exc

        lines = await self.repo.lines_for_update(po.id)
        lines_by_id = {ln.id: ln for ln in lines}
        line_states = [
            LineState(
                line_id=ln.id, product_id=ln.product_id,
                ordered_qty=Decimal(ln.ordered_qty), already_received=Decimal(ln.received_qty or 0),
            )
            for ln in lines
        ]
        receipt = {item.line_id: Decimal(item.quantity) for item in req.lines}

        try:
            outcome = apply_receipt(line_states, receipt)
        except ReceiptError as exc:
            raise BusinessRuleError(str(exc)) from exc

        movements = 0
        for lr in outcome.lines:
            line = lines_by_id[lr.line_id]
            inv = await self.inventory.get_for_update(line.product_id, po.warehouse_id)
            if inv is None:
                inv = await self.inventory.create(tenant_id, line.product_id, po.warehouse_id)
            inv.qty_on_hand = Decimal(inv.qty_on_hand or 0) + lr.received_now
            inv.version = (inv.version or 0) + 1
            await self.inventory.add_movement(
                tenant_id=tenant_id,
                product_id=line.product_id,
                warehouse_id=po.warehouse_id,
                movement_type="receipt",
                quantity=lr.received_now,
                reference_type="purchase_order",
                reference_id=po.id,
                unit_cost=Decimal(line.unit_cost),
                user_id=user_id,
                reason=f"PO {po.po_number} goods receipt",
            )
            line.received_qty = lr.new_received_total
            movements += 1

        from_status = po.status
        po.status = outcome.resulting_status.value
        po.version += 1
        await self.repo.session.flush()

        detail = {
            "received": [
                {"line_id": str(lr.line_id), "product_id": str(lr.product_id),
                 "qty": str(lr.received_now), "total": str(lr.new_received_total)}
                for lr in outcome.lines
            ],
            "total_now": str(outcome.total_received_now),
        }
        await self._record_event(
            po, action="received", from_status=from_status, to_status=po.status,
            comment=req.note, actor=user_id, tenant=tenant_id, detail=detail,
        )
        await self._audit(
            tenant=tenant_id, actor=user_id, action="goods.received", entity_id=po.id,
            changes={**detail, "status": po.status, "po_number": po.po_number}, ip=ip,
        )
        if outcome.fully_received:
            await self._record_event(
                po, action="closed", from_status=po.status, to_status=po.status,
                comment=None, actor=user_id, tenant=tenant_id, detail=None,
            )
            await self._audit(
                tenant=tenant_id, actor=user_id, action="po.closed", entity_id=po.id,
                changes={"po_number": po.po_number}, ip=ip,
            )

        line_models = await self.repo.lines_for(po.id)
        return ReceiptResult(
            purchase_order=self._po_out(po, line_models),
            received_now=outcome.total_received_now,
            fully_received=outcome.fully_received,
            movements_created=movements,
        )

    # ============================== queries =============================== #
    async def list_pos(self, **kw):
        return await self.repo.list(**kw)

    async def get_po(self, po_id: uuid.UUID) -> POOut:
        po = await self.repo.get(po_id)
        if po is None:
            raise NotFoundError("Purchase order not found")
        lines = await self.repo.lines_for(po.id)
        return self._po_out(po, lines)

    async def list_events(self, po_id: uuid.UUID):
        po = await self.repo.get(po_id)
        if po is None:
            raise NotFoundError("Purchase order not found")
        return await self.repo.events_for(po.id)

    # ============================ pdf & email ============================= #
    async def build_pdf(self, po_id: uuid.UUID) -> bytes:
        from app.core.config import settings

        po = await self.repo.get(po_id)
        if po is None:
            raise NotFoundError("Purchase order not found")
        supplier = await self.repo.get_supplier(po.supplier_id)
        lines = await self.repo.lines_for(po.id)

        line_dicts = []
        for ln in lines:
            product = await self.repo.get_product(ln.product_id)
            line_dicts.append(
                {
                    "sku": getattr(product, "sku", "") if product else "",
                    "name": getattr(product, "name", "") if product else "",
                    "ordered_qty": ln.ordered_qty,
                    "units_per_carton": getattr(product, "units_per_carton", None) if product else None,
                    "cartons": ln.ordered_cartons,
                    "unit_cost": ln.unit_cost,
                    "line_total": ln.line_total,
                }
            )

        # Same block every other document prints (address/email/phone + tax id), so a PO
        # can't drift from the rest of the paperwork.
        from app.core.pdf_branding import company_contact_lines

        _addr, _email, _phone, _tax = company_contact_lines()
        company = {
            "name": settings.company_name,
            "address": _addr,
            "email": _email,
            "phone": _phone,
            "tax": _tax,
        }
        supplier_d = {
            "name": getattr(supplier, "name", "") if supplier else "",
            "contact_person": getattr(supplier, "contact_person", None) if supplier else None,
            "email": getattr(supplier, "email", None) if supplier else None,
            "phone": getattr(supplier, "phone", None) if supplier else None,
            "country": getattr(supplier, "country", None) if supplier else None,
        }
        po_d = {
            "po_number": po.po_number,
            "status": po.status,
            "currency": po.currency,
            "order_date": po.created_at.date().isoformat() if po.created_at else "",
            "expected_date": po.expected_date.isoformat() if po.expected_date else None,
            "subtotal": po.subtotal,
            "tax": po.tax,
            "total": po.total,
            "notes": po.notes,
        }
        return build_purchase_order_pdf(
            company=company, supplier=supplier_d, po=po_d, lines=line_dicts, terms=settings.po_terms
        )

    async def email_po(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, po_id: uuid.UUID,
        req: EmailPORequest, ip: str | None
    ) -> EmailResult:
        po = await self.repo.get(po_id)
        if po is None:
            raise NotFoundError("Purchase order not found")
        supplier = await self.repo.get_supplier(po.supplier_id)
        supplier_email = getattr(supplier, "email", None) if supplier else None
        to = [str(req.to)] if req.to else ([supplier_email] if supplier_email else [])
        if not to:
            raise BusinessRuleError(
                "No recipient: the supplier has no email on file and none was provided."
            )

        pdf_bytes = await self.build_pdf(po_id)
        cc = [str(c) for c in req.cc]
        sent, detail = await self.email.send_purchase_order(
            to=to, po_number=po.po_number, pdf_bytes=pdf_bytes, cc=cc
        )

        await self._record_event(
            po, action="emailed", from_status=po.status, to_status=po.status,
            comment=detail, actor=user_id, tenant=tenant_id, detail={"to": to, "sent": sent},
        )
        await self._audit(
            tenant=tenant_id, actor=user_id, action="po.emailed", entity_id=po.id,
            changes={"po_number": po.po_number, "to": to, "sent": sent, "detail": detail}, ip=ip,
        )
        return EmailResult(sent=sent, detail=detail)
