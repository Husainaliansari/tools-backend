"""Base application settings.

All configuration is sourced from the environment (Twelve-Factor App, factor
III). No secret or environment-specific value is ever hard-coded here; defaults
present in this file are safe, non-secret fallbacks suitable for local
development only.

The settings object is the single source of truth for configuration and is
consumed everywhere via :func:`app.config.get_settings`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import (
    AnyHttpUrl,
    Field,
    PostgresDsn,
    RedisDsn,
    computed_field,
    field_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "staging", "production", "testing"]


class BaseAppSettings(BaseSettings):
    """Shared settings for every environment.

    Environment-specific subclasses (see ``development.py`` / ``production.py``)
    override individual fields. Values are read from environment variables and,
    if present, an ``.env`` file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --------------------------------------------------------------------- #
    # Application metadata (surfaced in OpenAPI docs)
    # --------------------------------------------------------------------- #
    PROJECT_NAME: str = "FastAPI Enterprise Backend"
    PROJECT_DESCRIPTION: str = (
        "Production-ready FastAPI backend foundation. Clean architecture, "
        "fully configured, ready for feature development."
    )
    VERSION: str = "0.1.0"
    APP_ENV: Environment = "development"
    DEBUG: bool = False

    # --------------------------------------------------------------------- #
    # API / server
    # --------------------------------------------------------------------- #
    API_V1_PREFIX: str = "/api/v1"
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # OpenAPI / documentation endpoints. Disabled by toggling in prod config.
    DOCS_URL: str | None = "/docs"
    REDOC_URL: str | None = "/redoc"
    OPENAPI_URL: str | None = "/openapi.json"

    # --------------------------------------------------------------------- #
    # Security
    # --------------------------------------------------------------------- #
    # SECRET_KEY MUST be provided via the environment in every real deployment.
    SECRET_KEY: str = Field(
        default="change-me-in-production-this-is-not-a-secret",
        min_length=1,
        description="Cryptographic secret. Override via env in all deployments.",
    )
    # JWT session tokens.
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14
    # Hosts allowed by the TrustedHost middleware (Host header allow-list).
    ALLOWED_HOSTS: list[str] = Field(default_factory=lambda: ["*"])
    # Origins allowed by CORS middleware.
    CORS_ORIGINS: list[AnyHttpUrl | Literal["*"]] = Field(default_factory=list)
    CORS_ALLOW_CREDENTIALS: bool = True

    # --------------------------------------------------------------------- #
    # PostgreSQL (SQLAlchemy)
    # --------------------------------------------------------------------- #
    POSTGRES_SCHEME: str = "postgresql+asyncpg"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "app"

    # Connection pool tuning.
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800
    DB_POOL_PRE_PING: bool = True
    DB_ECHO: bool = False

    # --------------------------------------------------------------------- #
    # Redis
    # --------------------------------------------------------------------- #
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str | None = None

    # --------------------------------------------------------------------- #
    # Celery (broker/result backend default to Redis; override as needed)
    # --------------------------------------------------------------------- #
    CELERY_BROKER_URL: str | None = None
    CELERY_RESULT_BACKEND: str | None = None
    CELERY_TASK_ALWAYS_EAGER: bool = False
    #: With eager mode, run the task in a background thread instead of inline
    #: so the API responds immediately and clients can poll progress. Meant
    #: for broker-less local development; tests keep inline execution.
    CELERY_EAGER_BACKGROUND: bool = False

    # --------------------------------------------------------------------- #
    # Local storage
    # --------------------------------------------------------------------- #
    # Root of the on-disk storage tree. Relative paths resolve against the
    # process working directory (the backend project root in all run modes).
    STORAGE_ROOT: Path = Path("storage")

    # --------------------------------------------------------------------- #
    # File uploads
    # --------------------------------------------------------------------- #
    # Legacy global caps. Uploads and jobs are now governed by the per-plan
    # limits in ``app/config/plans.py``; MAX_FILES_PER_UPLOAD remains the
    # fallback for ``validate_file_count`` callers without plan context.
    MAX_UPLOAD_SIZE_MB: int = 50
    MAX_FILES_PER_UPLOAD: int = 20
    # Streaming chunk size for reading uploads / writing downloads (bytes).
    UPLOAD_CHUNK_SIZE: int = 1024 * 1024

    # --------------------------------------------------------------------- #
    # File retention & cleanup
    # --------------------------------------------------------------------- #
    # How long uploaded/processed files remain downloadable before the
    # cleanup scheduler removes them.
    FILE_RETENTION_HOURS: int = 24
    # Temp workspaces older than this are considered orphaned and purged.
    TEMP_FILE_MAX_AGE_MINUTES: int = 120
    # How often the Celery Beat cleanup task runs.
    CLEANUP_INTERVAL_MINUTES: int = 15

    # --------------------------------------------------------------------- #
    # External PDF tooling (Ghostscript, QPDF, LibreOffice, ...)
    # --------------------------------------------------------------------- #
    # Hard wall-clock limit for a single external command invocation.
    TOOL_COMMAND_TIMEOUT_SECONDS: int = 240
    # LibreOffice launcher. May contain arguments (it is shlex-split), so a
    # quoted absolute path or a wrapper command both work.
    SOFFICE_BIN: str = "soffice"
    # Optional unoserver client. When set, Office conversions go through an
    # *externally managed* unoserver instance (no per-conversion LibreOffice
    # startup). Takes precedence over OFFICE_ENGINE below.
    UNOCONVERT_BIN: str = ""
    # Office conversion engine selection:
    #   auto      — run a managed unoserver pool when one can be launched on
    #               this machine, otherwise fall back to per-conversion
    #               soffice (the safe default on both Windows and Linux).
    #   unoserver — require the managed pool; conversions fail loudly when it
    #               cannot start (surfaces misconfiguration in production).
    #   soffice   — always launch one soffice process per conversion.
    OFFICE_ENGINE: Literal["auto", "unoserver", "soffice"] = "auto"
    # Explicit launcher for the managed unoserver *server* process (shlex
    # split, may contain arguments). Empty = auto-detect: `unoserver` on
    # PATH, LibreOffice's bundled python (Windows), or the current
    # interpreter when both `unoserver` and `uno` are importable (Linux).
    UNOSERVER_BIN: str = ""
    # Long-lived LibreOffice instances kept per worker process by the managed
    # engine. Each instance holds ~200-400 MB RSS and converts one document
    # at a time; this also caps in-process conversion parallelism.
    UNOSERVER_POOL_SIZE: int = 2
    # Warm LibreOffice user profiles kept per worker process. Reusing a
    # bootstrapped profile skips soffice's first-run setup on every
    # conversion; the pool size caps how many soffice instances run at once.
    SOFFICE_PROFILE_POOL_SIZE: int = 4
    # Poppler's PDF rasteriser (PDF -> JPG/PNG page images).
    PDFTOPPM_BIN: str = "pdftoppm"
    # Ghostscript (PDF compression). Windows binary is usually gswin64c.
    GHOSTSCRIPT_BIN: str = "gs"
    # OCRmyPDF (adds a searchable text layer to scanned PDFs). The bare name
    # falls back to `python -m ocrmypdf` in this venv when not on PATH.
    OCRMYPDF_BIN: str = "ocrmypdf"
    # Tesseract (the OCR engine underneath OCRmyPDF; also used directly for
    # language auto-detection). Bare name falls back to well-known Windows
    # install locations when not on PATH.
    TESSERACT_BIN: str = "tesseract"
    # Directory of Tesseract .traineddata language packs (exported as
    # TESSDATA_PREFIX to OCR subprocesses). Empty = Tesseract's bundled dir.
    TESSDATA_DIR: str = ""
    # Repair PDF needs no external binary — it rebuilds damaged PDFs in-process
    # via libqpdf, bundled inside pikepdf (an existing dependency).
    # PDF->image rendering: documents larger than this many pages are rendered
    # in parallel chunks; worker thread count for those chunks.
    RENDER_PARALLEL_THRESHOLD_PAGES: int = 16
    RENDER_PARALLEL_WORKERS: int = 4

    # --------------------------------------------------------------------- #
    # Upload rate limiting (fail-open when Redis is unavailable)
    # --------------------------------------------------------------------- #
    UPLOAD_RATE_LIMIT_PER_MINUTE: int = 30

    # --------------------------------------------------------------------- #
    # Logging
    # --------------------------------------------------------------------- #
    LOG_LEVEL: str = "INFO"
    # "json" for machine-readable production logs, "console" for local dev.
    LOG_RENDERER: Literal["json", "console"] = "json"
    # Also write logs to a rotating file under <STORAGE_ROOT>/logs/.
    LOG_TO_FILE: bool = True
    LOG_FILE_MAX_BYTES: int = 10 * 1024 * 1024
    LOG_FILE_BACKUP_COUNT: int = 5

    # --------------------------------------------------------------------- #
    # Validators
    # --------------------------------------------------------------------- #
    @field_validator("CORS_ORIGINS", "ALLOWED_HOSTS", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Allow comma-separated strings from the environment.

        e.g. ``CORS_ORIGINS="https://a.com,https://b.com"``.
        """
        if isinstance(value, str) and not value.startswith("["):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("LOG_LEVEL", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    # --------------------------------------------------------------------- #
    # Computed DSNs
    # --------------------------------------------------------------------- #
    @computed_field  # type: ignore[prop-decorator]
    @property
    def DATABASE_URL(self) -> str:
        """Async SQLAlchemy database URL used by the application."""
        return str(
            PostgresDsn.build(
                scheme=self.POSTGRES_SCHEME,
                username=self.POSTGRES_USER,
                password=self.POSTGRES_PASSWORD,
                host=self.POSTGRES_HOST,
                port=self.POSTGRES_PORT,
                path=self.POSTGRES_DB,
            )
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SYNC_DATABASE_URL(self) -> str:
        """Synchronous database URL (used by tooling that requires it)."""
        return str(
            PostgresDsn.build(
                scheme="postgresql+psycopg",
                username=self.POSTGRES_USER,
                password=self.POSTGRES_PASSWORD,
                host=self.POSTGRES_HOST,
                port=self.POSTGRES_PORT,
                path=self.POSTGRES_DB,
            )
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def REDIS_URL(self) -> str:
        """Redis connection URL."""
        return str(
            RedisDsn.build(
                scheme="redis",
                password=self.REDIS_PASSWORD,
                host=self.REDIS_HOST,
                port=self.REDIS_PORT,
                path=str(self.REDIS_DB),
            )
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def effective_celery_broker_url(self) -> str:
        return self.CELERY_BROKER_URL or self.REDIS_URL

    @computed_field  # type: ignore[prop-decorator]
    @property
    def effective_celery_result_backend(self) -> str:
        return self.CELERY_RESULT_BACKEND or self.REDIS_URL

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    # --------------------------------------------------------------------- #
    # Storage tree (uploads/ processed/ temp/ thumbnails/ logs/)
    # --------------------------------------------------------------------- #
    @computed_field  # type: ignore[prop-decorator]
    @property
    def storage_root_resolved(self) -> Path:
        return self.STORAGE_ROOT.resolve()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def UPLOADS_DIR(self) -> Path:
        return self.storage_root_resolved / "uploads"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def PROCESSED_DIR(self) -> Path:
        return self.storage_root_resolved / "processed"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def TEMP_DIR(self) -> Path:
        return self.storage_root_resolved / "temp"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def THUMBNAILS_DIR(self) -> Path:
        return self.storage_root_resolved / "thumbnails"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def LOGS_DIR(self) -> Path:
        return self.storage_root_resolved / "logs"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def CACHE_DIR(self) -> Path:
        """Long-lived worker caches (e.g. warm LibreOffice profiles).

        Deliberately outside TEMP_DIR: the cleanup scheduler purges any
        aged entry under temp/, which would evict warm caches mid-use.
        """
        return self.storage_root_resolved / "cache"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def max_upload_size_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024
