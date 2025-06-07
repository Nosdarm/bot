import sys
from os.path import abspath, dirname

# This adds the project root (directory containing 'bot') to sys.path
# Ensure this path correction is correct for your project structure.
# For example, if env.py is in 'migrations/' and 'bot' is in the parent directory,
# this line might be needed:
sys.path.insert(0, dirname(dirname(abspath(__file__))))

# --- BEGIN: Import models to populate metadata ---
# You need to import the actual modules where your models are defined.
# Example assuming models are defined directly in bot.database.models:
# import bot.database.models # Or import specific classes if they are in __init__.py
# Example assuming models are in submodules like bot.database.models.user, bot.database.models.item:
import bot.database.models # Assuming importing the package imports the relevant submodules via __init__.py
# OR explicitly import submodules:
# import bot.database.models.user
# import bot.database.models.item
# ... import all other model modules ...

# If your models are defined within the bot.database.models package,
# ensure that __init__.py in that package imports the actual model modules
# or define your models directly in files that are imported here.
# If you're unsure, a common pattern is:
# from bot.database.models import Base # This is already there
# from bot.database.models import User, Item, Order # Example: Import specific classes if defined in bot.database.models/__init__.py or directly in bot.database.models.py
# --- END: Import models to populate metadata ---


import asyncio # Add asyncio import
from logging.config import fileConfig
from sqlalchemy import pool # engine_from_config will be replaced for async
from sqlalchemy.ext.asyncio import create_async_engine # Import for async engine
from alembic import context

# assuming 'Base' is defined in bot.database.models and has a 'metadata' attribute
from bot.database.models import Base

# this is the MetaData object that Alembic will use for comparison
target_metadata = Base.metadata
print(f"DEBUG env.py: Tables in target_metadata: {list(target_metadata.tables.keys())}")

# Ensure target_metadata is now populated. You could add a print here *before*
# the function definitions if you want to verify it *outside* the function.
# print(f"DEBUG: Tables in target_metadata (at file top): {target_metadata.tables.keys()}")


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is necessary
    to associate the Sys.
    """
    url = context.config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    # retrieve the SQLAlchemy URL from the alembic.ini file
    db_url = context.config.get_main_option("sqlalchemy.url")
    if not db_url:
        raise ValueError("sqlalchemy.url is not set in alembic.ini for online CLI mode.")

    # create an asyncio event loop and run the migration logic
    # We create an async engine here.
    connectable = create_async_engine(db_url, poolclass=pool.NullPool)

    async def run_async_migrations():
        """Wrapper to run migrations in an async context."""
        async with connectable.connect() as connection:
            # Detect if we are running against SQLite (though less likely with asyncpg)
            # For async, the dialect name might be different or this check might need adjustment
            # However, render_as_batch is primarily for SQLite's limitations with ALTER TABLE.
            # For PostgreSQL, batch mode is generally not needed.
            is_sqlite = connection.dialect.name == 'sqlite'

            await connection.run_sync(do_run_migrations, is_sqlite)

    asyncio.run(run_async_migrations())


def do_run_migrations(connection, is_sqlite: bool):
    """Helper function to be called by await connection.run_sync()"""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        render_as_batch=is_sqlite # Enable batch mode only for SQLite
    )

    with context.begin_transaction():
        context.run_migrations()

# This is the section for CLI execution or direct script run
if context.is_offline_mode():
    print("Alembic env.py: Running migrations in offline mode...")
    run_migrations_offline()
    print("Alembic env.py: Offline migrations completed.")
else:
    print("Alembic env.py: Running migrations in online mode...")
    run_migrations_online()
    print("Alembic env.py: Online migrations completed.")