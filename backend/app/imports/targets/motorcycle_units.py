"""The "motorcycle_units" import target: bulk-load the serialized unit registry from a
spreadsheet.

Unlike the fungible inventory import, a serialized registry cannot half-create, so this
is an ATOMIC target (see app/imports/domain/atomic.py): the whole batch is validated up
front, new reference values (models / variants / colours / suppliers) are surfaced for
explicit confirmation instead of being created silently, and the commit writes every row
or nothing.

Rules enforced here:
- chassis_number unique within the file AND against the DB; engine_number unique too
  when present.
- branch matched by name — NEVER auto-created (an unmatched branch is a row error).
- model / variant / colour / supplier matched by name; unmatched values are collected
  as "new references" and only created on confirm (guards typos).
- status maps to the lifecycle entry state; sold/reserved rows are recorded as HISTORICAL
  directly on the unit (customer + dates + charged price, imported_historical=True) — no
  back-dated sales documents are fabricated.
- consistency: a sold row needs a customer + sale date; a reserved row needs a customer;
  a non-sold row must not carry sale-only fields (sale date / charged price).
"""
from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.imports.domain.atomic import AtomicImporter, ImportPlan, NewRef, RowInput, RowPlan
from app.imports.domain.fields import (
    LEVEL_ADVANCED,
    LEVEL_BASIC,
    LEVEL_STANDARD,
    FieldKind,
    FieldSpec,
    RowResult,
)
from app.imports.domain.registry import register
from app.models import (
    Brand,
    Customer,
    CustomerAddress,
    MotorcycleColour,
    MotorcycleModel,
    MotorcycleUnit,
    MotorcycleUnitEvent,
    MotorcycleVariant,
    Supplier,
)
from app.models.inventory import Branch

_ALL = (LEVEL_BASIC, LEVEL_STANDARD, LEVEL_ADVANCED)
_STD = (LEVEL_STANDARD, LEVEL_ADVANCED)
_ADV = (LEVEL_ADVANCED,)

# Spreadsheet status -> (lifecycle status, assembly_status, inspection_status).
_STATUS_MAP: dict[str, tuple[str, str, str]] = {
    "unassembled": ("assembly_required", "required", "pending"),
    "assembled": ("assembled", "assembled", "pending"),
    "reserved": ("reserved", "assembled", "passed"),
    "sold": ("sold", "assembled", "passed"),
}

_IMPORT_FALLBACK_BRAND = "Unspecified"
_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%m/%d/%Y")


def _parse_date(raw: Any) -> tuple[dt.date | None, bool]:
    """Return (date|None, ok). Empty -> (None, True). Unparseable -> (None, False)."""
    s = ("" if raw is None else str(raw)).strip()
    if not s:
        return None, True
    s = s.split(" ")[0].split("T")[0]  # tolerate a trailing time component
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(s, fmt).date(), True
        except ValueError:
            continue
    return None, False


_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("chassis_number", "Chassis Number", required=True, kind=FieldKind.STRING, levels=_ALL,
              aliases=("chassis", "chassis no", "chassis number", "vin", "frame number", "frame no")),
    FieldSpec("engine_number", "Engine Number", kind=FieldKind.STRING, levels=_ALL,
              aliases=("engine", "engine no", "engine number", "motor number")),
    FieldSpec("model", "Model", required=True, kind=FieldKind.STRING, levels=_ALL,
              aliases=("model", "model name", "bike model", "motorcycle model")),
    FieldSpec("make", "Make / Brand", kind=FieldKind.STRING, levels=_STD,
              aliases=("make", "brand", "manufacturer", "oem")),
    FieldSpec("variant", "Variant", kind=FieldKind.STRING, levels=_STD,
              aliases=("variant", "trim", "grade", "spec")),
    FieldSpec("colour", "Colour", kind=FieldKind.STRING, levels=_ALL,
              aliases=("colour", "color", "paint")),
    FieldSpec("date_received", "Date Received", kind=FieldKind.STRING, levels=_STD,
              aliases=("date received", "received", "received date", "arrival date", "grn date")),
    FieldSpec("branch", "Branch", required=True, kind=FieldKind.STRING, levels=_ALL,
              aliases=("branch", "branch name", "location", "showroom", "outlet")),
    FieldSpec("status", "Status", required=True, kind=FieldKind.ENUM, levels=_ALL,
              choices=tuple(_STATUS_MAP.keys()),
              aliases=("status", "state", "stage", "condition")),
    FieldSpec("assembled_date", "Assembled Date", kind=FieldKind.STRING, levels=_ADV,
              aliases=("assembled date", "assembly date", "pdi date")),
    FieldSpec("customer_name", "Customer Name", kind=FieldKind.STRING, levels=_STD,
              aliases=("customer", "customer name", "buyer", "buyer name", "client")),
    FieldSpec("customer_phone", "Customer Phone", kind=FieldKind.STRING, levels=_STD,
              aliases=("customer phone", "phone", "contact", "mobile", "buyer phone")),
    FieldSpec("customer_address", "Customer Address", kind=FieldKind.STRING, levels=_ADV,
              aliases=("customer address", "address", "buyer address")),
    FieldSpec("date_sold", "Date Sold", kind=FieldKind.STRING, levels=_STD,
              aliases=("date sold", "sold date", "sale date", "invoice date")),
    FieldSpec("registration", "Registered", kind=FieldKind.BOOL, levels=_STD,
              aliases=("registration", "registered", "is registered")),
    FieldSpec("registration_number", "Registration Number", kind=FieldKind.STRING, levels=_STD,
              aliases=("registration number", "reg no", "reg number", "plate", "number plate", "license plate")),
    FieldSpec("unit_price", "Unit Price", kind=FieldKind.DECIMAL, levels=_STD,
              aliases=("unit price", "list price", "selling price", "price")),
    FieldSpec("charged_price", "Charged Price", kind=FieldKind.DECIMAL, levels=_STD,
              aliases=("charged price", "sold price", "final price", "amount charged", "invoice amount")),
    FieldSpec("supplier", "Supplier", kind=FieldKind.STRING, levels=_STD,
              aliases=("supplier", "vendor", "source", "importer")),
)


class _Repo:
    """Thin read/find + create helpers over the request session (RLS scopes to tenant)."""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.s = session
        self.tenant_id = tenant_id

    async def find_model(self, name: str) -> MotorcycleModel | None:
        return await self.s.scalar(
            select(MotorcycleModel).where(func.lower(MotorcycleModel.name) == name.strip().lower()).limit(1)
        )

    async def find_variant(self, model_id: uuid.UUID, name: str) -> MotorcycleVariant | None:
        return await self.s.scalar(
            select(MotorcycleVariant).where(
                MotorcycleVariant.model_id == model_id,
                func.lower(MotorcycleVariant.name) == name.strip().lower(),
            ).limit(1)
        )

    async def find_colour(self, name: str) -> MotorcycleColour | None:
        return await self.s.scalar(
            select(MotorcycleColour).where(func.lower(MotorcycleColour.name) == name.strip().lower()).limit(1)
        )

    async def find_supplier(self, name: str) -> Supplier | None:
        return await self.s.scalar(
            select(Supplier).where(func.lower(Supplier.name) == name.strip().lower()).limit(1)
        )

    async def find_branch(self, name: str) -> Branch | None:
        return await self.s.scalar(
            select(Branch).where(func.lower(Branch.name) == name.strip().lower()).limit(1)
        )

    async def chassis_exists(self, chassis: str) -> bool:
        return await self.s.scalar(
            select(MotorcycleUnit.id).where(
                func.lower(MotorcycleUnit.chassis_number) == chassis.strip().lower()
            ).limit(1)
        ) is not None

    async def engine_exists(self, engine: str) -> bool:
        return await self.s.scalar(
            select(MotorcycleUnit.id).where(
                func.lower(MotorcycleUnit.engine_number) == engine.strip().lower()
            ).limit(1)
        ) is not None

    async def get_or_create_brand(self, name: str) -> Brand:
        existing = await self.s.scalar(select(Brand).where(func.lower(Brand.name) == name.strip().lower()).limit(1))
        if existing is not None:
            return existing
        brand = Brand(tenant_id=self.tenant_id, name=name.strip())
        self.s.add(brand)
        await self.s.flush()
        return brand

    async def get_or_create_model(self, name: str, make: str | None) -> MotorcycleModel:
        existing = await self.find_model(name)
        if existing is not None:
            return existing
        brand = await self.get_or_create_brand((make or "").strip() or _IMPORT_FALLBACK_BRAND)
        model = MotorcycleModel(tenant_id=self.tenant_id, brand_id=brand.id, name=name.strip())
        self.s.add(model)
        await self.s.flush()
        return model

    async def get_or_create_variant(self, model_id: uuid.UUID, name: str) -> MotorcycleVariant:
        existing = await self.find_variant(model_id, name)
        if existing is not None:
            return existing
        variant = MotorcycleVariant(tenant_id=self.tenant_id, model_id=model_id, name=name.strip())
        self.s.add(variant)
        await self.s.flush()
        return variant

    async def get_or_create_colour(self, name: str) -> MotorcycleColour:
        existing = await self.find_colour(name)
        if existing is not None:
            return existing
        colour = MotorcycleColour(tenant_id=self.tenant_id, name=name.strip())
        self.s.add(colour)
        await self.s.flush()
        return colour

    async def get_or_create_supplier(self, name: str) -> Supplier:
        existing = await self.find_supplier(name)
        if existing is not None:
            return existing
        supplier = Supplier(tenant_id=self.tenant_id, name=name.strip())
        self.s.add(supplier)
        await self.s.flush()
        return supplier

    async def get_or_create_customer(self, name: str, phone: str | None, address: str | None) -> Customer:
        stmt = select(Customer).where(func.lower(Customer.name) == name.strip().lower())
        if phone:
            stmt = stmt.where(Customer.phone == phone)
        existing = await self.s.scalar(stmt.limit(1))
        if existing is not None:
            return existing
        code = await self.s.scalar(
            text("SELECT next_customer_number(CAST(:t AS uuid))"), {"t": str(self.tenant_id)}
        )
        customer = Customer(tenant_id=self.tenant_id, code=code, name=name.strip(), phone=phone or None)
        self.s.add(customer)
        await self.s.flush()
        if address:
            self.s.add(CustomerAddress(tenant_id=self.tenant_id, customer_id=customer.id, line1=address))
        await self.s.flush()
        return customer


class MotorcycleUnitImporter(AtomicImporter):
    key = "motorcycle_units"
    label = "Motorcycles (units)"
    key_field = "chassis_number"

    @property
    def fields(self) -> Sequence[FieldSpec]:
        return _FIELDS

    # ------------------------------- plan ------------------------------ #
    async def plan(self, session: Any, *, tenant_id: Any, rows: list[RowInput]) -> ImportPlan:
        repo = _Repo(session, tenant_id)
        plan = ImportPlan()
        seen_chassis: dict[str, int] = {}
        seen_engine: dict[str, int] = {}
        new_refs: dict[tuple[str, str], NewRef] = {}

        # per-plan resolution caches (name.lower -> found?/display)
        model_cache: dict[str, MotorcycleModel | None] = {}
        colour_cache: dict[str, MotorcycleColour | None] = {}
        supplier_cache: dict[str, Supplier | None] = {}
        branch_cache: dict[str, Branch | None] = {}

        def add_new_ref(kind: str, display: str) -> None:
            k = (kind, display.strip().lower())
            if k in new_refs:
                nr = new_refs[k]
                new_refs[k] = NewRef(kind, nr.value, nr.count + 1)
            else:
                new_refs[k] = NewRef(kind, display.strip(), 1)

        for row_number, clean, field_errors in rows:
            errors = list(field_errors)
            chassis = clean.get("chassis_number")
            status = clean.get("status")

            # chassis uniqueness (in-file + DB)
            if chassis:
                cl = chassis.strip().lower()
                if cl in seen_chassis:
                    errors.append(f"Duplicate chassis '{chassis}' in file (row {seen_chassis[cl]})")
                else:
                    seen_chassis[cl] = row_number
                    if await repo.chassis_exists(chassis):
                        errors.append(f"Chassis '{chassis}' already exists")

            # engine uniqueness (in-file + DB) when present
            engine = clean.get("engine_number")
            if engine:
                el = engine.strip().lower()
                if el in seen_engine:
                    errors.append(f"Duplicate engine number '{engine}' in file (row {seen_engine[el]})")
                else:
                    seen_engine[el] = row_number
                    if await repo.engine_exists(engine):
                        errors.append(f"Engine number '{engine}' already exists")

            # dates
            d_recv, ok1 = _parse_date(clean.get("date_received"))
            d_asm, ok2 = _parse_date(clean.get("assembled_date"))
            d_sold, ok3 = _parse_date(clean.get("date_sold"))
            for ok, lbl in ((ok1, "Date Received"), (ok2, "Assembled Date"), (ok3, "Date Sold")):
                if not ok:
                    errors.append(f"{lbl} is not a valid date")

            # consistency
            customer_name = clean.get("customer_name")
            charged = clean.get("charged_price")
            if status == "sold":
                if not customer_name:
                    errors.append("A sold unit needs a Customer Name")
                if not clean.get("date_sold"):
                    errors.append("A sold unit needs a Date Sold")
            elif status == "reserved":
                if not customer_name:
                    errors.append("A reserved unit needs a Customer Name")
            if status not in ("sold",) and (clean.get("date_sold") or charged is not None):
                errors.append("Only a sold unit may carry Date Sold / Charged Price")

            # branch (never auto-created)
            branch_obj = None
            branch = clean.get("branch")
            if branch:
                bl = branch.strip().lower()
                if bl not in branch_cache:
                    branch_cache[bl] = await repo.find_branch(branch)
                branch_obj = branch_cache[bl]
                if branch_obj is None:
                    errors.append(f"Branch '{branch}' not found - create the branch first")

            # references (collect new; not errors)
            model = clean.get("model")
            model_obj = None
            if model:
                ml = model.strip().lower()
                if ml not in model_cache:
                    model_cache[ml] = await repo.find_model(model)
                model_obj = model_cache[ml]
                if model_obj is None:
                    add_new_ref("model", model)
            variant = clean.get("variant")
            if variant and model:
                if model_obj is not None:
                    if await repo.find_variant(model_obj.id, variant) is None:
                        add_new_ref("variant", f"{model} / {variant}")
                else:
                    add_new_ref("variant", f"{model} / {variant}")
            colour = clean.get("colour")
            if colour:
                cl2 = colour.strip().lower()
                if cl2 not in colour_cache:
                    colour_cache[cl2] = await repo.find_colour(colour)
                if colour_cache[cl2] is None:
                    add_new_ref("colour", colour)
            supplier = clean.get("supplier")
            if supplier:
                sl = supplier.strip().lower()
                if sl not in supplier_cache:
                    supplier_cache[sl] = await repo.find_supplier(supplier)
                if supplier_cache[sl] is None:
                    add_new_ref("supplier", supplier)

            data = None
            if not errors:
                data = {
                    "chassis_number": chassis, "engine_number": engine,
                    "model": model, "make": clean.get("make"), "variant": variant, "colour": colour,
                    "supplier": supplier, "branch_id": branch_obj.id if branch_obj else None,
                    "status": status, "date_received": d_recv, "assembled_date": d_asm, "date_sold": d_sold,
                    "customer_name": customer_name, "customer_phone": clean.get("customer_phone"),
                    "customer_address": clean.get("customer_address"),
                    "registration": clean.get("registration"), "registration_number": clean.get("registration_number"),
                    "unit_price": clean.get("unit_price"), "charged_price": charged,
                }
            plan.rows.append(RowPlan(row_number=row_number, key=chassis, errors=errors, data=data))

        plan.new_refs = list(new_refs.values())
        return plan

    # ------------------------------ commit ----------------------------- #
    async def commit(self, session: Any, *, tenant_id: Any, user_id: Any, job_id: Any, plan: ImportPlan) -> int:
        repo = _Repo(session, tenant_id)
        created = 0
        for rp in plan.rows:
            if rp.data is None:
                continue
            d = rp.data
            model = await repo.get_or_create_model(d["model"], d.get("make"))
            variant_id = None
            if d.get("variant"):
                variant_id = (await repo.get_or_create_variant(model.id, d["variant"])).id
            colour_id = None
            if d.get("colour"):
                colour_id = (await repo.get_or_create_colour(d["colour"])).id
            supplier_id = None
            if d.get("supplier"):
                supplier_id = (await repo.get_or_create_supplier(d["supplier"])).id

            status, assembly_status, inspection_status = _STATUS_MAP[d["status"]]
            historical = d["status"] in ("sold", "reserved")

            customer_id = None
            if d.get("customer_name"):
                customer_id = (await repo.get_or_create_customer(
                    d["customer_name"], d.get("customer_phone"), d.get("customer_address")
                )).id

            registered = bool(d.get("registration"))
            unit = MotorcycleUnit(
                tenant_id=tenant_id, chassis_number=d["chassis_number"].strip(),
                engine_number=d.get("engine_number"), model_id=model.id, variant_id=variant_id,
                colour_id=colour_id, supplier_id=supplier_id, branch_id=d.get("branch_id"),
                date_received=d.get("date_received"), assembled_date=d.get("assembled_date"),
                status=status, assembly_status=assembly_status, inspection_status=inspection_status,
                customer_id=customer_id,
                selling_price=_dec(d.get("unit_price")),
                price_charged=_dec(d.get("charged_price")) if d["status"] == "sold" else None,
                date_sold=d.get("date_sold") if d["status"] == "sold" else None,
                registration_status="registered" if registered else "unregistered",
                registration_number=d.get("registration_number"),
                registration_papers_received=registered,
                imported_historical=historical, import_job_id=job_id,
            )
            session.add(unit)
            await session.flush()
            note = f"Imported from spreadsheet (status: {d['status']})"
            session.add(MotorcycleUnitEvent(
                tenant_id=tenant_id, unit_id=unit.id, event_type="created", to_status=status,
                user_id=user_id, reference_type="import_job", reference_id=job_id, note=note,
            ))
            created += 1
        await session.flush()
        return created

    # Not used for atomic targets (kept to satisfy the base contract).
    async def process_row(self, ctx: Any, clean: dict[str, Any]) -> RowResult:  # pragma: no cover
        raise NotImplementedError("motorcycle_units is an atomic target; use plan()/commit()")


def _dec(v: Any) -> Decimal | None:
    return Decimal(str(v)) if v is not None else None


register(MotorcycleUnitImporter())
