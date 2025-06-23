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
    # Заменяем URL по умолчанию на предоставленный пользователем
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

    # Parse the URL to handle sslmode, similar to postgres_adapter.py
    parsed_url = urlparse(db_url_for_engine_str)
    query_params_dict = dict(parse_qs(parsed_url.query)) # Make it a mutable dict of lists

    # Convert query_params_dict from {'key': ['value']} to {'key': 'value'} for make_url
    # and for easier processing. Take the first value if multiple are present.
    processed_query_params = {k: v[0] if isinstance(v, list) and v else v for k, v in query_params_dict.items()}

    ssl_mode_from_url = processed_query_params.get('sslmode')

    if ssl_mode_from_url:
        print(f"ℹ️ [Alembic env.py] Found 'sslmode={ssl_mode_from_url}' in DATABASE_URL. Processing for connect_args.")
        if ssl_mode_from_url == 'require':
            connect_args['ssl'] = 'require' # asyncpg can handle this string
        elif ssl_mode_from_url == 'prefer':
            connect_args['ssl'] = 'prefer' # asyncpg can handle this string
        elif ssl_mode_from_url == 'allow':
            # 'allow' means SSL is optional; client tries SSL, falls back to non-SSL if server doesn't support.
            # asyncpg interprets ssl='allow' or ssl=True (with server negotiation) appropriately.
            connect_args['ssl'] = 'allow'
        elif ssl_mode_from_url == 'disable':
            connect_args['ssl'] = 'disable' # asyncpg can handle this string, same as False
        elif ssl_mode_from_url in ['verify-ca', 'verify-full']:
            # These modes require SSL and verification.
            # Pass the string directly; asyncpg handles it.
            # For actual CA verification, SSLContext with CA certs might be needed if not configured elsewhere.
            connect_args['ssl'] = ssl_mode_from_url
            print(f"ℹ️ [Alembic env.py] For sslmode={ssl_mode_from_url}, using connect_args['ssl'] = '{ssl_mode_from_url}'. Ensure CA certs are available if needed.")
        else:
            print(f"⚠️ [Alembic env.py] Unsupported 'sslmode={ssl_mode_from_url}' from URL. SSL will not be explicitly configured by Alembic based on this mode.")

        # Remove sslmode from processed_query_params as it's now handled by connect_args
        # or if it's not supported and shouldn't be in the DSN query string for the engine.
        if 'sslmode' in processed_query_params:
            del processed_query_params['sslmode']

        # Rebuild the URL without sslmode in query string
        # urlunparse expects query to be a string, so urlencode it back
        db_url_for_engine_str = urlunparse(parsed_url._replace(query=urlencode(processed_query_params)))
        print(f"ℹ️ [Alembic env.py] DB URL for engine (sslmode removed from query): {db_url_for_engine_str}")
    else:
        print(f"ℹ️ [Alembic env.py] No 'sslmode' found in DATABASE_URL query parameters.")

    engine_config_from_ini = config.get_section(config.config_ini_section, {})
    engine_config_from_ini["sqlalchemy.url"] = db_url_for_engine_str

    # Add connect_args if SSL was configured (or for other future args)
    if connect_args:
        engine_config_from_ini["connect_args"] = connect_args
        print(f"ℹ️ [Alembic env.py] Using connect_args for engine: {connect_args}")


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