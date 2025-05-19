# bot/database/sqlite_adapter.py
print(f"DEBUG: Loading sqlite_adapter.py from: {__file__}")
import sqlite3
import traceback
from typing import Optional, List, Tuple, Any, Union

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
    LATEST_SCHEMA_VERSION = 1

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

    async def execute_insert(self, sql: str, params: Optional[Union[Tuple, List]] = None) -> int:
        """
        Выполняет INSERT запрос и возвращает rowid последней вставленной строки.
        Предполагает, что таблица использует INTEGER PRIMARY KEY AUTOINCREMENT.
        Автоматически коммитит при успехе, откатывает при ошибке.
        """
        if not self._conn:
            raise ConnectionError("Database connection is not established.")
        try:
            cursor = await self._conn.execute(sql, params or ())
            last_id = cursor.lastrowid
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
             return # Ничего не делаем, если данных нет

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
            return rows
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

    async def get_current_schema_version(self, cursor: Cursor) -> int:
        """Получает текущую версию схемы из БД, используя предоставленный курсор."""
        await cursor.execute("CREATE TABLE IF NOT EXISTS schema_versions (version INTEGER PRIMARY KEY);")
        await cursor.execute("SELECT version FROM schema_versions")
        row = await cursor.fetchone()
        return row['version'] if row else 0

    async def set_schema_version(self, cursor: Cursor, version: int) -> None:
        """Устанавливает текущую версию схемы в БД, используя предоставленный курсор."""
        await cursor.execute("INSERT OR REPLACE INTO schema_versions (version) VALUES (?)", (version,))

    # --- Метод инициализации базы данных (восстановлен) ---
    async def initialize_database(self) -> None:
        """
        Применяет все необходимые миграции для обновления схемы БД до последней версии.
        """
        print("SqliteAdapter: Initializing database schema...")
        if not self._conn:
            raise ConnectionError("Database connection is not established.")

        try:
            async with self._conn.cursor() as cursor:
                current_version = await self.get_current_schema_version(cursor)
                print(f"SqliteAdapter: Current database schema version: {current_version}")

                for version in range(current_version + 1, self.LATEST_SCHEMA_VERSION + 1):
                    print(f"SqliteAdapter: Running migration to version {version}...")
                    migrate_method_name = f'_migrate_v{version-1}_to_v{version}'
                    migrate_method = getattr(self, migrate_method_name, None)
                    if migrate_method:
                        await migrate_method(cursor)
                        await self.set_schema_version(cursor, version)
                        print(f"SqliteAdapter: Successfully migrated to version {version}.")
                    else:
                        print(f"SqliteAdapter: ❌ No migration method found: {migrate_method_name}.")
                        raise NotImplementedError(f"Migration method {migrate_method_name} not implemented.")

                if current_version == self.LATEST_SCHEMA_VERSION:
                    print("SqliteAdapter: Database schema is up to date.")
                else:
                     print(f"SqliteAdapter: Database schema initialization/migration finished. Final version: {self.LATEST_SCHEMA_VERSION}")

            # Коммит ВСЕЙ транзакции миграции после успешного выполнения всех шагов
            await self._conn.commit()

        except Exception as e:
            print(f"SqliteAdapter: ❌ CRITICAL ERROR during database schema initialization or migration: {e}")
            traceback.print_exc()
            try:
                if self._conn:
                    await self._conn.rollback()
                    print("SqliteAdapter: Transaction rolled back due to migration error.")
            except Exception as rb_e:
                print(f"SqliteAdapter: Error during rollback after schema init/migration error: {rb_e}")
            raise # Перебрасываем исключение

    # --- Методы миграции схемы ---
    async def _migrate_v0_to_v1(self, cursor: Cursor) -> None:
        """Миграция с Версии 0 (пустая БД) на Версию 1 (начальная схема)."""
        print("SqliteAdapter: Running v0 to v1 migration (creating initial tables)...")

        # Здесь должны быть ТОЛЬКО CREATE TABLE IF NOT EXISTS для ВСЕХ таблиц
        # НИКАКИХ ALTER TABLE здесь быть не должно

        sql_characters = '''
            CREATE TABLE IF NOT EXISTS characters (
                id TEXT PRIMARY KEY,
                discord_user_id INTEGER NULL,
                name TEXT NOT NULL,
                guild_id TEXT NOT NULL, -- <-- ДОБАВЛЕНА КОЛОНКА GUILD_ID
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
                status_effects TEXT DEFAULT '[]', -- JSON
                -- ИСПРАВЛЕНИЕ: Изменены UNIQUE ограничения для уникальности per-guild
                UNIQUE(discord_user_id, guild_id),
                UNIQUE(name, guild_id)
            );
        '''
        print(f"DEBUG: Executing CREATE TABLE characters SQL:\n---\n{sql_characters}\n---")
        await cursor.execute(sql_characters)


        sql_events = '''
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                template_id TEXT NOT NULL,
                name TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                channel_id INTEGER UNIQUE, -- NOTE: channel_id UNIQUE может быть проблемой, если несколько событий могут быть активны, но в разных каналах. Лучше UNIQUE(channel_id, is_active) или убрать UNIQUE.
                guild_id TEXT NOT NULL, -- <-- ДОБАВЛЕНА КОЛОНКА GUILD_ID для событий
                current_stage_id TEXT NOT NULL,
                players TEXT DEFAULT '[]', -- JSON список player_id, участвующих в событии
                state_variables TEXT DEFAULT '{}', -- JSON
                stages_data TEXT DEFAULT '{}', -- JSON определение стадий события
                end_message_template TEXT NULL
            );
        '''
        print(f"DEBUG: Executing CREATE TABLE events SQL:\n---\n{sql_events}\n---")
        await cursor.execute(sql_events)

        sql_npcs = '''
            CREATE TABLE IF NOT EXISTS npcs (
                id TEXT PRIMARY KEY,
                template_id TEXT,
                name TEXT NOT NULL, -- Имя NPC не обязательно уникально
                guild_id TEXT NOT NULL, -- <-- ДОБАВЛЕНА КОЛОНКА GUILD_ID для NPC
                description TEXT NULL,
                location_id TEXT NULL,
                owner_id TEXT NULL, -- ID владельца (например, игрока или другой сущности)
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
                is_temporary INTEGER DEFAULT 0,
                UNIQUE(name, guild_id) -- <-- ДОБАВЛЕНО UNIQUE(name, guild_id) ЕСЛИ NPC ДОЛЖНЫ БЫТЬ УНИКАЛЬНЫ ПО ИМЕНИ В ГИЛЬДИИ
                                      -- Если имя NPC не должно быть уникальным per-guild, удалите эту строку
            );
        '''
        print(f"DEBUG: Executing CREATE TABLE npcs SQL:\n---\n{sql_npcs}\n---")
        await cursor.execute(sql_npcs)

        sql_locations = '''
             CREATE TABLE IF NOT EXISTS locations (
                 id TEXT PRIMARY KEY,
                 name TEXT NOT NULL, -- Имя локации не обязательно уникально
                 guild_id TEXT NOT NULL, -- <-- ДОБАВЛЕНА КОЛОНКА GUILD_ID для локаций
                 description TEXT NULL,
                 exits TEXT DEFAULT '{}', -- JSON: {"direction": "location_id"}
                 state_variables TEXT DEFAULT '{}', -- JSON
                 UNIQUE(name, guild_id) -- <-- ДОБАВЛЕНО UNIQUE(name, guild_id)
             );
        '''
        print(f"DEBUG: Executing CREATE TABLE locations SQL:\n---\n{sql_locations}\n---")
        await cursor.execute(sql_locations)

        sql_item_templates = '''
             CREATE TABLE IF NOT EXISTS item_templates (
                 id TEXT PRIMARY KEY, -- Global ID
                 name TEXT NOT NULL UNIQUE, -- Global unique name
                 description TEXT NULL,
                 type TEXT NULL,
                 properties TEXT DEFAULT '{}' -- JSON
             );
        '''
        print(f"DEBUG: Executing CREATE TABLE item_templates SQL:\n---\n{sql_item_templates}\n---")
        await cursor.execute(sql_item_templates)


        sql_items = '''
              CREATE TABLE IF NOT EXISTS items (
                 id TEXT PRIMARY KEY, -- Unique ID for this item instance
                 template_id TEXT NOT NULL, -- Links to item_templates.id
                 guild_id TEXT NOT NULL, -- <-- ДОБАВЛЕНА КОЛОНКА GUILD_ID для предметов (принадлежат гильдии или владельцу внутри гильдии)
                 owner_id TEXT NULL, -- ID владельца (персонажа, NPC, локации)
                 owner_type TEXT NULL, -- Тип владельца ('character', 'npc', 'location')
                 location_id TEXT NULL, -- ID локации, если item лежит на земле (redundant if owner_type='location'?)
                 quantity INTEGER DEFAULT 1,
                 state_variables TEXT DEFAULT '{}', -- JSON instance-specific variables
                 name TEXT NULL, -- Added name based on past logs (redundant if using template name?)
                 is_temporary INTEGER DEFAULT 0 -- Added is_temporary based on past logs
                 -- NOTE: Если item.owner_type = 'location', то owner_id - это location_id.
                 -- Чтобы найти все предметы в локации, можно искать WHERE owner_type = 'location' AND owner_id = ?
                 -- Или использовать location_id колонку для предметов на земле: WHERE location_id = ? AND owner_id IS NULL (or some other criteria)
              );
        '''
        print(f"DEBUG: Executing CREATE TABLE items SQL:\n---\n{sql_items}\n---")
        await cursor.execute(sql_items)


        sql_combats = '''
            CREATE TABLE IF NOT EXISTS combats (
                id TEXT PRIMARY KEY,
                guild_id TEXT NOT NULL, -- <-- ДОБАВЛЕНА КОЛОНКА GUILD_ID для боев
                is_active INTEGER DEFAULT 1,
                channel_id INTEGER NULL, -- Канал, где идет бой
                event_id TEXT NULL, -- Связь с событием, если бой начался из события
                current_round INTEGER DEFAULT 0,
                time_in_current_phase REAL DEFAULT 0.0,
                participants TEXT DEFAULT '{}', -- JSON {entity_id: {role: 'player'/'npc', team: 'A'/'B'}}
                state_variables TEXT DEFAULT '{}' -- JSON
            );
        '''
        print(f"DEBUG: Executing CREATE TABLE combats SQL:\n---\n{sql_combats}\n---")
        await cursor.execute(sql_combats)


        sql_statuses = '''
            CREATE TABLE IF NOT EXISTS statuses (
                id TEXT PRIMARY KEY, -- Unique ID for this status effect instance
                status_type TEXT NOT NULL, -- Type of status effect (e.g., 'poison', 'stun')
                target_id TEXT NOT NULL, -- ID сущности, на которую наложен эффект
                target_type TEXT NOT NULL, -- Тип сущности ('character', 'npc', 'party')
                guild_id TEXT NOT NULL, -- <-- ДОБАВЛЕНА КОЛОНКА GUILD_ID для статусов
                duration REAL NULL, -- Длительность в игровых секундах (NULL для постоянных)
                applied_at REAL NOT NULL, -- Игровое время, когда наложен эффект
                source_id TEXT NULL, -- ID источника эффекта (напр., персонажа, предмета)
                state_variables TEXT DEFAULT '{}' -- JSON instance-specific variables
            );
        '''
        print(f"DEBUG: Executing CREATE TABLE statuses SQL:\n---\n{sql_statuses}\n---")
        await cursor.execute(sql_statuses)

        # global_state остается глобальным
        sql_global_state = '''
            CREATE TABLE IF NOT EXISTS global_state (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        '''
        print(f"DEBUG: Executing CREATE TABLE global_state SQL:\n---\n{sql_global_state}\n---")
        await cursor.execute(sql_global_state)

        # Timers могут быть глобальными или пер-гильдийными.
        sql_timers = '''
            CREATE TABLE IF NOT EXISTS timers (
                id TEXT PRIMARY KEY, -- Unique timer ID
                guild_id TEXT NULL, -- <-- ДОБАВЛЕНА КОЛОНКА GUILD_ID для таймеров (NULL, если глобальный)
                type TEXT NOT NULL, -- Тип таймера (напр., 'world_tick', 'status_duration', 'event_phase')
                ends_at REAL NOT NULL, -- Игровое время, когда таймер истекает
                callback_data TEXT NULL, -- JSON данные, передаваемые в колбэк
                is_active INTEGER DEFAULT 1,
                target_id TEXT NULL, -- ID сущности, связанной с таймером (опционально)
                target_type TEXT NULL -- Тип сущности (опционально)
            );
        '''
        print(f"DEBUG: Executing CREATE TABLE timers SQL:\n---\n{sql_timers}\n---")
        await cursor.execute(sql_timers)

        # crafting_queues привязаны к персонажу, у которого есть guild_id
        sql_crafting_queues = '''
            CREATE TABLE IF NOT EXISTS crafting_queues (
                character_id TEXT PRIMARY KEY, -- ID персонажа как PRIMARY KEY
                guild_id TEXT NOT NULL, -- <-- ДОБАВЛЕНА КОЛОНКА GUILD_ID
                queue TEXT DEFAULT '[]', -- JSON список задач крафтинга
                state_variables TEXT DEFAULT '{}' -- JSON
            );
        '''
        print(f"DEBUG: Executing CREATE TABLE crafting_queues SQL:\n---\n{sql_crafting_queues}\n---")
        await cursor.execute(sql_crafting_queues)


        # market_inventories привязаны к локации, у которой есть guild_id
        sql_market_inventories = '''
            CREATE TABLE IF NOT EXISTS market_inventories (
                location_id TEXT PRIMARY KEY, -- ID локации как PRIMARY KEY
                guild_id TEXT NOT NULL, -- <-- ДОБАВЛЕНА КОЛОНКА GUILD_ID
                inventory TEXT DEFAULT '{}', -- JSON {item_id: {quantity: ..., price: ...}}
                state_variables TEXT DEFAULT '{}' -- JSON
            );
        '''
        print(f"DEBUG: Executing CREATE TABLE market_inventories SQL:\n---\n{sql_market_inventories}\n---")
        await cursor.execute(sql_market_inventories)


        # Parties принадлежат гильдии
        sql_parties = '''
            CREATE TABLE IF NOT EXISTS parties (
                id TEXT PRIMARY KEY, -- Unique Party ID (likely global UUID)
                guild_id TEXT NOT NULL, -- <-- ДОБАВЛЕНА КОЛОНКА GUILD_ID
                name TEXT NULL, -- Имя партии не обязательно уникально
                leader_id TEXT NULL, -- ID лидера (character/npc)
                member_ids TEXT DEFAULT '[]', -- JSON список ID участников
                state_variables TEXT DEFAULT '{}', -- JSON
                current_action TEXT NULL -- JSON
                -- NOTE: Можно добавить UNIQUE(name, guild_id) если имена партий должны быть уникальны per-guild.
            );
        '''
        print(f"DEBUG: Executing CREATE TABLE parties SQL:\n---\n{sql_parties}\n---")
        await cursor.execute(sql_parties)

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
    #        pass # Колонка уже существует (если миграция запускалась повторно)
    #    # Пример: добавить новую таблицу
    #    # await cursor.execute("CREATE TABLE new_table (...)")
    #    print("SqliteAdapter: v1 to v2 migration complete.")

# --- Конец класса SqliteAdapter ---