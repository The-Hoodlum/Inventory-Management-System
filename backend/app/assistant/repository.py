"""Read queries behind the assistant tools, plus conversation logging and
branch-access / WhatsApp-identity lookups.

Every query is scoped to a concrete list of warehouse ids the caller is allowed to
see (branch-based access control), on top of PostgreSQL RLS (tenant isolation). All
methods return plain JSON-ready structures (Decimals -> float) so the tool results
can be handed straight to the LLM.
"""
from __future__ import annotations

import datetime as dt
import math
import uuid

from sqlalchemy import Numeric, cast, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.cache import stock_cache
from app.assistant.domain.prompt import TenantConfig
from app.core.config import settings
from app.models import (
    AssistantConversation,
    AssistantMessage,
    Category,
    Inventory,
    Permission,
    Product,
    PurchaseOrder,
    ReorderRecommendation,
    Role,
    RolePermission,
    SalesDaily,
    StockMovement,
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

    async def all_warehouse_ids(self) -> list[uuid.UUID]:
        """Every warehouse id in the current tenant (for system-wide alerts)."""
        res = await self.session.execute(select(Warehouse.id))
        return [wid for (wid,) in res.all()]

    async def alert_recipients(self) -> list[str]:
        """Phone numbers registered for the assistant in the current tenant (alert targets)."""
        res = await self.session.execute(select(WhatsAppIdentity.phone))
        return [p for (p,) in res.all()]

    async def tenant_currency(self) -> str:
        cur = await self.session.scalar(
            text("SELECT base_currency FROM tenants WHERE id = "
                 "NULLIF(current_setting('app.current_tenant', true), '')::uuid")
        )
        return (cur or "USD").strip()

    async def tenant_config(self) -> TenantConfig:
        """Tenant business-identity used to shape the assistant's persona dynamically
        (industry-agnostic: nothing business-specific is hard-coded in the engine)."""
        row = (await self.session.execute(
            text("SELECT name, brand_name, industry, base_currency, assistant_name, assistant_prompt "
                 "FROM tenants WHERE id = NULLIF(current_setting('app.current_tenant', true), '')::uuid")
        )).first()
        if row is None:
            return TenantConfig()
        return TenantConfig(
            company_name=row[0], brand_name=row[1], industry=row[2],
            currency=(row[3] or "USD").strip(), assistant_name=row[4], assistant_prompt=row[5],
        )

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

    async def user_permissions(self, user_id: uuid.UUID) -> set[str]:
        """Permission codes a user holds (via roles) — gates the assistant's write tools."""
        res = await self.session.execute(
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .where(UserRole.user_id == user_id)
        )
        return {code for (code,) in res.all()}

    async def find_product(self, term: str) -> tuple[uuid.UUID, str, str] | None:
        """Best single product match by name/SKU (for turning a chat phrase into a line).
        Returns (id, sku, name) or None."""
        like = f"%{term.strip()}%"
        row = (await self.session.execute(
            select(Product.id, Product.sku, Product.name)
            .where(Product.deleted_at.is_(None),
                   or_(Product.name.ilike(like), Product.sku.ilike(like)))
            .order_by(func.length(Product.name))  # prefer the most specific (shortest) name
            .limit(1)
        )).first()
        return (row[0], row[1], row[2]) if row else None

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
        self, start: dt.date, end: dt.date, warehouse_ids: list[uuid.UUID], limit: int,
        category: str | None = None,
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
        if category:
            stmt = stmt.join(Category, Category.id == Product.category_id).where(
                Category.name.ilike(f"%{category.strip()}%")
            )
        res = await self.session.execute(stmt)
        items = [{"sku": sku, "name": name, "units_sold": _f(qty)} for sku, name, qty in res.all()]
        out = {"period": f"{start.isoformat()} to {end.isoformat()}", "items": items}
        if category:
            out["category"] = category
        return out

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

    # ------------------------- movements / analytics ------------------- #
    async def stock_movements(
        self, term: str | None, warehouse_ids: list[uuid.UUID], days: int, limit: int = 20
    ) -> dict:
        cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=max(1, days))
        stmt = (
            select(StockMovement.created_at, StockMovement.movement_type, StockMovement.quantity,
                   Product.sku, Product.name, Warehouse.name, StockMovement.reason)
            .join(Product, Product.id == StockMovement.product_id)
            .join(Warehouse, Warehouse.id == StockMovement.warehouse_id)
            .where(StockMovement.warehouse_id.in_(warehouse_ids), StockMovement.created_at >= cutoff)
            .order_by(StockMovement.created_at.desc())
            .limit(min(limit, _MAX_ROWS))
        )
        if term:
            like = f"%{term.strip()}%"
            stmt = stmt.where(or_(Product.name.ilike(like), Product.sku.ilike(like)))
        res = await self.session.execute(stmt)
        movements = [
            {"date": created.date().isoformat(), "type": mtype, "qty": _f(qty),
             "sku": sku, "item": name, "branch": wh, "reason": reason}
            for created, mtype, qty, sku, name, wh, reason in res.all()
        ]
        return {"days": days, "count": len(movements), "movements": movements}

    async def slow_moving(
        self, start: dt.date, warehouse_ids: list[uuid.UUID], limit: int = 10
    ) -> dict:
        sold = (
            select(SalesDaily.product_id, func.sum(SalesDaily.qty_sold).label("sold"))
            .where(SalesDaily.sale_date >= start, SalesDaily.warehouse_id.in_(warehouse_ids))
            .group_by(SalesDaily.product_id)
        ).subquery()
        on_hand = func.sum(Inventory.qty_on_hand)
        units = func.coalesce(func.max(sold.c.sold), 0)
        stmt = (
            select(Product.sku, Product.name, on_hand, units)
            .join(Product, Product.id == Inventory.product_id)
            .outerjoin(sold, sold.c.product_id == Product.id)
            .where(Inventory.warehouse_id.in_(warehouse_ids), Product.deleted_at.is_(None))
            .group_by(Product.sku, Product.name)
            .having(on_hand > 0)
            .order_by(units.asc(), on_hand.desc())
            .limit(min(limit, _MAX_ROWS))
        )
        res = await self.session.execute(stmt)
        items = [
            {"sku": sku, "name": name, "on_hand": _f(stock), "units_sold_in_period": _f(u)}
            for sku, name, stock, u in res.all()
        ]
        return {"since": start.isoformat(), "count": len(items), "items": items}

    async def pending_purchase_requests(self, warehouse_ids: list[uuid.UUID]) -> dict:
        stmt = (
            select(PurchaseOrder.po_number, PurchaseOrder.status, Warehouse.name,
                   PurchaseOrder.total, PurchaseOrder.currency, Supplier.name, PurchaseOrder.created_at)
            .join(Warehouse, Warehouse.id == PurchaseOrder.warehouse_id)
            .join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
            .where(
                PurchaseOrder.warehouse_id.in_(warehouse_ids),
                PurchaseOrder.status.in_(("draft", "pending_approval")),
            )
            .order_by(PurchaseOrder.created_at.desc())
            .limit(_MAX_ROWS)
        )
        res = await self.session.execute(stmt)
        requests = [
            {"po_number": po, "status": st, "branch": wh, "total": _f(total),
             "currency": ccy, "supplier": sup, "created_at": created.date().isoformat()}
            for po, st, wh, total, ccy, sup, created in res.all()
        ]
        return {"count": len(requests), "requests": requests}

    async def reorder_proposal(self, warehouse_ids: list[uuid.UUID], currency: str) -> dict:
        """READ-ONLY reorder proposal: for items at/below reorder point, size an order from
        reorder point + safety stock vs available, honour MOQ, round up to full cartons, and
        attach estimated cost, supplier, and lead time. Writes nothing — staff act on it."""
        stmt = (
            select(Product.sku, Product.name, Warehouse.name, Inventory.qty_available,
                   Product.reorder_point, Product.safety_stock, Product.moq,
                   Product.units_per_carton, Product.lead_time_days, Product.cost_price,
                   Supplier.name, Supplier.default_lead_time_days)
            .join(Product, Product.id == Inventory.product_id)
            .join(Warehouse, Warehouse.id == Inventory.warehouse_id)
            .outerjoin(Supplier, Supplier.id == Product.primary_supplier_id)
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
        items: list[dict] = []
        total = 0.0
        for sku, name, branch, avail, rop, safety, moq, upc, lead, cost, sup, sup_lead in res.all():
            avail = _f(avail)
            rop = int(rop or 0)
            safety = int(safety or 0)
            moq = int(moq or 0)
            upc = max(1, int(upc or 1))
            deficit = max(0.0, (rop + safety) - avail)
            cartons = math.ceil(max(deficit, moq) / upc) if (deficit > 0 or moq > 0) else 0
            order_qty = cartons * upc
            est_cost = order_qty * _f(cost)
            total += est_cost
            items.append({
                "sku": sku, "name": name, "branch": branch, "available": avail,
                "reorder_point": rop, "safety_stock": safety, "suggested_qty": order_qty,
                "cartons": cartons, "estimated_cost": round(est_cost, 2),
                "supplier": sup, "lead_time_days": int(sup_lead or lead or 0),
                "reason": f"available {avail:g} at/below reorder {rop} (+safety {safety}); "
                          f"MOQ {moq}, {upc}/carton",
            })
        return {
            "currency": currency, "count": len(items), "estimated_total_cost": round(total, 2),
            "is_proposal": True,
            "note": "Read-only proposal — no purchase order created. Forecast and container "
                    "utilisation are not yet factored in.",
            "items": items,
        }

    async def branch_performance(
        self, start: dt.date, end: dt.date, warehouse_ids: list[uuid.UUID], currency: str
    ) -> dict:
        # Sales (units + estimated revenue) per branch over the period.
        sales = await self.session.execute(
            select(Warehouse.name, func.sum(SalesDaily.qty_sold),
                   func.sum(SalesDaily.qty_sold * Product.selling_price))
            .join(Product, Product.id == SalesDaily.product_id)
            .join(Warehouse, Warehouse.id == SalesDaily.warehouse_id)
            .where(SalesDaily.sale_date >= start, SalesDaily.sale_date <= end,
                   SalesDaily.warehouse_id.in_(warehouse_ids))
            .group_by(Warehouse.name)
        )
        sold = {n: (_f(u), _f(r)) for n, u, r in sales.all()}
        # Stock value at cost per branch.
        val = await self.session.execute(
            select(Warehouse.name, func.coalesce(func.sum(Inventory.qty_on_hand * Product.cost_price), 0))
            .join(Product, Product.id == Inventory.product_id)
            .join(Warehouse, Warehouse.id == Inventory.warehouse_id)
            .where(Product.deleted_at.is_(None), Inventory.warehouse_id.in_(warehouse_ids))
            .group_by(Warehouse.name)
        )
        value = {n: _f(v) for n, v in val.all()}
        # Low-stock line count per branch.
        low = await self.session.execute(
            select(Warehouse.name, func.count(Inventory.id))
            .join(Product, Product.id == Inventory.product_id)
            .join(Warehouse, Warehouse.id == Inventory.warehouse_id)
            .where(Product.deleted_at.is_(None), Inventory.warehouse_id.in_(warehouse_ids),
                   Product.reorder_point.isnot(None),
                   Inventory.qty_available <= cast(Product.reorder_point, Numeric))
            .group_by(Warehouse.name)
        )
        low_counts = {n: int(c) for n, c in low.all()}
        names = sorted(set(sold) | set(value) | set(low_counts))
        by_branch = [
            {"branch": n, "units_sold": sold.get(n, (0.0, 0.0))[0],
             "estimated_revenue": round(sold.get(n, (0.0, 0.0))[1], 2),
             "stock_value": round(value.get(n, 0.0), 2), "low_stock_items": low_counts.get(n, 0)}
            for n in names
        ]
        return {
            "period": start.isoformat() if start == end else f"{start.isoformat()} to {end.isoformat()}",
            "currency": currency, "revenue_is_estimate": True, "by_branch": by_branch,
        }

    async def daily_summary(
        self, day: dt.date, warehouse_ids: list[uuid.UUID], currency: str
    ) -> dict:
        totals = await self.sales_summary(day, day, warehouse_ids, currency)
        branches = await self.branch_summary(day, warehouse_ids, currency)
        low = await self.low_stock(warehouse_ids)
        pending = await self.pending_purchase_requests(warehouse_ids)
        return {
            "date": day.isoformat(), "currency": currency,
            "units_sold": totals["units_sold"], "estimated_revenue": totals["estimated_revenue"],
            "revenue_is_estimate": True, "top_item": totals["top_item"], "best_branch": totals["best_branch"],
            "low_stock_count": low["count"], "pending_purchase_requests": pending["count"],
            "by_branch": branches["by_branch"],
        }
