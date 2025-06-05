# bot/database/sqlite_adapter.py
"""
Модуль для адаптера базы данных SQLite, включая систему миграции схемы.
"""

print(f"DEBUG: Loading sqlite_adapter.py from: {__file__}")
import sqlite3 # Keep for sqlite3.OperationalError
import traceback
import json # Needed for json.loads/dumps
from typing import Optional, List, Tuple, Any, Union, Dict

import aiosqlite
# Типы для аннотаций
from aiosqlite import Connection, Cursor, Row

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session as SQLAlchemySession
from .models import Base # Assuming models.py is in the same directory


class SqliteAdapter:
    """
    Асинхронный адаптер для работы с базой данных SQLite с базовой системой миграции схемы.
    Автоматически коммитит успешные операции изменения данных и откатывает при ошибке
    в методах execute, execute_insert, execute_many.
    """
    # LATEST_SCHEMA_VERSION constant removed as schema is managed by Alembic.

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn: Optional[Connection] = None
        self._engine = create_engine(f"sqlite+aiosqlite:///{self._db_path}")
        self._SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self._engine)
        self.db: Optional[SQLAlchemySession] = None
        print(f"SqliteAdapter initialized for database: {self._db_path}")

    async def connect(self) -> None:
        """Устанавливает соединение с базой данных."""
        if self._conn is None:
            print("SqliteAdapter: Connecting to database...")
            try:
                self._conn = await aiosqlite.connect(self._db_path, check_same_thread=False)
                self._conn.row_factory = aiosqlite.Row
                await self._conn.execute('PRAGMA journal_mode=WAL')
                await self._conn.execute('PRAGMA foreign_keys=ON')

                self.db = self._SessionLocal()
                print("SqliteAdapter: Database connected successfully. SQLAlchemy session created.")

            except Exception as e:
                print(f"SqliteAdapter: ❌ Error connecting to database: {e}")
                traceback.print_exc()
                if self.db:
                    self.db.close()
                    self.db = None
                if self._conn:
                    await self._conn.close()
                    self._conn = None
                raise

    async def close(self) -> None:
        """Закрывает соединение с базой данных."""
        if self.db:
            print("SqliteAdapter: Closing SQLAlchemy session...")
            try:
                self.db.close()
                print("SqliteAdapter: SQLAlchemy session closed.")
            except Exception as e:
                print(f"SqliteAdapter: ❌ Error closing SQLAlchemy session: {e}")
                traceback.print_exc()
            finally:
                self.db = None

        if self._conn:
            print("SqliteAdapter: Closing aiosqlite connection...")
            try:
                await self._conn.close()
                print("SqliteAdapter: aiosqlite connection closed.")
            except Exception as e:
                print(f"SqliteAdapter: ❌ Error closing aiosqlite connection: {e}")
                traceback.print_exc()
            finally:
                self._conn = None

    async def execute(self, sql: str, params: Optional[Union[Tuple, List]] = None) -> Cursor:
        """
        Выполняет одиночный SQL запрос (например, INSERT, UPDATE, DELETE, CREATE).
        Автоматически коммитит при успехе, откатывает при ошибке.
        """
        if not self._conn:
            raise ConnectionError("Database connection is not established.")
        try:
            cursor = await self._conn.execute(sql, params or ())
            await self._conn.commit()
            return cursor
        except Exception as e:
            print(f"SqliteAdapter: ❌ Error executing SQL: {sql} | params: {params} | {e}")
            traceback.print_exc()
            try:
                 await self._conn.rollback()
                 print("SqliteAdapter: Transaction rolled back.")
            except Exception as rb_e:
                 print(f"SqliteAdapter: Error during rollback: {rb_e}")
            raise

    async def execute_insert(self, sql: str, params: Optional[Union[Tuple, List]] = None) -> Optional[int]:
        """
        Выполняет INSERT запрос и возвращает rowid последней вставленной строки.
        Предполагает, что таблица использует INTEGER PRIMARY KEY AUTOINCREMENT.
        Автоматически коммитит при успехе, откатывает при ошибке.
        """
        if not self._conn:
            raise ConnectionError("Database connection is not established.")
        try:
            cursor = await self._conn.execute(sql, params or ())
            last_id: Optional[int] = cursor.lastrowid # type: ignore
            await self._conn.commit()
            return last_id
        except Exception as e:
            print(f"SqliteAdapter: ❌ Error executing INSERT SQL (with lastrowid): {sql} | params: {params} | {e}")
            traceback.print_exc()
            try:
                 await self._conn.rollback()
                 print("SqliteAdapter: Transaction rolled back.")
            except Exception as rb_e:
                 print(f"SqliteAdapter: Error during rollback: {rb_e}")
            raise

    async def execute_many(self, sql: str, data: List[Union[Tuple, List]]) -> None:
         """
         Выполняет один SQL запрос много раз с разными данными (пакетная операция).
         Используется для пакетных INSERT, UPDATE, DELETE.
         Автоматически коммитит при успехе, откатывает при ошибке.
         """
         if not self._conn:
             raise ConnectionError("Database connection is not established.")
         if not data:
             return

         try:
             await self._conn.executemany(sql, data)
             await self._conn.commit()
         except Exception as e:
             print(f"SqliteAdapter: ❌ Error executing many SQL: {sql} | data count: {len(data)} | {e}")
             traceback.print_exc()
             try:
                 await self._conn.rollback()
                 print("SqliteAdapter: Transaction rolled back.")
             except Exception as rb_e:
                 print(f"SqliteAdapter: Error during rollback: {rb_e}")
             raise

    async def fetchall(self, sql: str, params: Optional[Union[Tuple, List]] = None) -> List[Row]:
        """Выполняет SELECT запрос и возвращает все строки."""
        if not self._conn:
            raise ConnectionError("Database connection is not established.")
        try:
            cursor = await self._conn.execute(sql, params or ())
            rows = await cursor.fetchall()
            await cursor.close()
            return list(rows)
        except Exception as e:
            print(f"SqliteAdapter: ❌ Error fetching all SQL: {sql} | params: {params} | {e}")
            traceback.print_exc()
            raise

    async def fetchone(self, sql: str, params: Optional[Union[Tuple, List]] = None) -> Optional[Row]:
        """Выполняет SELECT запрос и возвращает одну строку (или None)."""
        if not self._conn:
            raise ConnectionError("Database connection is not established.")
        try:
            cursor = await self._conn.execute(sql, params or ())
            row = await cursor.fetchone()
            await cursor.close()
            return row
        except Exception as e:
            print(f"SqliteAdapter: ❌ Error fetching one SQL: {sql} | params: {params} | {e}")
            traceback.print_exc()
            raise


    async def commit(self) -> None:
        """Выполняет коммит текущей транзакции."""
        if not self._conn:
            print("SqliteAdapter: Warning: commit called but no connection.")
            return
        try:
            await self._conn.commit()
        except Exception as e:
            print(f"SqliteAdapter: ❌ Error committing transaction: {e}")
            traceback.print_exc()
            raise

    async def rollback(self) -> None:
        """Откатывает текущую транзакцию."""
        if not self._conn:
            print("SqliteAdapter: Warning: rollback called but no connection.")
            return
        try:
            await self._conn.rollback()
            print("SqliteAdapter: Transaction rolled back.")
        except Exception as e:
            print(f"SqliteAdapter: ❌ Error rolling back transaction: {e}")
            traceback.print_exc()
            raise

    # Removed get_current_schema_version method.
    # Removed set_schema_version method.

    # --- Метод инициализации базы данных ---
    async def initialize_database(self) -> None:
        """
        Ensures the database is connected. Schema management is now handled by Alembic.
        The old migration logic (_migrate_vX_to_vY methods) and PRAGMA user_version
        are no longer used by this method.
        """
        print("SqliteAdapter: Initializing database connection for application use.")
        if not self._conn:
            await self.connect()
        print("SqliteAdapter: Database initialization checks complete. Schema is managed by Alembic.")

    # Removing old migration methods block...
# --- Методы миграции схемы (OLD - NO LONGER CALLED BY initialize_database) ---
    # --- Методы для работы с таблицей pending_conflicts ---

    async def save_pending_conflict(self, conflict_id: str, guild_id: str, conflict_data: str) -> None:
        """Saves or updates a pending manual conflict in the database."""
        if not isinstance(conflict_data, str):
             raise TypeError("conflict_data must be a JSON string.")
        sql = """
            INSERT INTO pending_conflicts (id, guild_id, conflict_data)
            VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                guild_id = excluded.guild_id,
                conflict_data = excluded.conflict_data,
                created_at = strftime('%s','now');
        """
        await self.execute(sql, (conflict_id, guild_id, conflict_data))

    async def get_pending_conflict(self, conflict_id: str) -> Optional[Row]:
        """Retrieves a pending manual conflict by its ID."""
        sql = "SELECT id, guild_id, conflict_data FROM pending_conflicts WHERE id = ?;"
        row = await self.fetchone(sql, (conflict_id,))
        return row

    async def delete_pending_conflict(self, conflict_id: str) -> None:
        """Deletes a pending manual conflict by its ID."""
        sql = "DELETE FROM pending_conflicts WHERE id = ?;"
        await self.execute(sql, (conflict_id,))

    async def get_pending_conflicts_by_guild(self, guild_id: str) -> List[Row]:
        """Retrieves all pending manual conflicts for a specific guild."""
        sql = "SELECT id, guild_id, conflict_data FROM pending_conflicts WHERE guild_id = ? ORDER BY created_at DESC;"
        rows = await self.fetchall(sql, (guild_id,))
        return rows

    # --- Методы для работы с таблицей pending_moderation_requests ---

    async def save_pending_moderation_request(self, request_id: str, guild_id: str, user_id: str, content_type: str, data_json: str, status: str = 'pending') -> None:
        """Saves a new pending moderation request."""
        if not isinstance(data_json, str):
            raise TypeError("data_json must be a JSON string.")
        sql = """
            INSERT INTO pending_moderation_requests (id, guild_id, user_id, content_type, data, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, strftime('%s','now'))
        """
        await self.execute(sql, (request_id, guild_id, user_id, content_type, data_json, status))

    async def get_pending_moderation_request(self, request_id: str) -> Optional[Row]:
        """Retrieves a pending moderation request by its ID."""
        sql = "SELECT * FROM pending_moderation_requests WHERE id = ?;"
        row = await self.fetchone(sql, (request_id,))
        return row

    async def update_pending_moderation_request(self, request_id: str, status: str, moderator_id: Optional[str], data_json: Optional[str] = None, moderator_notes: Optional[str] = None) -> bool: # Added moderator_notes
        """Updates the status, moderator, notes and optionally data of a moderation request."""
        if data_json is not None and not isinstance(data_json, str):
            raise TypeError("data_json must be a JSON string if provided.")

        fields_to_update = ["status = ?", "moderator_id = ?", "moderated_at = strftime('%s','now')"]
        params_list: List[Any] = [status, moderator_id]

        if data_json is not None:
            fields_to_update.append("data = ?")
            params_list.append(data_json)

        if moderator_notes is not None: # Add notes if provided
            fields_to_update.append("moderator_notes = ?")
            params_list.append(moderator_notes)

        params_list.append(request_id)

        sql = f"""
            UPDATE pending_moderation_requests
            SET {', '.join(fields_to_update)}
            WHERE id = ?;
        """

        cursor = await self.execute(sql, tuple(params_list))
        return cursor.rowcount > 0


    async def delete_pending_moderation_request(self, request_id: str) -> bool:
        """Deletes a pending moderation request by its ID."""
        sql = "DELETE FROM pending_moderation_requests WHERE id = ?;"
        cursor = await self.execute(sql, (request_id,))
        return cursor.rowcount > 0

    async def get_pending_requests_by_guild(self, guild_id: str, status: str = 'pending') -> List[Row]:
        """Retrieves all pending moderation requests for a specific guild, optionally filtered by status."""
        sql = "SELECT * FROM pending_moderation_requests WHERE guild_id = ? AND status = ? ORDER BY created_at ASC;"
        rows = await self.fetchall(sql, (guild_id, status))
        return rows

    # --- Методы для работы с таблицей generated_locations ---
    async def add_generated_location(self, location_id: str, guild_id: str, user_id: str) -> None:
        """Marks a location as having been generated by a user."""
        sql = """
            INSERT INTO generated_locations (location_id, guild_id, user_id, generated_at)
            VALUES (?, ?, ?, strftime('%s','now'))
            ON CONFLICT(location_id) DO NOTHING;
        """
        await self.execute(sql, (location_id, guild_id, user_id))

    async def _recreate_table_with_new_schema(self, cursor: Cursor, table_name: str, new_schema_sql: str, old_columns: List[str], data_migration_sql: Optional[str] = None):
        """Helper function to recreate a table with a new schema and copy data."""
        # This method might be removed if no longer used after migrations are fully Alembic-managed
        print(f"SqliteAdapter: Recreating table '{table_name}'...")
        await cursor.execute(f"ALTER TABLE {table_name} RENAME TO {table_name}_old;")
        print(f"SqliteAdapter: Renamed '{table_name}' to '{table_name}_old'.")

        await cursor.execute(new_schema_sql)
        print(f"SqliteAdapter: Created new '{table_name}' table with updated schema.")

        columns_str = ", ".join(old_columns)
        if data_migration_sql:
            await cursor.execute(data_migration_sql)
            print(f"SqliteAdapter: Migrated data from '{table_name}_old' to new '{table_name}' using custom SQL.")
        else:
            # Ensure columns_str is not empty if old_columns was empty, though this shouldn't happen for existing tables.
            if columns_str:
                 await cursor.execute(f"INSERT INTO {table_name} ({columns_str}) SELECT {columns_str} FROM {table_name}_old;")
                 print(f"SqliteAdapter: Copied data from '{table_name}_old' to new '{table_name}'.")
            else:
                 print(f"SqliteAdapter: No columns to copy for table {table_name}_old.")


        await cursor.execute(f"DROP TABLE {table_name}_old;")
        print(f"SqliteAdapter: Dropped '{table_name}_old'.")
        print(f"SqliteAdapter: Table '{table_name}' recreated successfully.")

    async def _get_table_columns(self, cursor: Cursor, table_name: str) -> List[str]:
        """Helper to get column names of a table."""
        # This method might be removed if no longer used after migrations are fully Alembic-managed
        await cursor.execute(f"PRAGMA table_info({table_name});")
        return [row['name'] for row in await cursor.fetchall()]

# --- Конец класса SqliteAdapter ---
print(f"DEBUG: Finished loading sqlite_adapter.py from: {__file__}")
