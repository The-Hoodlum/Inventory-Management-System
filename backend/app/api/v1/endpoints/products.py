"""Product endpoints: create, search/list, get, update, delete."""
from __future__ import annotations

import math
import uuid

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.api.v1.deps import CurrentUser, get_product_service, require_permission
from app.core.permissions import P
from app.schemas.common import Page
from app.schemas.product import ProductCreate, ProductOut, ProductStatus, ProductUpdate
from app.services.product_service import ProductService

router = APIRouter()


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreate,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.PRODUCT_CREATE)),
    svc: ProductService = Depends(get_product_service),
) -> ProductOut:
    product = await svc.create(
        tenant_id=user.tenant_id, user_id=user.id, data=payload, ip=_ip(request)
    )
    return ProductOut.model_validate(product)


@router.get("", response_model=Page[ProductOut])
async def list_products(
    search: str | None = Query(default=None, description="Match SKU, name, or barcode"),
    category_id: uuid.UUID | None = None,
    brand_id: uuid.UUID | None = None,
    supplier_id: uuid.UUID | None = None,
    status_: ProductStatus | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    _: CurrentUser = Depends(require_permission(P.PRODUCT_READ)),
    svc: ProductService = Depends(get_product_service),
) -> Page[ProductOut]:
    items, total = await svc.search(
        search=search,
        category_id=category_id,
        brand_id=brand_id,
        supplier_id=supplier_id,
        status=status_,
        page=page,
        page_size=page_size,
    )
    return Page[ProductOut](
        items=[ProductOut.model_validate(p) for p in items],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/{product_id}", response_model=ProductOut)
async def get_product(
    product_id: uuid.UUID,
    _: CurrentUser = Depends(require_permission(P.PRODUCT_READ)),
    svc: ProductService = Depends(get_product_service),
) -> ProductOut:
    return ProductOut.model_validate(await svc.get(product_id))


@router.patch("/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: uuid.UUID,
    payload: ProductUpdate,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.PRODUCT_UPDATE)),
    svc: ProductService = Depends(get_product_service),
) -> ProductOut:
    product = await svc.update(
        tenant_id=user.tenant_id,
        user_id=user.id,
        product_id=product_id,
        data=payload,
        ip=_ip(request),
    )
    return ProductOut.model_validate(product)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_product(
    product_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.PRODUCT_DELETE)),
    svc: ProductService = Depends(get_product_service),
) -> Response:
    await svc.delete(
        tenant_id=user.tenant_id,
        user_id=user.id,
        product_id=product_id,
        ip=_ip(request),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
