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
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

# Moved to module level to be accessible by run_async_upgrade and CLI path
def do_run_migrations(connection):
    # This function is called from run_async_upgrade via run_sync.
    # The `context` here is the module-level proxy.
    # We need to configure it for this specific programmatic run.
    print(f"Alembic env.py: do_run_migrations called for programmatic upgrade with connection: {connection}")

    # Use the imported alembic.context proxy directly
    # This call to configure() is intended to "establish" the proxy for this thread/context of execution.
    context.configure(
        connection=connection,
        target_metadata=target_metadata, # Make sure target_metadata is defined in the scope or globally
        render_as_batch=True # Important for SQLite support with some types of migrations
    )

    print("Alembic env.py: Context configured for do_run_migrations.")

    try:
        with context.begin_transaction():
            print("Alembic env.py: Transaction begun for migrations.")
            context.run_migrations()
            print("Alembic env.py: context.run_migrations() called within transaction.")
        print("Alembic env.py: Transaction committed, migrations should be done.")
    except Exception as e:
        print(f"Alembic env.py: ERROR during migration execution in do_run_migrations: {e}")
        import traceback
        traceback.print_exc()
        raise

async def run_async_upgrade(db_url: str):
    """
    New function to run migrations programmatically with a given database URL.
    This will be called by the GameManager.
    """
    print(f"Alembic env.py: run_async_upgrade called with db_url: {db_url}")
    if not db_url:
        raise ValueError("Database URL cannot be empty for run_async_upgrade.")
        
    engine = create_async_engine(db_url, poolclass=pool.NullPool)
    
    print(f"Alembic env.py: Async engine created for {db_url}")
    async with engine.connect() as connection:
        print("Alembic env.py: Async connection established for run_async_upgrade.")
        await connection.run_sync(do_run_migrations)
        print("Alembic env.py: do_run_migrations completed via run_sync.")
    
    await engine.dispose()
    print("Alembic env.py: Async engine disposed.")

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
        print("Alembic env.py: Running migrations in online mode (CLI context)...")
        config = context.config # Added local config
        # Interpret the config file for Python logging.
        # This line sets up loggers basically.
        if config.config_file_name is not None:
            fileConfig(config.config_file_name)

        cli_db_url = config.get_main_option("sqlalchemy.url") # Get URL from alembic.ini for CLI
        
        if not cli_db_url:
            # Fallback to environment variable if not in alembic.ini, or raise error
            # For this setup, we expect it in alembic.ini or set by GameManager for programmatic calls.
            # GameManager now sets it via alembic_cfg.set_main_option for its Config object,
            # but for CLI, alembic loads alembic.ini directly.
            cli_db_url_from_context = context.config.get_main_option("sqlalchemy.url")
            if not cli_db_url_from_context:
                raise ValueError("sqlalchemy.url is not set in alembic.ini (or context) for CLI online mode.")
            cli_db_url = cli_db_url_from_context

        print(f"Alembic env.py: Using DB URL for CLI online mode: {cli_db_url}")
        
        try:
            # Ensure we are in a situation where it's safe to call asyncio.run
            # This means we are likely being run as a script by Alembic CLI
            asyncio.run(run_async_upgrade(cli_db_url))
            print("Alembic env.py: Online migrations (CLI) completed via asyncio.run(run_async_upgrade).")
        except RuntimeError as e:
            if "cannot be called from a running event loop" in str(e):
                print("Alembic env.py: ERROR - Attempted to call asyncio.run from within an existing event loop (CLI context).")
                print("This might indicate env.py is being imported and run by an async process that isn't correctly awaiting run_async_upgrade directly, or an issue with Alembic's CLI runner.")
                # Potentially, if an outer loop exists, one might try to schedule run_async_upgrade differently,
                # but for CLI, asyncio.run should be the entry point to async code.
                raise
            else:
                # Re-raise other RuntimeErrors
                print(f"Alembic env.py: A RuntimeError occurred: {e}")
                raise
        except Exception as e:
            print(f"Alembic env.py: An unexpected error occurred during CLI online migrations: {e}")
            import traceback
            traceback.print_exc()
            raise
