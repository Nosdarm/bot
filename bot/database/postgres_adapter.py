# bot/database/postgres_adapter.py
"""
Модуль для асинхронного адаптера базы данных PostgreSQL.
"""

import asyncio
import os # For accessing environment variables
import traceback
import json
from typing import Optional, List, Tuple, Any, Union, Dict

import asyncpg # Driver for PostgreSQL
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from .models import Base # Assuming models.py is in the same directory

# Database Connection URL Configuration
# The application uses the DATABASE_URL environment variable to configure the
# PostgreSQL connection. If this variable is not set, it falls back to a
# default URL suitable for local development.
# For production and other environments, it is strongly recommended to set
from bot.database.base_adapter import BaseDbAdapter
from urllib.parse import urlparse, parse_qs, urlunparse, urlencode # Add imports for URL manipulation
# For production and other environments, it is strongly recommended to set
# DATABASE_URL to a valid PostgreSQL connection string.
# Example: DATABASE_URL="postgresql+asyncpg://user:password@host:port/dbname"

DATABASE_URL_ENV_VAR = "DATABASE_URL"
# Заменяем URL по умолчанию на предоставленный пользователем, УБРАЛИ ?sslmode=require
DEFAULT_SQLALCHEMY_DATABASE_URL = "postgresql+asyncpg://neondb_owner:npg_O2HrF6JYDPpG@ep-old-hat-a9ctb4yy-pooler.gwc.azure.neon.tech:5432/neondb"

SQLALCHEMY_DATABASE_URL_FROM_ENV = os.getenv(DATABASE_URL_ENV_VAR)
_used_env_var_globally = False

if SQLALCHEMY_DATABASE_URL_FROM_ENV is None:
    print(f"⚠️ WARNING: Environment variable {DATABASE_URL_ENV_VAR} is not set.")
    print(f"Falling back to default database URL: {DEFAULT_SQLALCHEMY_DATABASE_URL}")
    print(f"👉 For production, please set the {DATABASE_URL_ENV_VAR} environment variable.")
    SQLALCHEMY_DATABASE_URL = DEFAULT_SQLALCHEMY_DATABASE_URL
    _used_env_var_globally = False
else:
    print(f"Using database URL from environment variable {DATABASE_URL_ENV_VAR}.")
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL_FROM_ENV
    _used_env_var_globally = True


class PostgresAdapter(BaseDbAdapter):
    """
    Асинхронный адаптер для работы с базой данных PostgreSQL.
    """

    def __init__(self, db_url: Optional[str] = None):
        is_testing_mode = os.getenv("TESTING_MODE") == "true"
        allow_postgres_in_test = os.getenv("ALLOW_POSTGRES_IN_TEST") == "true"

        determined_db_url = db_url or SQLALCHEMY_DATABASE_URL # SQLALCHEMY_DATABASE_URL is from env or default (which is Neon)

        if is_testing_mode and not allow_postgres_in_test:
            # Check if the determined URL looks like a Postgres/Neon URL
            if "postgres" in determined_db_url.lower() or "neon.tech" in determined_db_url.lower():
                logger.error(
                    "PostgresAdapter initialized with a PostgreSQL URL (%s) in TESTING_MODE "
                    "without ALLOW_POSTGRES_IN_TEST set. This is likely an error. "
                    "Tests should typically use SQLite. Halting to prevent external connection.",
                    determined_db_url
                )
                raise RuntimeError(
                    "Attempted to initialize PostgresAdapter with a live PostgreSQL URL during general testing. "
                    "Set DATABASE_TYPE=sqlite and ensure TEST_DATABASE_URL points to SQLite, "
                    "or set ALLOW_POSTGRES_IN_TEST=true if a Postgres test DB is intended for this specific test."
                )

        self._default_db_url = DEFAULT_SQLALCHEMY_DATABASE_URL # This is the Neon URL (clean of sslmode)
        self._used_env_var_url: bool

        if db_url: # If a specific URL is passed, it takes precedence
            self._db_url = db_url
            self._used_env_var_url = (db_url == SQLALCHEMY_DATABASE_URL_FROM_ENV if SQLALCHEMY_DATABASE_URL_FROM_ENV else False)
        else:
            self._db_url = SQLALCHEMY_DATABASE_URL # This is (ENV_URL or DEFAULT_NEON_URL)
            self._used_env_var_url = _used_env_var_globally

        # Ensure the URL scheme is compatible with asyncpg if used directly for raw pool
        self._asyncpg_url = self._db_url.replace("postgresql+asyncpg://", "postgresql://")

        # --- Define final_engine_connect_args and construct URL object ---
        from sqlalchemy.engine import URL

        original_parsed_url = urlparse(self._db_url) # Parse the original full URL (now without sslmode in default)

        ssl_connect_arg: Optional[Union[bool, object]] = None

        # Heuristic: if host contains 'neon.tech', assume SSL is required.
        # A more robust solution would be an explicit config setting for SSL.
        if original_parsed_url.hostname and "neon.tech" in original_parsed_url.hostname.lower():
            print(f"PostgresAdapter __init__: Detected NeonDB host ({original_parsed_url.hostname}), enabling SSL via SSLContext.")
            import ssl
            # Create a basic SSL context. For 'sslmode=require', asyncpg typically needs ssl=True or an SSLContext.
            # This context enables SSL. Verification behavior depends on server and context defaults.
            # To mimic 'require' (verify server cert against system CAs if server provides it),
            # ssl.create_default_context() is a good start.
            # If Neon's pooler uses a self-signed or non-standard CA, further context customization might be needed.
            ssl_context = ssl.create_default_context()
            # For 'require', we usually don't need to check hostname if connecting to a pooler
            # and don't need to provide client certs unless server mandates it.
            # Default context usually tries to verify server cert against system CAs.
            # If this fails, one might need:
            # ssl_context.check_hostname = False
            # ssl_context.verify_mode = ssl.CERT_NONE # This would be like sslmode=allow/prefer if server is lax
                                                    # or connect if server forces SSL but client doesn't validate CA.
                                                    # For true 'require', server cert must be validated.
            ssl_connect_arg = ssl_context

        # Allow environment variable to override SSL behavior if needed for other hosts or specific neon setups
        env_ssl_setting = os.getenv("PGSSL_ADAPTER_SETTING")
        if env_ssl_setting:
            if env_ssl_setting.lower() == "disable":
                ssl_connect_arg = False
                print(f"PostgresAdapter __init__: Overridden SSL to 'false' due to PGSSL_ADAPTER_SETTING.")
            elif env_ssl_setting.lower() == "true" or env_ssl_setting.lower() == "require":
                if not isinstance(ssl_connect_arg, ssl.SSLContext): # Avoid overwriting a context with True
                    ssl_connect_arg = True
                print(f"PostgresAdapter __init__: Set SSL to '{ssl_connect_arg}' due to PGSSL_ADAPTER_SETTING.")
            elif os.path.exists(env_ssl_setting): # Check if it's a path to a cert file for context
               import ssl
               try:
                   context = ssl.create_default_context(cafile=env_ssl_setting)
                   ssl_connect_arg = context
                   print(f"PostgresAdapter __init__: Loaded SSLContext from CA file '{env_ssl_setting}' due to PGSSL_ADAPTER_SETTING.")
               except Exception as e:
                   print(f"PostgresAdapter __init__: WARNING: Failed to load SSLContext from CA file '{env_ssl_setting}': {e}. Using previous SSL setting: {ssl_connect_arg}")
            # Add more complex SSLContext loading from path if needed in future



        final_engine_connect_args: Dict[str, Any] = {}
        if ssl_connect_arg is not None:
            final_engine_connect_args['ssl'] = ssl_connect_arg

        # Query parameters from the URL (should be clean of sslmode now)
        query_for_sqla_url = {
            key: val_list[0]
            for key, val_list in parse_qs(original_parsed_url.query).items()
            # No need to filter sslmode here as it's removed from default URL string
        }

        driver_name = original_parsed_url.scheme
        if driver_name == "postgresql":
            driver_name = "postgresql+asyncpg"

        db_url_object = URL.create(
            drivername=driver_name,
            username=original_parsed_url.username,
            password=original_parsed_url.password,
            host=original_parsed_url.hostname,
            port=original_parsed_url.port,
            database=original_parsed_url.path.lstrip('/'),
            query=query_for_sqla_url
        )
        self._db_url_for_engine = str(db_url_object)

        # --- End Define ---

        self._asyncpg_ssl_param = ssl_connect_arg # Store for raw pool creation

        print(f"SQLAlchemy engine will be created for URL object: {str(db_url_object)} with explicit connect_args: {final_engine_connect_args}")
        self._engine = create_async_engine(db_url_object, echo=False, connect_args=final_engine_connect_args)

        self._SessionLocal = sessionmaker(
            bind=self._engine, # type: ignore [arg-type]
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
        self.db: Optional[AsyncSession] = None
        self._conn_pool: Optional[asyncpg.Pool] = None
        self._initial_asyncpg_url = self._asyncpg_url # Store initial for fallback logic
        print(f"PostgresAdapter initialized. Engine URL: {self._db_url_for_engine}, Asyncpg DSN: {self._asyncpg_url}")

    async def _get_raw_connection(self) -> asyncpg.Connection:
        """Gets a raw connection from the pool, creating pool if necessary."""
        if self._conn_pool is None:
            max_retries = 2
            auth_fallback_attempted = False
            last_retryable_exception_for_loop: Optional[Union[ConnectionRefusedError, asyncpg.exceptions.CannotConnectNowError]] = None

            for attempt in range(max_retries + 2):
                last_retryable_exception_for_loop = None # Reset for current attempt type
                try:
                    print(f"PostgresAdapter: Attempting to create pool with DSN: {self._asyncpg_url} (Attempt {attempt + 1})")

                    from urllib.parse import urlparse, parse_qs, urlunparse, urlencode

                    parsed_original_url = urlparse(self._db_url)
                    query_params_original_url = {k: v[0] for k, v in parse_qs(parsed_original_url.query).items()}
                    ssl_mode = query_params_original_url.get('sslmode')

                    connect_kwargs_for_pool = {}
                    asyncpg_dsn_for_pool = self._asyncpg_url

                    if ssl_mode:
                        print(f"PostgresAdapter: Found 'sslmode={ssl_mode}' in DB_URL. Configuring for asyncpg pool.")
                        if ssl_mode in ['require', 'prefer', 'allow']:
                            connect_kwargs_for_pool['ssl'] = True
                        elif ssl_mode == 'disable':
                            connect_kwargs_for_pool['ssl'] = False
                        elif ssl_mode in ['verify-ca', 'verify-full']:
                            connect_kwargs_for_pool['ssl'] = True
                            print(f"PostgresAdapter: INFO: For sslmode={ssl_mode}, using ssl=True. For full verification, an SSLContext with CA certs might be needed.")
                        else:
                            print(f"PostgresAdapter: WARNING: Unsupported 'sslmode={ssl_mode}'. SSL will not be explicitly configured based on this mode for asyncpg pool.")

                        parsed_asyncpg_dsn = urlparse(self._asyncpg_url)
                        query_params_asyncpg_dsn = {k: v[0] for k, v in parse_qs(parsed_asyncpg_dsn.query).items()}
                        if 'sslmode' in query_params_asyncpg_dsn:
                            del query_params_asyncpg_dsn['sslmode']

                        asyncpg_dsn_for_pool = urlunparse(parsed_asyncpg_dsn._replace(query=urlencode(query_params_asyncpg_dsn)))
                        print(f"PostgresAdapter: Modified asyncpg DSN (sslmode removed from query): {asyncpg_dsn_for_pool}")
                    else:
                        print(f"PostgresAdapter: No 'sslmode' found in DB_URL query parameters. Asyncpg will use its default SSL behavior.")


                    self._conn_pool = await asyncpg.create_pool(
                        dsn=asyncpg_dsn_for_pool,
                        min_size=1,
                        max_size=10,
                        **connect_kwargs_for_pool
                    )

                    if self._conn_pool is None:
                        print("PostgresAdapter: ❌ Failed to create asyncpg connection pool: create_pool returned None")
                        raise ConnectionError("Failed to create asyncpg connection pool: create_pool returned None")

                    print("PostgresAdapter: Asyncpg connection pool created successfully.")
                    break

                except (ConnectionRefusedError, asyncpg.exceptions.CannotConnectNowError) as e:
                    last_retryable_exception_for_loop = e
                    print(f"PostgresAdapter: Connection attempt {attempt + 1} failed due to {type(e).__name__}: {e}")
                    if attempt < max_retries:
                        print(f"PostgresAdapter: Retrying in 5 seconds...")
                        await asyncio.sleep(5)
                    else:
                        break

                except asyncpg.exceptions.InternalServerError as e:
                    if "password authentication failed" in str(e).lower():
                        if self._used_env_var_url and not auth_fallback_attempted and self._initial_asyncpg_url == self._asyncpg_url :
                            auth_fallback_attempted = True
                            print(f"PostgresAdapter: 🔑 Password authentication failed with environment variable URL.")
                            print(f"PostgresAdapter: Attempting fallback to default database URL.")
                            self._asyncpg_url = self._default_db_url.replace("postgresql+asyncpg://", "postgresql://")
                            # Reset engine and session factory if URL changes
                            # Need to ensure _db_url_for_engine and final_engine_connect_args are also updated if using fallback for SQLAlchemy
                            self._engine = create_async_engine(self._default_db_url, echo=False) # type: ignore[call-overload]
                            self._SessionLocal = sessionmaker( # type: ignore[call-overload]
                                bind=self._engine, class_=AsyncSession, expire_on_commit=False, # type: ignore[arg-type]
                                autocommit=False, autoflush=False
                            )
                            print(f"PostgresAdapter: Switched to default DSN: {self._asyncpg_url}. Retrying pool creation.")
                            continue
                        else:
                            print(f"PostgresAdapter: ❌ Password authentication failed: {e}")
                            traceback.print_exc()
                            raise
                    else:
                        print(f"PostgresAdapter: ❌ An unexpected InternalServerError occurred: {e}")
                        traceback.print_exc()
                        raise

                except Exception as e:
                    print(f"PostgresAdapter: ❌ An unexpected error occurred while creating asyncpg connection pool: {e}")
                    traceback.print_exc()
                    raise

            if last_retryable_exception_for_loop is not None:
                error_message = f"""
PostgresAdapter: ❌ DATABASE CONNECTION FAILED AFTER {max_retries + 1} ATTEMPTS!
--------------------------------------------------------------------------------------
Attempted to connect to: {self._asyncpg_url} (derived from {self._db_url})

Could not establish a connection to the PostgreSQL server after multiple retries.
Please check the following:
1. Is the PostgreSQL server running?
2. Is the hostname and port in your DATABASE_URL correct?
   Current raw DATABASE_URL (from env or default): {self._db_url}
   Current asyncpg connection DSN: {self._asyncpg_url}
3. Are the username and password in your DATABASE_URL correct?
4. Is a firewall blocking the connection to the PostgreSQL server?
5. Ensure the `DATABASE_URL` environment variable is correctly set if you are not using the default.
   Environment variable name: {DATABASE_URL_ENV_VAR}

Last encountered error: {last_retryable_exception_for_loop}
--------------------------------------------------------------------------------------
"""
                print(error_message)
                traceback.print_exc()
                raise last_retryable_exception_for_loop

        if self._conn_pool is None:
            print("PostgresAdapter: ❌ Connection pool is None after initialization attempts, and no exception was raised from retries.")
            raise ConnectionError("PostgresAdapter: Connection pool is None after initialization attempts.")

        conn = await self._conn_pool.acquire()
        if conn is None: # Should not happen if pool.acquire() is successful
            raise ConnectionError("Failed to acquire connection from asyncpg pool: acquire returned None")
        return conn


    async def connect(self) -> None:
        """
        Устанавливает соединение с базой данных PostgreSQL и создает сессию SQLAlchemy.
        Also initializes the asyncpg connection pool.
        """
        if self.db is None:
            print("PostgresAdapter: Creating SQLAlchemy async session...")
            try:
                self.db = self._SessionLocal()
                print("PostgresAdapter: SQLAlchemy async session created.")
            except Exception as e:
                print(f"PostgresAdapter: ❌ Error creating SQLAlchemy async session: {e}")
                traceback.print_exc()
                if self.db:
                    await self.db.close()
                    self.db = None
                raise
        
        if self._conn_pool is None:
            # Initialize the pool by acquiring and releasing a connection
            conn = await self._get_raw_connection()
            if conn and self._conn_pool:
                 await self._conn_pool.release(conn)
            print("PostgresAdapter: Connection pool initialized and test connection released.")


    async def close(self) -> None:
        """Закрывает сессию SQLAlchemy, пул соединений asyncpg и движок SQLAlchemy."""
        if self.db:
            print("PostgresAdapter: Closing SQLAlchemy async session...")
            try:
                await self.db.close()
                print("PostgresAdapter: SQLAlchemy async session closed.")
            except Exception as e:
                print(f"PostgresAdapter: ❌ Error closing SQLAlchemy async session: {e}")
                traceback.print_exc()
            finally:
                self.db = None
        
        if self._conn_pool:
            print("PostgresAdapter: Closing asyncpg connection pool...")
            try:
                await self._conn_pool.close()
                print("PostgresAdapter: Asyncpg connection pool closed.")
            except Exception as e:
                print(f"PostgresAdapter: ❌ Error closing asyncpg connection pool: {e}")
                traceback.print_exc()
            finally:
                self._conn_pool = None

        if self._engine:
            print("PostgresAdapter: Disposing SQLAlchemy engine...")
            try:
                await self._engine.dispose()
                print("PostgresAdapter: SQLAlchemy engine disposed.")
            except Exception as e:
                print(f"PostgresAdapter: ❌ Error disposing SQLAlchemy engine: {e}")
            finally:
                self._engine = None


    async def execute(self, sql: str, params: Optional[Union[Tuple, List]] = None) -> str:
        """
        Выполняет одиночный SQL запрос (например, INSERT, UPDATE, DELETE) с использованием raw asyncpg connection.
        Возвращает статус выполнения команды (e.g., "INSERT 0 1").
        """
        if not self._conn_pool: 
            await self.connect()
        
        raw_conn = await self._get_raw_connection()
        try:
            status = await raw_conn.execute(sql, *(params or []))
            return status 
        except Exception as e:
            print(f"PostgresAdapter: ❌ Error executing SQL with asyncpg: {sql} | params: {params} | {e}")
            traceback.print_exc()
            raise
        finally:
            if self._conn_pool and raw_conn:
                await self._conn_pool.release(raw_conn)

    async def execute_insert(self, sql: str, params: Optional[Union[Tuple, List]] = None) -> Optional[Any]:
        """
        Выполняет INSERT запрос и возвращает значение (например, ID) используя 'RETURNING id'.
        SQL запрос ДОЛЖЕН содержать 'RETURNING ...' clause.
        """
        if not self._conn_pool:
            await self.connect()
        
        raw_conn = await self._get_raw_connection()
        try:
            inserted_value = await raw_conn.fetchval(sql, *(params or []))
            return inserted_value
        except Exception as e:
            print(f"PostgresAdapter: ❌ Error executing INSERT SQL (with RETURNING): {sql} | params: {params} | {e}")
            traceback.print_exc()
            raise
        finally:
            if self._conn_pool and raw_conn:
                await self._conn_pool.release(raw_conn)

    async def execute_many(self, sql: str, data: List[Union[Tuple, List]]) -> None:
         """
         Выполняет один SQL запрос много раз с разными данными (пакетная операция) с asyncpg.
         """
         if not self._conn_pool:
             await self.connect()
         if not data:
             return

         raw_conn = await self._get_raw_connection()
         try:
             async with raw_conn.transaction():
                 await raw_conn.executemany(sql, data)
         except Exception as e:
             print(f"PostgresAdapter: ❌ Error executing many SQL with asyncpg: {sql} | data count: {len(data)} | {e}")
             traceback.print_exc()
             raise
         finally:
            if self._conn_pool and raw_conn:
                await self._conn_pool.release(raw_conn)


    async def fetchall(self, sql: str, params: Optional[Union[Tuple, List]] = None) -> List[Dict[str, Any]]:
        """Выполняет SELECT запрос и возвращает все строки как список словарей."""
        if not self._conn_pool:
            await self.connect()
        
        raw_conn = await self._get_raw_connection()
        try:
            records = await raw_conn.fetch(sql, *(params or []))
            return [dict(record) for record in records] 
        except Exception as e:
            print(f"PostgresAdapter: ❌ Error fetching all SQL with asyncpg: {sql} | params: {params} | {e}")
            traceback.print_exc()
            raise
        finally:
            if self._conn_pool and raw_conn:
                await self._conn_pool.release(raw_conn)

    async def fetchone(self, sql: str, params: Optional[Union[Tuple, List]] = None) -> Optional[Dict[str, Any]]:
        """Выполняет SELECT запрос и возвращает одну строку (или None) как словарь."""
        if not self._conn_pool:
            await self.connect()

        raw_conn = await self._get_raw_connection()
        try:
            record = await raw_conn.fetchrow(sql, *(params or []))
            return dict(record) if record else None 
        except Exception as e:
            print(f"PostgresAdapter: ❌ Error fetching one SQL with asyncpg: {sql} | params: {params} | {e}")
            traceback.print_exc()
            raise
        finally:
            if self._conn_pool and raw_conn:
                await self._conn_pool.release(raw_conn)

    async def commit(self) -> None:
        """Коммитит текущую транзакцию SQLAlchemy сессии."""
        if not self.db:
            raise ConnectionError("SQLAlchemy session is not established.")
        try:
            await self.db.commit()
            print("PostgresAdapter: SQLAlchemy session committed.")
        except Exception as e:
            print(f"PostgresAdapter: ❌ Error committing SQLAlchemy session: {e}")
            traceback.print_exc()
            await self.db.rollback() 
            print("PostgresAdapter: SQLAlchemy session rolled back due to commit error.")
            raise

    async def rollback(self) -> None:
        """Откатывает текущую транзакцию SQLAlchemy сессии."""
        if not self.db:
            raise ConnectionError("SQLAlchemy session is not established.")
        try:
            await self.db.rollback()
            print("PostgresAdapter: SQLAlchemy session rolled back.")
        except Exception as e:
            print(f"PostgresAdapter: ❌ Error rolling back SQLAlchemy session: {e}")
            traceback.print_exc()
            raise

    async def initialize_database(self) -> None:
        """
        Ensures the database is connected. Schema management is handled by Alembic.
        """
        print("PostgresAdapter: Initializing database connection for application use.")
        if self.db is None: 
            await self.connect()
        print("PostgresAdapter: Database initialization checks complete. Schema is managed by Alembic.")

    async def begin_transaction(self) -> None:
        """Begins a new transaction on the SQLAlchemy session."""
        if not self.db:
            # Attempt to connect if session is not active. This might be needed if begin_transaction
            # can be called before other methods that establish self.db.
            await self.connect()
            if not self.db: # Still no session after connect attempt
                raise ConnectionError("SQLAlchemy session is not established, cannot begin transaction.")
        try:
            # SQLAlchemy AsyncSession typically uses await self.db.begin() or similar
            # For now, assuming self.db is an AsyncSession, begin a transaction if not already in one.
            # AsyncSession might manage transactions differently, often per operation or via begin_nested.
            # A simple explicit begin might not be standard for all uses.
            # However, if a block of operations needs to be atomic, an explicit transaction is good.
            # Let's assume begin() starts a top-level transaction if one isn't active.
            # await self.db.begin() # This starts a new transaction or sub-transaction
            # For asyncpg, transactions are usually managed on a specific connection.
            # The SQLAlchemy AsyncSession handles this abstraction.
            # If a transaction is already active, this might create a savepoint.
            # For now, we'll assume this is the intended way to ensure a transaction context.
            # If self.db.in_transaction check is available:
            # if not self.db.in_transaction:
            #    await self.db.begin()
            # print("PostgresAdapter: Began SQLAlchemy session transaction (or savepoint).")
            # Simpler for now: ensure a connection is ready. The transaction is often managed by `with session.begin():`
            # For explicit calls, this is more complex.
            # For now, this method primarily ensures connection. Actual transaction start might be implicit with first operation
            # or needs to be handled by how `self.db` operations are grouped.
            # Awaiting more specific transaction block patterns in DBService.
            # For this step, let's make it a no-op that ensures connection,
            # assuming transactions will be handled by `with self.db.begin():` in higher layers if needed,
            # or that individual `commit/rollback` calls are sufficient.
            # To make it work as expected by DBService:
            if not self.db.in_transaction(): # Check if already in a transaction
                 self._current_transaction = await self.db.begin()
                 print("PostgresAdapter: Began new SQLAlchemy session transaction.")
            else:
                 # If already in a transaction, create a savepoint (nested transaction)
                 self._current_transaction = await self.db.begin_nested()
                 print("PostgresAdapter: Began nested SQLAlchemy session transaction (savepoint).")

        except Exception as e:
            print(f"PostgresAdapter: ❌ Error beginning SQLAlchemy session transaction: {e}")
            traceback.print_exc()
            raise


    async def save_pending_conflict(self, conflict_id: str, guild_id: str, conflict_data: str) -> None:
        if not isinstance(conflict_data, str):
             raise TypeError("conflict_data must be a JSON string.")
        sql = """
            INSERT INTO pending_conflicts (id, guild_id, conflict_data, created_at)
            VALUES ($1, $2, $3::jsonb, NOW())
            ON CONFLICT(id) DO UPDATE SET
                guild_id = EXCLUDED.guild_id,
                conflict_data = EXCLUDED.conflict_data,
                created_at = NOW();
        """
        await self.execute(sql, (conflict_id, guild_id, conflict_data))

    async def get_pending_conflict(self, conflict_id: str) -> Optional[Dict[str, Any]]:
        sql = "SELECT id, guild_id, conflict_data FROM pending_conflicts WHERE id = $1;"
        return await self.fetchone(sql, (conflict_id,))

    async def delete_pending_conflict(self, conflict_id: str) -> None:
        sql = "DELETE FROM pending_conflicts WHERE id = $1;"
        await self.execute(sql, (conflict_id,))

    async def get_pending_conflicts_by_guild(self, guild_id: str) -> List[Dict[str, Any]]:
        sql = "SELECT id, guild_id, conflict_data FROM pending_conflicts WHERE guild_id = $1 ORDER BY created_at DESC;"
        return await self.fetchall(sql, (guild_id,))

    async def save_pending_moderation_request(self, request_id: str, guild_id: str, user_id: str, content_type: str, data_json: str, status: str = 'pending') -> None:
        if not isinstance(data_json, str):
            raise TypeError("data_json must be a JSON string.")
        sql = """
            INSERT INTO pending_moderation_requests (id, guild_id, user_id, content_type, data, status, created_at)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6, NOW())
        """
        await self.execute(sql, (request_id, guild_id, user_id, content_type, data_json, status))

    async def get_pending_moderation_request(self, request_id: str) -> Optional[Dict[str, Any]]:
        sql = "SELECT * FROM pending_moderation_requests WHERE id = $1;"
        return await self.fetchone(sql, (request_id,))

    async def update_pending_moderation_request(
        self, request_id: str, status: str, moderator_id: Optional[str],
        data_json: Optional[str] = None, moderator_notes: Optional[str] = None
    ) -> bool:
        if data_json is not None and not isinstance(data_json, str):
            raise TypeError("data_json must be a JSON string if provided.")

        fields_to_update = ["status = $1", "moderator_id = $2", "moderated_at = NOW()"]
        params_list: List[Any] = [status, moderator_id]
        current_param_idx = 3 

        if data_json is not None:
            fields_to_update.append(f"data = ${current_param_idx}::jsonb")
            params_list.append(data_json)
            current_param_idx += 1
        
        if moderator_notes is not None:
            fields_to_update.append(f"moderator_notes = ${current_param_idx}")
            params_list.append(moderator_notes)
            current_param_idx +=1

        params_list.append(request_id) 

        sql = f"""
            UPDATE pending_moderation_requests
            SET {', '.join(fields_to_update)}
            WHERE id = ${current_param_idx};
        """
        
        result_status = await self.execute(sql, tuple(params_list)) 
        return "UPDATE 1" in result_status 

    async def delete_pending_moderation_request(self, request_id: str) -> bool:
        sql = "DELETE FROM pending_moderation_requests WHERE id = $1;"
        result_status = await self.execute(sql, (request_id,))
        return "DELETE 1" in result_status

    async def get_pending_requests_by_guild(self, guild_id: str, status: str = 'pending') -> List[Dict[str, Any]]:
        sql = "SELECT * FROM pending_moderation_requests WHERE guild_id = $1 AND status = $2 ORDER BY created_at ASC;"
        return await self.fetchall(sql, (guild_id, status))

    async def add_generated_location(self, location_id: str, guild_id: str, user_id: str) -> None:
        sql = """
            INSERT INTO generated_locations (location_id, guild_id, user_id, generated_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT(location_id) DO NOTHING;
        """
        await self.execute(sql, (location_id, guild_id, user_id))

    async def upsert_location(self, location_data: Dict[str, Any]) -> bool:
        """
        Inserts a new location or updates an existing one based on ID.
        location_data should be a dictionary matching Location model fields.
        """
        if not location_data.get('id') or not location_data.get('guild_id'):
            print("PostgresAdapter: Error: Location data must include 'id' and 'guild_id' for upsert.")
            return False

        # Ensure all JSON fields are dumped to strings for the query
        data_for_sql = {}
        for key, value in location_data.items():
            if isinstance(value, dict) or isinstance(value, list):
                data_for_sql[key] = json.dumps(value)
            else:
                data_for_sql[key] = value

        # Ensure boolean is_active is correctly represented if not present or None
        if 'is_active' not in data_for_sql or data_for_sql['is_active'] is None:
            data_for_sql['is_active'] = True # Default to True

        # Define all columns that can be inserted/updated
        # Order must match the VALUES clause and the EXCLUDED part of ON CONFLICT
        # Ensure all fields from Location.to_dict() are covered here.
        # 'static_name' was present in Location.to_dict(), ensure it's handled.
        # 'static_connections' was present in Location.to_dict().
        # 'inventory' was present in Location.to_dict().
        columns = [
            'id', 'guild_id', 'template_id', 'name_i18n', 'descriptions_i18n',
            'details_i18n', 'tags_i18n', 'atmosphere_i18n', 'features_i18n',
            'neighbor_locations_json', 'state_variables', 'is_active', 'channel_id', 'image_url', # Changed 'exits' to 'neighbor_locations_json'
            'static_name', 'static_connections', 'inventory' # Assuming static_name and static_connections are still desired; schema review needed
        ]

        # Prepare values in the correct order, using None for missing optional fields
        values_tuple = tuple(data_for_sql.get(col) for col in columns)

        # Construct SET clause for ON CONFLICT
        set_clauses = [f"{col} = EXCLUDED.{col}" for col in columns if col != 'id']

        sql = f"""
            INSERT INTO locations ({', '.join(columns)})
            VALUES ({', '.join([f'${i+1}' for i in range(len(columns))])})
            ON CONFLICT (id) DO UPDATE SET
                {', '.join(set_clauses)};
        """
        try:
            status = await self.execute(sql, values_tuple)
            # Successful execution might return "INSERT 0 1" or "UPDATE 1"
            print(f"PostgresAdapter: Upserted location {location_data.get('id')}. Status: {status}")
            return True # Assuming success if no exception for now
        except Exception as e:
            print(f"PostgresAdapter: ❌ Error upserting location {location_data.get('id')}: {e}")
            traceback.print_exc()
            return False

    @property
    def supports_returning_id_on_insert(self) -> bool:
        return True

    @property
    def json_column_type_cast(self) -> Optional[str]:
        return "::jsonb"

print(f"DEBUG: Finished loading postgres_adapter.py from: {__file__}")
