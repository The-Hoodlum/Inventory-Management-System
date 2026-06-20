"""In-process background runner for imports (Phase 3).

Confirm hands a job here; this runs it off the request, in its own DB session with
the per-tenant RLS GUC set exactly as a request would (mirrors
``intelligence/scheduler.py``). Rows are processed in independently-committed batches
so progress survives interruption, the cancel flag is checked between batches, and
50k+ rows never block the browser. Fire-and-forget tasks are tracked in ``_TASKS`` so
they aren't garbage-collected mid-run.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import uuid

from sqlalchemy import select, text, update

from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.imports.domain.detection import header_signature
from app.imports.domain.fields import ROW_IMPORTED, ROW_SKIPPED
from app.imports.domain.parsing import parse_table
from app.imports.domain.registry import get_importer
from app.imports.repository import ImportRepository
from app.imports.schemas import ImportOptions
from app.imports.service import ImportContext, ImportService
from app.models import ImportJob
from app.repositories.audit_repo import AuditRepository

logger = get_logger(__name__)

BATCH_SIZE = 500
_TASKS: set[asyncio.Task] = set()


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


async def _set_tenant(session, tenant_id: uuid.UUID) -> None:
    await session.execute(
        text("SELECT set_config('app.current_tenant', :t, true)"), {"t": str(tenant_id)}
    )


def launch_import_job(
    *, job_id: uuid.UUID, tenant_id: uuid.UUID, user_id: uuid.UUID,
    mapping: dict[str, int | None], options: ImportOptions,
) -> None:
    """Schedule the import to run in the background and return immediately."""
    task = asyncio.create_task(_safe_run(job_id, tenant_id, user_id, mapping, options))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


async def _safe_run(job_id, tenant_id, user_id, mapping, options) -> None:
    try:
        await run_import_job(
            job_id=job_id, tenant_id=tenant_id, user_id=user_id, mapping=mapping, options=options
        )
    except Exception as exc:  # noqa: BLE001 — never let the background task crash silently
        logger.exception("import_job_failed", job_id=str(job_id), error=str(exc))
        try:
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    await _set_tenant(session, tenant_id)
                    await ImportRepository(session).add_error(
                        tenant_id=tenant_id, job_id=job_id, row_number=0, sku=None,
                        message=f"Import failed: {exc}",
                    )
                    await session.execute(
                        update(ImportJob).where(ImportJob.id == job_id)
                        .values(status="failed", completed_at=_now())
                    )
        except Exception:  # noqa: BLE001
            logger.exception("import_job_fail_mark_failed", job_id=str(job_id))


async def run_import_job(
    *, job_id: uuid.UUID, tenant_id: uuid.UUID, user_id: uuid.UUID,
    mapping: dict[str, int | None], options: ImportOptions,
) -> None:
    if not isinstance(options, ImportOptions):
        options = ImportOptions(**(options or {}))

    async with AsyncSessionLocal() as session:
        # 1. Claim the job (abort if it was cancelled before we started).
        async with session.begin():
            await _set_tenant(session, tenant_id)
            job = await session.get(ImportJob, job_id)
            if job is None or job.status != "pending":
                return
            job.status = "running"
            job.started_at = _now()
            job.column_mapping = mapping
            job.options = options.model_dump()
            filename, target_key = job.filename, job.target_key

        # 2. Load the uploaded bytes (committed at upload time) and parse (pure).
        async with session.begin():
            await _set_tenant(session, tenant_id)
            data = await ImportRepository(session).get_file_content(job_id)
        if data is None:
            await _fail_job(session, tenant_id, job_id, "Uploaded file is no longer available")
            return
        parsed = parse_table(filename, data)
        importer = get_importer(target_key)
        rows = list(enumerate(parsed.rows, start=2))  # (file_row_number, cells)
        total = len(rows)

        repo = ImportRepository(session)
        ctx = ImportContext(repo, tenant_id=tenant_id, user_id=user_id, job_id=job_id, options=options)
        seen_skus: set[str] = set()
        imported = skipped = errors = processed = 0
        cancelled = False

        # 3. Process in independently-committed batches.
        for start in range(0, total, BATCH_SIZE):
            async with session.begin():  # cancel check (sees committed cancel)
                await _set_tenant(session, tenant_id)
                status = await session.scalar(select(ImportJob.status).where(ImportJob.id == job_id))
            if status == "cancelled":
                cancelled = True
                break

            async with session.begin():
                await _set_tenant(session, tenant_id)
                for i, cells in rows[start:start + BATCH_SIZE]:
                    outcome = await ImportService._handle_row(
                        repo=repo, ctx=ctx, importer=importer, session=session,
                        row_number=i, cells=cells, mapping=mapping, seen_skus=seen_skus,
                        job_id=job_id, tenant_id=tenant_id,
                    )
                    processed += 1
                    if outcome == ROW_IMPORTED:
                        imported += 1
                    elif outcome == ROW_SKIPPED:
                        skipped += 1
                    else:
                        errors += 1
                await session.execute(
                    update(ImportJob).where(ImportJob.id == job_id).values(
                        processed_rows=processed, imported_rows=imported,
                        skipped_rows=skipped, error_count=errors,
                    )
                )
            # Keep memory flat across 50k rows: drop the batch's ORM objects. The
            # ctx's cached reference entities are detached but retain their loaded
            # ids (expire_on_commit=False), so they're still reusable.
            session.expunge_all()

        # 4. Finalize.
        async with session.begin():
            await _set_tenant(session, tenant_id)
            await session.execute(
                update(ImportJob).where(ImportJob.id == job_id).values(
                    processed_rows=processed, imported_rows=imported, skipped_rows=skipped,
                    error_count=errors, completed_at=_now(),
                    status="cancelled" if cancelled else "completed",
                )
            )
            audit = AuditRepository(session)
            if cancelled:
                await audit.add(
                    tenant_id=tenant_id, user_id=user_id, action="data.import.cancelled",
                    entity_type="import_job", entity_id=job_id,
                    changes={"processed": processed, "imported": imported, "errors": errors},
                )
            else:
                await ImportRepository(session).upsert_mapping(
                    tenant_id=tenant_id, target_key=target_key,
                    signature=header_signature(parsed.headers), mapping=mapping, user_id=user_id,
                )
                await audit.add(
                    tenant_id=tenant_id, user_id=user_id, action="data.import",
                    entity_type="import_job", entity_id=job_id,
                    changes={
                        "target": target_key, "filename": filename, "total": total,
                        "imported": imported, "skipped": skipped, "errors": errors, "mode": "background",
                    },
                )
        logger.info(
            "import_job_done", job_id=str(job_id),
            status="cancelled" if cancelled else "completed",
            imported=imported, skipped=skipped, errors=errors,
        )


async def _fail_job(session, tenant_id: uuid.UUID, job_id: uuid.UUID, message: str) -> None:
    async with session.begin():
        await _set_tenant(session, tenant_id)
        await ImportRepository(session).add_error(
            tenant_id=tenant_id, job_id=job_id, row_number=0, sku=None, message=message
        )
        await session.execute(
            update(ImportJob).where(ImportJob.id == job_id).values(status="failed", completed_at=_now())
        )
