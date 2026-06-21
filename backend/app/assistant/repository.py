"""Read queries behind the assistant tools, plus conversation logging and
branch-access / WhatsApp-identity lookups.

Every query is scoped to a concrete list of warehouse ids the caller is allowed to
see (branch-based access control), on top of PostgreSQL RLS (tenant isolation). All
methods return plain JSON-ready structures (Decimals -> float) so the tool results
can be handed straight to the LLM.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Numeric, cast, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.cache import stock_cache
from app.core.config import settings
from app.models import (
    AssistantConversation,
    AssistantMessage,
    Inventory,
    Product,
    PurchaseOrder,
    ReorderRecommendation,
    Role,
    SalesDaily,
    Supplier,
    UserRole,
    UserWarehouseAccess,
    Warehouse,
    WhatsAppIdentity,
)

_MAX_ROWS = 50  # cap any single tool result so responses stay small


def _f(value) -> float:
    return float(value) if value is not None else 0.0


class AssistantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --------------------------- access / identity --------------------- #
    async def accessible_warehouses(self, user_id: uuid.UUID) -> list[Warehouse]:
        """Warehouses the user may see: their explicit grants, or ALL tenant
        warehouses when they have no grant rows (unrestricted)."""
        granted = await self.session.execute(
            select(Warehouse)
            .join(UserWarehouseAccess, UserWarehouseAccess.warehouse_id == Warehouse.id)
            .where(UserWarehouseAccess.user_id == user_id)
            .order_by(Warehouse.name)
        )
        rows = list(granted.scalars().all())
        if rows:
            return rows
        allwh = await self.session.execute(select(Warehouse).order_by(Warehouse.name))
        return list(allwh.scalars().all())

    async def tenant_currency(self) -> str:
        cur = await self.session.scalar(
            text("SELECT base_currency FROM tenants WHERE id = "
                 "NULLIF(current_setting('app.current_tenant', true), '')::uuid")
        )
        return (cur or "USD").strip()

    async def user_id_for_phone(self, phone: str) -> uuid.UUID | None:
        return await self.session.scalar(
            select(WhatsAppIdentity.user_id).where(WhatsAppIdentity.phone == phone)
        )

    async def user_roles(self, user_id: uuid.UUID) -> list[str]:
        """Role names assigned to a user — used to gate which tools the assistant exposes."""
        res = await self.session.execute(
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
        )
        return [r for (r,) in res.all()]

    # ------------------------------ logging ---------------------------- #
    async def create_conversation(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, channel: str, external_id: str | None
    ) -> AssistantConversation:
        conv = AssistantConversation(
            tenant_id=tenant_id, user_id=user_id, channel=channel, external_id=external_id
        )
        self.session.add(conv)
        await self.session.flush()
        return conv

    async def add_message(
        self, *, tenant_id: uuid.UUID, conversation_id: uuid.UUID, role: str,
        content: str | None, tool_name: str | None = None,
    ) -> None:
        self.session.add(
            AssistantMessage(
                tenant_id=tenant_id, conversation_id=conversation_id, role=role,
                content=content, tool_name=tool_name,
            )
        )
        await self.session.flush()

    # ------------------------------- stock ----------------------------- #
    async def stock_by_item(self, term: str, warehouse_ids: list[uuid.UUID]) -> dict:
        # Short-lived cache: repeated identical stock lookups (common in a chat) skip the DB.
        cache = stock_cache() if settings.assistant_cache_enabled else None
        cache_key = ("stock", term.strip().lower(), tuple(sorted(str(w) for w in warehouse_ids)))
        if cache is not None:
            cached = cache.get(cache_key)
            if cached is not None:
                return cached
        like = f"%{term.strip()}%"
        stmt = (
            select(Product.sku, Product.name, Warehouse.name, Inventory.qty_on_hand, Inventory.qty_available)
            .join(Product, Product.id == Inventory.product_id)
            .join(Warehouse, Warehouse.id == Inventory.warehouse_id)
            .where(
                Product.deleted_at.is_(None),
                Inventory.warehouse_id.in_(warehouse_ids),
                or_(Product.name.ilike(like), Product.sku.ilike(like)),
            )
            .order_by(Product.name)
        )
        res = await self.session.execute(stmt)
        items: dict[str, dict] = {}
        for sku, name, branch, on_hand, available in res.all():
            entry = items.setdefault(sku, {"sku": sku, "name": name, "total_available": 0.0, "by_branch": []})
            entry["by_branch"].append({"branch": branch, "available": _f(available), "on_hand": _f(on_hand)})
            entry["total_available"] += _f(available)
        out = list(items.values())[:_MAX_ROWS]
        result = {"search": term, "matched_items": len(items), "items": out}
        if cache is not None:
            cache.set(cache_key, result)
        return result

    async def low_stock(self, warehouse_ids: list[uuid.UUID]) -> dict:
        stmt = (
            select(Product.sku, Product.name, Warehouse.name, Inventory.qty_available, Product.reorder_point)
            .join(Product, Product.id == Inventory.product_id)
            .join(Warehouse, Warehouse.id == Inventory.warehouse_id)
            .where(
                Product.deleted_at.is_(None),
                Inventory.warehouse_id.in_(warehouse_ids),
                Product.reorder_point.isnot(None),
                Inventory.qty_available <= cast(Product.reorder_point, Numeric),
            )
            .order_by(Inventory.qty_available)
            .limit(_MAX_ROWS)
        )
        res = await self.session.execute(stmt)
        items = [
            {"sku": sku, "name": name, "branch": branch, "available": _f(avail), "reorder_point": int(rop)}
            for sku, name, branch, avail, rop in res.all()
        ]
        return {"count": len(items), "items": items}

    async def reorder_recommendations(self, warehouse_ids: list[uuid.UUID]) -> dict:
        stmt = (
            select(Product.sku, Product.name, Warehouse.name,
                   ReorderRecommendation.recommended_qty, ReorderRecommendation.recommended_cartons,
                   ReorderRecommendation.expedite)
            .join(Product, Product.id == ReorderRecommendation.product_id)
            .join(Warehouse, Warehouse.id == ReorderRecommendation.warehouse_id)
            .where(ReorderRecommendation.status == "pending", ReorderRecommendation.warehouse_id.in_(warehouse_ids))
            .order_by(ReorderRecommendation.expedite.desc(), ReorderRecommendation.recommended_qty.desc())
            .limit(_MAX_ROWS)
        )
        res = await self.session.execute(stmt)
        items = [
            {"sku": sku, "name": name, "branch": branch, "recommended_qty": _f(qty),
             "recommended_cartons": int(cartons or 0), "expedite": bool(exp)}
            for sku, name, branch, qty, cartons, exp in res.all()
        ]
        return {"count": len(items), "items": items}

    async def valuation(self, warehouse_ids: list[uuid.UUID], currency: str) -> dict:
        value = func.coalesce(func.sum(Inventory.qty_on_hand * Product.cost_price), 0)
        stmt = (
            select(Warehouse.name, value)
            .join(Product, Product.id == Inventory.product_id)
            .join(Warehouse, Warehouse.id == Inventory.warehouse_id)
            .where(Product.deleted_at.is_(None), Inventory.warehouse_id.in_(warehouse_ids))
            .group_by(Warehouse.name)
            .order_by(Warehouse.name)
        )
        res = await self.session.execute(stmt)
        by_branch = [{"branch": name, "value": _f(v)} for name, v in res.all()]
        return {
            "currency": currency,
            "total": round(sum(b["value"] for b in by_branch), 2),
            "by_branch": by_branch,
        }

    async def purchase_orders(self, status: str | None, warehouse_ids: list[uuid.UUID]) -> dict:
        stmt = (
            select(PurchaseOrder.po_number, PurchaseOrder.status, Warehouse.name,
                   PurchaseOrder.total, PurchaseOrder.currency, Supplier.name, PurchaseOrder.created_at)
            .join(Warehouse, Warehouse.id == PurchaseOrder.warehouse_id)
            .join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
            .where(PurchaseOrder.warehouse_id.in_(warehouse_ids))
            .order_by(PurchaseOrder.created_at.desc())
            .limit(_MAX_ROWS)
        )
        if status:
            stmt = stmt.where(PurchaseOrder.status == status.strip().lower())
        res = await self.session.execute(stmt)
        orders = [
            {"po_number": po, "status": st, "branch": wh, "total": _f(total),
             "currency": ccy, "supplier": sup, "created_at": created.date().isoformat()}
            for po, st, wh, total, ccy, sup, created in res.all()
        ]
        return {"count": len(orders), "orders": orders}

    # ------------------------------- sales ----------------------------- #
    async def sales_summary(
        self, start: dt.date, end: dt.date, warehouse_ids: list[uuid.UUID], currency: str
    ) -> dict:
        base = (
            select(SalesDaily.qty_sold, Product.selling_price, Product.name, Warehouse.name)
            .join(Product, Product.id == SalesDaily.product_id)
            .join(Warehouse, Warehouse.id == SalesDaily.warehouse_id)
            .where(
                SalesDaily.sale_date >= start, SalesDaily.sale_date <= end,
                SalesDaily.warehouse_id.in_(warehouse_ids),
            )
        )
        res = await self.session.execute(base)
        units = 0.0
        revenue = 0.0
        by_item: dict[str, float] = {}
        by_branch: dict[str, float] = {}
        for qty, price, item, branch in res.all():
            q = _f(qty)
            units += q
            revenue += q * _f(price)
            by_item[item] = by_item.get(item, 0.0) + q
            by_branch[branch] = by_branch.get(branch, 0.0) + q
        top_item = max(by_item.items(), key=lambda kv: kv[1], default=(None, 0.0))
        best_branch = max(by_branch.items(), key=lambda kv: kv[1], default=(None, 0.0))
        period = start.isoformat() if start == end else f"{start.isoformat()} to {end.isoformat()}"
        return {
            "period": period,
            "units_sold": round(units, 2),
            "estimated_revenue": round(revenue, 2),
            "currency": currency,
            "revenue_is_estimate": True,
            "top_item": top_item[0],
            "best_branch": best_branch[0],
        }

    async def top_items(
        self, start: dt.date, end: dt.date, warehouse_ids: list[uuid.UUID], limit: int
    ) -> dict:
        total_qty = func.sum(SalesDaily.qty_sold)
        stmt = (
            select(Product.sku, Product.name, total_qty)
            .join(Product, Product.id == SalesDaily.product_id)
            .where(
                SalesDaily.sale_date >= start, SalesDaily.sale_date <= end,
                SalesDaily.warehouse_id.in_(warehouse_ids),
            )
            .group_by(Product.sku, Product.name)
            .order_by(total_qty.desc())
            .limit(max(1, min(limit, _MAX_ROWS)))
        )
        res = await self.session.execute(stmt)
        items = [{"sku": sku, "name": name, "units_sold": _f(qty)} for sku, name, qty in res.all()]
        return {"period": f"{start.isoformat()} to {end.isoformat()}", "items": items}

    async def branch_summary(
        self, day: dt.date, warehouse_ids: list[uuid.UUID], currency: str
    ) -> dict:
        # Stock lines + low-stock per branch
        stock = await self.session.execute(
            select(Warehouse.name, func.count(Inventory.id))
            .join(Warehouse, Warehouse.id == Inventory.warehouse_id)
            .where(Inventory.warehouse_id.in_(warehouse_ids))
            .group_by(Warehouse.name)
        )
        lines = {name: int(n) for name, n in stock.all()}
        # Sales that day per branch
        sales = await self.session.execute(
            select(Warehouse.name, func.sum(SalesDaily.qty_sold),
                   func.sum(SalesDaily.qty_sold * Product.selling_price))
            .join(Product, Product.id == SalesDaily.product_id)
            .join(Warehouse, Warehouse.id == SalesDaily.warehouse_id)
            .where(SalesDaily.sale_date == day, SalesDaily.warehouse_id.in_(warehouse_ids))
            .group_by(Warehouse.name)
        )
        sold = {name: (_f(u), _f(r)) for name, u, r in sales.all()}
        names = sorted(set(lines) | set(sold))
        by_branch = [
            {"branch": n, "stock_lines": lines.get(n, 0),
             "units_sold": sold.get(n, (0.0, 0.0))[0],
             "estimated_revenue": round(sold.get(n, (0.0, 0.0))[1], 2)}
            for n in names
        ]
        return {"date": day.isoformat(), "currency": currency, "by_branch": by_branch}
