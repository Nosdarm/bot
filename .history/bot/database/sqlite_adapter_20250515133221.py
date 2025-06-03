# bot/database/sqlite_adapter.py

import sqlite3
import traceback
# from typing import Optional, List, Tuple, Any # Already imported below from aiosqlite
from typing import Optional, List, Tuple, Any

import aiosqlite
# Типы для аннотаций
from aiosqlite import Connection, Cursor, Row


class SqliteAdapter:
    """
    Асинхронный адаптер для работы с базой данных SQLite с базовой системой миграции схемы.
    Автоматически коммитит успешные операции изменения данных и откатывает при ошибке
    в методах execute, execute_insert, execute_many.
    """
    # Определяем последнюю версию схемы, которую знает этот адаптер
    LATEST_SCHEMA_VERSION = 1 # Увеличиваем эту версию при каждом изменении схемы

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn: Optional[Connection] = None
        print(f"SqliteAdapter initialized for database: {self._db_path}")

    async def connect(self) -> None:
        """Устанавливает соединение с базой данных."""
        if self._conn is None:
            print("SqliteAdapter: Connecting to database...")
            try:
                self._conn = await aiosqlite.connect(self._db_path)
                self._conn.row_factory = aiosqlite.Row
                await self._conn.execute('PRAGMA journal_mode=WAL')
                print("SqliteAdapter: Database connected successfully.")
            except Exception as e:
                print(f"SqliteAdapter: ❌ Error connecting to database: {e}")
                traceback.print_exc()
                self._conn = None
                raise

    async def close(self) -> None:
        """Закрывает соединение с базой данных."""
        if self._conn:
            print("SqliteAdapter: Closing database connection...")
            try:
                await self._conn.close()
                print("SqliteAdapter: Database connection closed.")
            except Exception as e:
                print(f"SqliteAdapter: ❌ Error closing database connection: {e}")
                traceback.print_exc()
            finally:
                self._conn = None # Убеждаемся, что self._conn None

    async def execute(self, sql: str, params: Optional[Tuple | List] = None) -> Cursor:
        """
        Выполняет одиночный SQL запрос (например, INSERT, UPDATE, DELETE, CREATE).
        Автоматически коммитит при успехе, откатывает при ошибке.
        """
        if not self._conn:
            raise ConnectionError("Database connection is not established.")
        try:
            # print(f"SqliteAdapter: Executing SQL: {sql} | params: {params}") # Отладочный вывод
            cursor = await self._conn.execute(sql, params or ())
            await self._conn.commit() # Коммит после успешного выполнения
            # print("SqliteAdapter: SQL executed and committed.")
            return cursor
        except Exception as e:
            print(f"SqliteAdapter: ❌ Error executing SQL: {sql} | params: {params} | {e}")
            traceback.print_exc()
            try:
                 await self._conn.rollback()
                 print("SqliteAdapter: Transaction rolled back.")
            except Exception as rb_e:
                 print(f"SqliteAdapter: Error during rollback: {rb_e}")
            raise # Перебрасываем исключение

    async def execute_insert(self, sql: str, params: Optional[Tuple | List] = None) -> int:
        """
        Выполняет INSERT запрос и возвращает rowid последней вставленной строки.
        Предполагает, что таблица использует INTEGER PRIMARY KEY AUTOINCREMENT.
        Автоматически коммитит при успехе, откатывает при ошибке.
        """
        if not self._conn:
            raise ConnectionError("Database connection is not established.")
        try:
            # print(f"SqliteAdapter: Executing INSERT SQL (with lastrowid): {sql} | params: {params}") # Отладочный вывод
            cursor = await self._conn.execute(sql, params or ())
            last_id = cursor.lastrowid
            await self._conn.commit() # Коммит после успешной вставки
            # print(f"SqliteAdapter: INSERT executed, lastrowid: {last_id}.")
            return last_id
        except Exception as e:
            print(f"SqliteAdapter: ❌ Error executing INSERT SQL (with lastrowid): {sql} | params: {params} | {e}")
            traceback.print_exc()
            try:
                 await self._conn.rollback()
                 print("SqliteAdapter: Transaction rolled back.")
            except Exception as rb_e:
                 print(f"SqliteAdapter: Error during rollback: {rb_e}")
            raise # Перебрасываем исключение


    async def execute_many(self, sql: str, data: List[Tuple | List]) -> None:
         """
         Выполняет один SQL запрос много раз с разными данными (пакетная операция).
         Используется для пакетных INSERT, UPDATE, DELETE.
         Автоматически коммитит при успехе, откатывает при ошибке.
         """
         if not self._conn:
             raise ConnectionError("Database connection is not established.")
         if not data:
             return # Ничего не делаем, если данных нет

         try:
             await self._conn.executemany(sql, data)
             await self._conn.commit() # Коммит после пакетной операции
         except Exception as e:
             print(f"SqliteAdapter: ❌ Error executing many SQL: {sql} | data count: {len(data)} | {e}")
             traceback.print_exc()
             try:
                 await self._conn.rollback()
                 print("SqliteAdapter: Transaction rolled back.")
             except Exception as rb_e:
                 print(f"SqliteAdapter: Error during rollback: {rb_e}")
             raise # Перебрасываем исключение


    async def fetchall(self, sql: str, params: Optional[Tuple | List] = None) -> List[Row]:
        """Выполняет SELECT запрос и возвращает все строки."""
        if not self._conn:
            raise ConnectionError("Database connection is not established.")
        try:
            cursor = await self._conn.execute(sql, params or ())
            rows = await cursor.fetchall()
            await cursor.close() # Закрываем курсор
            return rows
        except Exception as e:
            print(f"SqliteAdapter: ❌ Error fetching all SQL: {sql} | params: {params} | {e}")
            traceback.print_exc()
            raise # Перебрасываем исключение

    async def fetchone(self, sql: str, params: Optional[Tuple | List] = None) -> Optional[Row]:
        """Выполняет SELECT запрос и возвращает одну строку (или None)."""
        if not self._conn:
            raise ConnectionError("Database connection is not established.")
        try:
            cursor = await self._conn.execute(sql, params or ())
            row = await cursor.fetchone()
            await cursor.close() # Закрываем курсор
            return row
        except Exception as e:
            print(f"SqliteAdapter: ❌ Error fetching one SQL: {sql} | params: {params} | {e}")
            traceback.print_exc()
            raise # Перебрасываем исключение

    # Методы commit/rollback оставлены как публичные для явного управления транзакциями,
    # но НЕ должны вызываться там, где execute методы уже делают авто-коммит/откат.

    async def commit(self) -> None:
        """Выполняет коммит текущей транзакции."""
        if not self._conn:
            print("SqliteAdapter: Warning: commit called but no connection.")
            return
        try:
            await self._conn.commit()
            # print("SqliteAdapter: Transaction committed.")
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

    async def get_current_schema_version(self, cursor: Cursor) -> int:
        """Получает текущую версию схемы из БД, используя предоставленный курсор."""
        # Используем execute через cursor, так как get_current_schema_version вызывается внутри
        # async with cursor: блока в initialize_database
        await cursor.execute("CREATE TABLE IF NOT EXISTS schema_versions (version INTEGER PRIMARY KEY);")
        # Не вызываем commit здесь, так как initialize_database управляет транзакцией

        # fetchone тоже должен работать через курсор
        # row = await self.fetchone("SELECT version FROM schema_versions") # Эта строка была неправильной
        # Правильно: используем cursor.execute для fetchone
        await cursor.execute("SELECT version FROM schema_versions")
        row = await cursor.fetchone()

        return row['version'] if row else 0

    async def set_schema_version(self, cursor: Cursor, version: int) -> None:
        """Устанавливает текущую версию схемы в БД, используя предоставленный курсор."""
        # Используем execute через cursor
        await cursor.execute("INSERT OR REPLACE INTO schema_versions (version) VALUES (?)", (version,))
        # Не вызываем commit здесь, так как initialize_database управляет транзакцией


    async def initialize_database(self) -> None:
        """
        Применяет все необходимые миграции для обновления схемы БД до последней версии.
        """
        print("SqliteAdapter: Initializing database schema...")
        if not self._conn:
            raise ConnectionError("Database connection is not established.")

        try:
            # Используем асинхронный context manager для курсора.
            # ВЕСЬ КОД СОЗДАНИЯ ТАБЛИЦ И МИГРАЦИИ ДОЛЖЕН БЫТЬ ВНУТРИ ЭТОГО БЛОКА 'async with cursor:'
            async with self._conn.cursor() as cursor:
                # Получаем текущую версию схемы БД, передавая курсор
                current_version = await self.get_current_schema_version(cursor)
                print(f"SqliteAdapter: Current database schema version: {current_version}")

                # Применяем миграции последовательно
                # Миграции v0->v1, v1->v2 и т.д.
                for version in range(current_version + 1, self.LATEST_SCHEMA_VERSION + 1):
                    print(f"SqliteAdapter: Migrating to version {version}...")
                    # Название метода миграции: _migrate_v<старая>_to_v<новая>
                    migrate_method_name = f'_migrate_v{version-1}_to_v{version}'
                    migrate_method = getattr(self, migrate_method_name, None)
                    if migrate_method:
                        # Вызываем метод миграции, передавая курсор
                        await migrate_method(cursor)
                        # Обновляем версию схемы в БД, передавая курсор
                        await self.set_schema_version(cursor, version)
                        print(f"SqliteAdapter: Successfully migrated to version {version}.")
                    else:
                        # Это критическая ошибка: версия в LATEST_SCHEMA_VERSION есть, но нет метода миграции
                        print(f"SqliteAdapter: ❌ No migration method found: {migrate_method_name}.")
                        raise NotImplementedError(f"Migration method {migrate_method_name} not implemented.")

                if current_version == self.LATEST_SCHEMA_VERSION:
                    print("SqliteAdapter: Database schema is up to date.")
                else:
                     print(f"SqliteAdapter: Database schema initialization/migration finished. Final version: {self.LATEST_SCHEMA_VERSION}")


            # Коммит всей транзакции миграции после успешного выполнения всех шагов
            # Этот коммит важен, чтобы все изменения были сохранены.
            # Поскольку execute методы авто-коммитят, этот коммит может быть избыточен,
            # но явный коммит в конце init_database при успехе не повредит.
            # Удалим его, чтобы избежать потенциальных проблем, полагаясь на авто-коммит set_schema_version.
            # await self.commit() # Удалено

        except Exception as e:
            print(f"SqliteAdapter: ❌ CRITICAL ERROR during database schema initialization or migration: {e}")
            traceback.print_exc()
            # Откатываем при ошибке инициализации/миграции
            try:
                if self._conn:
                    # Используем явный откат, так как execute методы коммитят по отдельности.
                    # Если миграция состоит из нескольких шагов, и один упал после коммита предыдущего,
                    # полный откат невозможен. Это ограничение простой системы.
                    # await self.rollback() # Удалено
                    # Лучше просто сообщить об ошибке и оставить базу в промежуточном состоянии.
                    pass # Просто логируем и перебрасываем исключение

            except Exception as rb_e:
                print(f"SqliteAdapter: Error during rollback after schema init/migration error: {rb_e}")
            raise # Перебрасываем исключение

    # --- Методы миграции схемы ---
    # Каждый метод _migrate_vX_to_vY должен принимать курсор и содержать SQL команды для перехода от версии X к версии Y.

    async def _migrate_v0_to_v1(self, cursor: Cursor) -> None:
        """Миграция с Версии 0 (пустая БД) на Версию 1 (начальная схема)."""
        print("SqliteAdapter: Running v0 to v1 migration (creating initial tables)...")

        # Здесь должны быть ТОЛЬКО CREATE TABLE IF NOT EXISTS для ВСЕХ таблиц
        # НИКАКИХ ALTER TABLE здесь быть не должно

        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS characters (
                id TEXT PRIMARY KEY,
                discord_user_id INTEGER UNIQUE NULL,
                name TEXT NOT NULL UNIQUE,
                location_id TEXT NULL,
                stats TEXT DEFAULT '{}', -- JSON
                inventory TEXT DEFAULT '[]', -- JSON
                current_action TEXT NULL, -- JSON
                action_queue TEXT DEFAULT '[]', -- JSON
                party_id TEXT NULL, -- Связь с таблицей parties (ID TEXT)
                state_variables TEXT DEFAULT '{}', -- JSON
                health REAL DEFAULT 100.0,
                max_health REAL DEFAULT 100.0,
                is_alive INTEGER DEFAULT 1, -- 0 or 1
                status_effects TEXT DEFAULT '[]' -- JSON
            );
        ''')

        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                template_id TEXT NOT NULL,
                name TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                channel_id INTEGER UNIQUE,
                current_stage_id TEXT NOT NULL,
                players TEXT DEFAULT '[]',
                state_variables TEXT DEFAULT '{}',
                stages_data TEXT DEFAULT '{}',
                end_message_template TEXT NULL
            );
        ''')

        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS npcs (
                id TEXT PRIMARY KEY,
                template_id TEXT,
                name TEXT NOT NULL UNIQUE,
                description TEXT NULL,
                location_id TEXT NULL,
                owner_id TEXT NULL,
                stats TEXT DEFAULT '{}',
                inventory TEXT DEFAULT '[]',
                current_action TEXT NULL,
                action_queue TEXT DEFAULT '[]',
                party_id TEXT NULL,
                state_variables TEXT DEFAULT '{}',
                health REAL DEFAULT 100.0,
                max_health REAL DEFAULT 100.0,
                is_alive INTEGER DEFAULT 1,
                status_effects TEXT DEFAULT '[]',
                is_temporary INTEGER DEFAULT 0
            );
        ''')

        await cursor.execute('''
             CREATE TABLE IF NOT EXISTS locations (
                 id TEXT PRIMARY KEY,
                 name TEXT NOT NULL UNIQUE,
                 description TEXT NULL,
                 exits TEXT DEFAULT '{}', -- JSON: {"direction": "location_id"}
                 state_variables TEXT DEFAULT '{}' -- JSON
             );
        ''')

        await cursor.execute('''
             CREATE TABLE IF NOT EXISTS item_templates (
                 id TEXT PRIMARY KEY,
                 name TEXT NOT NULL UNIQUE,
                 description TEXT NULL,
                 type TEXT NULL,
                 properties TEXT DEFAULT '{}'
             );
        ''')

        await cursor.execute('''
              CREATE TABLE IF NOT EXISTS items (
                 id TEXT PRIMARY KEY,
                 template_id TEXT NOT NULL,
                 owner_id TEXT NULL,
                 owner_type TEXT NULL,
                 quantity INTEGER DEFAULT 1,
                 state_variables TEXT DEFAULT '{}',
                 name TEXT NULL, -- Added name based on past logs
                 location_id TEXT NULL, -- Added location_id based on past logs
                 is_temporary INTEGER DEFAULT 0 -- Added is_temporary based on past logs
              );
        ''')
        # NOTE: Если в будущей миграции вы добавите колонку в items (например, 'durability'),
        # соответствующий ALTER TABLE должен быть в _migrate_v1_to_v2.

        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS combats (
                id TEXT PRIMARY KEY,
                is_active INTEGER DEFAULT 1,
                channel_id INTEGER NULL,
                event_id TEXT NULL,
                current_round INTEGER DEFAULT 0,
                time_in_current_phase REAL DEFAULT 0.0,
                participants TEXT DEFAULT '{}',
                state_variables TEXT DEFAULT '{}'
            );
        ''')

        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS statuses (
                id TEXT PRIMARY KEY,
                status_type TEXT NOT NULL,
                target_id TEXT NOT NULL,
                target_type TEXT NOT NULL,
                duration REAL NULL,
                applied_at REAL NOT NULL,
                source_id TEXT NULL,
                state_variables TEXT DEFAULT '{}'
            );
        ''')

        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS global_state (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        ''')

        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS timers (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                ends_at REAL NOT NULL,
                callback_data TEXT NULL,
                is_active INTEGER DEFAULT 1
            );
        ''')

        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS crafting_queues (
                character_id TEXT PRIMARY KEY, -- ID персонажа как PRIMARY KEY
                queue TEXT DEFAULT '[]', -- JSON список задач крафтинга
                state_variables TEXT DEFAULT '{}' -- JSON
            );
        ''')
        # NOTE: Если структура crafting_queues изменится, ALTER TABLE пойдет в _migrate_v1_to_v2.

        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS market_inventories (
                location_id TEXT PRIMARY KEY,
                inventory TEXT DEFAULT '{}',
                state_variables TEXT DEFAULT '{}'
            );
        ''')

        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS parties (
                id TEXT PRIMARY KEY,
                name TEXT NULL,
                leader_id TEXT NULL,
                member_ids TEXT DEFAULT '[]',
                state_variables TEXT DEFAULT '{}',
                current_action TEXT NULL
            );
        ''')

        # ВСЕ CREATE TABLE IF NOT EXISTS ДОЛЖНЫ БЫТЬ ВЫШЕ И ВНУТРИ ЭТОГО МЕТОДА МИГРАЦИИ

        print("SqliteAdapter: v0 to v1 migration complete.")

    # Для будущих миграций:
    # async def _migrate_v1_to_v2(self, cursor: Cursor) -> None:
    #    """Миграция с Версии 1 на Версию 2."""
    #    print("SqliteAdapter: Running v1 to v2 migration...")
    #    # Пример: добавить новую колонку в таблицу characters
    #    try:
    #        await cursor.execute("ALTER TABLE characters ADD COLUMN new_skill_slot INTEGER DEFAULT 0")
    #        print("SqliteAdapter: Added 'new_skill_slot' to characters table.")
    #    except sqlite3.OperationalError:
    #        pass # Колонка уже существует
    #    # Пример: изменить структуру таблицы
    #    # Это сложнее и часто требует создания новой таблицы, копирования данных, удаления старой, переименования новой.
    #    # Пример: добавить новую таблицу
    #    # await cursor.execute("CREATE TABLE new_table (...)")
    #    print("SqliteAdapter: v1 to v2 migration complete.")


# --- Конец класса SqliteAdapter ---
