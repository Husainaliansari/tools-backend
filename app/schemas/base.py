"""Base Pydantic schema definitions.

Every request/response schema in the application should inherit from
:class:`BaseSchema` so that serialisation behaviour (ORM compatibility,
whitespace stripping, enum handling) is consistent across the codebase.

No *business* schemas live here — only the shared foundation.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class BaseSchema(BaseModel):
    """Common base for all schemas.

    * ``from_attributes`` — allow construction directly from ORM objects.
    * ``populate_by_name`` — accept both field name and alias on input.
    * ``str_strip_whitespace`` — trim incoming string values.
    """

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        use_enum_values=True,
        extra="ignore",
    )


class ORMSchema(BaseSchema):
    """Marker base for schemas that mirror persistence models.

    Behaviourally identical to :class:`BaseSchema` today; kept as a distinct
    type so read-models can be evolved independently of request payloads.
    """
