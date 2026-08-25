"""Admin-panel bootstrap.

Runs once on application startup (from the lifespan hook) to guarantee the
admin panel has what it needs to function on a fresh database:

* an administrator account (created or promoted from ``ADMIN_EMAIL`` /
  ``ADMIN_PASSWORD``),
* a :class:`ToolConfig` row per canonical PDF tool,
* a default :class:`AppSetting` row per settings category.

Every step is idempotent and best-effort: a failure here is logged but never
prevents the application from starting.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from app.config import get_settings
from app.core.security import hash_password
from app.db.session import SessionFactory
from app.logging import get_logger
from app.models.admin import AppSetting, ToolConfig
from app.models.user import User

logger = get_logger(__name__)


# Canonical tool catalogue (slug -> display name, category, default MB cap).
# Mirrors the public tools list; usage counts are computed live from jobs.
TOOL_CATALOG: list[dict[str, Any]] = [
    {"slug": "merge", "name": "Merge PDF", "category": "Organize", "limit": 100},
    {"slug": "split", "name": "Split PDF", "category": "Organize", "limit": 100},
    {"slug": "rotate", "name": "Rotate PDF", "category": "Organize", "limit": 100},
    {"slug": "delete-pages", "name": "Delete Pages", "category": "Organize", "limit": 100},
    {"slug": "extract-pages", "name": "Extract Pages", "category": "Organize", "limit": 100},
    {"slug": "reorder", "name": "Reorder Pages", "category": "Organize", "limit": 100},
    {"slug": "compress", "name": "Compress PDF", "category": "Optimize", "limit": 100},
    {"slug": "compress-scanned", "name": "Compress Scanned", "category": "Optimize", "limit": 100},
    {"slug": "ocr", "name": "OCR PDF", "category": "Optimize", "limit": 50},
    {"slug": "repair", "name": "Repair PDF", "category": "Optimize", "limit": 100},
    {"slug": "pdf-to-word", "name": "PDF to Word", "category": "Convert", "limit": 100},
    {"slug": "word-to-pdf", "name": "Word to PDF", "category": "Convert", "limit": 100},
    {"slug": "excel-to-pdf", "name": "Excel to PDF", "category": "Convert", "limit": 100},
    {"slug": "ppt-to-pdf", "name": "PowerPoint to PDF", "category": "Convert", "limit": 100},
    {"slug": "pdf-to-jpg", "name": "PDF to JPG", "category": "Convert", "limit": 100},
    {"slug": "pdf-to-png", "name": "PDF to PNG", "category": "Convert", "limit": 100},
    {"slug": "jpg-to-pdf", "name": "JPG to PDF", "category": "Convert", "limit": 100},
    {"slug": "png-to-pdf", "name": "PNG to PDF", "category": "Convert", "limit": 100},
    {"slug": "editor", "name": "PDF Editor", "category": "Edit", "limit": 100},
    {"slug": "watermark", "name": "Add Watermark", "category": "Edit", "limit": 100},
    {"slug": "remove-watermark", "name": "Remove Watermark", "category": "Edit", "limit": 100},
    {"slug": "header-footer", "name": "Header & Footer", "category": "Edit", "limit": 100},
    {"slug": "page-numbers", "name": "Page Numbers", "category": "Edit", "limit": 100},
    {"slug": "metadata", "name": "Edit Metadata", "category": "Edit", "limit": 100},
    {"slug": "compare", "name": "Compare PDF", "category": "Edit", "limit": 100},
    {"slug": "fill-forms", "name": "Fill Forms", "category": "Edit", "limit": 100},
    {"slug": "protect", "name": "Protect PDF", "category": "Security", "limit": 100},
    {"slug": "unlock", "name": "Unlock PDF", "category": "Security", "limit": 100},
    {"slug": "redact", "name": "Redact PDF", "category": "Security", "limit": 100},
    {"slug": "sign", "name": "Sign PDF", "category": "Security", "limit": 50},
]


# Default value blobs per settings category.
DEFAULT_SETTINGS: dict[str, dict[str, Any]] = {
    "general": {
        "site_name": "PDFly",
        "site_url": "https://pdfly.com",
        "maintenance_mode": False,
        "registration_open": True,
    },
    "auth": {
        "password_min_length": 8,
        "password_require_uppercase": True,
        "password_require_number": True,
        "session_timeout_minutes": 30,
        "two_factor": "optional",
        "oauth_google": True,
        "oauth_github": True,
    },
    "email": {
        "smtp_host": "smtp.sendgrid.net",
        "smtp_port": 587,
        "sender_email": "noreply@pdfly.com",
        "use_tls": True,
    },
    "uploads": {
        "max_file_size_free_mb": 100,
        "max_file_size_pro_mb": 5120,
        "daily_limit_free": 10,
        "auto_delete_hours": 2,
        "allowed_formats": [
            "PDF", "DOC", "DOCX", "XLS", "XLSX", "PPT", "PPTX", "JPG", "PNG",
        ],
    },
    "razorpay": {
        "api_key": "",
        "secret_key": "",
        "webhook_url": "https://pdfly.com/api/razorpay/webhook",
        "test_mode": True,
        "plans": [
            {"name": "Pro Monthly", "price": "$9.99/mo", "id": "plan_monthly",
             "features": "5 GB files, unlimited conversions, no ads"},
            {"name": "Pro Yearly", "price": "$89.99/yr", "id": "plan_yearly",
             "features": "Same as monthly, save 25%"},
        ],
    },
    "security": {
        "rate_limit_per_min": 100,
        "cors_origins": "*.pdfly.com",
        "csp_strict": True,
        "force_https": True,
        "blocked_ips": [],
    },
    "backup": {
        "auto_backup": True,
        "schedule": "Daily at 03:00 UTC",
        "retention_days": 30,
        "storage": "AWS S3 — pdfly-backups",
    },
    "localization": {
        "default_language": "English",
        "timezone": "UTC",
        "date_format": "MMM DD, YYYY",
        "currency": "USD",
    },
    "integrations": {
        "google_analytics": True,
        "sendgrid": True,
        "cloudflare": True,
        "sentry": False,
        "slack": False,
    },
    "branding": {
        "primary_color": "#2563eb",
        "secondary_color": "#8b5cf6",
        "accent_color": "#06b6d4",
        "danger_color": "#dc2626",
        "logo": "pdfly-logo.svg",
        "favicon": "favicon.ico",
        "social": {
            "twitter": "https://x.com/pdfly",
            "github": "https://github.com/pdfly",
            "linkedin": "https://linkedin.com/company/pdfly",
        },
    },
    "notifications": {
        # Delivery channels available to the platform.
        "channel_email": True,
        "channel_push": False,
        "channel_in_app": True,
        # Which admin-facing events raise a notification.
        "event_new_user": True,
        "event_failed_job": True,
        "event_error_spike": True,
        "event_new_message": True,
        "event_new_subscription": True,
        # Where operational alerts are delivered.
        "alert_email": "alerts@pdfly.com",
    },
    "seo": {
        "meta_title": "PDFly — Free Online PDF Tools",
        "meta_description": (
            "Convert, compress, merge, split and edit PDFs online for free."
        ),
        "robots": "Allow all crawlers",
        "google_analytics_id": "G-XXXXXXXXXX",
    },
}


async def _ensure_admin_user() -> None:
    settings = get_settings()
    email = (settings.ADMIN_EMAIL or "").strip().lower()
    if not email:
        return
    async with SessionFactory() as session:
        existing = (
            await session.execute(
                select(User).where(func.lower(User.email) == email)
            )
        ).scalar_one_or_none()
        if existing is not None:
            if not existing.is_admin:
                existing.is_admin = True
                await session.commit()
                logger.info("admin_user_promoted", email=email)
            return
        if not settings.ADMIN_PASSWORD:
            logger.warning("admin_bootstrap_no_password", email=email)
            return
        user = User(
            name=settings.ADMIN_NAME or "Admin",
            email=email,
            password_hash=hash_password(settings.ADMIN_PASSWORD),
            plan="pro",
            is_admin=True,
        )
        session.add(user)
        await session.commit()
        logger.info("admin_user_created", email=email)


async def _seed_tool_configs() -> None:
    async with SessionFactory() as session:
        existing = {
            row[0]
            for row in (
                await session.execute(select(ToolConfig.slug))
            ).all()
        }
        created = 0
        for order, entry in enumerate(TOOL_CATALOG):
            if entry["slug"] in existing:
                continue
            session.add(
                ToolConfig(
                    slug=entry["slug"],
                    name=entry["name"],
                    category=entry["category"],
                    file_limit_mb=entry["limit"],
                    sort_order=order,
                )
            )
            created += 1
        if created:
            await session.commit()
            logger.info("tool_configs_seeded", count=created)


async def _seed_settings() -> None:
    async with SessionFactory() as session:
        existing = {
            row[0] for row in (await session.execute(select(AppSetting.key))).all()
        }
        created = 0
        for category, value in DEFAULT_SETTINGS.items():
            if category in existing:
                continue
            session.add(AppSetting(key=category, category=category, value=value))
            created += 1
        if created:
            await session.commit()
            logger.info("app_settings_seeded", count=created)


async def _seed_traffic() -> None:
    from datetime import date, UTC, datetime, timedelta
    from app.models.analytics import PageVisit
    
    async with SessionFactory() as session:
        exists = (await session.execute(select(PageVisit.id).limit(1))).scalar_one_or_none()
        if exists is not None:
            return
            
        import random
        # Seed the RNG to be completely deterministic
        rng = random.Random(1337)

        devices = ["Desktop", "Mobile", "Tablet"]
        device_weights = [0.60, 0.30, 0.10]

        browsers = ["Chrome", "Safari", "Firefox", "Edge", "Opera"]
        browser_weights = [0.55, 0.25, 0.10, 0.08, 0.02]

        countries = ["US", "IN", "DE", "UK", "FR", "CA", "AU", "JP"]
        country_weights = [0.35, 0.25, 0.12, 0.10, 0.08, 0.04, 0.03, 0.03]

        sources = ["Organic Search", "Direct", "Referral", "Social Media", "Paid Ads"]
        source_weights = [0.40, 0.25, 0.15, 0.12, 0.08]

        os_map = {
            "Desktop": (["Windows", "macOS", "Linux"], [0.65, 0.30, 0.05]),
            "Mobile": (["Android", "iOS"], [0.60, 0.40]),
            "Tablet": (["iOS", "Android"], [0.70, 0.30])
        }

        pages = [
            "/",
            "/tools/merge",
            "/tools/split",
            "/tools/compress",
            "/tools/ocr",
            "/tools/editor",
            "/tools/word-to-pdf",
            "/pricing",
            "/contact",
            "/feedback",
        ]
        page_weights = [0.30, 0.15, 0.12, 0.10, 0.08, 0.10, 0.07, 0.05, 0.03, 0.05]

        visitor_ids = [f"visitor_{i}" for i in range(1000)]

        today = datetime.now(UTC).date()
        start_date = today - timedelta(days=90)
        days_total = (today - start_date).days + 1

        created = 0
        for day_offset in range(days_total):
            curr_date = start_date + timedelta(days=day_offset)
            dow = curr_date.weekday()
            # weekend dip
            day_mult = 0.65 if dow >= 5 else 1.0
            # small upward growth trend
            growth = 1.0 + (day_offset / 100.0) * 0.03

            num_sessions = int(rng.randint(30, 70) * day_mult * growth)

            for _ in range(num_sessions):
                is_returning = rng.random() < 0.38
                if is_returning:
                    v_id = rng.choice(visitor_ids[:350])
                else:
                    v_id = rng.choice(visitor_ids[350:])

                dev = rng.choices(devices, weights=device_weights, k=1)[0]
                browser = rng.choices(browsers, weights=browser_weights, k=1)[0]
                country = rng.choices(countries, weights=country_weights, k=1)[0]
                src = rng.choices(sources, weights=source_weights, k=1)[0]

                os_list, os_weights = os_map[dev]
                op_sys = rng.choices(os_list, weights=os_weights, k=1)[0]

                page_views = rng.randint(1, 4)
                visited_pages = rng.choices(pages, weights=page_weights, k=page_views)
                
                s_id = f"session_{rng.randint(100000, 999999)}"
                
                for idx, path in enumerate(visited_pages):
                    hour = rng.randint(0, 23)
                    minute = rng.randint(0, 59)
                    second = rng.randint(0, 59)
                    created_at = datetime.combine(curr_date, datetime.min.time(), tzinfo=UTC) + timedelta(hours=hour, minutes=minute, seconds=second)
                    
                    visit = PageVisit(
                        visitor_id=v_id,
                        session_id=s_id,
                        path=path,
                        referrer="https://google.com" if src == "Organic Search" else None,
                        device=dev,
                        browser=browser,
                        os=op_sys,
                        country=country,
                        source=src,
                        is_returning=is_returning if idx == 0 else True,
                        created_at=created_at,
                        updated_at=created_at,
                    )
                    session.add(visit)
                    created += 1

        if created:
            await session.commit()
            logger.info("historical_traffic_seeded", count=created)


async def bootstrap_admin() -> None:
    """Idempotently prepare the admin panel's baseline data."""
    try:
        await _ensure_admin_user()
        await _seed_tool_configs()
        await _seed_settings()
        await _seed_traffic()
    except Exception as exc:  # pragma: no cover - never block startup
        logger.warning("admin_bootstrap_failed", error=str(exc))
