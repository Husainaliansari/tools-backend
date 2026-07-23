"""Admin API router.

Aggregates every admin sub-router under a single ``/admin`` prefix, guarded by
:func:`app.dependencies.admin.get_current_admin`. Mounted by the v1 router at
``/api/v1/admin``. Completely additive: no existing route is touched.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.endpoints.admin import (
    billing,
    monitoring,
    overview,
    settings,
    storage,
    support,
    tools,
    users,
    website,
)
from app.dependencies.admin import get_current_admin

router = APIRouter(
    prefix="/admin",
    dependencies=[Depends(get_current_admin)],
)

for _module in (
    overview,
    users,
    billing,
    tools,
    storage,
    support,
    website,
    monitoring,
    settings,
):
    router.include_router(_module.router)
