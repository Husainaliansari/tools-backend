"""Middleware registration.

Central place that assembles the middleware stack in the correct order.

Starlette applies middleware in *reverse* order of registration: the middleware
added **last** becomes the **outermost** layer (runs first on the way in, last
on the way out). Below we register from innermost to outermost so the resulting
execution order (outer -> inner) is:

    RequestContext -> RequestLogging -> TrustedHost -> CORS
        -> SecurityHeaders -> GZip -> application
"""

from __future__ import annotations

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import BaseAppSettings
from app.middleware.logging import RequestLoggingMiddleware
from app.middleware.request_context import RequestContextMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware


def register_middleware(app: FastAPI, settings: BaseAppSettings) -> None:
    """Register the full middleware stack on the application."""
    # --- innermost first ---

    # 1. GZip compression of outgoing responses.
    app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=6)

    # 2. Security headers.
    app.add_middleware(SecurityHeadersMiddleware, enable_hsts=settings.is_production)

    # 3. CORS.
    # AnyHttpUrl serialises with a trailing slash ("http://localhost:3000/"),
    # but browsers send the Origin header without one. Starlette matches origins
    # by exact string, so strip the slash or every request would 400.
    cors_origins = [str(origin).rstrip("/") for origin in settings.CORS_ORIGINS]

    if settings.DEBUG or settings.APP_ENV == "development":
        import socket
        try:
            # Method 1: Connect to external host to detect primary interface IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            if local_ip and local_ip != "127.0.0.1":
                cors_origins.extend([
                    f"http://{local_ip}:3000",
                    f"http://{local_ip}:3001",
                    f"http://{local_ip}:5173",
                ])
        except Exception:
            pass

        try:
            # Method 2: Get all IPs assigned to the hostname
            local_hostname = socket.gethostname()
            local_ips = socket.gethostbyname_ex(local_hostname)[2]
            for ip in local_ips:
                if ip != "127.0.0.1":
                    cors_origins.extend([
                        f"http://{ip}:3000",
                        f"http://{ip}:3001",
                        f"http://{ip}:5173",
                    ])
        except Exception:
            pass

        # Deduplicate while preserving order
        cors_origins = list(dict.fromkeys(cors_origins))

    allow_all = "*" in cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if allow_all else cors_origins,
        # Credentials cannot be combined with the "*" wildcard per the spec.
        allow_credentials=settings.CORS_ALLOW_CREDENTIALS and not allow_all,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Correlation-ID"],
    )

    # 4. Trusted hosts (Host header allow-list).
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS)

    # 5. Request access logging.
    app.add_middleware(RequestLoggingMiddleware)

    # 6. Request context (outermost — binds ids for everything above).
    app.add_middleware(RequestContextMiddleware)
