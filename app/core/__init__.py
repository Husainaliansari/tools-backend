"""Core cross-cutting concerns.

The ``core`` package holds framework-agnostic building blocks that many other
layers depend on but that do not themselves belong to any single feature:
request context propagation, the application lifespan manager, and (in future)
security primitives. Keeping these here preserves a clean dependency direction —
features depend on core, never the reverse.
"""
