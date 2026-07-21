"""Per-plan upload limits.

The single source of truth for how much each subscription tier may upload:
how many files per request, how large each file may be, and how large the
whole batch may be. Anonymous requests get the free tier.

Mirrored on the frontend in ``frontend/src/constants/planLimits.ts`` so the
client can validate before sending a byte — keep the two files in sync.
"""

from __future__ import annotations

from dataclasses import dataclass

_MB = 1024 * 1024


@dataclass(frozen=True)
class PlanLimits:
    """Upload ceilings for one subscription tier."""

    plan: str
    #: Human-facing tier name for error messages ("Free", "Pro", ...).
    label: str
    #: Maximum number of files in one upload / one job.
    max_files: int
    #: Maximum size of any single file, in megabytes.
    max_file_size_mb: int
    #: Maximum combined size of one upload / one job's inputs, in megabytes.
    max_total_size_mb: int

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * _MB

    @property
    def max_total_size_bytes(self) -> int:
        return self.max_total_size_mb * _MB


PLAN_LIMITS: dict[str, PlanLimits] = {
    "free": PlanLimits("free", "Free", 20, 50, 50),
    "basic": PlanLimits("basic", "Basic", 50, 500, 500),
    "pro": PlanLimits("pro", "Pro", 100, 1024, 1024),
    # No published tier of its own — enterprise accounts get the top tier.
    "enterprise": PlanLimits("enterprise", "Enterprise", 100, 1024, 1024),
}


def limits_for_plan(plan: str | None) -> PlanLimits:
    """Limits for a plan name; unknown plans and anonymous get the free tier."""
    return PLAN_LIMITS.get((plan or "free").lower(), PLAN_LIMITS["free"])
