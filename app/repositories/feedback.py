"""Data access for feedback submissions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_, select

from app.models.feedback import Feedback
from app.repositories.base import BaseRepository


class FeedbackRepository(BaseRepository[Feedback]):
    model = Feedback

    async def count_recent(
        self, *, since: datetime, email: str, client_ip: str | None
    ) -> int:
        """Count submissions from the same email OR IP created since ``since``.

        Powers the once-per-day limit: a match on either identifier counts, so
        neither changing the email on one machine nor reusing an email across
        machines slips past the window.
        """
        predicates = [func.lower(Feedback.email) == email.strip().lower()]
        if client_ip:
            predicates.append(Feedback.client_ip == client_ip)

        result = await self.session.execute(
            select(func.count())
            .select_from(Feedback)
            .where(Feedback.created_at >= since, or_(*predicates))
        )
        return int(result.scalar_one())
