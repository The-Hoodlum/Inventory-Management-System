"""Inventory service.

Every operation runs inside the request transaction (opened by the API layer),
acquires row-level locks on the affected inventory rows, updates the running
balance, writes one or more rows to the append-only ``stock_movements`` ledger,
and records an ``audit_logs`` entry. Available stock is computed locally
(on_hand - reserved - damaged) rather than read from the DB-generated column, so
the logic is unit-testable without a database.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from app.core.exceptions import BusinessRuleError, NotFoundError
from app.models import Inventory, StockMovement
from app.repositories.audit_repo import AuditRepository
from app.repositories.inventory_repo import InventoryRepository
from app.repositories.product_repo import ProductRepository
from app.repositories.reservation_repo import ReservationRepository
from app.repositories.warehouse_repo import WarehouseRepository
from app.schemas.inventory import (
    AdjustStockRequest,
    IssueStockRequest,
    ReceiveStockRequest,
    TransferStockRequest,
)


def _available(inv: Inventory) -> Decimal:
    return inv.qty_on_hand - inv.qty_reserved - inv.qty_damaged


class InventoryService:
    def __init__(
        self,
        inventory: InventoryRepository,
        products: ProductRepository,
        warehouses: WarehouseRepository,
        audit: AuditRepository,
        reservations: ReservationRepository | None = None,
    ) -> None:
        self.inventory = inventory
        self.products = products
        self.warehouses = warehouses
        self.audit = audit
        # Optional: only required for reservation-aware issues (sales delivery / POS).
        self.reservations = reservations

    # ----------------------------- helpers ----------------------------- #
    async def _require_product(self, product_id: uuid.UUID) -> None:
        if await self.products.get(product_id) is None:
            raise NotFoundError(f"Product {product_id} not found")

    async def _require_warehouse(self, warehouse_id: uuid.UUID) -> None:
        if await self.warehouses.get(warehouse_id) is None:
            raise NotFoundError(f"Warehouse {warehouse_id} not found")

    async def _get_or_create_locked(
        self, tenant_id: uuid.UUID, product_id: uuid.UUID, warehouse_id: uuid.UUID
    ) -> Inventory:
        inv = await self.inventory.get_for_update(product_id, warehouse_id)
        if inv is None:
            inv = await self.inventory.create(tenant_id, product_id, warehouse_id)
        return inv

    async def _audit_movement(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        action: str,
        inv: Inventory,
        movement: StockMovement,
        before_on_hand: Decimal,
        extra: dict[str, Any] | None = None,
    ) -> None:
        changes: dict[str, Any] = {
            "product_id": str(inv.product_id),
            "warehouse_id": str(inv.warehouse_id),
            "movement_type": movement.movement_type,
            "quantity": str(movement.quantity),
            "on_hand_before": str(before_on_hand),
            "on_hand_after": str(inv.qty_on_hand),
            "movement_id": str(movement.id),
        }
        if extra:
            changes.update(extra)
        await self.audit.add(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            entity_type="inventory",
            entity_id=inv.id,
            changes=changes,
            ip_address=extra.get("ip") if extra else None,
        )

    # ----------------------------- receive ----------------------------- #
    async def receive(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        req: ReceiveStockRequest,
        ip: str | None = None,
    ) -> list[Inventory]:
        await self._require_warehouse(req.warehouse_id)
        affected: list[Inventory] = []
        for line in req.lines:
            await self._require_product(line.product_id)
            inv = await self._get_or_create_locked(tenant_id, line.product_id, req.warehouse_id)
            before = inv.qty_on_hand
            inv.qty_on_hand = before + line.quantity
            inv.version += 1
            movement = await self.inventory.add_movement(
                tenant_id=tenant_id,
                product_id=line.product_id,
                warehouse_id=req.warehouse_id,
                movement_type="receipt",
                quantity=line.quantity,
                reference_type=req.reference_type,
                reference_id=req.reference_id,
                unit_cost=line.unit_cost,
                user_id=user_id,
            )
            await self._audit_movement(
                tenant_id=tenant_id,
                user_id=user_id,
                action="stock.receive",
                inv=inv,
                movement=movement,
                before_on_hand=before,
                extra={"reference_type": req.reference_type, "ip": ip},
            )
            affected.append(inv)
        return affected

    # ------------------------------ issue ------------------------------ #
    async def issue(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        req: IssueStockRequest,
        ip: str | None = None,
    ) -> list[Inventory]:
        await self._require_warehouse(req.warehouse_id)
        affected: list[Inventory] = []
        for line in req.lines:
            await self._require_product(line.product_id)
            inv = await self.inventory.get_for_update(line.product_id, req.warehouse_id)
            avail = _available(inv) if inv is not None else Decimal("0")
            if inv is None or avail < line.quantity:
                raise BusinessRuleError(
                    "Insufficient available stock to issue",
                    details={
                        "product_id": str(line.product_id),
                        "warehouse_id": str(req.warehouse_id),
                        "available": str(avail),
                        "requested": str(line.quantity),
                    },
                )
            before = inv.qty_on_hand
            inv.qty_on_hand = before - line.quantity
            inv.version += 1
            movement = await self.inventory.add_movement(
                tenant_id=tenant_id,
                product_id=line.product_id,
                warehouse_id=req.warehouse_id,
                movement_type="issue",
                quantity=-line.quantity,
                reference_type=req.reference_type,
                reference_id=req.reference_id,
                reason=req.reason,
                user_id=user_id,
            )
            await self._audit_movement(
                tenant_id=tenant_id,
                user_id=user_id,
                action="stock.issue",
                inv=inv,
                movement=movement,
                before_on_hand=before,
                extra={"reason": req.reason, "ip": ip},
            )
            affected.append(inv)
        return affected

    # ------------------- issue against a reservation ------------------- #
    async def issue_against_reservation(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        product_id: uuid.UUID,
        warehouse_id: uuid.UUID,
        quantity: Decimal,
        reference_type: str,
        reference_id: uuid.UUID,
        reason: str,
        reservation_ref: uuid.UUID | None = None,
        reservation_ref_type: str | None = None,
        demand_source: str | None = None,
        ip: str | None = None,
    ) -> Inventory:
        """Issue stock for a demand line, drawing on the line's OWN reservation first.

        This is the reservation-aware sibling of :meth:`issue`, and the single path a
        sales delivery or POS sale uses to move stock. It honours OTHER demands' holds
        (``available = on_hand - reserved - damaged``) while letting this line also use
        its own held units (``reservation_ref`` / ``reservation_ref_type``). POS passes
        no reservation and must fit within free availability.

        Like every mutation here it locks the row, decrements ``qty_on_hand`` exactly
        once, writes one ``issue`` movement to the ledger, records an inventory
        ``audit_logs`` entry, and — when ``demand_source`` is set — feeds ``sales_daily``
        so the forecast/reorder engines see the consumption. Raises
        :class:`BusinessRuleError` (rolling back the caller's transaction) on shortfall.
        """
        if quantity <= 0:
            raise BusinessRuleError("Issue quantity must be positive")

        inv = await self.inventory.get_for_update(product_id, warehouse_id)
        reservation = None
        if reservation_ref is not None and self.reservations is not None:
            reservation = (
                await self.reservations.active_for(reservation_ref, reservation_ref_type)
                if reservation_ref_type is not None
                else await self.reservations.active_for(reservation_ref)
            )
        own_hold = reservation.qty if reservation is not None else Decimal("0")
        on_hand = inv.qty_on_hand if inv is not None else Decimal("0")
        available = _available(inv) if inv is not None else Decimal("0")
        # The line may consume its own hold plus the free pool, never more than on-hand.
        if inv is None or on_hand < quantity or (available + own_hold) < quantity:
            raise BusinessRuleError(
                "Insufficient available stock to issue",
                details={
                    "product_id": str(product_id),
                    "warehouse_id": str(warehouse_id),
                    "available": str(available + own_hold),
                    "on_hand": str(on_hand),
                    "requested": str(quantity),
                },
            )
        if reservation is not None:
            await self.reservations.consume(
                tenant_id=tenant_id, inv=inv, reservation=reservation,
                qty=quantity, user_id=user_id,
            )
        before = inv.qty_on_hand
        inv.qty_on_hand = before - quantity
        inv.version += 1
        movement = await self.inventory.add_movement(
            tenant_id=tenant_id,
            product_id=product_id,
            warehouse_id=warehouse_id,
            movement_type="issue",
            quantity=-quantity,
            reference_type=reference_type,
            reference_id=reference_id,
            reason=reason,
            user_id=user_id,
        )
        extra: dict[str, Any] = {"reason": reason, "reference_type": reference_type, "ip": ip}
        if demand_source is not None:
            extra["demand_source"] = demand_source
        await self._audit_movement(
            tenant_id=tenant_id,
            user_id=user_id,
            action="stock.issue",
            inv=inv,
            movement=movement,
            before_on_hand=before,
            extra=extra,
        )
        if demand_source is not None:
            await self.inventory.record_demand(
                tenant_id=tenant_id, product_id=product_id, warehouse_id=warehouse_id,
                qty=quantity, source=demand_source,
            )
        return inv

    # ------------------------------ adjust ----------------------------- #
    async def adjust(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        req: AdjustStockRequest,
        ip: str | None = None,
    ) -> Inventory:
        await self._require_warehouse(req.warehouse_id)
        await self._require_product(req.product_id)
        inv = await self._get_or_create_locked(tenant_id, req.product_id, req.warehouse_id)
        before = inv.qty_on_hand
        new_on_hand = before + req.delta
        if new_on_hand < 0:
            raise BusinessRuleError(
                "Adjustment would drive on-hand quantity below zero",
                details={"on_hand": str(before), "delta": str(req.delta)},
            )
        inv.qty_on_hand = new_on_hand
        inv.version += 1
        movement = await self.inventory.add_movement(
            tenant_id=tenant_id,
            product_id=req.product_id,
            warehouse_id=req.warehouse_id,
            movement_type="adjustment",
            quantity=req.delta,
            reference_type="manual",
            reason=req.reason,
            user_id=user_id,
        )
        await self._audit_movement(
            tenant_id=tenant_id,
            user_id=user_id,
            action="stock.adjust",
            inv=inv,
            movement=movement,
            before_on_hand=before,
            extra={"reason": req.reason, "ip": ip},
        )
        return inv

    # ----------------------------- transfer ---------------------------- #
    async def transfer(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        req: TransferStockRequest,
        ip: str | None = None,
    ) -> list[Inventory]:
        if req.from_warehouse_id == req.to_warehouse_id:
            raise BusinessRuleError("Source and destination warehouses must differ")
        await self._require_product(req.product_id)
        await self._require_warehouse(req.from_warehouse_id)
        await self._require_warehouse(req.to_warehouse_id)

        # Lock both rows in a deterministic order (by warehouse id) to avoid deadlocks.
        order = sorted(
            [req.from_warehouse_id, req.to_warehouse_id], key=lambda w: str(w)
        )
        locked: dict[uuid.UUID, Inventory] = {
            wid: await self._get_or_create_locked(tenant_id, req.product_id, wid)
            for wid in order
        }
        src = locked[req.from_warehouse_id]
        dst = locked[req.to_warehouse_id]

        avail = _available(src)
        if avail < req.quantity:
            raise BusinessRuleError(
                "Insufficient available stock to transfer",
                details={
                    "product_id": str(req.product_id),
                    "from_warehouse_id": str(req.from_warehouse_id),
                    "available": str(avail),
                    "requested": str(req.quantity),
                },
            )

        src_before = src.qty_on_hand
        dst_before = dst.qty_on_hand
        src.qty_on_hand = src_before - req.quantity
        dst.qty_on_hand = dst_before + req.quantity
        src.version += 1
        dst.version += 1

        out_mv = await self.inventory.add_movement(
            tenant_id=tenant_id,
            product_id=req.product_id,
            warehouse_id=req.from_warehouse_id,
            movement_type="transfer_out",
            quantity=-req.quantity,
            reference_type="transfer",
            from_warehouse_id=req.from_warehouse_id,
            to_warehouse_id=req.to_warehouse_id,
            reason=req.reason,
            user_id=user_id,
        )
        in_mv = await self.inventory.add_movement(
            tenant_id=tenant_id,
            product_id=req.product_id,
            warehouse_id=req.to_warehouse_id,
            movement_type="transfer_in",
            quantity=req.quantity,
            reference_type="transfer",
            from_warehouse_id=req.from_warehouse_id,
            to_warehouse_id=req.to_warehouse_id,
            reason=req.reason,
            user_id=user_id,
        )
        await self._audit_movement(
            tenant_id=tenant_id,
            user_id=user_id,
            action="stock.transfer",
            inv=src,
            movement=out_mv,
            before_on_hand=src_before,
            extra={
                "to_warehouse_id": str(req.to_warehouse_id),
                "reason": req.reason,
                "ip": ip,
            },
        )
        await self._audit_movement(
            tenant_id=tenant_id,
            user_id=user_id,
            action="stock.transfer",
            inv=dst,
            movement=in_mv,
            before_on_hand=dst_before,
            extra={
                "from_warehouse_id": str(req.from_warehouse_id),
                "reason": req.reason,
                "ip": ip,
            },
        )
        return [src, dst]

    # ------------------------------ reads ------------------------------ #
    async def list_inventory(self, **kwargs) -> tuple[list[Inventory], int]:
        return await self.inventory.list_inventory(**kwargs)

    async def list_movements(self, **kwargs) -> tuple[list[StockMovement], int]:
        return await self.inventory.list_movements(**kwargs)
