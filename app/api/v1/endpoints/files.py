"""File endpoints: multi-file upload, metadata, download, thumbnail, delete.

These are tool-agnostic — every PDF tool consumes files uploaded here and
produces files downloadable here. Authentication is optional: authenticated
uploads belong to the user (and are only visible to them); anonymous uploads
stay accessible via their unguessable ID.
"""

from __future__ import annotations

import uuid
from typing import Annotated

import anyio
from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import FileStatus
from app.core.context import get_request_id
from app.db import get_db
from app.dependencies.auth import CurrentUserDep, OptionalUserDep, OptionalUserIdDep
from app.dependencies.rate_limit import upload_rate_limit
from app.dependencies.services import DownloadServiceDep, UploadServiceDep
from app.exceptions.base import ValidationError
from app.exceptions.files import FileNotFoundAppError
from app.repositories.file import FileRepository
from app.schemas.file import FileInfo, UploadResult
from app.schemas.response import SuccessResponse
from app.services.download import archive_download_name
from app.services.storage import get_storage
from app.services.thumbnails import generate_thumbnail

router = APIRouter(prefix="/files", tags=["Files"])

SessionDep = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=SuccessResponse[UploadResult],
    summary="Upload one or more files",
    dependencies=[Depends(upload_rate_limit)],
)
async def upload_files(
    service: UploadServiceDep,
    user: OptionalUserDep,
    files: Annotated[list[UploadFile], File(description="Files to upload.")],
) -> SuccessResponse[UploadResult]:
    stored = await service.upload_files(
        files,
        user_id=user.id if user else None,
        plan=user.plan if user else None,
    )
    return SuccessResponse(
        data=UploadResult.from_models(stored),
        message=f"{len(stored)} file(s) uploaded.",
        request_id=get_request_id(),
    )


@router.get(
    "",
    response_model=SuccessResponse[list[FileInfo]],
    summary="List my files (requires authentication)",
)
async def list_files(
    user: CurrentUserDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SuccessResponse[list[FileInfo]]:
    records = await FileRepository(session).list_for_user(
        user.id, limit=limit, offset=offset
    )
    return SuccessResponse(
        data=[FileInfo.from_model(r) for r in records],
        request_id=get_request_id(),
    )


# Declared before /{file_id} so the literal path segment wins the route match.
@router.get(
    "/archive",
    response_class=FileResponse,
    summary="Download several files as a ZIP",
    description=(
        "Bundles the given files into one ZIP (a single id downloads "
        "directly). Used by tools whose batch runs produce results across "
        "several per-file jobs."
    ),
)
async def download_archive(
    service: DownloadServiceDep,
    user_id: OptionalUserIdDep,
    ids: Annotated[
        str, Query(description="Comma-separated file IDs (max 50).", min_length=1)
    ],
    tool: Annotated[
        str | None,
        Query(description="Tool slug used in the ZIP's download name."),
    ] = None,
) -> FileResponse:
    try:
        file_ids = [uuid.UUID(part) for part in ids.split(",") if part.strip()]
    except ValueError as exc:
        raise ValidationError("Invalid file id in 'ids'.") from exc
    if not 1 <= len(file_ids) <= 50:
        raise ValidationError("'ids' must contain between 1 and 50 file IDs.")
    return await service.build_archive_response(
        file_ids,
        user_id=user_id,
        download_name=archive_download_name(tool, len(file_ids)),
    )


@router.get(
    "/{file_id}",
    response_model=SuccessResponse[FileInfo],
    summary="Get file metadata",
)
async def get_file(
    file_id: uuid.UUID,
    session: SessionDep,
    user_id: OptionalUserIdDep,
) -> SuccessResponse[FileInfo]:
    record = await FileRepository(session).get_active(file_id, user_id=user_id)
    if record is None:
        raise FileNotFoundAppError()
    return SuccessResponse(
        data=FileInfo.from_model(record), request_id=get_request_id()
    )


@router.get(
    "/{file_id}/download",
    response_class=FileResponse,
    summary="Download a file",
)
async def download_file(
    file_id: uuid.UUID,
    service: DownloadServiceDep,
    user_id: OptionalUserIdDep,
) -> FileResponse:
    return await service.build_response(file_id, user_id=user_id)


@router.get(
    "/{file_id}/thumbnail",
    response_class=FileResponse,
    summary="Get a JPEG thumbnail of a file",
    description=(
        "First page for PDFs, downscaled image for JPG/PNG. Generated on "
        "first request and cached."
    ),
)
async def get_thumbnail(
    file_id: uuid.UUID,
    session: SessionDep,
    user_id: OptionalUserIdDep,
) -> FileResponse:
    record = await FileRepository(session).get_active(file_id, user_id=user_id)
    if record is None:
        raise FileNotFoundAppError()
    path = await anyio.to_thread.run_sync(generate_thumbnail, record, get_storage())
    return FileResponse(path=path, media_type="image/jpeg")


@router.delete(
    "/{file_id}",
    response_model=SuccessResponse[None],
    summary="Delete a file",
)
async def delete_file(
    file_id: uuid.UUID,
    session: SessionDep,
    user_id: OptionalUserIdDep,
) -> SuccessResponse[None]:
    repo = FileRepository(session)
    record = await repo.get_active(file_id, user_id=user_id)
    if record is None:
        raise FileNotFoundAppError()

    get_storage().delete(record.category, record.relative_path)
    record.status = FileStatus.DELETED
    await session.commit()
    return SuccessResponse(
        data=None, message="File deleted.", request_id=get_request_id()
    )
