"""Search providers for the entities that already exist in the platform.

Each runs a tenant-scoped ILIKE (RLS narrows rows to the current tenant) and maps
matches to :class:`SearchHit`s with a route the UI can open. Keep providers thin —
they read existing tables only; they never create new ones.
"""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import P
from app.models import (
    Customer,
    Invoice,
    MotorcycleUnit,
    Product,
    Quotation,
    SalesOrder,
    Supplier,
)
from app.search.registry import SearchHit, register


def _like(query: str) -> str:
    return f"%{query.strip()}%"


class ProductSearch:
    entity = "product"
    label = "Products"
    permission = P.PRODUCT_READ

    async def search(self, session: AsyncSession, query: str, limit: int) -> list[SearchHit]:
        like = _like(query)
        rows = (
            await session.execute(
                select(Product.id, Product.sku, Product.name, Product.status)
                .where(Product.deleted_at.is_(None))
                .where(or_(Product.name.ilike(like), Product.sku.ilike(like), Product.barcode.ilike(like)))
                .order_by(Product.name)
                .limit(limit)
            )
        ).all()
        return [
            SearchHit(entity=self.entity, id=str(r.id), title=r.name, subtitle=r.sku,
                      badge=r.status, href="/products")
            for r in rows
        ]


class CustomerSearch:
    entity = "customer"
    label = "Customers"
    permission = P.CUSTOMER_READ

    async def search(self, session: AsyncSession, query: str, limit: int) -> list[SearchHit]:
        like = _like(query)
        rows = (
            await session.execute(
                select(Customer.id, Customer.code, Customer.name, Customer.phone)
                .where(or_(Customer.name.ilike(like), Customer.code.ilike(like),
                           Customer.phone.ilike(like), Customer.email.ilike(like)))
                .order_by(Customer.name)
                .limit(limit)
            )
        ).all()
        return [
            SearchHit(entity=self.entity, id=str(r.id), title=r.name,
                      subtitle=r.phone or r.code, badge=r.code, href="/customers")
            for r in rows
        ]


class SupplierSearch:
    entity = "supplier"
    label = "Suppliers"
    permission = P.SUPPLIER_READ

    async def search(self, session: AsyncSession, query: str, limit: int) -> list[SearchHit]:
        like = _like(query)
        rows = (
            await session.execute(
                select(Supplier.id, Supplier.name, Supplier.code, Supplier.contact_person)
                .where(Supplier.deleted_at.is_(None))
                .where(or_(Supplier.name.ilike(like), Supplier.code.ilike(like),
                           Supplier.contact_person.ilike(like), Supplier.email.ilike(like)))
                .order_by(Supplier.name)
                .limit(limit)
            )
        ).all()
        return [
            SearchHit(entity=self.entity, id=str(r.id), title=r.name,
                      subtitle=r.contact_person or r.code, badge=r.code, href="/suppliers")
            for r in rows
        ]


class InvoiceSearch:
    entity = "invoice"
    label = "Invoices"
    permission = P.SALES_READ

    async def search(self, session: AsyncSession, query: str, limit: int) -> list[SearchHit]:
        rows = (
            await session.execute(
                select(Invoice.id, Invoice.invoice_number, Invoice.status)
                .where(Invoice.invoice_number.ilike(_like(query)))
                .order_by(Invoice.created_at.desc())
                .limit(limit)
            )
        ).all()
        return [
            SearchHit(entity=self.entity, id=str(r.id), title=r.invoice_number,
                      subtitle="Invoice", badge=r.status, href="/sales")
            for r in rows
        ]


class QuotationSearch:
    entity = "quotation"
    label = "Quotations"
    permission = P.SALES_READ

    async def search(self, session: AsyncSession, query: str, limit: int) -> list[SearchHit]:
        rows = (
            await session.execute(
                select(Quotation.id, Quotation.quote_number, Quotation.status)
                .where(Quotation.quote_number.ilike(_like(query)))
                .order_by(Quotation.created_at.desc())
                .limit(limit)
            )
        ).all()
        return [
            SearchHit(entity=self.entity, id=str(r.id), title=r.quote_number,
                      subtitle="Quotation", badge=r.status, href="/sales")
            for r in rows
        ]


class SalesOrderSearch:
    entity = "sales_order"
    label = "Sales orders"
    permission = P.SALES_READ

    async def search(self, session: AsyncSession, query: str, limit: int) -> list[SearchHit]:
        rows = (
            await session.execute(
                select(SalesOrder.id, SalesOrder.so_number, SalesOrder.status)
                .where(SalesOrder.so_number.ilike(_like(query)))
                .order_by(SalesOrder.created_at.desc())
                .limit(limit)
            )
        ).all()
        return [
            SearchHit(entity=self.entity, id=str(r.id), title=r.so_number,
                      subtitle="Sales order", badge=r.status, href="/sales")
            for r in rows
        ]


class MotorcycleSearch:
    entity = "motorcycle"
    label = "Motorcycles"
    permission = P.MOTORCYCLE_READ

    async def search(self, session: AsyncSession, query: str, limit: int) -> list[SearchHit]:
        like = _like(query)
        rows = (
            await session.execute(
                select(
                    MotorcycleUnit.id, MotorcycleUnit.chassis_number, MotorcycleUnit.model,
                    MotorcycleUnit.status, MotorcycleUnit.registration_number,
                )
                .where(or_(
                    MotorcycleUnit.chassis_number.ilike(like),
                    MotorcycleUnit.engine_number.ilike(like),
                    MotorcycleUnit.registration_number.ilike(like),
                    MotorcycleUnit.customer_id.in_(
                        select(Customer.id).where(Customer.name.ilike(like))
                    ),
                ))
                .order_by(MotorcycleUnit.created_at.desc())
                .limit(limit)
            )
        ).all()
        return [
            SearchHit(
                entity=self.entity, id=str(r.id), title=r.chassis_number,
                subtitle=" · ".join(x for x in (r.model, r.registration_number) if x) or "Motorcycle",
                badge=r.status, href=f"/motorcycles/{r.id}",
            )
            for r in rows
        ]


def register_default_providers() -> None:
    """Register the providers for the entities that exist today. Called once at import."""
    for provider in (
        ProductSearch(), CustomerSearch(), SupplierSearch(),
        InvoiceSearch(), QuotationSearch(), SalesOrderSearch(), MotorcycleSearch(),
    ):
        register(provider)


register_default_providers()
