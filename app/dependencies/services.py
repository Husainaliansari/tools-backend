"""Service dependency providers.

Each provider builds a request-scoped service on top of the shared database
session dependency, keeping endpoint signatures declarative::

    async def upload(service: UploadServiceDep) -> ...
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.download import DownloadService
from app.services.jobs import JobService
from app.services.upload import UploadService


def get_upload_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UploadService:
    return UploadService(session)


def get_download_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> DownloadService:
    return DownloadService(session)


def get_job_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> JobService:
    return JobService(session)


UploadServiceDep = Annotated[UploadService, Depends(get_upload_service)]
DownloadServiceDep = Annotated[DownloadService, Depends(get_download_service)]
JobServiceDep = Annotated[JobService, Depends(get_job_service)]
