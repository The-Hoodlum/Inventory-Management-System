"""FastAPI dependencies: DB session, authentication, RBAC, and service wiring.

Request/transaction model
-------------------------
``get_db`` opens one transaction per request. ``get_current_user`` validates the
JWT, loads the user + permissions, and then sets the tenant GUC
(``app.current_tenant``) *transaction-locally*, so PostgreSQL RLS scopes every
subsequent business query to that tenant and the setting is cleared automatically
when the transaction ends (no leakage across pooled connections).
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.advisor.providers import build_llm_provider
from app.advisor.service import AdvisorService
from app.assistant.providers import build_llm_provider as build_assistant_provider
from app.assistant.repository import AssistantRepository
from app.assistant.service import AssistantService
from app.assistant.whatsapp import build_whatsapp_adapter
from app.container.repository import ContainerRepository
from app.container.service import ContainerService
from app.core.config import settings
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.feature_flags import is_enabled
from app.core.security import TokenTypeError, decode_access_token
from app.dashboard.repository import DashboardRepository
from app.dashboard.service import DashboardService
from app.db.session import AsyncSessionLocal
from app.demand.repository import DemandRepository
from app.demand.service import DemandService
from app.forecast.repository import ForecastRepository
from app.forecast.service import ForecastService
from app.imports.repository import ImportRepository
from app.imports.service import ImportService
from app.integrations.whatsapp.service import WhatsAppChannelService
from app.intelligence.providers.registry import build_free_providers
from app.intelligence.repository import IntelligenceRepository
from app.intelligence.service import IntelligenceService
from app.intelligence.sources.factory import build_external_source
from app.motorcycles.repository import MotorcycleRepository
from app.motorcycles.service import MotorcycleService
from app.order_requests.repository import OrderRequestRepository
from app.order_requests.service import OrderRequestService
from app.procurement.email import EmailService
from app.procurement.repository import ProcurementRepository
from app.procurement.service import ProcurementService
from app.reorder.repository import ReorderRepository
from app.reorder.service import ReorderService
from app.reports.repository import ReportsRepository
from app.reports.service import ReportsService
from app.repositories.audit_repo import AuditRepository
from app.repositories.branch_repo import BranchRepository
from app.repositories.customer_repo import CustomerRepository
from app.repositories.inventory_repo import InventoryRepository
from app.repositories.product_repo import ProductRepository
from app.repositories.refresh_repo import RefreshSessionRepository
from app.repositories.reservation_repo import ReservationRepository
from app.repositories.supplier_repo import SupplierRepository
from app.repositories.tenant_repo import TenantRepository
from app.repositories.user_admin_repo import UserAdminRepository
from app.repositories.user_repo import UserRepository
from app.repositories.warehouse_repo import WarehouseRepository
from app.sales.repository import SalesRepository
from app.sales.service import SalesService
from app.services.auth_service import AuthService
from app.services.branch_service import BranchService
from app.services.customer_service import CustomerService
from app.services.inventory_service import InventoryService
from app.services.product_service import ProductService
from app.services.supplier_service import SupplierService
from app.services.tenant_service import TenantSettingsService
from app.services.user_service import UserAdminService
from app.services.warehouse_service import WarehouseService

_bearer = HTTPBearer(auto_error=False)


# --------------------------------------------------------------------------- #
# Database session (one transaction per request)
# --------------------------------------------------------------------------- #
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        async with session.begin():  # commit on success, rollback on exception
            yield session


# --------------------------------------------------------------------------- #
# Authenticated principal
# --------------------------------------------------------------------------- #
@dataclass
class CurrentUser:
    id: uuid.UUID
    tenant_id: uuid.UUID
    email: str
    full_name: str
    permissions: set[str] = field(default_factory=set)
    roles: list[str] = field(default_factory=list)
    # Branches this user is scoped to. Empty = unrestricted (all branches; owners/admins).
    branch_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)

    @property
    def all_branches(self) -> bool:
        return not self.branch_ids


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Missing bearer token")

    try:
        payload = decode_access_token(credentials.credentials)
    except (jwt.PyJWTError, TokenTypeError) as exc:
        raise AuthenticationError("Invalid or expired token") from exc

    try:
        user_id = uuid.UUID(payload["sub"])
        token_tenant = uuid.UUID(payload["tenant_id"])
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("Malformed token claims") from exc

    users = UserRepository(db)
    user = await users.get(user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("Account not found or disabled")
    if user.tenant_id != token_tenant:
        raise AuthenticationError("Token/tenant mismatch")

    permissions = await users.get_permission_codes(user_id)
    roles = await users.get_role_names(user_id)

    # Scope the rest of the request to this tenant (RLS). Transaction-local.
    await db.execute(
        text("SELECT set_config('app.current_tenant', :tenant, true)"),
        {"tenant": str(user.tenant_id)},
    )
    # Branch scope (reads RLS-protected user_branch_access — must follow the tenant GUC).
    branch_ids = await users.get_branch_ids(user_id)

    return CurrentUser(
        id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        full_name=user.full_name,
        permissions=permissions,
        roles=roles,
        branch_ids=frozenset(branch_ids),
    )


# --------------------------------------------------------------------------- #
# Authorization
# --------------------------------------------------------------------------- #
def ensure_permission(permissions: set[str], code: str) -> None:
    """Pure permission check (unit-testable). Raises if the code is absent."""
    if code not in permissions:
        raise PermissionDeniedError(f"Missing required permission: {code}")


def require_permission(code: str):
    """Dependency factory that enforces a permission and returns the user."""

    async def _checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        ensure_permission(user.permissions, code)
        return user

    return _checker


def resolve_branch_scope(
    user: CurrentUser, requested: uuid.UUID | None = None
) -> list[uuid.UUID] | None:
    """Server-side branch boundary. Returns the branch id(s) a query may span:

    - unrestricted user (no grants): the requested branch if given, else ``None`` (= all).
    - scoped user: the requested branch (403 if it isn't one of theirs), else ALL of theirs.

    ``None`` means "no branch filter" and is only ever returned for an unrestricted user.
    A scoped user always gets a concrete, non-empty list — never all-branches.
    """
    if user.all_branches:
        return [requested] if requested is not None else None
    if requested is not None:
        if requested not in user.branch_ids:
            raise PermissionDeniedError("You are not assigned to that branch.")
        return [requested]
    return sorted(user.branch_ids)


async def resolve_warehouse_scope(
    user: CurrentUser, requested: uuid.UUID | None, warehouses: WarehouseRepository
) -> list[uuid.UUID] | None:
    """Branch boundary for WAREHOUSE-keyed reads (inventory, movements). A scoped user only
    sees warehouses inside their branch(es); a requested warehouse outside that is rejected.

    Returns the warehouse id(s) a query may span: ``None`` (no filter) only for an
    unrestricted user; a scoped user always gets a concrete list (possibly empty when their
    branches hold no warehouses, which correctly yields no rows).
    """
    if user.all_branches:
        return [requested] if requested is not None else None
    allowed = await warehouses.ids_in_branches(user.branch_ids)
    if requested is not None:
        if requested not in allowed:
            raise PermissionDeniedError("You are not assigned to that location's branch.")
        return [requested]
    return sorted(allowed)


def require_feature(key: str):
    """Dependency factory that 403s when a tenant has the given module disabled."""

    async def _checker(
        user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)
    ) -> CurrentUser:
        tenant = await TenantRepository(db).get(user.tenant_id)
        if tenant is None or not is_enabled(tenant.feature_flags, key):
            raise PermissionDeniedError(f"The '{key}' module is not enabled for this tenant.")
        return user

    return _checker


# --------------------------------------------------------------------------- #
# Service providers
# --------------------------------------------------------------------------- #
def get_auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    return AuthService(UserRepository(db), RefreshSessionRepository(db))


def get_product_service(db: AsyncSession = Depends(get_db)) -> ProductService:
    return ProductService(ProductRepository(db), AuditRepository(db))


def get_supplier_service(db: AsyncSession = Depends(get_db)) -> SupplierService:
    return SupplierService(SupplierRepository(db), AuditRepository(db))


def get_warehouse_service(db: AsyncSession = Depends(get_db)) -> WarehouseService:
    return WarehouseService(WarehouseRepository(db), AuditRepository(db))


def get_branch_service(db: AsyncSession = Depends(get_db)) -> BranchService:
    return BranchService(BranchRepository(db), AuditRepository(db))


def get_customer_service(db: AsyncSession = Depends(get_db)) -> CustomerService:
    return CustomerService(CustomerRepository(db), AuditRepository(db))


def get_inventory_service(db: AsyncSession = Depends(get_db)) -> InventoryService:
    return InventoryService(
        InventoryRepository(db),
        ProductRepository(db),
        WarehouseRepository(db),
        AuditRepository(db),
        ReservationRepository(db),
        get_notification_service(db),
    )


def get_sales_service(db: AsyncSession = Depends(get_db)) -> SalesService:
    # Sales delegates every stock movement to the inventory service (single write path),
    # so it is wired with one — sharing the request session/transaction.
    return SalesService(
        SalesRepository(db),
        AuditRepository(db),
        get_inventory_service(db),
    )


def get_dispatch_service(db: AsyncSession = Depends(get_db)):
    # Delivery notes never write stock: parts move via the inventory service (single
    # write path), bikes via the serialized registry — all on the request session.
    from app.dispatch.repository import DispatchRepository
    from app.dispatch.service import DispatchService

    return DispatchService(DispatchRepository(db), get_inventory_service(db), AuditRepository(db))


def get_customer_delivery_service(db: AsyncSession = Depends(get_db)):
    # Branch -> customer/reseller delivery (sale | consignment). Never writes stock.
    from app.customer_delivery.repository import CustomerDeliveryRepository
    from app.customer_delivery.service import CustomerDeliveryService

    return CustomerDeliveryService(CustomerDeliveryRepository(db), get_inventory_service(db), AuditRepository(db), get_notification_service(db))


def get_notification_service(db: AsyncSession = Depends(get_db)):
    # Event-driven, per-recipient notifications. Producers call emit(); the bell/inbox read.
    # The WhatsApp adapter powers opt-in push of critical events (mock until Cloud API is set).
    from app.notifications.repository import NotificationRepository
    from app.notifications.service import NotificationService

    return NotificationService(NotificationRepository(db), build_whatsapp_adapter(settings))


def get_issuance_service(db: AsyncSession = Depends(get_db)):
    # Internal issuance / handover: fungible loans go through the reservation mechanism +
    # inventory service; bikes through the serialized registry. Never writes stock.
    from app.issuance.repository import IssuanceRepository
    from app.issuance.service import IssuanceService

    return IssuanceService(IssuanceRepository(db), get_inventory_service(db), AuditRepository(db))


def get_assembly_service(db: AsyncSession = Depends(get_db)):
    # Assembly Planner: deterministic recommendation from CURRENT unit counts (assembled
    # vs unassembled). Reads no sales/demand; recommends only (assembling is the existing
    # unassembled->assembled lifecycle transition in the Motorcycle module).
    from app.assembly.repository import AssemblyRepository
    from app.assembly.service import AssemblyPlannerService

    return AssemblyPlannerService(AssemblyRepository(db), AuditRepository(db))


def get_service_followup_service(db: AsyncSession = Depends(get_db)):
    # Motorcycle service follow-up: computes the next service due for sold bikes (time-
    # only, usage-scaled) and logs services performed. Reads the serialized registry + an
    # append-only service log; writes only follow-up tables, never stock.
    from app.service_followup.repository import ServiceFollowUpRepository
    from app.service_followup.service import ServiceFollowUpService

    return ServiceFollowUpService(ServiceFollowUpRepository(db), AuditRepository(db))


def get_bike_issue_service(db: AsyncSession = Depends(get_db)):
    # Internal bike repairs: parts are CONSUMED through the inventory service (single write
    # path); the serialized unit is held/released via its own registry event. Never writes
    # qty_on_hand directly, and never creates a customer sale.
    from app.bike_issues.repository import BikeIssueRepository
    from app.bike_issues.service import BikeIssueService

    return BikeIssueService(BikeIssueRepository(db), get_inventory_service(db), AuditRepository(db))


def get_reorder_service(db: AsyncSession = Depends(get_db)) -> ReorderService:
    # PO creation is delegated to the single procurement path, so the reorder
    # service is wired with a ProcurementService (not its own PO repository).
    procurement = ProcurementService(
        ProcurementRepository(db),
        InventoryRepository(db),
        AuditRepository(db),
        EmailService.from_settings(),
    )
    return ReorderService(
        ReorderRepository(db),
        procurement,
        AuditRepository(db),
        DemandRepository(db),
        IntelligenceRepository(db),  # enables risk-aware procurement
    )


def get_procurement_service(db: AsyncSession = Depends(get_db)) -> ProcurementService:
    return ProcurementService(
        ProcurementRepository(db),
        InventoryRepository(db),
        AuditRepository(db),
        EmailService.from_settings(),
        get_notification_service(db),
    )


def get_dashboard_service(db: AsyncSession = Depends(get_db)) -> DashboardService:
    return DashboardService(DashboardRepository(db))


def get_finance_service(db: AsyncSession = Depends(get_db)):
    # Cash book / treasury: accounts + the append-only movement ledger + the single
    # derived-balance calculation. Every money movement is one append-only entry (never a
    # stored balance); corrections are reversals. Runs on the request session/transaction.
    from app.finance.repository import FinanceRepository
    from app.finance.service import FinanceService

    return FinanceService(FinanceRepository(db), AuditRepository(db))


def get_reports_service(db: AsyncSession = Depends(get_db)) -> ReportsService:
    return ReportsService(ReportsRepository(db))


def get_user_admin_service(db: AsyncSession = Depends(get_db)) -> UserAdminService:
    return UserAdminService(UserAdminRepository(db), AuditRepository(db))


def get_demand_service(db: AsyncSession = Depends(get_db)) -> DemandService:
    return DemandService(DemandRepository(db), AuditRepository(db))


def get_forecast_service(db: AsyncSession = Depends(get_db)) -> ForecastService:
    return ForecastService(
        ForecastRepository(db),
        DemandRepository(db),
        AuditRepository(db),
        IntelligenceRepository(db),  # risk-aware forecasts
    )


def get_container_service(db: AsyncSession = Depends(get_db)) -> ContainerService:
    return ContainerService(ContainerRepository(db))


def get_advisor_service(db: AsyncSession = Depends(get_db)) -> AdvisorService:
    # The LLM narrator is built from settings: Claude when configured (key present),
    # otherwise inert. The deterministic briefing is always served.
    return AdvisorService(
        ReorderRepository(db),
        IntelligenceRepository(db),
        ForecastRepository(db),
        ContainerRepository(db),
        build_llm_provider(settings),
    )


def get_import_service(db: AsyncSession = Depends(get_db)) -> ImportService:
    # Generic data-import engine (first target: inventory). Reference data
    # (warehouses/suppliers/categories/brands) is created-or-linked per the
    # request options; opening stock is written as 'initial_import' movements.
    return ImportService(ImportRepository(db), AuditRepository(db))


def get_assistant_service(db: AsyncSession = Depends(get_db)) -> AssistantService:
    # OpenAI function-calling assistant when configured (ASSISTANT_ENABLED + OPENAI_API_KEY),
    # otherwise inert. Tools run through the repository (RLS + branch-scoped); the model
    # never touches the DB directly.
    return AssistantService(
        AssistantRepository(db),
        build_assistant_provider(settings),
        max_tool_rounds=settings.assistant_max_tool_rounds,
        # enables the permission-gated create_order_request write tool
        order_requests=OrderRequestService(OrderRequestRepository(db), AuditRepository(db)),
    )


def get_tenant_service(db: AsyncSession = Depends(get_db)) -> TenantSettingsService:
    return TenantSettingsService(TenantRepository(db), AuditRepository(db))


def get_order_request_service(db: AsyncSession = Depends(get_db)) -> OrderRequestService:
    return OrderRequestService(OrderRequestRepository(db), AuditRepository(db), get_notification_service(db))


def get_motorcycle_service(db: AsyncSession = Depends(get_db)) -> MotorcycleService:
    # Serialized-asset registry. Selling links to the existing sales documents; the
    # unit's own event ledger is its immutable lifecycle history.
    return MotorcycleService(MotorcycleRepository(db), AuditRepository(db), get_notification_service(db))


def get_whatsapp_channel_service(db: AsyncSession = Depends(get_db)) -> WhatsAppChannelService:
    # Thin WhatsApp transport over the single AssistantService brain. Selects the mock or
    # Meta Cloud adapter by config; inbound routing is inert until WHATSAPP_DEFAULT_TENANT_ID.
    return WhatsAppChannelService(
        assistant=get_assistant_service(db),
        adapter=build_whatsapp_adapter(settings),
        session=db,
        default_tenant_id=settings.whatsapp_default_tenant_id,
        verify_token=settings.whatsapp_verify_token,
    )


def get_intelligence_service(db: AsyncSession = Depends(get_db)) -> IntelligenceService:
    # The external feed source is built from settings: Freightos when configured
    # (FREIGHTOS_ENABLED + key), otherwise inert (NullSource). Supplier risk is
    # always computed internally; freight/etc. feeds activate via env config.
    return IntelligenceService(
        IntelligenceRepository(db),
        AuditRepository(db),
        source=build_external_source(settings),
        extra_providers=build_free_providers(settings),
    )
