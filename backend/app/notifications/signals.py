"""Computed operational signals — the DERIVED half of the bell.

These are recomputed on demand from existing data (low stock, pending approvals) and
gated per read-permission, so a user only sees what they can act on. They carry NO read
state (there is nothing to store — they reflect current reality). The notifications bell
shows these alongside the stored, event-driven notifications.

Extracted here so both the notifications endpoint and the legacy /assistant/notifications
endpoint build them from ONE place (they were duplicated before).
"""
from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.repository import AssistantRepository
from app.core.permissions import P


class OperationalSignal(BaseModel):
    kind: str
    severity: str  # 'info' | 'warning' | 'critical'
    title: str
    detail: str | None = None
    count: int
    href: str  # frontend route the bell links to


async def operational_signals(session: AsyncSession, permissions: set[str]) -> list[OperationalSignal]:
    """Current operational alerts for the given user's permissions, via the RLS-scoped
    assistant repository. Each source is gated by the relevant read permission."""
    repo = AssistantRepository(session)
    warehouse_ids = await repo.all_warehouse_ids()
    items: list[OperationalSignal] = []

    if permissions & {P.INVENTORY_READ, P.REORDER_READ}:
        low = await repo.low_stock(warehouse_ids)
        if low["count"]:
            preview = ", ".join(f"{i['name']} ({i['branch']})" for i in low["items"][:3])
            items.append(OperationalSignal(
                kind="low_stock", severity="warning",
                title=f"{low['count']} item(s) at or below reorder point",
                detail=preview or None, count=low["count"], href="/reorder",
            ))

    if permissions & {P.PO_READ, P.PO_APPROVE}:
        pending_po = await repo.pending_purchase_requests(warehouse_ids)
        if pending_po["count"]:
            items.append(OperationalSignal(
                kind="pending_purchase_request", severity="info",
                title=f"{pending_po['count']} purchase request(s) awaiting approval",
                count=pending_po["count"], href="/purchase-orders",
            ))

    if permissions & {P.ORDER_REQUEST_READ, P.ORDER_REQUEST_APPROVE}:
        pending_or = await repo.pending_order_requests(warehouse_ids)
        if pending_or["count"]:
            items.append(OperationalSignal(
                kind="pending_order_request", severity="info",
                title=f"{pending_or['count']} order request(s) awaiting approval",
                count=pending_or["count"], href="/order-requests",
            ))

    return items
