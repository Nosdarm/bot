from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
# config = context.config # Removed global config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
# if config.config_file_name is not None: # Moved to relevant sections
#     fileConfig(config.config_file_name) # Moved to relevant sections

# add your model's MetaData object here
# for 'autogenerate' support
import sys
from os.path import abspath, dirname
sys.path.insert(0, dirname(dirname(dirname(abspath(__file__))))) # Adds project root /app

from bot.database.models import Base
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.

# Ensure necessary imports for async operations
from sqlalchemy.ext.asyncio import create_async_engine
import asyncio # Already present but good to confirm for async operations


def run_migrations_offline() -> None:
    config = context.config # Added local config
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    import sys # Add if not present at the top of the function
    print("!!! ALEMBIC DIAGNOSTIC (OFFLINE START) !!!", file=sys.stderr)
    print(f"Tables in target_metadata (inside run_migrations_offline): {target_metadata.tables.keys() if target_metadata else 'target_metadata is None'}", file=sys.stderr)
    print("!!! ALEMBIC DIAGNOSTIC (OFFLINE END) !!!", file=sys.stderr)
    sys.stderr.flush()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    # The 'config' object is accessible here if it's loaded by Alembic CLI
    # This typically comes from context.config if Alembic CLI is running env.py
    alembic_config = context.config # Use the config from Alembic's context

    # Interpret the config file for Python logging.
    if alembic_config.config_file_name is not None:
        fileConfig(alembic_config.config_file_name)

    # Attempt to get the sqlalchemy.url from the Alembic config
    db_url = alembic_config.get_main_option("sqlalchemy.url")
    if not db_url:
        raise ValueError("sqlalchemy.url is not set in alembic.ini for online CLI mode.")

    # Create an engine. For async, we'd use create_async_engine,
    # but Alembic's online migration typically uses a synchronous engine
    # for the connection it passes to context.configure.
    # However, if your models and operations are async, you might need
    # to handle this differently, possibly using run_sync as before,
    # but the main point is to configure context for online mode.
    # For simplicity and common Alembic patterns, using a sync engine here:
    connectable = engine_from_config(
        alembic_config.get_section(alembic_config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        import sys # Add if not present at the top of the function
        print("!!! ALEMBIC DIAGNOSTIC (ONLINE START) !!!", file=sys.stderr)
        print(f"Tables in target_metadata (inside run_migrations_online): {target_metadata.tables.keys() if target_metadata else 'target_metadata is None'}", file=sys.stderr)
        print("!!! ALEMBIC DIAGNOSTIC (ONLINE END) !!!", file=sys.stderr)
        sys.stderr.flush()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True
        )

        with context.begin_transaction():
            context.run_migrations()

# This is the section for CLI execution or direct script run
if __name__ == '__main__': # Guard to prevent execution when imported, though Alembic CLI might still execute it.
    # Alembic CLI will execute this file. We need to handle its context.
    # The `context` object is specific to Alembic's CLI invocation.
    # When this file is imported by game_manager, this block shouldn't run in a way that conflicts.
    # The `command.upgrade` in game_manager now directly calls `run_async_upgrade`.
    # This block here is for when `alembic upgrade head` etc. is called from the CLI.

    if context.is_offline_mode():
        print("Alembic env.py: Running migrations in offline mode (CLI context)...")
        run_migrations_offline()
        print("Alembic env.py: Offline migrations (CLI) completed.")
    else:
        # This 'else' block is executed for 'alembic upgrade head' (online mode)
        print("Alembic env.py: Running migrations in online mode (CLI context)...")
        run_migrations_online() # Call the new/standard online migration function
        print("Alembic env.py: Online migrations (CLI) completed.")
