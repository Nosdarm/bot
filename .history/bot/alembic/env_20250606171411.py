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


from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

# assuming 'Base' is defined in bot.database.models and has a 'metadata' attribute
from bot.database.models import Base

# this is the MetaData object that Alembic will use for comparison
target_metadata = Base.metadata

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
    alembic_config = context.config

    if alembic_config.config_file_name is not None:
        fileConfig(alembic_config.config_file_name)

    db_url = alembic_config.get_main_option("sqlalchemy.url")
    if not db_url:
        raise ValueError("sqlalchemy.url is not set in alembic.ini for online CLI mode.")

    connectable = engine_from_config(
        alembic_config.get_section(alembic_config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # --- REMOVED Diagnostic Exception and sys.path.insert ---
        # The target_metadata should be populated now because models were imported at the top.
        # You can add a print here for verification if needed, but don't raise an error:
        # print(f"DEBUG: Tables in target_metadata (inside run_migrations_online after imports): {target_metadata.tables.keys()}")

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True
            # add render_as_batch=True here if using SQLite and needing batch mode for alter column
            # render_as_batch=True
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