"""Admin panel service layer.

All read/aggregate/mutation logic for the admin panel lives here, on top of the
existing async session. Endpoints stay thin: they parse the request, call one
service method, and wrap the result in the standard response envelope.

The service reuses the existing user-facing tables (``users``,
``stored_files``, ``processing_jobs``, ``feedback``) read-only for dashboards
and owns the admin-only tables for CMS/settings/audit.
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    AdminLogCategory,
    ContentStatus,
    FileStatus,
    JobFileRole,
    JobStatus,
    SubscriptionStatus,
    UserStatus,
)
from app.core.security import hash_password
from app.exceptions.base import BadRequestError, ConflictError, NotFoundError
from app.models.admin import (
    AdminAuditLog,
    Announcement,
    AppSetting,
    BlogPost,
    ContactMessage,
    ContentPage,
    ErrorLog,
    Faq,
    Subscription,
    ToolConfig,
)
from app.models.analytics import PageVisit
from app.models.feedback import Feedback
from app.models.file import StoredFile
from app.models.job import JobFile, ProcessingJob
from app.models.user import User
from app.dependencies.pagination import PaginationParams

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or uuid.uuid4().hex[:8]


class AdminService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ─────────────────────────────────────────────────────────────────────
    # Audit logging
    # ─────────────────────────────────────────────────────────────────────
    async def audit(
        self,
        *,
        actor: User | None,
        action: str,
        summary: str,
        category: str = AdminLogCategory.AUDIT,
        entity_type: str | None = None,
        entity_id: str | None = None,
        ip: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        self.session.add(
            AdminAuditLog(
                actor_id=actor.id if actor else None,
                actor_email=actor.email if actor else None,
                action=action,
                summary=summary,
                category=category,
                entity_type=entity_type,
                entity_id=entity_id,
                ip=ip,
                meta=meta or {},
            )
        )
        await self.session.commit()

    async def _count(self, stmt: Select) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        return int(result.scalar_one())

    # ─────────────────────────────────────────────────────────────────────
    # Dashboard / analytics
    # ─────────────────────────────────────────────────────────────────────
    async def overview(self) -> dict[str, Any]:
        s = self.session
        now = datetime.now(UTC)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)

        total_users = int(
            (await s.execute(select(func.count(User.id)))).scalar_one()
        )
        active_users = int(
            (
                await s.execute(
                    select(func.count(func.distinct(ProcessingJob.user_id))).where(
                        ProcessingJob.user_id.is_not(None)
                    )
                )
            ).scalar_one()
        )
        total_conversions = int(
            (await s.execute(select(func.count(ProcessingJob.id)))).scalar_one()
        )
        today_conversions = int(
            (
                await s.execute(
                    select(func.count(ProcessingJob.id)).where(
                        ProcessingJob.created_at >= today
                    )
                )
            ).scalar_one()
        )
        total_subscribers = int(
            (
                await s.execute(
                    select(func.count(Subscription.id)).where(
                        Subscription.status == SubscriptionStatus.ACTIVE
                    )
                )
            ).scalar_one()
        )
        revenue_cents = int(
            (
                await s.execute(
                    select(func.coalesce(func.sum(Subscription.price_cents), 0)).where(
                        Subscription.status == SubscriptionStatus.ACTIVE
                    )
                )
            ).scalar_one()
        )
        storage_bytes = int(
            (
                await s.execute(
                    select(func.coalesce(func.sum(StoredFile.size_bytes), 0)).where(
                        StoredFile.status == FileStatus.ACTIVE
                    )
                )
            ).scalar_one()
        )
        failed_jobs = int(
            (
                await s.execute(
                    select(func.count(ProcessingJob.id)).where(
                        ProcessingJob.status == JobStatus.FAILED
                    )
                )
            ).scalar_one()
        )
        total_feedback = int(
            (await s.execute(select(func.count(Feedback.id)))).scalar_one()
        )

        return {
            "kpis": {
                "total_users": total_users,
                "active_users": active_users,
                "total_conversions": total_conversions,
                "today_conversions": today_conversions,
                "total_subscribers": total_subscribers,
                "monthly_revenue_cents": revenue_cents,
                "storage_bytes": storage_bytes,
                "failed_jobs": failed_jobs,
                "total_feedback": total_feedback,
                "server_status": "Operational",
            },
            "conversion_trend": await self._monthly_conversions(),
            "tool_usage": await self._tool_usage_distribution(limit=6),
            "recent_activity": await self._recent_activity(limit=6),
        }

    async def track_page_visit(
        self,
        *,
        visitor_id: str,
        session_id: str,
        path: str,
        referrer: str | None = None,
        source: str | None = None,
        user_agent: str = "",
        accept_lang: str = "",
        cf_country: str | None = None,
    ) -> None:
        exists_stmt = select(select(PageVisit.id).where(PageVisit.visitor_id == visitor_id).exists())
        is_returning = bool((await self.session.execute(exists_stmt)).scalar())

        os_name, device_type, browser_name = self._parse_user_agent(user_agent)
        country_code = self._detect_country(accept_lang, cf_country)
        source_name = source or self._detect_source(referrer)

        visit = PageVisit(
            visitor_id=visitor_id,
            session_id=session_id,
            path=path,
            referrer=referrer,
            device=device_type,
            browser=browser_name,
            os=os_name,
            country=country_code,
            source=source_name,
            is_returning=is_returning,
        )
        self.session.add(visit)
        await self.session.commit()

    @staticmethod
    def _parse_user_agent(ua_string: str) -> tuple[str, str, str]:
        if not ua_string:
            return "Other", "Desktop", "Other"
        ua = ua_string.lower()

        # OS detection
        if "windows" in ua:
            os_name = "Windows"
        elif "macintosh" in ua or "mac os x" in ua:
            if "ipad" in ua or "iphone" in ua:
                os_name = "iOS"
            else:
                os_name = "macOS"
        elif "android" in ua:
            os_name = "Android"
        elif "iphone" in ua or "ipad" in ua or "ipod" in ua:
            os_name = "iOS"
        elif "linux" in ua:
            os_name = "Linux"
        else:
            os_name = "Other"

        # Device detection
        if "mobi" in ua or "iphone" in ua or "ipod" in ua or "android" in ua and "mobile" in ua:
            device_type = "Mobile"
        elif "ipad" in ua or "tablet" in ua or "playbook" in ua or "kindle" in ua or ("android" in ua and "mobile" not in ua):
            device_type = "Tablet"
        else:
            device_type = "Desktop"

        # Browser detection
        if "opera" in ua or "opr/" in ua:
            browser_name = "Opera"
        elif "edge" in ua or "edg/" in ua:
            browser_name = "Edge"
        elif "chrome" in ua or "crios" in ua:
            browser_name = "Chrome"
        elif "firefox" in ua or "fxios" in ua:
            browser_name = "Firefox"
        elif "safari" in ua and "chrome" not in ua and "chromium" not in ua:
            browser_name = "Safari"
        else:
            browser_name = "Other"

        return os_name, device_type, browser_name

    @staticmethod
    def _detect_country(accept_lang: str, cf_country: str | None) -> str:
        if cf_country:
            return cf_country.upper()
        if accept_lang:
            first_lang = accept_lang.split(",")[0].strip()
            if "-" in first_lang:
                parts = first_lang.split("-")
                country_code = parts[-1].upper()
                if len(country_code) == 2:
                    return country_code
        return "US"

    @staticmethod
    def _detect_source(referrer: str | None) -> str:
        if not referrer:
            return "Direct"
        ref = referrer.lower()
        if "google" in ref:
            return "Organic Search"
        elif "facebook" in ref or "t.co" in ref or "twitter" in ref or "instagram" in ref or "linkedin" in ref:
            return "Social Media"
        elif "github" in ref or "reddit" in ref:
            return "Referral"
        elif "ads" in ref or "googleads" in ref:
            return "Paid Ads"
        return "Referral"

    async def analytics(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        device: str | None = None,
        browser: str | None = None,
        country: str | None = None,
        source: str | None = None,
        visitor_type: str | None = "total",
        group_by: str | None = "daily",
    ) -> dict[str, Any]:
        s = self.session
        from datetime import date
        today = datetime.now(UTC).date()

        # Parse end date
        parsed_end = today
        if end_date:
            try:
                parsed_end = datetime.strptime(end_date, "%Y-%m-%d").date()
            except ValueError:
                pass

        # Parse start date
        parsed_start = parsed_end - timedelta(days=30)
        if start_date:
            try:
                parsed_start = datetime.strptime(start_date, "%Y-%m-%d").date()
            except ValueError:
                pass

        # Combine into datetime bounds (inclusive of full start and end days)
        start_dt = datetime.combine(parsed_start, datetime.min.time(), tzinfo=UTC)
        end_dt = datetime.combine(parsed_end, datetime.max.time(), tzinfo=UTC)

        # Construct base filters for PageVisit queries
        base_filter = [
            PageVisit.created_at >= start_dt,
            PageVisit.created_at <= end_dt
        ]
        if device:
            base_filter.append(func.lower(PageVisit.device) == device.lower())
        if browser:
            base_filter.append(func.lower(PageVisit.browser) == browser.lower())
        if country:
            base_filter.append(func.lower(PageVisit.country) == country.lower())
        if source:
            base_filter.append(func.lower(PageVisit.source) == source.lower())

        if visitor_type == "unique":
            base_filter.append(PageVisit.is_returning == False)
        elif visitor_type == "returning":
            base_filter.append(PageVisit.is_returning == True)

        # Build query for Core KPIs
        pv_query = select(func.count(PageVisit.id)).where(*base_filter)
        page_views = int((await s.execute(pv_query)).scalar_one() or 0)

        tv_query = select(func.count(func.distinct(PageVisit.visitor_id))).where(*base_filter)
        total_visitors = int((await s.execute(tv_query)).scalar_one() or 0)

        uv_query = select(func.count(func.distinct(PageVisit.visitor_id))).where(*base_filter, PageVisit.is_returning == False)
        unique_visitors = int((await s.execute(uv_query)).scalar_one() or 0)

        rv_query = select(func.count(func.distinct(PageVisit.visitor_id))).where(*base_filter, PageVisit.is_returning == True)
        returning_visitors = int((await s.execute(rv_query)).scalar_one() or 0)

        session_query = select(func.count(func.distinct(PageVisit.session_id))).where(*base_filter)
        total_sessions = int((await s.execute(session_query)).scalar_one() or 0)

        # Calculations for period comparisons
        async def get_metric_val_for_range(s_date: date, e_date: date, v_type: str | None) -> int:
            s_dt = datetime.combine(s_date, datetime.min.time(), tzinfo=UTC)
            e_dt = datetime.combine(e_date, datetime.max.time(), tzinfo=UTC)
            filters = [
                PageVisit.created_at >= s_dt,
                PageVisit.created_at <= e_dt
            ]
            if device:
                filters.append(func.lower(PageVisit.device) == device.lower())
            if browser:
                filters.append(func.lower(PageVisit.browser) == browser.lower())
            if country:
                filters.append(func.lower(PageVisit.country) == country.lower())
            if source:
                filters.append(func.lower(PageVisit.source) == source.lower())

            if v_type == "unique":
                filters.append(PageVisit.is_returning == False)
                q = select(func.count(func.distinct(PageVisit.visitor_id))).where(*filters)
            elif v_type == "returning":
                filters.append(PageVisit.is_returning == True)
                q = select(func.count(func.distinct(PageVisit.visitor_id))).where(*filters)
            else:
                q = select(func.count(func.distinct(PageVisit.visitor_id))).where(*filters)
            return int((await s.execute(q)).scalar_one() or 0)

        # Today vs Yesterday
        today_val = await get_metric_val_for_range(today, today, visitor_type)
        yesterday_val = await get_metric_val_for_range(today - timedelta(days=1), today - timedelta(days=1), visitor_type)
        today_growth = round(((today_val - yesterday_val) / yesterday_val * 100), 1) if yesterday_val else 0.0

        # This Week vs Last Week
        this_week_val = await get_metric_val_for_range(today - timedelta(days=6), today, visitor_type)
        last_week_val = await get_metric_val_for_range(today - timedelta(days=13), today - timedelta(days=7), visitor_type)
        week_growth = round(((this_week_val - last_week_val) / last_week_val * 100), 1) if last_week_val else 0.0

        # This Month vs Last Month
        this_month_val = await get_metric_val_for_range(today - timedelta(days=29), today, visitor_type)
        last_month_val = await get_metric_val_for_range(today - timedelta(days=59), today - timedelta(days=30), visitor_type)
        month_growth = round(((this_month_val - last_month_val) / last_month_val * 100), 1) if last_month_val else 0.0

        # Traffic trend over time (charts)
        if group_by == "yearly":
            date_trunc_field = func.date_trunc("year", PageVisit.created_at)
        elif group_by == "monthly":
            date_trunc_field = func.date_trunc("month", PageVisit.created_at)
        elif group_by == "weekly":
            date_trunc_field = func.date_trunc("week", PageVisit.created_at)
        else: # daily
            date_trunc_field = func.date_trunc("day", PageVisit.created_at)

        # Construct group by query
        if visitor_type == "unique":
            metric_agg = func.count(func.distinct(PageVisit.visitor_id))
        else:
            metric_agg = func.count(PageVisit.id)

        trend_query = (
            select(date_trunc_field.label("grp"), metric_agg.label("val"))
            .where(*base_filter)
            .group_by(date_trunc_field)
            .order_by(date_trunc_field)
        )
        trend_rows = (await s.execute(trend_query)).all()

        trend_points = []
        for grp, val in trend_rows:
            if not grp:
                continue
            if group_by == "yearly":
                label = grp.strftime("%Y")
            elif group_by == "monthly":
                label = grp.strftime("%b %Y")
            elif group_by == "weekly":
                label = f"Wk {grp.isocalendar()[1]} ({grp.year})"
            else: # daily
                label = grp.strftime("%b %d")

            trend_points.append({
                "m": label,
                "v": int(val or 0)
            })

        # Dimensions rankings helper
        async def query_ranking(column_field, limit=7) -> list[dict]:
            q = (
                select(column_field, func.count(PageVisit.id))
                .where(*base_filter)
                .group_by(column_field)
                .order_by(func.count(PageVisit.id).desc())
                .limit(limit)
            )
            rows = (await s.execute(q)).all()
            return [{"name": str(row[0]), "count": int(row[1] or 0)} for row in rows if row[0] is not None]

        # Query rankings
        top_pages_rows = await query_ranking(PageVisit.path)
        top_browsers_rows = await query_ranking(PageVisit.browser)
        top_devices_rows = await query_ranking(PageVisit.device)
        top_os_rows = await query_ranking(PageVisit.os)
        top_countries_rows = await query_ranking(PageVisit.country)
        top_referrers_rows = await query_ranking(PageVisit.source)

        top_pages = [{"page": r["name"], "count": r["count"]} for r in top_pages_rows]
        top_browsers = [{"browser": r["name"], "count": r["count"]} for r in top_browsers_rows]
        top_devices = [{"device": r["name"], "count": r["count"]} for r in top_devices_rows]
        top_os = [{"os": r["name"], "count": r["count"]} for r in top_os_rows]
        top_countries = [{"country": r["name"], "count": r["count"]} for r in top_countries_rows]
        top_referrers = [{"referrer": r["name"], "count": r["count"]} for r in top_referrers_rows]

        # Construct base filters for ProcessingJob in rankings query
        job_base_filter = [
            ProcessingJob.created_at >= start_dt,
            ProcessingJob.created_at <= end_dt
        ]
        if device:
            job_base_filter.append(func.lower(ProcessingJob.device) == device.lower())
        if browser:
            job_base_filter.append(func.lower(ProcessingJob.browser) == browser.lower())
        if country:
            job_base_filter.append(func.lower(ProcessingJob.country) == country.lower())
        if source:
            job_base_filter.append(func.lower(ProcessingJob.source) == source.lower())
        if visitor_type == "unique":
            job_base_filter.append(ProcessingJob.is_returning == False)
        elif visitor_type == "returning":
            job_base_filter.append(ProcessingJob.is_returning == True)

        # Top Tools query
        tools_query = (
            select(ProcessingJob.tool, func.count(ProcessingJob.id))
            .where(*job_base_filter)
            .group_by(ProcessingJob.tool)
            .order_by(func.count(ProcessingJob.id).desc())
            .limit(7)
        )
        tools_rows = (await s.execute(tools_query)).all()
        top_tools = [{"tool": tool, "count": int(cnt or 0)} for tool, cnt in tools_rows]

        return {
            "kpis": {
                "total_visitors": total_visitors,
                "unique_visitors": unique_visitors,
                "returning_visitors": returning_visitors,
                "page_views": page_views,
                "total_sessions": total_sessions,
            },
            "comparison": {
                "today": {"value": today_val, "growth_pct": today_growth},
                "week": {"value": this_week_val, "growth_pct": week_growth},
                "month": {"value": this_month_val, "growth_pct": month_growth},
            },
            "traffic_trend": trend_points,
            "top_tools": top_tools,
            "top_pages": top_pages,
            "top_browsers": top_browsers,
            "top_devices": top_devices,
            "top_os": top_os,
            "top_countries": top_countries,
            "top_referrers": top_referrers,
        }

    async def tool_analytics(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        device: str | None = None,
        browser: str | None = None,
        country: str | None = None,
        source: str | None = None,
        visitor_type: str | None = "total",
        group_by: str | None = "daily",
    ) -> dict[str, Any]:
        s = self.session
        from datetime import date
        today = datetime.now(UTC).date()

        # Parse end date
        parsed_end = today
        if end_date:
            try:
                parsed_end = datetime.strptime(end_date, "%Y-%m-%d").date()
            except ValueError:
                pass

        # Parse start date
        parsed_start = parsed_end - timedelta(days=30)
        if start_date:
            try:
                parsed_start = datetime.strptime(start_date, "%Y-%m-%d").date()
            except ValueError:
                pass

        # Combine into datetime bounds
        start_dt = datetime.combine(parsed_start, datetime.min.time(), tzinfo=UTC)
        end_dt = datetime.combine(parsed_end, datetime.max.time(), tzinfo=UTC)

        # Construct base filters for ProcessingJob queries
        base_filter = [
            ProcessingJob.created_at >= start_dt,
            ProcessingJob.created_at <= end_dt
        ]
        if device:
            base_filter.append(func.lower(ProcessingJob.device) == device.lower())
        if browser:
            base_filter.append(func.lower(ProcessingJob.browser) == browser.lower())
        if country:
            base_filter.append(func.lower(ProcessingJob.country) == country.lower())
        if source:
            base_filter.append(func.lower(ProcessingJob.source) == source.lower())
        if visitor_type == "unique":
            base_filter.append(ProcessingJob.is_returning == False)
        elif visitor_type == "returning":
            base_filter.append(ProcessingJob.is_returning == True)

        # 1. General KPIs
        total_execs = int(
            (
                await s.execute(
                    select(func.count(ProcessingJob.id)).where(*base_filter)
                )
            ).scalar_one() or 0
        )
        success_execs = int(
            (
                await s.execute(
                    select(func.count(ProcessingJob.id)).where(
                        *base_filter,
                        ProcessingJob.status == JobStatus.COMPLETED
                    )
                )
            ).scalar_one() or 0
        )
        failed_execs = int(
            (
                await s.execute(
                    select(func.count(ProcessingJob.id)).where(
                        *base_filter,
                        ProcessingJob.status == JobStatus.FAILED
                    )
                )
            ).scalar_one() or 0
        )
        total_files = int(
            (
                await s.execute(
                    select(func.count(JobFile.file_id))
                    .join(ProcessingJob, JobFile.job_id == ProcessingJob.id)
                    .where(
                        *base_filter,
                        JobFile.role == JobFileRole.INPUT
                    )
                )
            ).scalar_one() or 0
        )
        total_bytes = int(
            (
                await s.execute(
                    select(func.coalesce(func.sum(StoredFile.size_bytes), 0))
                    .select_from(JobFile)
                    .join(ProcessingJob, JobFile.job_id == ProcessingJob.id)
                    .join(StoredFile, JobFile.file_id == StoredFile.id)
                    .where(
                        *base_filter,
                        JobFile.role == JobFileRole.INPUT
                    )
                )
            ).scalar_one() or 0
        )

        # 2. Tool breakdown
        tool_counts_query = (
            select(
                ProcessingJob.tool,
                func.count(ProcessingJob.id).label("total"),
                func.count(func.nullif(ProcessingJob.status != JobStatus.COMPLETED, True)).label("success"),
                func.count(func.nullif(ProcessingJob.status != JobStatus.FAILED, True)).label("failed")
            )
            .where(*base_filter)
            .group_by(ProcessingJob.tool)
        )
        tool_counts_rows = (await s.execute(tool_counts_query)).all()
        tool_counts = {
            row[0]: {"total": int(row[1]), "success": int(row[2]), "failed": int(row[3])}
            for row in tool_counts_rows
        }

        tool_files_query = (
            select(
                ProcessingJob.tool,
                func.count(JobFile.file_id).label("files_cnt"),
                func.coalesce(func.sum(StoredFile.size_bytes), 0).label("bytes_sum")
            )
            .select_from(JobFile)
            .join(ProcessingJob, JobFile.job_id == ProcessingJob.id)
            .join(StoredFile, JobFile.file_id == StoredFile.id)
            .where(
                *base_filter,
                JobFile.role == JobFileRole.INPUT
            )
            .group_by(ProcessingJob.tool)
        )
        tool_files_rows = (await s.execute(tool_files_query)).all()
        tool_files = {
            row[0]: {"files": int(row[1]), "bytes": int(row[2])}
            for row in tool_files_rows
        }

        tools = (
            await self.session.execute(
                select(ToolConfig).order_by(ToolConfig.sort_order, ToolConfig.name)
            )
        ).scalars().all()

        tools_list = []
        for t in tools:
            counts = tool_counts.get(t.slug, {"total": 0, "success": 0, "failed": 0})
            files_data = tool_files.get(t.slug, {"files": 0, "bytes": 0})
            
            usage_cnt = counts["total"]
            success_cnt = counts["success"]
            failure_cnt = counts["failed"]
            success_rate = round(100.0 * success_cnt / usage_cnt, 1) if usage_cnt > 0 else 100.0

            tools_list.append({
                "slug": t.slug,
                "name": t.name,
                "category": t.category,
                "usage_count": usage_cnt,
                "success_count": success_cnt,
                "failure_count": failure_cnt,
                "success_rate": success_rate,
                "files_processed": files_data["files"],
                "data_processed_bytes": files_data["bytes"],
            })

        sorted_tools = sorted(tools_list, key=lambda x: x["usage_count"], reverse=True)
        most_popular = sorted_tools[0]["name"] if sorted_tools and sorted_tools[0]["usage_count"] > 0 else "None"
        
        non_zero_tools = [x for x in sorted_tools if x["usage_count"] > 0]
        if non_zero_tools:
            least_used = non_zero_tools[-1]["name"]
        else:
            least_used = sorted_tools[-1]["name"] if sorted_tools else "None"

        # 3. Trend
        if group_by == "yearly":
            date_trunc_field = func.date_trunc("year", ProcessingJob.created_at)
        elif group_by == "monthly":
            date_trunc_field = func.date_trunc("month", ProcessingJob.created_at)
        elif group_by == "weekly":
            date_trunc_field = func.date_trunc("week", ProcessingJob.created_at)
        else: # daily
            date_trunc_field = func.date_trunc("day", ProcessingJob.created_at)

        trend_query = (
            select(date_trunc_field.label("grp"), func.count(ProcessingJob.id).label("val"))
            .where(*base_filter)
            .group_by(date_trunc_field)
            .order_by(date_trunc_field)
        )
        trend_rows = (await s.execute(trend_query)).all()

        trend_points = []
        for grp, val in trend_rows:
            if not grp:
                continue
            if group_by == "yearly":
                label = grp.strftime("%Y")
            elif group_by == "monthly":
                label = grp.strftime("%b %Y")
            elif group_by == "weekly":
                label = f"Wk {grp.isocalendar()[1]} ({grp.year})"
            else: # daily
                label = grp.strftime("%b %d")

            trend_points.append({
                "m": label,
                "v": int(val or 0)
            })

        return {
            "kpis": {
                "total_executions": total_execs,
                "success_executions": success_execs,
                "failed_executions": failed_execs,
                "total_files_processed": total_files,
                "total_data_processed_bytes": total_bytes,
                "most_popular_tool": most_popular,
                "least_used_tool": least_used,
            },
            "tools_list": tools_list,
            "trend": trend_points
        }

    async def _monthly_conversions(self) -> list[dict[str, Any]]:
        month = func.date_trunc("month", ProcessingJob.created_at)
        rows = (
            await self.session.execute(
                select(month.label("m"), func.count(ProcessingJob.id).label("v"))
                .group_by(month)
                .order_by(month)
            )
        ).all()
        out: list[dict[str, Any]] = []
        for m, v in rows:
            label = _MONTHS[m.month - 1] if isinstance(m, datetime) else str(m)
            out.append({"m": label, "v": int(v)})
        return out

    async def _tool_usage_counts(self, *, limit: int) -> list[dict[str, Any]]:
        rows = (
            await self.session.execute(
                select(ProcessingJob.tool, func.count(ProcessingJob.id).label("n"))
                .group_by(ProcessingJob.tool)
                .order_by(func.count(ProcessingJob.id).desc())
                .limit(limit)
            )
        ).all()
        return [{"tool": tool, "count": int(n)} for tool, n in rows]

    async def _tool_usage_distribution(self, *, limit: int) -> list[dict[str, Any]]:
        counts = await self._tool_usage_counts(limit=limit)
        total = sum(c["count"] for c in counts) or 1
        return [
            {"tool": c["tool"], "count": c["count"], "pct": round(100 * c["count"] / total, 1)}
            for c in counts
        ]

    async def _recent_activity(self, *, limit: int) -> list[dict[str, Any]]:
        rows = (
            await self.session.execute(
                select(AdminAuditLog)
                .order_by(AdminAuditLog.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        return [
            {
                "action": r.action,
                "summary": r.summary,
                "actor": r.actor_email,
                "category": r.category,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]

    # ─────────────────────────────────────────────────────────────────────
    # Users
    # ─────────────────────────────────────────────────────────────────────
    def _conversions_subq(self):
        return (
            select(func.count(ProcessingJob.id))
            .where(ProcessingJob.user_id == User.id)
            .correlate(User)
            .scalar_subquery()
        )

    async def list_users(
        self,
        *,
        page: PaginationParams,
        q: str | None = None,
        plan: str | None = None,
        status: str | None = None,
        sort: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        conv = self._conversions_subq()
        stmt = select(User, conv.label("conversions"))
        count_stmt = select(User.id)
        if q:
            like = f"%{q.lower()}%"
            pred = or_(func.lower(User.name).like(like), func.lower(User.email).like(like))
            stmt = stmt.where(pred)
            count_stmt = count_stmt.where(pred)
        if plan:
            stmt = stmt.where(User.plan == plan)
            count_stmt = count_stmt.where(User.plan == plan)
        if status:
            stmt = stmt.where(User.status == status)
            count_stmt = count_stmt.where(User.status == status)

        sort_map = {
            "name": User.name.asc(),
            "-name": User.name.desc(),
            "conversions": conv.asc(),
            "-conversions": conv.desc(),
            "created_at": User.created_at.asc(),
            "-created_at": User.created_at.desc(),
        }
        stmt = stmt.order_by(sort_map.get(sort or "-created_at", User.created_at.desc()))

        total = await self._count(count_stmt)
        rows = (
            await self.session.execute(stmt.limit(page.limit).offset(page.offset))
        ).all()
        out = []
        for user, conversions in rows:
            data = self._user_row(user)
            data["conversions"] = int(conversions or 0)
            out.append(data)
        return out, total

    @staticmethod
    def _user_row(user: User) -> dict[str, Any]:
        return {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "plan": user.plan,
            "status": user.status,
            "is_admin": user.is_admin,
            "avatar": user.avatar,
            "conversions": 0,
            "created_at": user.created_at,
            "updated_at": user.updated_at,
        }

    async def get_user(self, user_id: uuid.UUID) -> User:
        user = await self.session.get(User, user_id)
        if user is None:
            raise NotFoundError("User not found.")
        return user

    async def user_detail(self, user_id: uuid.UUID) -> dict[str, Any]:
        user = await self.get_user(user_id)
        conversions = int(
            (
                await self.session.execute(
                    select(func.count(ProcessingJob.id)).where(
                        ProcessingJob.user_id == user_id
                    )
                )
            ).scalar_one()
        )
        files_count = int(
            (
                await self.session.execute(
                    select(func.count(StoredFile.id)).where(
                        StoredFile.user_id == user_id
                    )
                )
            ).scalar_one()
        )
        sub = (
            await self.session.execute(
                select(Subscription)
                .where(Subscription.user_id == user_id)
                .order_by(Subscription.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        data = self._user_row(user)
        data["conversions"] = conversions
        data["files_count"] = files_count
        data["email_verified_at"] = user.email_verified_at
        data["subscription"] = self._subscription_row(sub, user) if sub else None
        return data

    async def create_user(self, payload) -> User:
        email = payload.email.strip().lower()
        exists = (
            await self.session.execute(
                select(User.id).where(func.lower(User.email) == email)
            )
        ).scalar_one_or_none()
        if exists is not None:
            raise ConflictError("An account with this email already exists.")
        user = User(
            name=payload.name.strip(),
            email=email,
            password_hash=hash_password(payload.password),
            plan=payload.plan,
            is_admin=payload.is_admin,
        )
        self.session.add(user)
        await self.session.commit()
        return user

    async def update_user(self, user_id: uuid.UUID, payload) -> User:
        user = await self.get_user(user_id)
        if payload.name is not None:
            user.name = payload.name.strip()
        if payload.plan is not None:
            user.plan = payload.plan
        if payload.status is not None:
            user.status = payload.status
        if payload.is_admin is not None:
            user.is_admin = payload.is_admin
        if payload.password:
            user.password_hash = hash_password(payload.password)
        await self.session.commit()
        # ``updated_at`` (DB-side onupdate) is expired after the UPDATE flush;
        # refresh so later synchronous attribute access doesn't trigger a lazy
        # load outside the async greenlet.
        await self.session.refresh(user)
        return user

    async def set_user_status(self, user_id: uuid.UUID, status: str) -> User:
        user = await self.get_user(user_id)
        user.status = status
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def delete_user(self, user_id: uuid.UUID) -> None:
        user = await self.get_user(user_id)
        await self.session.delete(user)
        await self.session.commit()

    async def bulk_users(self, action: str, ids: list[uuid.UUID]) -> int:
        if not ids:
            return 0
        if action == "delete":
            result = await self.session.execute(delete(User).where(User.id.in_(ids)))
            affected = int(result.rowcount or 0)
        elif action in {"suspend", "activate"}:
            status = UserStatus.SUSPENDED if action == "suspend" else UserStatus.ACTIVE
            users = (
                await self.session.execute(select(User).where(User.id.in_(ids)))
            ).scalars().all()
            affected = 0
            for u in users:
                if u.status != status:
                    u.status = status
                    affected += 1
        else:
            raise BadRequestError(f"Unknown bulk action: {action}")
        await self.session.commit()
        return affected

    async def user_stats(self) -> dict[str, int]:
        s = self.session
        total = int((await s.execute(select(func.count(User.id)))).scalar_one())
        active = int(
            (
                await s.execute(
                    select(func.count(User.id)).where(User.status == UserStatus.ACTIVE)
                )
            ).scalar_one()
        )
        suspended = int(
            (
                await s.execute(
                    select(func.count(User.id)).where(
                        User.status == UserStatus.SUSPENDED
                    )
                )
            ).scalar_one()
        )
        pro = int(
            (
                await s.execute(
                    select(func.count(User.id)).where(User.plan != "free")
                )
            ).scalar_one()
        )
        return {"total": total, "active": active, "suspended": suspended, "pro": pro}

    # ─────────────────────────────────────────────────────────────────────
    # Subscribers
    # ─────────────────────────────────────────────────────────────────────
    @staticmethod
    def _subscription_row(sub: Subscription, user: User | None) -> dict[str, Any]:
        return {
            "id": sub.id,
            "user_id": sub.user_id,
            "user_name": user.name if user else None,
            "user_email": user.email if user else None,
            "plan": sub.plan,
            "price_cents": sub.price_cents,
            "currency": sub.currency,
            "interval": sub.interval,
            "status": sub.status,
            "provider": sub.provider,
            "started_at": sub.started_at,
            "renews_at": sub.renews_at,
            "payments_count": sub.payments_count,
            "created_at": sub.created_at,
        }

    async def list_subscriptions(
        self,
        *,
        page: PaginationParams,
        q: str | None = None,
        status: str | None = None,
        sort: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        stmt = select(Subscription, User).join(User, Subscription.user_id == User.id)
        count_stmt = select(Subscription.id).join(User, Subscription.user_id == User.id)
        if q:
            like = f"%{q.lower()}%"
            pred = or_(func.lower(User.name).like(like), func.lower(User.email).like(like))
            stmt = stmt.where(pred)
            count_stmt = count_stmt.where(pred)
        if status:
            stmt = stmt.where(Subscription.status == status)
            count_stmt = count_stmt.where(Subscription.status == status)
        sort_map = {
            "user": User.name.asc(),
            "-user": User.name.desc(),
            "price": Subscription.price_cents.asc(),
            "-price": Subscription.price_cents.desc(),
            "renews_at": Subscription.renews_at.asc(),
            "-renews_at": Subscription.renews_at.desc(),
            "created_at": Subscription.created_at.asc(),
            "-created_at": Subscription.created_at.desc(),
        }
        stmt = stmt.order_by(
            sort_map.get(sort or "-created_at", Subscription.created_at.desc())
        )
        total = await self._count(count_stmt)
        rows = (
            await self.session.execute(stmt.limit(page.limit).offset(page.offset))
        ).all()
        return [self._subscription_row(sub, user) for sub, user in rows], total

    async def subscription_stats(self) -> dict[str, Any]:
        s = self.session
        active = int(
            (
                await s.execute(
                    select(func.count(Subscription.id)).where(
                        Subscription.status == SubscriptionStatus.ACTIVE
                    )
                )
            ).scalar_one()
        )
        expired = int(
            (
                await s.execute(
                    select(func.count(Subscription.id)).where(
                        Subscription.status == SubscriptionStatus.EXPIRED
                    )
                )
            ).scalar_one()
        )
        mrr_cents = int(
            (
                await s.execute(
                    select(func.coalesce(func.sum(Subscription.price_cents), 0)).where(
                        Subscription.status == SubscriptionStatus.ACTIVE,
                        Subscription.interval == "monthly",
                    )
                )
            ).scalar_one()
        )
        denom = active + expired
        churn = round(100 * expired / denom, 1) if denom else 0.0
        return {"active": active, "expired": expired, "mrr_cents": mrr_cents, "churn": churn}

    async def create_subscription(self, payload) -> Subscription:
        user = await self.get_user(payload.user_id)
        sub = Subscription(
            user_id=user.id,
            plan=payload.plan,
            price_cents=payload.price_cents,
            currency=payload.currency,
            interval=payload.interval,
            status=payload.status,
            started_at=datetime.now(UTC),
            renews_at=payload.renews_at,
        )
        self.session.add(sub)
        await self.session.commit()
        return sub

    async def update_subscription(self, sub_id: uuid.UUID, payload) -> Subscription:
        sub = await self.session.get(Subscription, sub_id)
        if sub is None:
            raise NotFoundError("Subscription not found.")
        for field in ("plan", "price_cents", "interval", "status", "renews_at"):
            val = getattr(payload, field)
            if val is not None:
                setattr(sub, field, val)
        await self.session.commit()
        return sub

    async def delete_subscription(self, sub_id: uuid.UUID) -> None:
        sub = await self.session.get(Subscription, sub_id)
        if sub is None:
            raise NotFoundError("Subscription not found.")
        await self.session.delete(sub)
        await self.session.commit()

    # ─────────────────────────────────────────────────────────────────────
    # Tools
    # ─────────────────────────────────────────────────────────────────────
    async def list_tools(self) -> list[dict[str, Any]]:
        tools = (
            await self.session.execute(
                select(ToolConfig).order_by(ToolConfig.sort_order, ToolConfig.name)
            )
        ).scalars().all()
        usage_rows = (
            await self.session.execute(
                select(ProcessingJob.tool, func.count(ProcessingJob.id)).group_by(
                    ProcessingJob.tool
                )
            )
        ).all()
        usage = {tool: int(n) for tool, n in usage_rows}
        return [
            {
                "id": t.id,
                "slug": t.slug,
                "name": t.name,
                "category": t.category,
                "enabled": t.enabled,
                "visible": t.visible,
                "maintenance": t.maintenance,
                "file_limit_mb": t.file_limit_mb,
                "usage": usage.get(t.slug, 0),
            }
            for t in tools
        ]

    async def update_tool(self, slug: str, payload) -> ToolConfig:
        tool = (
            await self.session.execute(
                select(ToolConfig).where(ToolConfig.slug == slug)
            )
        ).scalar_one_or_none()
        if tool is None:
            raise NotFoundError("Tool not found.")
        for field in ("enabled", "visible", "maintenance", "file_limit_mb"):
            val = getattr(payload, field)
            if val is not None:
                setattr(tool, field, val)
        await self.session.commit()
        return tool

    # ─────────────────────────────────────────────────────────────────────
    # Files
    # ─────────────────────────────────────────────────────────────────────
    async def file_stats(self) -> dict[str, Any]:
        rows = (
            await self.session.execute(
                select(
                    StoredFile.category,
                    func.count(StoredFile.id),
                    func.coalesce(func.sum(StoredFile.size_bytes), 0),
                )
                .where(StoredFile.status == FileStatus.ACTIVE)
                .group_by(StoredFile.category)
            )
        ).all()
        by_category = {
            str(cat): {"count": int(n), "bytes": int(size)} for cat, n, size in rows
        }
        total_bytes = sum(v["bytes"] for v in by_category.values())
        total_count = sum(v["count"] for v in by_category.values())
        return {
            "total_bytes": total_bytes,
            "total_count": total_count,
            "by_category": by_category,
        }

    async def list_files(
        self,
        *,
        page: PaginationParams,
        q: str | None = None,
        category: str | None = None,
        sort: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        tool_subquery = (
            select(ProcessingJob.tool)
            .select_from(JobFile)
            .join(ProcessingJob, JobFile.job_id == ProcessingJob.id)
            .where(JobFile.file_id == StoredFile.id)
            .order_by(ProcessingJob.created_at.desc())
            .limit(1)
            .correlate(StoredFile)
            .scalar_subquery()
        )

        stmt = select(StoredFile, User.email, tool_subquery).outerjoin(
            User, StoredFile.user_id == User.id
        )
        count_stmt = select(StoredFile.id)
        if q:
            like = f"%{q.lower()}%"
            stmt = stmt.where(func.lower(StoredFile.original_name).like(like))
            count_stmt = count_stmt.where(func.lower(StoredFile.original_name).like(like))
        if category:
            stmt = stmt.where(StoredFile.category == category)
            count_stmt = count_stmt.where(StoredFile.category == category)
        sort_map = {
            "name": StoredFile.original_name.asc(),
            "-name": StoredFile.original_name.desc(),
            "size": StoredFile.size_bytes.asc(),
            "-size": StoredFile.size_bytes.desc(),
            "created_at": StoredFile.created_at.asc(),
            "-created_at": StoredFile.created_at.desc(),
        }
        stmt = stmt.order_by(
            sort_map.get(sort or "-created_at", StoredFile.created_at.desc())
        )
        total = await self._count(count_stmt)
        rows = (
            await self.session.execute(stmt.limit(page.limit).offset(page.offset))
        ).all()
        out = [
            {
                "id": f.id,
                "original_name": f.original_name,
                "category": str(f.category),
                "media_type": f.media_type,
                "size_bytes": f.size_bytes,
                "status": str(f.status),
                "owner_email": email,
                "tool": tool,
                "created_at": f.created_at,
                "expires_at": f.expires_at,
            }
            for f, email, tool in rows
        ]
        return out, total

    async def delete_file(self, file_id: uuid.UUID) -> None:
        f = await self.session.get(StoredFile, file_id)
        if f is None:
            raise NotFoundError("File not found.")
        f.status = FileStatus.DELETED
        await self.session.commit()

    async def purge_expired_files(self) -> int:
        now = datetime.now(UTC)
        files = (
            await self.session.execute(
                select(StoredFile).where(
                    StoredFile.status == FileStatus.ACTIVE,
                    StoredFile.expires_at.is_not(None),
                    StoredFile.expires_at < now,
                )
            )
        ).scalars().all()
        for f in files:
            f.status = FileStatus.EXPIRED
        await self.session.commit()
        return len(files)

    # ─────────────────────────────────────────────────────────────────────
    # Jobs
    # ─────────────────────────────────────────────────────────────────────
    @staticmethod
    def _job_file_name(job: ProcessingJob) -> str | None:
        """Best-effort display name for a job: its first input file, falling
        back to any linked file. ``files`` is selectin-loaded on the model."""
        links = job.files or []
        inputs = [l for l in links if str(l.role) == JobFileRole.INPUT]
        chosen = (inputs or links)
        if not chosen:
            return None
        f = chosen[0].file
        return f.original_name if f is not None else None

    def _job_row(self, job: ProcessingJob, user_email: str | None) -> dict[str, Any]:
        return {
            "id": job.id,
            "tool": job.tool,
            "status": str(job.status),
            "progress": job.progress,
            "file_name": self._job_file_name(job),
            "user_email": user_email,
            "created_at": job.created_at,
            "error_code": job.error_code,
        }

    async def list_jobs(
        self,
        *,
        page: PaginationParams,
        q: str | None = None,
        status: str | None = None,
        sort: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        stmt = select(ProcessingJob, User.email).outerjoin(
            User, ProcessingJob.user_id == User.id
        )
        count_stmt = select(ProcessingJob.id)
        if q:
            like = f"%{q.lower()}%"
            stmt = stmt.where(func.lower(ProcessingJob.tool).like(like))
            count_stmt = count_stmt.where(func.lower(ProcessingJob.tool).like(like))
        if status:
            stmt = stmt.where(ProcessingJob.status == status)
            count_stmt = count_stmt.where(ProcessingJob.status == status)
        sort_map = {
            "tool": ProcessingJob.tool.asc(),
            "-tool": ProcessingJob.tool.desc(),
            "status": ProcessingJob.status.asc(),
            "-status": ProcessingJob.status.desc(),
            "progress": ProcessingJob.progress.asc(),
            "-progress": ProcessingJob.progress.desc(),
            "created_at": ProcessingJob.created_at.asc(),
            "-created_at": ProcessingJob.created_at.desc(),
        }
        stmt = stmt.order_by(
            sort_map.get(sort or "-created_at", ProcessingJob.created_at.desc())
        )
        total = await self._count(count_stmt)
        rows = (
            await self.session.execute(stmt.limit(page.limit).offset(page.offset))
        ).all()
        out = [self._job_row(j, email) for j, email in rows]
        return out, total

    async def job_stats(self) -> dict[str, int]:
        rows = (
            await self.session.execute(
                select(ProcessingJob.status, func.count(ProcessingJob.id)).group_by(
                    ProcessingJob.status
                )
            )
        ).all()
        counts = {str(status): int(n) for status, n in rows}
        return {
            "processing": counts.get(JobStatus.PROCESSING, 0),
            "queued": counts.get(JobStatus.QUEUED, 0) + counts.get(JobStatus.PENDING, 0),
            "completed": counts.get(JobStatus.COMPLETED, 0),
            "failed": counts.get(JobStatus.FAILED, 0),
        }

    async def cancel_job(self, job_id: uuid.UUID) -> ProcessingJob:
        job = await self.session.get(ProcessingJob, job_id)
        if job is None:
            raise NotFoundError("Job not found.")
        if JobStatus(job.status).is_terminal:
            raise BadRequestError("Job has already finished.")
        job.status = JobStatus.CANCELLED
        job.finished_at = datetime.now(UTC)
        await self.session.commit()
        return job

    async def retry_job(self, job_id: uuid.UUID) -> ProcessingJob:
        job = await self.session.get(ProcessingJob, job_id)
        if job is None:
            raise NotFoundError("Job not found.")
        job.status = JobStatus.QUEUED
        job.progress = 0
        job.error_code = None
        job.error_message = None
        job.finished_at = None
        await self.session.commit()
        return job

    # ─────────────────────────────────────────────────────────────────────
    # Feedback
    # ─────────────────────────────────────────────────────────────────────
    async def list_feedback(
        self,
        *,
        page: PaginationParams,
        category: str | None = None,
        q: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        stmt = select(Feedback)
        count_stmt = select(Feedback.id)
        if category:
            stmt = stmt.where(Feedback.category == category)
            count_stmt = count_stmt.where(Feedback.category == category)
        if q:
            like = f"%{q.lower()}%"
            pred = or_(
                func.lower(Feedback.name).like(like),
                func.lower(Feedback.email).like(like),
                func.lower(Feedback.message).like(like),
            )
            stmt = stmt.where(pred)
            count_stmt = count_stmt.where(pred)
        stmt = stmt.order_by(Feedback.created_at.desc())
        total = await self._count(count_stmt)
        rows = (
            await self.session.execute(stmt.limit(page.limit).offset(page.offset))
        ).scalars().all()
        out = [
            {
                "id": f.id,
                "name": f.name,
                "email": f.email,
                "subject": f.subject,
                "category": str(f.category),
                "message": f.message,
                "has_attachment": f.attachment_data is not None,
                "created_at": f.created_at,
            }
            for f in rows
        ]
        return out, total

    async def feedback_stats(self) -> dict[str, int]:
        rows = (
            await self.session.execute(
                select(Feedback.category, func.count(Feedback.id)).group_by(
                    Feedback.category
                )
            )
        ).all()
        counts = {str(cat): int(n) for cat, n in rows}
        counts["total"] = sum(counts.values())
        return counts

    async def delete_feedback(self, fb_id: uuid.UUID) -> None:
        fb = await self.session.get(Feedback, fb_id)
        if fb is None:
            raise NotFoundError("Feedback not found.")
        await self.session.delete(fb)
        await self.session.commit()

    # ─────────────────────────────────────────────────────────────────────
    # Contact messages
    # ─────────────────────────────────────────────────────────────────────
    @staticmethod
    def _message_row(m: ContactMessage) -> dict[str, Any]:
        return {
            "id": m.id,
            "name": m.name,
            "email": m.email,
            "subject": m.subject,
            "message": m.message,
            "is_read": m.is_read,
            "reply": m.reply,
            "replied_at": m.replied_at,
            "created_at": m.created_at,
        }

    async def list_messages(
        self, *, page: PaginationParams, q: str | None = None, unread: bool | None = None
    ) -> tuple[list[dict[str, Any]], int]:
        stmt = select(ContactMessage)
        count_stmt = select(ContactMessage.id)
        if q:
            like = f"%{q.lower()}%"
            pred = or_(
                func.lower(ContactMessage.name).like(like),
                func.lower(ContactMessage.email).like(like),
                func.lower(ContactMessage.subject).like(like),
            )
            stmt = stmt.where(pred)
            count_stmt = count_stmt.where(pred)
        if unread:
            stmt = stmt.where(ContactMessage.is_read.is_(False))
            count_stmt = count_stmt.where(ContactMessage.is_read.is_(False))
        stmt = stmt.order_by(ContactMessage.created_at.desc())
        total = await self._count(count_stmt)
        rows = (
            await self.session.execute(stmt.limit(page.limit).offset(page.offset))
        ).scalars().all()
        return [self._message_row(m) for m in rows], total

    async def get_message(self, msg_id: uuid.UUID) -> ContactMessage:
        m = await self.session.get(ContactMessage, msg_id)
        if m is None:
            raise NotFoundError("Message not found.")
        return m

    async def mark_message_read(self, msg_id: uuid.UUID, read: bool = True) -> ContactMessage:
        m = await self.get_message(msg_id)
        m.is_read = read
        await self.session.commit()
        return m

    async def reply_message(self, msg_id: uuid.UUID, reply: str) -> ContactMessage:
        m = await self.get_message(msg_id)
        m.reply = reply
        m.replied_at = datetime.now(UTC)
        m.is_read = True
        await self.session.commit()
        return m

    async def delete_message(self, msg_id: uuid.UUID) -> None:
        m = await self.get_message(msg_id)
        await self.session.delete(m)
        await self.session.commit()

    async def unread_message_count(self) -> int:
        return int(
            (
                await self.session.execute(
                    select(func.count(ContactMessage.id)).where(
                        ContactMessage.is_read.is_(False)
                    )
                )
            ).scalar_one()
        )

    # ─────────────────────────────────────────────────────────────────────
    # Announcements
    # ─────────────────────────────────────────────────────────────────────
    async def list_announcements(
        self, *, page: PaginationParams, q: str | None = None
    ) -> tuple[list[Announcement], int]:
        stmt = select(Announcement)
        count_stmt = select(Announcement.id)
        if q:
            like = f"%{q.lower()}%"
            pred = or_(
                func.lower(Announcement.title).like(like),
                func.lower(Announcement.body).like(like),
            )
            stmt = stmt.where(pred)
            count_stmt = count_stmt.where(pred)
        stmt = stmt.order_by(Announcement.created_at.desc())
        total = await self._count(count_stmt)
        rows = list(
            (
                await self.session.execute(stmt.limit(page.limit).offset(page.offset))
            ).scalars().all()
        )
        return rows, total

    async def create_announcement(self, payload, author: User | None) -> Announcement:
        ann = Announcement(
            title=payload.title,
            body=payload.body,
            status=payload.status,
            audience=payload.audience,
            author_id=author.id if author else None,
            published_at=datetime.now(UTC)
            if payload.status == ContentStatus.PUBLISHED
            else None,
        )
        self.session.add(ann)
        await self.session.commit()
        return ann

    async def update_announcement(self, ann_id: uuid.UUID, payload) -> Announcement:
        ann = await self.session.get(Announcement, ann_id)
        if ann is None:
            raise NotFoundError("Announcement not found.")
        was_published = ann.status == ContentStatus.PUBLISHED
        ann.title = payload.title
        ann.body = payload.body
        ann.status = payload.status
        ann.audience = payload.audience
        if payload.status == ContentStatus.PUBLISHED and not was_published:
            ann.published_at = datetime.now(UTC)
        await self.session.commit()
        await self.session.refresh(ann)
        return ann

    async def delete_announcement(self, ann_id: uuid.UUID) -> None:
        ann = await self.session.get(Announcement, ann_id)
        if ann is None:
            raise NotFoundError("Announcement not found.")
        await self.session.delete(ann)
        await self.session.commit()

    # ─────────────────────────────────────────────────────────────────────
    # FAQs
    # ─────────────────────────────────────────────────────────────────────
    async def list_faqs(
        self, *, page: PaginationParams, q: str | None = None
    ) -> tuple[list[Faq], int]:
        stmt = select(Faq)
        count_stmt = select(Faq.id)
        if q:
            like = f"%{q.lower()}%"
            pred = or_(
                func.lower(Faq.question).like(like),
                func.lower(Faq.answer).like(like),
            )
            stmt = stmt.where(pred)
            count_stmt = count_stmt.where(pred)
        stmt = stmt.order_by(Faq.sort_order, Faq.created_at)
        total = await self._count(count_stmt)
        rows = list(
            (
                await self.session.execute(stmt.limit(page.limit).offset(page.offset))
            ).scalars().all()
        )
        return rows, total

    async def create_faq(self, payload) -> Faq:
        faq = Faq(
            question=payload.question,
            answer=payload.answer,
            category=payload.category,
            sort_order=payload.sort_order,
            published=payload.published,
        )
        self.session.add(faq)
        await self.session.commit()
        return faq

    async def update_faq(self, faq_id: uuid.UUID, payload) -> Faq:
        faq = await self.session.get(Faq, faq_id)
        if faq is None:
            raise NotFoundError("FAQ not found.")
        faq.question = payload.question
        faq.answer = payload.answer
        faq.category = payload.category
        faq.sort_order = payload.sort_order
        faq.published = payload.published
        await self.session.commit()
        return faq

    async def delete_faq(self, faq_id: uuid.UUID) -> None:
        faq = await self.session.get(Faq, faq_id)
        if faq is None:
            raise NotFoundError("FAQ not found.")
        await self.session.delete(faq)
        await self.session.commit()

    # ─────────────────────────────────────────────────────────────────────
    # Blog posts
    # ─────────────────────────────────────────────────────────────────────
    async def list_blog(
        self, *, page: PaginationParams, q: str | None = None
    ) -> tuple[list[BlogPost], int]:
        stmt = select(BlogPost)
        count_stmt = select(BlogPost.id)
        if q:
            like = f"%{q.lower()}%"
            pred = or_(
                func.lower(BlogPost.title).like(like),
                func.lower(BlogPost.excerpt).like(like),
            )
            stmt = stmt.where(pred)
            count_stmt = count_stmt.where(pred)
        stmt = stmt.order_by(BlogPost.created_at.desc())
        total = await self._count(count_stmt)
        rows = list(
            (
                await self.session.execute(stmt.limit(page.limit).offset(page.offset))
            ).scalars().all()
        )
        return rows, total

    async def create_blog(self, payload, author: User | None) -> BlogPost:
        slug = payload.slug or _slugify(payload.title)
        post = BlogPost(
            title=payload.title,
            slug=slug,
            excerpt=payload.excerpt,
            content=payload.content or "",
            status=payload.status,
            cover_image=payload.cover_image,
            author_id=author.id if author else None,
            published_at=datetime.now(UTC)
            if payload.status == ContentStatus.PUBLISHED
            else None,
        )
        self.session.add(post)
        await self.session.commit()
        return post

    async def update_blog(self, post_id: uuid.UUID, payload) -> BlogPost:
        post = await self.session.get(BlogPost, post_id)
        if post is None:
            raise NotFoundError("Post not found.")
        was_published = post.status == ContentStatus.PUBLISHED
        post.title = payload.title
        if payload.slug:
            post.slug = payload.slug
        post.excerpt = payload.excerpt
        post.content = payload.content or ""
        post.status = payload.status
        post.cover_image = payload.cover_image
        if payload.status == ContentStatus.PUBLISHED and not was_published:
            post.published_at = datetime.now(UTC)
        await self.session.commit()
        await self.session.refresh(post)
        return post

    async def delete_blog(self, post_id: uuid.UUID) -> None:
        post = await self.session.get(BlogPost, post_id)
        if post is None:
            raise NotFoundError("Post not found.")
        await self.session.delete(post)
        await self.session.commit()

    # ─────────────────────────────────────────────────────────────────────
    # Content pages
    # ─────────────────────────────────────────────────────────────────────
    async def list_pages(
        self, *, page: PaginationParams, q: str | None = None
    ) -> tuple[list[ContentPage], int]:
        stmt = select(ContentPage)
        count_stmt = select(ContentPage.id)
        if q:
            like = f"%{q.lower()}%"
            pred = or_(
                func.lower(ContentPage.title).like(like),
                func.lower(ContentPage.path).like(like),
            )
            stmt = stmt.where(pred)
            count_stmt = count_stmt.where(pred)
        stmt = stmt.order_by(ContentPage.created_at)
        total = await self._count(count_stmt)
        rows = list(
            (
                await self.session.execute(stmt.limit(page.limit).offset(page.offset))
            ).scalars().all()
        )
        return rows, total

    async def create_page(self, payload) -> ContentPage:
        slug = payload.slug or _slugify(payload.title)
        page = ContentPage(
            title=payload.title,
            slug=slug,
            path=payload.path,
            content=payload.content,
            status=payload.status,
            meta_title=payload.meta_title,
            meta_description=payload.meta_description,
        )
        self.session.add(page)
        await self.session.commit()
        return page

    async def update_page(self, page_id: uuid.UUID, payload) -> ContentPage:
        page = await self.session.get(ContentPage, page_id)
        if page is None:
            raise NotFoundError("Page not found.")
        page.title = payload.title
        if payload.slug:
            page.slug = payload.slug
        page.path = payload.path
        page.content = payload.content
        page.status = payload.status
        page.meta_title = payload.meta_title
        page.meta_description = payload.meta_description
        await self.session.commit()
        await self.session.refresh(page)
        return page

    async def delete_page(self, page_id: uuid.UUID) -> None:
        page = await self.session.get(ContentPage, page_id)
        if page is None:
            raise NotFoundError("Page not found.")
        await self.session.delete(page)
        await self.session.commit()

    # ─────────────────────────────────────────────────────────────────────
    # Audit / error logs
    # ─────────────────────────────────────────────────────────────────────
    async def list_audit(
        self, *, page: PaginationParams, category: str | None = None, q: str | None = None
    ) -> tuple[list[AdminAuditLog], int]:
        stmt = select(AdminAuditLog)
        count_stmt = select(AdminAuditLog.id)
        if category:
            stmt = stmt.where(AdminAuditLog.category == category)
            count_stmt = count_stmt.where(AdminAuditLog.category == category)
        if q:
            like = f"%{q.lower()}%"
            pred = or_(
                func.lower(AdminAuditLog.summary).like(like),
                func.lower(AdminAuditLog.action).like(like),
            )
            stmt = stmt.where(pred)
            count_stmt = count_stmt.where(pred)
        stmt = stmt.order_by(AdminAuditLog.created_at.desc())
        total = await self._count(count_stmt)
        rows = list(
            (
                await self.session.execute(stmt.limit(page.limit).offset(page.offset))
            ).scalars().all()
        )
        return rows, total

    async def list_errors(
        self, *, page: PaginationParams, level: str | None = None, q: str | None = None
    ) -> tuple[list[ErrorLog], int]:
        stmt = select(ErrorLog)
        count_stmt = select(ErrorLog.id)
        if level:
            stmt = stmt.where(ErrorLog.level == level)
            count_stmt = count_stmt.where(ErrorLog.level == level)
        if q:
            like = f"%{q.lower()}%"
            stmt = stmt.where(func.lower(ErrorLog.message).like(like))
            count_stmt = count_stmt.where(func.lower(ErrorLog.message).like(like))
        stmt = stmt.order_by(ErrorLog.resolved, ErrorLog.created_at.desc())
        total = await self._count(count_stmt)
        rows = list(
            (
                await self.session.execute(stmt.limit(page.limit).offset(page.offset))
            ).scalars().all()
        )
        return rows, total

    async def resolve_error(self, err_id: uuid.UUID, resolved: bool = True) -> ErrorLog:
        err = await self.session.get(ErrorLog, err_id)
        if err is None:
            raise NotFoundError("Error log not found.")
        err.resolved = resolved
        await self.session.commit()
        return err

    async def delete_error(self, err_id: uuid.UUID) -> None:
        err = await self.session.get(ErrorLog, err_id)
        if err is None:
            raise NotFoundError("Error log not found.")
        await self.session.delete(err)
        await self.session.commit()

    async def clear_resolved_errors(self) -> int:
        result = await self.session.execute(
            delete(ErrorLog).where(ErrorLog.resolved.is_(True))
        )
        await self.session.commit()
        return int(result.rowcount or 0)

    # ─────────────────────────────────────────────────────────────────────
    # Monitoring
    # ─────────────────────────────────────────────────────────────────────
    async def performance(self) -> dict[str, Any]:
        metrics: dict[str, Any] = {}
        try:
            import psutil

            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            metrics = {
                "cpu_percent": psutil.cpu_percent(interval=0.1),
                "memory_percent": mem.percent,
                "memory_used": mem.used,
                "memory_total": mem.total,
                "disk_percent": disk.percent,
                "disk_used": disk.used,
                "disk_total": disk.total,
                "available": True,
            }
        except Exception:
            metrics = {"available": False}

        # Service health inferred from real signals.
        pending = int(
            (
                await self.session.execute(
                    select(func.count(ProcessingJob.id)).where(
                        ProcessingJob.status.in_([JobStatus.QUEUED, JobStatus.PENDING])
                    )
                )
            ).scalar_one()
        )
        recent_failures = int(
            (
                await self.session.execute(
                    select(func.count(ProcessingJob.id)).where(
                        ProcessingJob.status == JobStatus.FAILED,
                        ProcessingJob.finished_at
                        >= datetime.now(UTC) - timedelta(hours=1),
                    )
                )
            ).scalar_one()
        )
        redis_ok = True
        try:
            from app.db.redis import get_redis

            await get_redis().ping()
        except Exception:
            redis_ok = False

        # Real DB probe: a trivial round-trip proves the connection is live.
        db_ok = True
        try:
            await self.session.execute(select(1))
        except Exception:
            db_ok = False

        # Real storage probe: the upload directory must exist and be writable,
        # and we warn when the disk is nearly full.
        storage_status = "Healthy"
        try:
            from app.config import get_settings

            storage_root = Path(get_settings().storage_root_resolved)
            if not (storage_root.exists() and os.access(storage_root, os.W_OK)):
                storage_status = "Down"
            elif metrics.get("available") and metrics.get("disk_percent", 0) >= 90:
                storage_status = "Warning"
        except Exception:
            storage_status = "Warning"

        services = [
            # The request reaching this handler is itself proof the API is up.
            {"name": "API Gateway", "status": "Healthy"},
            {"name": "PDF Workers", "status": "Warning" if recent_failures else "Healthy"},
            {"name": "Database", "status": "Healthy" if db_ok else "Down"},
            {"name": "Redis Cache", "status": "Healthy" if redis_ok else "Warning"},
            {"name": "Storage Service", "status": storage_status},
        ]
        metrics["services"] = services
        metrics["pending_jobs"] = pending
        metrics["recent_failures"] = recent_failures
        metrics["server_status"] = (
            "Operational" if db_ok and storage_status != "Down" else "Degraded"
        )
        return metrics

    async def live_activity(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        window = now - timedelta(minutes=15)
        active_jobs = int(
            (
                await self.session.execute(
                    select(func.count(ProcessingJob.id)).where(
                        ProcessingJob.status.in_(
                            [JobStatus.PROCESSING, JobStatus.QUEUED]
                        )
                    )
                )
            ).scalar_one()
        )
        recent_jobs = (
            await self.session.execute(
                select(ProcessingJob, User.email)
                .outerjoin(User, ProcessingJob.user_id == User.id)
                .where(ProcessingJob.created_at >= window)
                .order_by(ProcessingJob.created_at.desc())
                .limit(15)
            )
        ).all()
        today_jobs = int(
            (
                await self.session.execute(
                    select(func.count(ProcessingJob.id)).where(
                        ProcessingJob.created_at
                        >= now.replace(hour=0, minute=0, second=0, microsecond=0)
                    )
                )
            ).scalar_one()
        )
        recent = [
            {
                "tool": j.tool,
                "status": str(j.status),
                "user": email,
                "created_at": j.created_at.isoformat(),
            }
            for j, email in recent_jobs
        ]
        return {
            "active_jobs": active_jobs,
            "today_jobs": today_jobs,
            "recent": recent,
        }

    # ─────────────────────────────────────────────────────────────────────
    # Settings
    # ─────────────────────────────────────────────────────────────────────
    async def all_settings(self) -> dict[str, Any]:
        rows = (
            await self.session.execute(select(AppSetting))
        ).scalars().all()
        return {r.key: r.value for r in rows}

    async def get_setting(self, category: str) -> dict[str, Any]:
        row = (
            await self.session.execute(
                select(AppSetting).where(AppSetting.key == category)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Setting category not found.")
        return row.value

    @staticmethod
    def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
        """Recursively merge ``overrides`` into a copy of ``base`` so that
        nested objects (e.g. ``branding.social``, ``razorpay.plans`` container)
        are merged key-by-key rather than replaced wholesale. Lists and scalars
        are replaced outright."""
        out = dict(base)
        for key, val in overrides.items():
            if (
                key in out
                and isinstance(out[key], dict)
                and isinstance(val, dict)
            ):
                out[key] = AdminService._deep_merge(out[key], val)
            else:
                out[key] = val
        return out

    async def update_setting(
        self, category: str, value: dict[str, Any], actor: User | None
    ) -> dict[str, Any]:
        row = (
            await self.session.execute(
                select(AppSetting).where(AppSetting.key == category)
            )
        ).scalar_one_or_none()
        if row is None:
            row = AppSetting(key=category, category=category, value={})
            self.session.add(row)
        merged = self._deep_merge(row.value or {}, value)
        # JSONB columns need a new object identity to be flagged dirty.
        row.value = merged
        row.updated_by = actor.id if actor else None
        await self.session.commit()
        return merged
