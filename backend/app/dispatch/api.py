"""Typed delivery / dispatch note endpoints (mounted at /api/v1/delivery-notes)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response

from app.api.v1.deps import CurrentUser, get_dispatch_service, require_permission
from app.core.permissions import P
from app.dispatch.schemas import (
    CancelBody,
    DispatchNoteCreate,
    DispatchNoteOut,
    DispatchReceive,
)
from app.dispatch.service import DispatchService

router = APIRouter()


@router.post("", response_model=DispatchNoteOut, status_code=201)
async def create_note(
    payload: DispatchNoteCreate,
    user: CurrentUser = Depends(require_permission(P.DELIVERY_NOTE_DISPATCH)),
    svc: DispatchService = Depends(get_dispatch_service),
) -> DispatchNoteOut:
    return await svc.create(tenant_id=user.tenant_id, user_id=user.id, payload=payload)


@router.get("", response_model=list[DispatchNoteOut])
async def list_notes(
    branch_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    type_filter: str | None = Query(default=None, alias="type"),
    limit: int = Query(default=100, ge=1, le=500),
    _: CurrentUser = Depends(require_permission(P.DELIVERY_NOTE_READ)),
    svc: DispatchService = Depends(get_dispatch_service),
) -> list[DispatchNoteOut]:
    return await svc.list_notes(branch_id=branch_id, status=status_filter, dispatch_type=type_filter, limit=limit)


@router.get("/{note_id}", response_model=DispatchNoteOut)
async def get_note(
    note_id: uuid.UUID,
    _: CurrentUser = Depends(require_permission(P.DELIVERY_NOTE_READ)),
    svc: DispatchService = Depends(get_dispatch_service),
) -> DispatchNoteOut:
    return await svc.get(note_id)


@router.post("/{note_id}/dispatch", response_model=DispatchNoteOut)
async def dispatch_note(
    note_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission(P.DELIVERY_NOTE_DISPATCH)),
    svc: DispatchService = Depends(get_dispatch_service),
) -> DispatchNoteOut:
    return await svc.dispatch(tenant_id=user.tenant_id, user_id=user.id, note_id=note_id)


@router.post("/{note_id}/receive", response_model=DispatchNoteOut)
async def receive_note(
    note_id: uuid.UUID,
    payload: DispatchReceive,
    user: CurrentUser = Depends(require_permission(P.DELIVERY_NOTE_RECEIVE)),
    svc: DispatchService = Depends(get_dispatch_service),
) -> DispatchNoteOut:
    return await svc.receive(tenant_id=user.tenant_id, user_id=user.id, note_id=note_id, payload=payload)


@router.post("/{note_id}/cancel", response_model=DispatchNoteOut)
async def cancel_note(
    note_id: uuid.UUID,
    payload: CancelBody,
    user: CurrentUser = Depends(require_permission(P.DELIVERY_NOTE_DISPATCH)),
    svc: DispatchService = Depends(get_dispatch_service),
) -> DispatchNoteOut:
    return await svc.cancel(tenant_id=user.tenant_id, user_id=user.id, note_id=note_id, reason=payload.reason)


@router.get("/{note_id}/pdf")
async def note_pdf(
    note_id: uuid.UUID,
    _: CurrentUser = Depends(require_permission(P.DELIVERY_NOTE_READ)),
    svc: DispatchService = Depends(get_dispatch_service),
) -> Response:
    from app.dispatch.pdf import build_dispatch_note_pdf

    note = await svc.get(note_id)
    pdf = build_dispatch_note_pdf(note)
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{note.note_number}.pdf"'},
    )
