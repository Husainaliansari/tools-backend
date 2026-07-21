"""Alembic migration environment (async).

Wires Alembic into the application:

* The database URL is read from application settings (no secrets in ini files).
* ``target_metadata`` is the application's declarative ``Base.metadata``, imported
  via ``app.db.base_registry`` (the single module that imports all models).
* Migrations run against the async engine using ``run_sync``.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import get_settings
from app.db.base_registry import Base

# Alembic Config object providing access to values in alembic.ini.
config = context.config

# Configure Python logging from the ini file, if present.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject the runtime database URL from settings (escape % for ConfigParser).
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL.replace("%", "%%"))

# Metadata Alembic diffs against for autogeneration.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a DB connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Configure the context with a live connection and run migrations."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations within it."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode against the async engine."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
