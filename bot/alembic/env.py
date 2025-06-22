import os
import sys
import configparser # Added for manual .ini parsing

# Add the project root directory to sys.path
# This assumes env.py is at bot/alembic/env.py
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import asyncio
from logging.config import fileConfig # Keep this for fileConfig itself

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# MODIFICATION: Manually read alembic.ini with UTF-8 and pass a ConfigParser object
if config.config_file_name is not None:
    # Create a ConfigParser instance
    parser = configparser.ConfigParser()
    try:
        # Read the .ini file explicitly with UTF-8
        with open(config.config_file_name, 'r', encoding='utf-8') as f_ini:
            parser.read_file(f_ini)

        # Pass the ConfigParser object to fileConfig
        # disable_existing_loggers=False is often a good practice
        fileConfig(parser, disable_existing_loggers=False)
    except Exception as e:
        print(f"Error processing logging configuration from {config.config_file_name}: {e}")
        # Fallback or raise error if logging config is critical
        # For now, just print and continue; Alembic might still work if logging isn't essential for it.


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
    # Fallback to a generic local async URL if DATABASE_URL is not set
    # This ensures that if DATABASE_URL is missing, it defaults to something,
    # rather than relying on alembic.ini's potentially sync URL for async engine setup.
    default_async_url = "postgresql+asyncpg://postgres:test123@localhost:5432/kvelin_bot_default"

    db_url_for_engine = os.getenv(DATABASE_URL_ENV_VAR)

    if not db_url_for_engine:
        print(f"Warning: {DATABASE_URL_ENV_VAR} is not set. Falling back to default URL: {default_async_url}")
        db_url_for_engine = default_async_url
    elif not db_url_for_engine.startswith("postgresql+asyncpg://"):
        if db_url_for_engine.startswith("postgresql://"):
            # Convert sync URL from env to async
            db_url_for_engine = db_url_for_engine.replace("postgresql://", "postgresql+asyncpg://", 1)
            print(f"Info: Converted sync DATABASE_URL to async: {db_url_for_engine}")
        else:
            # If DATABASE_URL is set but not a recognized postgresql format, this is problematic.
            print(f"Error: DATABASE_URL ('{db_url_for_engine}') is not a valid 'postgresql+asyncpg://' or 'postgresql://' URL. Using hardcoded default.")
            db_url_for_engine = default_async_url # Fallback to a known safe default

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