import os
import sys

# Add the project root directory to sys.path
# This assumes env.py is at bot/alembic/env.py
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    # MODIFICATION: Explicitly set encoding to utf-8
    # Also, ensure 'here' is available in defaults if paths in alembic.ini use it.
    file_config_defaults = {}
    if config.config_file_name: # Ensure config_file_name is not None before using dirname
        file_config_defaults['here'] = os.path.dirname(os.path.abspath(config.config_file_name))

    fileConfig(
        config.config_file_name,
        defaults=file_config_defaults,
        disable_existing_loggers=False, # Often a good practice
        encoding='utf-8' # Explicitly set encoding
    )

# add your model's MetaData object here
# for 'autogenerate' support
from bot.database.models import Base # Corrected import path
target_metadata = Base.metadata

def include_object(object, name, type_, reflected, compare_to):
    if type_ == "unique_constraint" and name == "uq_guild_configs_guild_id":
        return False
    return True

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        compare_type=True
    )
    with context.begin_transaction():
        context.run_migrations()

def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        compare_type=True
    )
    with context.begin_transaction():
        context.run_migrations()

async def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    DATABASE_URL_ENV_VAR = "DATABASE_URL"
    default_url_from_ini = config.get_main_option("sqlalchemy.url")
    default_async_url = "postgresql+asyncpg://postgres:test123@localhost:5432/kvelin_bot" # Default fallback

    if default_url_from_ini and default_url_from_ini.startswith("postgresql://"):
        default_async_url = default_url_from_ini.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif default_url_from_ini: # If ini has a URL but not in expected sync format, use it as is for getenv fallback
        default_async_url = default_url_from_ini

    db_url_for_engine = os.getenv(DATABASE_URL_ENV_VAR, default_async_url)

    if db_url_for_engine and db_url_for_engine.startswith("postgresql://"):
        db_url_for_engine = db_url_for_engine.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif not db_url_for_engine.startswith("postgresql+asyncpg://"):
        # If it's still not an asyncpg URL (e.g. from a misconfigured DATABASE_URL or ini), force a default
        print(f"Warning: db_url_for_engine ('{db_url_for_engine}') is not in 'postgresql+asyncpg://' format. Using a hardcoded default.")
        db_url_for_engine = "postgresql+asyncpg://postgres:test123@localhost:5432/kvelin_bot"

    engine_config_from_ini = config.get_section(config.config_ini_section, {})
    engine_config_from_ini["sqlalchemy.url"] = db_url_for_engine

    connectable = async_engine_from_config(
        engine_config_from_ini,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()

if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())