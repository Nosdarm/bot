import os
import sys
import configparser
import ssl # Added for SSL context
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode # Added for URL manipulation

# Add the project root directory to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

config = context.config

if config.config_file_name is not None:
    parser = configparser.ConfigParser()
    try:
        with open(config.config_file_name, 'r', encoding='utf-8') as f_ini:
            parser.read_file(f_ini)
        fileConfig(parser, disable_existing_loggers=False)
    except Exception as e:
        print(f"Error processing logging configuration from {config.config_file_name}: {e}")

from bot.database.models import Base
target_metadata = Base.metadata

def include_object(object, name, type_, reflected, compare_to):
    if type_ == "unique_constraint" and name == "uq_guild_configs_guild_id":
        return False
    return True

def run_migrations_offline() -> None:
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
    DATABASE_URL_ENV_VAR = "DATABASE_URL"
    default_async_url = "postgresql+asyncpg://neondb_owner:npg_O2HrF6JYDPpG@ep-old-hat-a9ctb4yy-pooler.gwc.azure.neon.tech:5432/neondb?sslmode=require"

    db_url_for_engine_str = os.getenv(DATABASE_URL_ENV_VAR)
    connect_args = {} # Initialize connect_args

    if not db_url_for_engine_str:
        print(f"Warning: {DATABASE_URL_ENV_VAR} is not set. Falling back to default URL: {default_async_url}")
        db_url_for_engine_str = default_async_url
    elif not db_url_for_engine_str.startswith("postgresql+asyncpg://"):
        if db_url_for_engine_str.startswith("postgresql://"):
            db_url_for_engine_str = db_url_for_engine_str.replace("postgresql://", "postgresql+asyncpg://", 1)
            print(f"Info: Converted sync DATABASE_URL to async: {db_url_for_engine_str}")
        else:
            print(f"Error: DATABASE_URL ('{db_url_for_engine_str}') is not a valid 'postgresql+asyncpg://' or 'postgresql://' URL. Using hardcoded default.")
            db_url_for_engine_str = default_async_url

    # Parse the URL to handle sslmode
    parsed_url = urlparse(db_url_for_engine_str)
    query_params = parse_qs(parsed_url.query)

    if 'sslmode' in query_params:
        sslmode_val = query_params['sslmode'][0] # Get the value
        # Remove sslmode from query params as asyncpg takes ssl context directly
        del query_params['sslmode']

        if sslmode_val == 'require':
            # For asyncpg, 'require' often means just enable SSL.
            ssl_context = ssl.create_default_context()
            # You might need to adjust context for specific server certs / CAs if default fails
            # e.g., ssl_context.load_verify_locations(cafile='/path/to/ca.crt')
            # For simple "require" (encryption without full CA validation against a specific CA cert):
            # ssl_context.check_hostname = False
            # ssl_context.verify_mode = ssl.CERT_NONE
            connect_args["ssl"] = ssl_context
            print(f"Info: Enabled SSL context due to sslmode={sslmode_val}")
        else:
            # If other sslmodes need specific asyncpg connection params, handle them here.
            # For now, we only explicitly handle 'require'. Other modes might pass through
            # if asyncpg supports them directly in its DSN or connection params.
            # We put back the sslmode if it's not 'require' and we don't handle it.
            # However, it's safer to only allow modes we explicitly support or know asyncpg handles.
            # For now, if it's not 'require', we'll let the original URL (potentially with sslmode) pass,
            # which might lead to the same TypeError if asyncpg doesn't like that sslmode value.
            # A better approach would be to raise an error for unsupported sslmodes.
            # Let's assume for now only 'require' is intended to be handled this way,
            # and other sslmodes should not be in the query string for this connect_args method.
            # So, if sslmode was present and not 'require', we've already removed it.
            # If it needs to be passed differently, that's a separate logic branch.
            print(f"Warning: sslmode='{sslmode_val}' found in URL. Only 'require' is explicitly handled by creating an SSLContext. Other modes might not work as expected with asyncpg via this method.")

        # Rebuild the query string without the original sslmode
        new_query_string = urlencode(query_params, doseq=True)
        # Rebuild the URL
        parsed_url = parsed_url._replace(query=new_query_string)
        db_url_for_engine_str = urlunparse(parsed_url)
        print(f"Info: DB URL for engine (potentially modified for SSL): {db_url_for_engine_str}")


    engine_config_from_ini = config.get_section(config.config_ini_section, {})
    engine_config_from_ini["sqlalchemy.url"] = db_url_for_engine_str

    # Add connect_args if SSL context was created (or other args in the future)
    if connect_args: # This ensures connect_args is only added if it's populated
        engine_config_from_ini["connect_args"] = connect_args

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