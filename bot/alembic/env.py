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
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata

# Explicitly import all models to ensure they are registered with Base.metadata
# before target_metadata is assigned. This helps Alembic's autogenerate.
import bot.database.models  # This will run models/__init__.py

# Ensure the path to your models is correct
from bot.database.models import Base # Corrected import path
target_metadata = Base.metadata

# Custom include_object function to ignore specific constraints
def include_object(object, name, type_, reflected, compare_to):
    if type_ == "unique_constraint" and name == "uq_guild_configs_guild_id":
        return False
    # Optionally, filter out the unique constraint backing the PK if it's being problematic,
    # though typically PKs are handled well. This is a more aggressive filter.
    # if type_ == "unique_constraint" and name is not None and name.endswith("_pkey") and object.table.name == "guild_configs":
    #     return False
    return True

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,  # Add this line
        compare_type=True  # Recommended when using include_object for constraints
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,  # Add this line
        compare_type=True  # Recommended when using include_object for constraints
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    # Get the SQLAlchemy URL from environment or use default, similar to postgres_adapter.py
    # This ensures the async engine uses the correct async driver.
    DATABASE_URL_ENV_VAR = "DATABASE_URL"
    DEFAULT_SQLALCHEMY_DATABASE_URL = "postgresql+asyncpg://postgres:test123@localhost:5432/kvelin_bot" # From postgres_adapter.py
    db_url = os.getenv(DATABASE_URL_ENV_VAR, DEFAULT_SQLALCHEMY_DATABASE_URL)

    # Create a configuration dictionary for async_engine_from_config
    # We are not using config.get_section directly to ensure the correct URL with async driver is used.
    engine_config = {
        "sqlalchemy.url": db_url,
        # Add other options from config.get_section if needed, e.g., echo
        # For now, only URL is critical.
    }
    # Add other options from alembic.ini's main section if they exist and are needed by the engine
    # For example, 'sqlalchemy.echo': config.get_main_option('sqlalchemy.echo')
    # This example assumes such options might exist and be relevant.
    ini_section_options = config.get_section(config.config_ini_section, {})
    for key, value in ini_section_options.items():
        if key not in engine_config and key.startswith("sqlalchemy."):
             engine_config[key] = value


    connectable = async_engine_from_config(
        engine_config, # Use our constructed config
        prefix="sqlalchemy.", # Standard prefix
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())