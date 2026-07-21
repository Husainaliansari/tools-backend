"""API package.

Contains the HTTP interface layer only: routers and (later) endpoint handlers,
grouped by version. This layer translates between HTTP and the service layer and
must contain no business logic itself (Separation of Concerns).
"""

from app.api.router import api_router

__all__ = ["api_router"]
