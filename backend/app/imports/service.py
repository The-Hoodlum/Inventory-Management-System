"""Import orchestration: list targets, generate templates, upload+detect, validate
preview, and execute the import.

Phase 1 runs the import synchronously inside the request transaction, isolating each
row in a SAVEPOINT (``begin_nested``) so a single bad row is recorded as an error
without poisoning the rest. The per-row loop is factored out so the Phase 3 async
runner can reuse it for batched, cancellable, 50k-row imports.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Any

import app.imports.targets  # noqa: F401  (registers built-in targets on import)
from app.core.exceptions import BusinessRuleError, NotFoundError
from app.imports.domain.base import ResourceImporter
from app.imports.domain.detection import detect_columns, header_signature, merge_mapping
from app.imports.domain.fields import ROW_ERROR, ROW_IMPORTED, ROW_SKIPPED
from app.imports.domain.parsing import UnsupportedFileType, parse_table
from app.imports.domain.registry import all_importers, get_importer
from app.imports.domain.validation import validate_mapped
from app.imports.repository import ImportRepository
from app.imports.schemas import (
    FieldOut,
    ImportJobOut,
    ImportOptions,
    PreviewResponse,
    RowErrorOut,
    TargetOut,
    UploadResponse,
)
from app.repositories.audit_repo import AuditRepository

MAX_PREVIEW_ROWS = 20
_MISSING = object()


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class ImportContext:
    """Per-run persistence helper passed to a target's ``process_row``. Caches
    resolved reference entities; new entities created within a row stay in
    ``_pending`` until the row's savepoint commits (then ``commit_row`` promotes
    them), so a rolled-back row never leaves a dangling cache entry."""

    def __init__(
        self,
        repo: ImportRepository,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        job_id: uuid.UUID,
        options: ImportOptions,
    ) -> None:
        self.repo = repo
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.job_id = job_id
        self.options = options
        self._cache: dict[tuple[str, str], Any] = {}
        self._pending: dict[tuple[str, str], Any] = {}

    def commit_row(self) -> None:
        self._cache.update(self._pending)
        self._pending.clear()

    def rollback_row(self) -> None:
        self._pending.clear()

    def _get(self, kind: str, name: str) -> Any:
        key = (kind, name)
        if key in self._pending:
            return self._pending[key]
        return self._cache.get(key, _MISSING)

    async def resolve_warehouse(self, name: str | None) -> Any:
        wh_name = (name or "").strip() or self.options.default_warehouse
        if not wh_name:
            return None
        key = wh_name.lower()
        hit = self._get("wh", key)
        if hit is not _MISSING:
            return hit
        wh = await self.repo.find_warehouse(wh_name)
        if wh is not None:
            self._cache[("wh", key)] = wh
            return wh
        if self.options.warehouse_mode != "create":
            return None
        wh = await self.repo.create_warehouse(self.tenant_id, wh_name)
        self._pending[("wh", key)] = wh
        return wh

    async def resolve_supplier(self, name: str | None) -> uuid.UUID | None:
        sup_name = (name or "").strip()
        if not sup_name:
            return None
        key = sup_name.lower()
        hit = self._get("sup", key)
        if hit is not _MISSING:
            return hit
        sup = await self.repo.find_supplier(sup_name)
        if sup is not None:
            self._cache[("sup", key)] = sup.id
            return sup.id
        if self.options.supplier_mode != "create":
            return None
        sup = await self.repo.create_supplier(self.tenant_id, sup_name)
        self._pending[("sup", key)] = sup.id
        return sup.id

    async def get_or_create_category(self, name: str | None) -> uuid.UUID | None:
        return await self._get_or_create_taxonomy("cat", name, self.repo.find_category, self.repo.create_category)

    async def get_or_create_brand(self, name: str | None) -> uuid.UUID | None:
        return await self._get_or_create_taxonomy("brand", name, self.repo.find_brand, self.repo.create_brand)

    async def _get_or_create_taxonomy(self, kind, name, finder, creator) -> uuid.UUID | None:
        clean = (name or "").strip()
        if not clean:
            return None
        key = clean.lower()
        hit = self._get(kind, key)
        if hit is not _MISSING:
            return hit
        existing = await finder(clean)
        if existing is not None:
            self._cache[(kind, key)] = existing.id
            return existing.id
        created = await creator(self.tenant_id, clean)
        self._pending[(kind, key)] = created.id
        return created.id

    async def upsert_product(self, *, sku, attrs, category, brand, supplier) -> Any:
        existing = await self.repo.get_product_by_sku(sku)
        if existing is not None:
            return await self.repo.update_product(
                existing, attrs=attrs, category_id=category, brand_id=brand, supplier_id=supplier
            )
        return await self.repo.create_product(
            tenant_id=self.tenant_id, sku=sku, attrs=attrs,
            category_id=category, brand_id=brand, supplier_id=supplier,
            import_job_id=self.job_id,
        )

    async def set_initial_stock(self, *, product, warehouse, qty, unit_cost) -> None:
        inv = await self.repo.get_inventory(product.id, warehouse.id)
        if inv is None:
            inv = await self.repo.create_inventory(self.tenant_id, product.id, warehouse.id)
        inv.qty_on_hand = inv.qty_on_hand + qty
        inv.version += 1
        await self.repo.add_movement(
            tenant_id=self.tenant_id,
            product_id=product.id,
            warehouse_id=warehouse.id,
            movement_type="initial_import",
            quantity=qty,
            reference_type="inventory_import",
            reference_id=self.job_id,
            unit_cost=unit_cost,
            reason="Excel Inventory Import",
            user_id=self.user_id,
        )


class ImportService:
    def __init__(self, repo: ImportRepository, audit: AuditRepository) -> None:
        self.repo = repo
        self.audit = audit

    # ------------------------------ targets ---------------------------- #
    @staticmethod
    def targets() -> list[TargetOut]:
        return [ImportService._target_out(imp) for imp in all_importers()]

    @staticmethod
    def target(key: str) -> TargetOut:
        return ImportService._target_out(ImportService._importer(key))

    @staticmethod
    def _importer(key: str) -> ResourceImporter:
        try:
            return get_importer(key)
        except KeyError:
            raise NotFoundError(f"Unknown import target '{key}'")

    @staticmethod
    def _target_out(imp: ResourceImporter) -> TargetOut:
        return TargetOut(
            key=imp.key,
            label=imp.label,
            fields=[
                FieldOut(
                    name=f.name, label=f.label, required=f.required,
                    kind=f.kind.value, choices=list(f.choices), aliases=list(f.aliases),
                )
                for f in imp.fields
            ],
        )

    def template(self, key: str, level: str) -> tuple[str, bytes]:
        imp = self._importer(key)
        columns = imp.template_columns(level)
        buf = io.StringIO()
        csv.writer(buf).writerow(columns)
        filename = f"{key}_{level}_template.csv"
        return filename, buf.getvalue().encode("utf-8-sig")

    # ------------------------------ upload ----------------------------- #
    async def upload(
        self, *, key: str, filename: str, data: bytes, content_type: str | None,
        tenant_id: uuid.UUID, user_id: uuid.UUID,
    ) -> UploadResponse:
        imp = self._importer(key)
        if not data:
            raise BusinessRuleError("Uploaded file is empty")
        try:
            parsed = parse_table(filename, data)
        except UnsupportedFileType as exc:
            raise BusinessRuleError(str(exc))
        except Exception as exc:  # malformed workbook, etc.
            raise BusinessRuleError(f"Could not read the file: {exc}")
        if not parsed.headers:
            raise BusinessRuleError("No header row found in the file")

        detected = detect_columns(parsed.headers, imp.fields)
        mapping_source = "detected"
        saved = await self.repo.find_mapping(key, header_signature(parsed.headers))
        if saved is not None:
            detected = merge_mapping(detected, saved.mapping)
            mapping_source = "saved"
        job = await self.repo.create_job(
            tenant_id=tenant_id, user_id=user_id, target_key=key,
            filename=filename, total_rows=len(parsed.rows),
            column_mapping=detected, status="pending",
        )
        await self.repo.save_file(
            job_id=job.id, tenant_id=tenant_id, content=data, content_type=content_type
        )
        return UploadResponse(
            job_id=job.id, target_key=key, filename=filename, status=job.status,
            total_rows=len(parsed.rows), headers=parsed.headers,
            detected_mapping=detected, mapping_source=mapping_source,
            sample_rows=self._sample(parsed.headers, parsed.rows),
        )

    # ------------------------------ preview ---------------------------- #
    async def preview(self, *, job_id: uuid.UUID, mapping: dict[str, int | None], options: ImportOptions) -> PreviewResponse:
        job = await self._require_job(job_id)
        imp = self._importer(job.target_key)
        parsed = self._reparse(job, await self._require_file(job_id))

        missing = [f.label for f in imp.fields if f.required and mapping.get(f.name) is None]
        if missing:
            return PreviewResponse(
                total_rows=len(parsed.rows), valid_count=0, invalid_count=len(parsed.rows),
                missing_required=missing, headers=parsed.headers,
                sample_rows=self._sample(parsed.headers, parsed.rows),
            )

        valid = invalid = 0
        sample_errors: list[RowErrorOut] = []
        for i, row in enumerate(parsed.rows, start=2):  # row 1 = headers
            raw = self._row_to_fields(row, mapping, imp)
            clean, errors = validate_mapped(imp.fields, raw)
            if errors:
                invalid += 1
                if len(sample_errors) < MAX_PREVIEW_ROWS:
                    sample_errors.append(RowErrorOut(row_number=i, sku=clean.get("sku"), errors=errors))
            else:
                valid += 1
        return PreviewResponse(
            total_rows=len(parsed.rows), valid_count=valid, invalid_count=invalid,
            sample_errors=sample_errors, headers=parsed.headers,
            sample_rows=self._sample(parsed.headers, parsed.rows),
        )

    # ------------------------------ confirm ---------------------------- #
    async def confirm(
        self, *, job_id: uuid.UUID, mapping: dict[str, int | None],
        options: ImportOptions, tenant_id: uuid.UUID, user_id: uuid.UUID,
    ) -> ImportJobOut:
        job = await self._require_job(job_id)
        imp = self._importer(job.target_key)
        if job.status != "pending":
            raise BusinessRuleError(f"Import job is already {job.status}")
        if not await self.repo.file_exists(job_id):
            raise NotFoundError("Uploaded file for this job is no longer available")

        missing = [f.label for f in imp.fields if f.required and mapping.get(f.name) is None]
        if missing:
            raise BusinessRuleError("Required fields are not mapped: " + ", ".join(missing))

        # Hand off to the background runner (its own session + per-tenant RLS GUC).
        # The request returns immediately; the client polls GET /imports/{id} for
        # progress + ETA, and can POST /cancel. Local import avoids an import cycle.
        from app.imports.runner import launch_import_job

        launch_import_job(
            job_id=job.id, tenant_id=tenant_id, user_id=user_id, mapping=mapping, options=options
        )
        return ImportJobOut.model_validate(job)  # status "pending" — runner flips it to running

    async def cancel(self, *, job_id: uuid.UUID, tenant_id: uuid.UUID, user_id: uuid.UUID) -> ImportJobOut:
        job = await self._require_job(job_id)
        if job.status not in ("pending", "running"):
            raise BusinessRuleError(f"Cannot cancel a {job.status} import")
        # The runner re-reads status between batches and stops safely; partial,
        # already-committed batches are kept.
        job.status = "cancelled"
        job.completed_at = _now()
        await self.repo.session.flush()
        return ImportJobOut.model_validate(job)

    async def _process_rows(
        self, *, job, importer: ResourceImporter, rows: list[tuple[int, list[str]]],
        mapping: dict[str, int | None], options: ImportOptions,
        tenant_id: uuid.UUID, user_id: uuid.UUID,
    ) -> tuple[int, int, int]:
        """Validate + persist (row_number, cells) within the CURRENT transaction, each
        row isolated in a SAVEPOINT. Used by retry() (small, synchronous). Returns
        (imported, skipped, errors)."""
        ctx = ImportContext(self.repo, tenant_id=tenant_id, user_id=user_id, job_id=job.id, options=options)
        seen_skus: set[str] = set()
        imported = skipped = errors = 0
        for i, row in rows:
            status = await self._handle_row(
                repo=self.repo, ctx=ctx, importer=importer, session=self.repo.session,
                row_number=i, cells=row, mapping=mapping, seen_skus=seen_skus,
                job_id=job.id, tenant_id=tenant_id,
            )
            if status == ROW_IMPORTED:
                imported += 1
            elif status == ROW_SKIPPED:
                skipped += 1
            else:
                errors += 1
        return imported, skipped, errors

    @staticmethod
    async def _handle_row(
        *, repo, ctx: ImportContext, importer: ResourceImporter, session,
        row_number: int, cells: list[str], mapping: dict[str, int | None],
        seen_skus: set[str], job_id: uuid.UUID, tenant_id: uuid.UUID,
    ) -> str:
        """Validate + persist ONE row inside a SAVEPOINT; record any errors. Returns
        ROW_IMPORTED | ROW_SKIPPED | ROW_ERROR. Shared by the sync path and the
        background runner. Must be called inside an active transaction."""
        raw = ImportService._row_to_fields(cells, mapping, importer)
        clean, verrs = validate_mapped(importer.fields, raw)
        sku = clean.get("sku")
        if verrs:
            for e in verrs:
                await repo.add_error(tenant_id=tenant_id, job_id=job_id, row_number=row_number, sku=sku, message=e)
            return ROW_ERROR
        if sku in seen_skus:
            await repo.add_error(
                tenant_id=tenant_id, job_id=job_id, row_number=row_number, sku=sku,
                message="Duplicate SKU within file",
            )
            return ROW_ERROR
        seen_skus.add(sku)

        try:
            async with session.begin_nested():
                result = await importer.process_row(ctx, clean)
            ctx.commit_row()
        except Exception as exc:  # DB/constraint failure on this row only
            ctx.rollback_row()
            await repo.add_error(
                tenant_id=tenant_id, job_id=job_id, row_number=row_number, sku=sku,
                message=f"Could not import row: {exc}",
            )
            return ROW_ERROR

        if result.status == ROW_IMPORTED:
            return ROW_IMPORTED
        if result.status == ROW_SKIPPED:
            for e in result.errors:
                await repo.add_error(tenant_id=tenant_id, job_id=job_id, row_number=row_number, sku=sku, message=f"Skipped: {e}")
            return ROW_SKIPPED
        for e in result.errors:
            await repo.add_error(tenant_id=tenant_id, job_id=job_id, row_number=row_number, sku=sku, message=e)
        return ROW_ERROR

    # ----------------------------- rollback ---------------------------- #
    async def rollback(self, *, job_id: uuid.UUID, tenant_id: uuid.UUID, user_id: uuid.UUID) -> ImportJobOut:
        job = await self._require_job(job_id)
        if job.status != "completed":
            raise BusinessRuleError(f"Only completed imports can be rolled back (status: {job.status})")

        movements = await self.repo.job_movements(job_id)
        pair_qty: dict[tuple[uuid.UUID, uuid.UUID], Decimal] = defaultdict(lambda: Decimal("0"))
        for mv in movements:
            pair_qty[(mv.product_id, mv.warehouse_id)] += mv.quantity

        # Safety: refuse if any affected (product, warehouse) saw other stock activity.
        for pid, wid in pair_qty:
            if await self.repo.other_movement_exists(pid, wid, job_id):
                raise BusinessRuleError(
                    "Cannot roll back: stock has moved since this import for one or more "
                    "products. Reverse those movements first."
                )

        # Reverse opening stock, then delete the import's movements.
        for (pid, wid), qty in pair_qty.items():
            inv = await self.repo.get_inventory_for_update(pid, wid)
            if inv is not None:
                inv.qty_on_hand = inv.qty_on_hand - qty
                inv.version += 1
        for mv in movements:
            await self.repo.delete_movement(mv)
        await self.repo.session.flush()

        # Hard-delete products this import created (cascades their inventory rows).
        created = await self.repo.products_created_by_job(job_id)
        for product in created:
            await self.repo.delete_product(product)
        await self.repo.session.flush()

        job.status = "rolled_back"
        await self.repo.session.flush()
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action="data.import.rollback",
            entity_type="import_job", entity_id=job.id,
            changes={"movements_reversed": len(movements), "products_deleted": len(created)},
        )
        return ImportJobOut.model_validate(job)

    # ------------------------------- retry ----------------------------- #
    async def retry(self, *, job_id: uuid.UUID, tenant_id: uuid.UUID, user_id: uuid.UUID) -> ImportJobOut:
        source = await self._require_job(job_id)
        imp = self._importer(source.target_key)
        failed = await self.repo.failed_row_numbers(job_id)
        if not failed:
            raise BusinessRuleError("No failed rows to retry")
        data = await self._require_file(job_id)
        parsed = parse_table(source.filename, data)
        mapping = source.column_mapping or {}
        options = ImportOptions(**(source.options or {}))
        rows = [(rn, parsed.rows[rn - 2]) for rn in failed if 0 <= rn - 2 < len(parsed.rows)]

        job = await self.repo.create_job(
            tenant_id=tenant_id, user_id=user_id, target_key=source.target_key,
            filename=f"{source.filename} (retry of failed rows)", total_rows=len(rows),
            column_mapping=mapping, options=source.options, status="running",
        )
        await self.repo.save_file(job_id=job.id, tenant_id=tenant_id, content=data, content_type="text/csv")
        job.started_at = _now()
        imported, skipped, errors = await self._process_rows(
            job=job, importer=imp, rows=rows, mapping=mapping, options=options,
            tenant_id=tenant_id, user_id=user_id,
        )
        job.processed_rows = len(rows)
        job.imported_rows = imported
        job.skipped_rows = skipped
        job.error_count = errors
        job.status = "completed"
        job.completed_at = _now()
        await self.repo.session.flush()
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action="data.import.retry",
            entity_type="import_job", entity_id=job.id,
            changes={"source_job": str(job_id), "retried": len(rows), "imported": imported, "errors": errors},
        )
        return ImportJobOut.model_validate(job)

    # --------------------------- error report -------------------------- #
    async def errors_csv(self, job_id: uuid.UUID) -> tuple[str, bytes]:
        job = await self._require_job(job_id)
        rows = await self.repo.list_errors(job_id)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["row_number", "sku", "error_message"])
        for r in rows:
            w.writerow([r.row_number, r.sku or "", r.error_message])
        return f"import_{str(job.id)[:8]}_errors.csv", buf.getvalue().encode("utf-8-sig")

    # ------------------------------- reads ----------------------------- #
    async def get_job(self, job_id: uuid.UUID) -> ImportJobOut:
        return ImportJobOut.model_validate(await self._require_job(job_id))

    async def list_jobs(self, *, target_key: str | None, page: int, page_size: int):
        jobs, total = await self.repo.list_jobs(target_key=target_key, page=page, page_size=page_size)
        return [ImportJobOut.model_validate(j) for j in jobs], total

    # ------------------------------ helpers ---------------------------- #
    async def _require_job(self, job_id: uuid.UUID):
        job = await self.repo.get_job(job_id)
        if job is None:
            raise NotFoundError(f"Import job {job_id} not found")
        return job

    async def _require_file(self, job_id: uuid.UUID) -> bytes:
        data = await self.repo.get_file_content(job_id)
        if data is None:
            raise NotFoundError("Uploaded file for this job is no longer available")
        return data

    @staticmethod
    def _reparse(job, data: bytes):
        return parse_table(job.filename, data)

    @staticmethod
    def _row_to_fields(row: list[str], mapping: dict[str, int | None], imp: ResourceImporter) -> dict[str, str]:
        raw: dict[str, str] = {}
        for f in imp.fields:
            idx = mapping.get(f.name)
            raw[f.name] = row[idx] if (idx is not None and 0 <= idx < len(row)) else ""
        return raw

    @staticmethod
    def _sample(headers: list[str], rows: list[list[str]]) -> list[list[str]]:
        width = len(headers)
        out = []
        for row in rows[:MAX_PREVIEW_ROWS]:
            padded = list(row[:width]) + [""] * max(0, width - len(row))
            out.append(padded)
        return out
