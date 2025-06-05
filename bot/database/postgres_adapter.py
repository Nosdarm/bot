# bot/database/postgres_adapter.py
"""
Модуль для асинхронного адаптера базы данных PostgreSQL.
"""

import traceback
import json
from typing import Optional, List, Tuple, Any, Union, Dict

import asyncpg # Driver for PostgreSQL
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from .models import Base # Assuming models.py is in the same directory

# Default PostgreSQL connection URL (ideally, this should come from config)
# Using the one from alembic.ini: postgresql://postgres:test123@localhost:5433/kvelin_bot
# For asyncpg, the connection string scheme is 'postgresql://' or 'postgres://'
# For SQLAlchemy with asyncpg, it's 'postgresql+asyncpg://'
SQLALCHEMY_DATABASE_URL = "postgresql+asyncpg://postgres:test123@localhost:5433/kvelin_bot"

class PostgresAdapter:
    """
    Асинхронный адаптер для работы с базой данных PostgreSQL.
    """

    def __init__(self, db_url: Optional[str] = None):
        self._db_url = db_url or SQLALCHEMY_DATABASE_URL
        # Ensure the URL scheme is compatible with asyncpg if used directly
        self._asyncpg_url = self._db_url.replace("postgresql+asyncpg://", "postgresql://")

        self._engine = create_async_engine(self._db_url, echo=False) # Set echo=True for SQL query logging
        self._SessionLocal = sessionmaker(
            bind=self._engine,
            class_=AsyncSession, # Use AsyncSession for SQLAlchemy 2.0 async support
            expire_on_commit=False,
            autocommit=False, # Explicit commit needed
            autoflush=False, # Explicit flush needed
        )
        self.db: Optional[AsyncSession] = None # SQLAlchemy async session
        self._conn_pool: Optional[asyncpg.Pool] = None # Asyncpg connection pool
        print(f"PostgresAdapter initialized for database URL: {self._db_url}")

    async def _get_raw_connection(self) -> asyncpg.Connection:
        """Gets a raw connection from the pool, creating pool if necessary."""
        if self._conn_pool is None:
            try:
                # Adjust connect_min_size and connect_max_size as needed
                self._conn_pool = await asyncpg.create_pool(dsn=self._asyncpg_url, min_size=1, max_size=10)
                if self._conn_pool is None: # Check if create_pool actually returned a pool
                    raise ConnectionError("Failed to create asyncpg connection pool: create_pool returned None")
                print("PostgresAdapter: Asyncpg connection pool created.")
            except Exception as e:
                print(f"PostgresAdapter: ❌ Error creating asyncpg connection pool: {e}")
                traceback.print_exc()
                raise

        # The pool itself is now stored in self._conn_pool
        # Connections should be acquired from this pool when needed
        conn = await self._conn_pool.acquire()
        if conn is None:
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

print(f"DEBUG: Finished loading postgres_adapter.py from: {__file__}")
