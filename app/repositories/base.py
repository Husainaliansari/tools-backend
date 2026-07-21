"""Generic async repository.

Thin, typed data-access layer over an :class:`AsyncSession`. Repositories own
*queries*; transaction boundaries (commit) belong to the service layer so a
single request can compose several repository calls atomically.
"""

from __future__ import annotations

import uuid
from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """CRUD building blocks shared by all repositories."""

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, entity_id: uuid.UUID) -> ModelT | None:
        return await self.session.get(self.model, entity_id)

    async def list_all(self, *, limit: int = 100, offset: int = 0) -> list[ModelT]:
        result = await self.session.execute(
            select(self.model).limit(limit).offset(offset)
        )
        return list(result.scalars().all())

    def add(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        return entity

    async def delete(self, entity: ModelT) -> None:
        await self.session.delete(entity)

    async def flush(self) -> None:
        await self.session.flush()

    async def commit(self) -> None:
        await self.session.commit()
