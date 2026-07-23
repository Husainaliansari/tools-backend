"""Admin PDF-tool configuration endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints.admin._common import ok
from app.dependencies.admin import AdminUserDep
from app.dependencies.services import AdminServiceDep
from app.schemas.admin import ToolConfigRow, ToolConfigUpdate
from app.schemas.response import SuccessResponse

router = APIRouter(prefix="/tools", tags=["Admin: Tools"])


@router.get("", response_model=SuccessResponse[list[ToolConfigRow]])
async def list_tools(service: AdminServiceDep) -> SuccessResponse[list[ToolConfigRow]]:
    rows = await service.list_tools()
    return ok([ToolConfigRow(**r) for r in rows])


@router.patch("/{slug}", response_model=SuccessResponse[ToolConfigRow])
async def update_tool(
    slug: str,
    payload: ToolConfigUpdate,
    service: AdminServiceDep,
    admin: AdminUserDep,
) -> SuccessResponse[ToolConfigRow]:
    tool = await service.update_tool(slug, payload)
    await service.audit(
        actor=admin,
        action="tool.update",
        summary=f"Updated tool {tool.name}",
        entity_type="tool",
        entity_id=tool.slug,
    )
    # Re-read with usage for a consistent row shape.
    rows = await service.list_tools()
    row = next((r for r in rows if r["slug"] == slug), None)
    return ok(ToolConfigRow(**row) if row else ToolConfigRow.model_validate(tool))
