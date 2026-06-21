"""Application configuration, loaded from environment variables / .env."""
from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# The built-in development secret. Startup checks refuse to run with this value
# in production (see app.main).
DEFAULT_JWT_SECRET = "CHANGE_ME_use_a_long_random_secret"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- App ---
    app_name: str = "Inventory & Procurement API"
    api_v1_prefix: str = "/api/v1"
    environment: str = "development"  # development | staging | production
    debug: bool = False

    # --- Database (async driver required: postgresql+asyncpg://) ---
    database_url: str = (
        "postgresql+asyncpg://app_user:change-me@localhost:5432/inventory"
    )
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_pre_ping: bool = True

    # --- JWT / auth ---
    jwt_secret_key: str = DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # --- Login lockout (failed-login throttling) ---
    lockout_max_attempts: int = 5
    lockout_window_seconds: int = 900     # window in which failures accumulate
    lockout_duration_seconds: int = 900   # lock duration once the threshold is hit

    # --- CORS ---
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173", "http://localhost:3000"]

    # --- Edge protection (rate limiting, security headers, HTTPS) ---
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 120         # general API limit, per client IP
    auth_rate_limit_per_minute: int = 10     # stricter limit for /auth/* (login, refresh)
    trust_proxy_headers: bool = False        # honor X-Forwarded-For (only behind a trusted proxy)
    security_headers_enabled: bool = True
    hsts_enabled: bool = False               # enable once served over HTTPS
    hsts_max_age: int = 31536000
    https_redirect: bool = False             # redirect http->https (enable behind TLS termination)

    # --- Logging ---
    log_level: str = "INFO"
    log_json: bool = True

    # --- SMTP / email (optional; sending is skipped when disabled) ---
    smtp_enabled: bool = False
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    smtp_from: str = "no-reply@example.com"

    # --- Freightos freight-rate intelligence (optional external source) ---
    # Disabled by default. When FREIGHTOS_ENABLED=true AND a key is present, the
    # intelligence layer pulls freight-rate signals from Freightos; otherwise the
    # source stays inert (no calls, no data) — see app.intelligence.sources.
    freightos_enabled: bool = False
    freightos_api_key: str | None = None
    freightos_api_secret: str | None = None
    freightos_base_url: str = "https://api.freightos.com/api/v1"
    # How the key+secret are presented to Freightos. See the auth-flow doc in
    # app/intelligence/sources/freightos.py:
    #   basic   -> Authorization: Basic base64(key:secret)   (default)
    #   oauth2  -> client_credentials grant at FREIGHTOS_TOKEN_URL -> Bearer token
    #   headers -> x-api-key / x-api-secret request headers
    freightos_auth_mode: str = "basic"
    freightos_token_url: str = "https://api.freightos.com/oauth/token"
    # Freightos CO2 API endpoint path (POST). Confirm against your plan; kept
    # configurable so no code change is needed to point at the right endpoint.
    freightos_index_path: str = "/co2calc"
    freightos_timeout_seconds: float = 20.0
    # Lanes to pull, comma-separated origin-destination keys, e.g.
    # "CNSHA-USLAX,CNSHA-NLRTM". Empty = the provider's default tracked lanes.
    freightos_lanes: Annotated[list[str], NoDecode] = []

    # --- AI Supply Chain Analyst (Phase 10; optional LLM narration) ---
    # Disabled by default. The advisor always serves a deterministic, explainable
    # briefing; when ADVISOR_LLM_ENABLED=true AND ANTHROPIC_API_KEY is set, it also
    # asks Claude to narrate the (grounded) findings. Otherwise no LLM call is made.
    advisor_llm_enabled: bool = False
    anthropic_api_key: str | None = None
    advisor_model: str = "claude-opus-4-8"
    advisor_base_url: str = "https://api.anthropic.com/v1/messages"
    advisor_max_tokens: int = 1024
    advisor_timeout_seconds: float = 30.0

    # --- Conversational assistant (WhatsApp/OpenAI; optional, inert by default) ---
    # The assistant answers natural-language questions via OpenAI function-calling over
    # the platform's own read services (the model never touches the DB directly).
    # Disabled unless ASSISTANT_ENABLED=true AND OPENAI_API_KEY is set.
    assistant_enabled: bool = False
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    assistant_max_tokens: int = 1024
    assistant_timeout_seconds: float = 30.0
    assistant_max_tool_rounds: int = 5  # cap LLM<->tool loops per question
    # Short-lived in-process cache for repeated stock lookups (cuts duplicate DB hits).
    assistant_cache_enabled: bool = True
    assistant_cache_ttl_seconds: int = 30

    # Proactive alerts (OPTIONAL, off by default). When enabled, a scheduler delivers
    # low-stock, daily-sales, weekly, and PO-approval notifications via the WhatsApp adapter.
    assistant_alerts_enabled: bool = False
    assistant_alerts_interval_minutes: int = 60
    assistant_daily_summary_hour: int = 17      # local closing hour (0-23)
    assistant_weekly_report_weekday: int = 0    # Monday=0 .. Sunday=6

    # WhatsApp channel adapter. 'mock' records messages (default; for testing).
    # 'cloud' = Meta WhatsApp Cloud API (needs phone id + token). The assistant engine
    # is identical for both — only this selector + credentials change.
    whatsapp_provider: str = "mock"             # mock | cloud
    whatsapp_phone_number_id: str | None = None
    whatsapp_access_token: str | None = None
    whatsapp_verify_token: str | None = None    # for the Meta webhook GET handshake
    whatsapp_api_base_url: str = "https://graph.facebook.com/v21.0"

    # --- External intelligence providers (production feeds; all OPTIONAL, inert by default) ---
    # Each provider is off until enabled; enabling one lets ingest/the scheduler pull
    # from it and convert results into intelligence signals (which already feed risk,
    # forecasting, and reorder). Free providers need no key except OpenWeather. Paid
    # providers (Freightos/Xeneta/Trading Economics) plug into the same registry later
    # without touching the core engine.
    intel_http_timeout_seconds: float = 20.0
    intel_exchangerate_enabled: bool = False
    intel_exchangerate_base_url: str = "https://api.exchangerate.host"
    intel_exchangerate_api_key: str | None = None       # access_key (free tier)
    intel_worldbank_enabled: bool = False
    intel_worldbank_base_url: str = "https://api.worldbank.org/v2"
    intel_imf_enabled: bool = False
    intel_imf_base_url: str = "https://www.imf.org/external/datamapper/api/v1"
    intel_comtrade_enabled: bool = False
    intel_comtrade_base_url: str = "https://comtradeapi.un.org"
    intel_comtrade_api_key: str | None = None
    intel_gdelt_enabled: bool = False
    intel_gdelt_base_url: str = "https://api.gdeltproject.org/api/v2"
    intel_openweather_enabled: bool = False
    intel_openweather_base_url: str = "https://api.openweathermap.org/data/2.5"
    intel_openweather_api_key: str | None = None

    # Daily intelligence scheduler (background pull → signals → risk → scores). Off by default.
    intel_scheduler_enabled: bool = False
    intel_scheduler_interval_hours: int = 24

    # --- Company identity (rendered on generated purchase-order documents) ---
    company_name: str = "Your Company"
    company_address: str = ""
    company_email: str = ""
    company_phone: str = ""
    po_terms: str = (
        "Payment due within 30 days of receipt. Goods remain the property of "
        "the supplier until paid in full. Please quote the PO number on all "
        "correspondence and delivery notes."
    )

    @field_validator("database_url")
    @classmethod
    def _require_async_driver(cls, v: str) -> str:
        # The application runs on the async engine; migrations use the sync driver.
        if v.startswith("postgresql://"):
            # Tolerate a plain URL by upgrading it to the async driver.
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    @field_validator("cors_origins", "freightos_lanes", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def freightos_configured(self) -> bool:
        """True only when Freightos is enabled AND both credentials are present.
        Freightos developer apps issue an API key *and* a secret — both are
        required for any authentication mode."""
        return self.freightos_enabled and bool(self.freightos_api_key) and bool(self.freightos_api_secret)

    @property
    def advisor_llm_configured(self) -> bool:
        """True only when the advisor LLM is enabled AND an API key is present;
        otherwise the advisor stays deterministic (no external call)."""
        return self.advisor_llm_enabled and bool(self.anthropic_api_key)

    @property
    def assistant_configured(self) -> bool:
        """True only when the assistant is enabled AND an OpenAI key is present."""
        return self.assistant_enabled and bool(self.openai_api_key)

    @property
    def whatsapp_cloud_configured(self) -> bool:
        """True when the Meta WhatsApp Cloud API has both a phone-number id and token."""
        return bool(self.whatsapp_phone_number_id and self.whatsapp_access_token)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
