"""Admin platform-settings endpoints (all settings categories)."""

from __future__ import annotations

import base64
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, UploadFile

from app.api.v1.endpoints.admin._common import ok
from app.dependencies.admin import AdminUserDep
from app.dependencies.services import AdminServiceDep
from app.exceptions.base import BadRequestError
from app.schemas.admin import SettingUpdate
from app.schemas.response import SuccessResponse

router = APIRouter(prefix="/settings", tags=["Admin: Settings"])

# Brand assets are stored inline (as data URIs) in the branding setting, so no
# static-file server or new table is needed. Keep the cap small accordingly.
_MAX_ASSET_BYTES = 512 * 1024
_ALLOWED_ASSET_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/svg+xml",
    "image/x-icon",
    "image/vnd.microsoft.icon",
}


@router.get("", response_model=SuccessResponse[dict])
async def all_settings(service: AdminServiceDep) -> SuccessResponse[dict[str, Any]]:
    return ok(await service.all_settings())


@router.get("/{category}", response_model=SuccessResponse[dict])
async def get_setting(
    category: str, service: AdminServiceDep
) -> SuccessResponse[dict[str, Any]]:
    return ok(await service.get_setting(category))


@router.put("/{category}", response_model=SuccessResponse[dict])
async def update_setting(
    category: str,
    payload: SettingUpdate,
    service: AdminServiceDep,
    admin: AdminUserDep,
) -> SuccessResponse[dict[str, Any]]:
    value = await service.update_setting(category, payload.value, admin)
    await service.audit(
        actor=admin,
        action="settings.update",
        summary=f"Updated {category} settings",
        entity_type="settings",
        entity_id=category,
    )
    return ok(value, "Settings saved.")


@router.post("/branding/asset", response_model=SuccessResponse[dict])
async def upload_branding_asset(
    service: AdminServiceDep,
    admin: AdminUserDep,
    kind: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
) -> SuccessResponse[dict[str, Any]]:
    """Upload a logo or favicon. The image is stored inline as a data URI in
    the ``branding`` setting so it needs no static-file server."""
    if kind not in {"logo", "favicon"}:
        raise BadRequestError("Asset kind must be 'logo' or 'favicon'.")
    content_type = (file.content_type or "").lower()
    if content_type not in _ALLOWED_ASSET_TYPES:
        raise BadRequestError("Unsupported image type.")
    data = await file.read()
    if not data:
        raise BadRequestError("The uploaded file is empty.")
    if len(data) > _MAX_ASSET_BYTES:
        raise BadRequestError("Image must be 512 KB or smaller.")
    data_uri = f"data:{content_type};base64,{base64.b64encode(data).decode()}"
    value = await service.update_setting("branding", {kind: data_uri}, admin)
    await service.audit(
        actor=admin,
        action="settings.branding_asset",
        summary=f"Uploaded branding {kind}",
        entity_type="settings",
        entity_id="branding",
    )
    return ok(value, f"{kind.capitalize()} updated.")
