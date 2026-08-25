"""Analytics tracking endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Request, status

from app.core.context import get_request_id
from app.dependencies.services import AdminServiceDep
from app.schemas.analytics import PageVisitCreate
from app.schemas.response import SuccessResponse

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.post(
    "/track",
    status_code=status.HTTP_201_CREATED,
    response_model=SuccessResponse[None],
    summary="Track a visitor page view/event",
)
async def track_visit(
    request: Request,
    payload: PageVisitCreate,
    service: AdminServiceDep,
) -> SuccessResponse[None]:
    user_agent = request.headers.get("user-agent", "")
    accept_lang = request.headers.get("accept-language", "")
    cf_country = request.headers.get("cf-ipcountry", None)

    await service.track_page_visit(
        visitor_id=payload.visitor_id,
        session_id=payload.session_id,
        path=payload.path,
        referrer=payload.referrer,
        source=payload.source,
        user_agent=user_agent,
        accept_lang=accept_lang,
        cf_country=cf_country,
    )

    return SuccessResponse(
        data=None,
        message="Event tracked.",
        request_id=get_request_id(),
    )
