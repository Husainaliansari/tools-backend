"""Health package.

Isolates operational/liveness endpoints from feature APIs so infrastructure
concerns (monitoring, load-balancer probes) stay decoupled from business
routes.
"""

from app.health.router import router as health_router

__all__ = ["health_router"]
