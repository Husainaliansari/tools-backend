"""Repositories package (data-access layer).

Encapsulates all persistence access behind a stable interface, isolating the
service layer from SQLAlchemy specifics (Dependency Inversion). Repository
implementations will live here, one per aggregate.

No repository logic is implemented in the foundation (by design).
"""
