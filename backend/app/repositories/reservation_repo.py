"""Inventory reservations: hold available stock at approval, consume it at issue,
release it on cancel/reject.

A reservation reduces a product's AVAILABLE quantity (``qty_reserved`` goes up)
WITHOUT moving ``qty_on_hand``, so the same units cannot be promised to two
demands. ``inventory.qty_available`` is a generated column
(``qty_on_hand - qty_reserved - qty_damaged``), so maintaining ``qty_reserved``
here keeps availability correct everywhere (transfers, POS, reports).

These primitives operate on an inventory row the CALLER has already locked
(``SELECT … FOR UPDATE``) so the caller controls lock ordering (e.g. a transfer
locks source + destination together). Every change appends a paired
``reserve`` / ``unreserve`` stock movement for a full audit trail.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Inventory, InventoryReservation, StockMovement

# Reservations are keyed to the demand LINE that raised them, so a partial issue can
# consume part of a line's hold and leave the rest reserved. The reference_type names
# the demand kind ('order_request_line' for transfers, 'sales_order_line' for sales).
REF_TYPE = "order_request_line"


class ReservationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def reserve(
        self, *, tenant_id: uuid.UUID, inv: Inventory, qty: Decimal,
        reference_id: uuid.UUID, user_id: uuid.UUID | None, reference_type: str = REF_TYPE,
    ) -> InventoryReservation:
        """Hold ``qty`` against an already-locked inventory row. The caller must have
        verified availability (``qty_available >= qty``) under the same lock."""
        inv.qty_reserved = (inv.qty_reserved or Decimal("0")) + qty
        inv.version = (inv.version or 0) + 1
        reservation = InventoryReservation(
            tenant_id=tenant_id, product_id=inv.product_id, warehouse_id=inv.warehouse_id,
            qty=qty, status="active", reference_type=reference_type, reference_id=reference_id,
            created_by=user_id,
        )
        self.session.add(reservation)
        self.session.add(StockMovement(
            tenant_id=tenant_id, product_id=inv.product_id, warehouse_id=inv.warehouse_id,
            movement_type="reserve", quantity=-qty, reference_type=reference_type,
            reference_id=reference_id, reason="Stock reserved", user_id=user_id,
        ))
        await self.session.flush()
        return reservation

    async def active_for(
        self, reference_id: uuid.UUID, reference_type: str = REF_TYPE
    ) -> InventoryReservation | None:
        return await self.session.scalar(
            select(InventoryReservation).where(
                InventoryReservation.reference_type == reference_type,
                InventoryReservation.reference_id == reference_id,
                InventoryReservation.status == "active",
            ).with_for_update()
        )

    async def consume(
        self, *, tenant_id: uuid.UUID, inv: Inventory, reservation: InventoryReservation,
        qty: Decimal, user_id: uuid.UUID | None,
    ) -> None:
        """Release ``qty`` of an active hold because the stock is being issued. The
        physical ``qty_on_hand`` deduction is done by the caller; here we only drop the
        hold (``qty_reserved``) so availability nets out. Partial consumption leaves the
        remainder reserved for the line's outstanding quantity."""
        take = min(qty, reservation.qty)
        if take <= 0:
            return
        inv.qty_reserved = max(Decimal("0"), (inv.qty_reserved or Decimal("0")) - take)
        inv.version = (inv.version or 0) + 1
        reservation.qty = reservation.qty - take
        if reservation.qty <= 0:
            reservation.status = "consumed"
            reservation.released_at = dt.datetime.now(dt.UTC)
        self.session.add(StockMovement(
            tenant_id=tenant_id, product_id=inv.product_id, warehouse_id=inv.warehouse_id,
            movement_type="unreserve", quantity=take, reference_type="order_request",
            reference_id=reservation.reference_id, reason="Reservation consumed on issue",
            user_id=user_id,
        ))
        await self.session.flush()

    async def release(
        self, *, tenant_id: uuid.UUID, inv: Inventory, reservation: InventoryReservation,
        user_id: uuid.UUID | None,
    ) -> None:
        """Return a held quantity to AVAILABLE (cancel / reject). ``qty_on_hand`` is
        untouched — the stock never left."""
        qty = reservation.qty
        if qty <= 0:
            reservation.status = "released"
            reservation.released_at = dt.datetime.now(dt.UTC)
            return
        inv.qty_reserved = max(Decimal("0"), (inv.qty_reserved or Decimal("0")) - qty)
        inv.version = (inv.version or 0) + 1
        reservation.qty = Decimal("0")
        reservation.status = "released"
        reservation.released_at = dt.datetime.now(dt.UTC)
        self.session.add(StockMovement(
            tenant_id=tenant_id, product_id=inv.product_id, warehouse_id=inv.warehouse_id,
            movement_type="unreserve", quantity=qty, reference_type="order_request",
            reference_id=reservation.reference_id, reason="Reservation released",
            user_id=user_id,
        ))
        await self.session.flush()
