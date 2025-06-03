# bot/database/sqlite_adapter.py
print(f"DEBUG: Loading sqlite_adapter.py from: {__file__}")
import sqlite3 # Keep for sqlite3.OperationalError
import traceback
import json # Needed for json.loads/dumps
from typing import Optional, List, Tuple, Any, Union, Dict # Add Dict

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
    LATEST_SCHEMA_VERSION = 14 # Add current_location_id to parties table

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn: Optional[Connection] = None
        print(f"SqliteAdapter initialized for database: {self._db_path}")

    async def connect(self) -> None:
        """Устанавливает соединение с базой данных."""
        if self._conn is None:
            print("SqliteAdapter: Connecting to database...")
            try:
                # IMPORTANT: Use check_same_thread=False for aiosqlite in a multi-threaded/async environment
                self._conn = await aiosqlite.connect(self._db_path, check_same_thread=False)
                self._conn.row_factory = aiosqlite.Row
                await self._conn.execute('PRAGMA journal_mode=WAL') # Recommended for concurrency
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
            raise # Перебрасываем исключение, чтобы вызывающий код знал об ошибке

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
            raise # Перебрасываем исключение, чтобы вызывающий код знал об ошибке


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
        # Используем PRAGMA user_version для версионирования схемы
        await cursor.execute("PRAGMA user_version;")
        row = await cursor.fetchone()
        version = row[0] if row else 0
        # print(f"SqliteAdapter: PRAGMA user_version reports {version}") # Debug
        return version

    async def set_schema_version(self, cursor: Cursor, version: int) -> None:
        """Устанавливает текущую версию схемы в БД, используя предоставленный курсор."""
        # Используем PRAGMA user_version для версионирования схемы
        await cursor.execute(f"PRAGMA user_version = {version};")
        # print(f"SqliteAdapter: Set PRAGMA user_version to {version}") # Debug


    # --- Метод инициализации базы данных ---
    async def initialize_database(self) -> None:
        """
        Применяет все необходимые миграции для обновления схемы БД до последней версии.
        """
        print("SqliteAdapter: Initializing database schema...")
        if not self._conn:
            raise ConnectionError("Database connection is not established.")

        try:
            # Миграции должны выполняться в одной транзакции
            async with self._conn.cursor() as cursor:
                current_version = await self.get_current_schema_version(cursor)
                print(f"SqliteAdapter: Current database schema version: {current_version}")

                if current_version < self.LATEST_SCHEMA_VERSION:
                     print(f"SqliteAdapter: Migrating from version {current_version} to {self.LATEST_SCHEMA_VERSION}...")
                     for version in range(current_version + 1, self.LATEST_SCHEMA_VERSION + 1):
                         print(f"SqliteAdapter: Running migration to version {version}...")
                         migrate_method_name = f'_migrate_v{version-1}_to_v{version}'
                         migrate_method = getattr(self, migrate_method_name, None)
                         if migrate_method:
                             # Pass the cursor to the migration method
                             await migrate_method(cursor)
                             # Set the new schema version after successful migration steps
                             await self.set_schema_version(cursor, version)
                             print(f"SqliteAdapter: Successfully migrated to version {version}.")
                         else:
                             print(f"SqliteAdapter: ❌ No migration method found: {migrate_method_name}.")
                             raise NotImplementedError(f"Migration method {migrate_method_name} not implemented.")
                else:
                    print("SqliteAdapter: Database schema is up to date.")

            # Commit the entire migration transaction after successful execution of all steps
            await self._conn.commit()
            print("SqliteAdapter: Database schema initialization/migration finished.")

        except Exception as e:
            print(f"SqliteAdapter: ❌ CRITICAL ERROR during database schema initialization or migration: {e}")
            traceback.print_exc()
            try:
                if self._conn:
                    # Rollback the transaction in case of any error during migration
                    await self._conn.rollback()
                    print("SqliteAdapter: Transaction rolled back due to migration error.")
            except Exception as rb_e:
                print(f"SqliteAdapter: Error during rollback after schema init/migration error: {rb_e}")
            # Re-raise the exception so GameManager knows setup failed
            raise


    # --- Методы миграции схемы ---
    # Этот метод должен содержать ВСЕ CREATE TABLE IF NOT EXISTS statements
    async def _migrate_v0_to_v1(self, cursor: Cursor) -> None:
        """Миграция с Версии 0 (пустая БД) на Версию 1 (начальная схема)."""
        print("SqliteAdapter: Running v0 to v1 migration (creating initial tables)...")

        # Убедитесь, что здесь перечислены ВСЕ таблицы со ВСЕМИ необходимыми колонками
        # Character Table
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS characters (
                id TEXT PRIMARY KEY,
                discord_user_id INTEGER NULL,
                name TEXT NOT NULL,
                guild_id TEXT NOT NULL,
                location_id TEXT NULL,
                stats TEXT DEFAULT '{}', -- JSON
                inventory TEXT DEFAULT '[]', -- JSON [{item_id: ..., quantity: ...}, ...]
                current_action TEXT NULL, -- JSON {type: ..., details: {...}}
                action_queue TEXT DEFAULT '[]', -- JSON [{type: ..., details: {...}}, ...]
                party_id TEXT NULL, -- ID партии
                state_variables TEXT DEFAULT '{}', -- JSON
                health REAL DEFAULT 100.0,
                max_health REAL DEFAULT 100.0,
                is_alive INTEGER DEFAULT 1, -- 0 or 1
                status_effects TEXT DEFAULT '[]', -- JSON [{status_type: ..., duration: ..., applied_at: ..., state_variables: {...}}, ...]
                level INTEGER DEFAULT 1,
                experience INTEGER DEFAULT 0,
                active_quests TEXT DEFAULT '[]', -- JSON list of quest IDs
                created_at REAL NOT NULL DEFAULT (strftime('%s','now')), -- Unix timestamp as REAL
                last_played_at REAL NULL, -- <-- Конец колонок. Далее ограничения.
                -- UNIQUE ограничения в пределах гильдии
                UNIQUE(discord_user_id, guild_id),
                UNIQUE(name, guild_id) -- <--- Последнее ограничение. БЕЗ ЗАПЯТОЙ перед ');'
            );
        ''')
        # Add new columns to characters if they don't exist (for existing databases)
        # These will only succeed if the columns don't already exist.
        try:
            await cursor.execute("ALTER TABLE characters ADD COLUMN level INTEGER DEFAULT 1;")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" not in str(e): raise
        try:
            await cursor.execute("ALTER TABLE characters ADD COLUMN experience INTEGER DEFAULT 0;")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" not in str(e): raise
        try:
            await cursor.execute("ALTER TABLE characters ADD COLUMN active_quests TEXT DEFAULT '[]';")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" not in str(e): raise

        # Event Table
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                template_id TEXT NOT NULL,
                name TEXT NOT NULL,
                is_active INTEGER DEFAULT 1, -- 0 or 1
                channel_id INTEGER NULL,
                guild_id TEXT NOT NULL,
                current_stage_id TEXT NOT NULL,
                players TEXT DEFAULT '[]', -- JSON список entity_id, участвующих в событии
                state_variables TEXT DEFAULT '{}', -- JSON
                stages_data TEXT DEFAULT '{}', -- JSON
                end_message_template TEXT NULL,
                started_at REAL NOT NULL DEFAULT (strftime('%s','now')), -- <-- Конец колонок
                UNIQUE(channel_id, guild_id) -- <--- Последнее ограничение. БЕЗ ЗАПЯТОЙ перед ');'
            );
        ''')


        # NPC Table
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS npcs (
                id TEXT PRIMARY KEY,
                template_id TEXT,
                name TEXT NOT NULL,
                guild_id TEXT NOT NULL,
                description TEXT NULL,
                location_id TEXT NULL,
                owner_id TEXT NULL,
                owner_type TEXT NULL,
                stats TEXT DEFAULT '{}', -- JSON
                inventory TEXT DEFAULT '[]', -- JSON
                current_action TEXT NULL, -- JSON
                action_queue TEXT DEFAULT '[]', -- JSON
                party_id TEXT NULL,
                state_variables TEXT DEFAULT '{}', -- JSON
                health REAL DEFAULT 100.0,
                max_health REAL DEFAULT 100.0,
                is_alive INTEGER DEFAULT 1, -- 0 or 1
                status_effects TEXT DEFAULT '[]', -- JSON
                is_temporary INTEGER DEFAULT 0,
                archetype TEXT DEFAULT 'commoner',
                traits TEXT DEFAULT '[]', -- JSON list of strings
                desires TEXT DEFAULT '[]', -- JSON list of strings
                motives TEXT DEFAULT '[]', -- JSON list of strings
                backstory TEXT DEFAULT '' -- <--- Конец колонок (если UNIQUE закомментировано). БЕЗ ЗАПЯТОЙ
                -- UNIQUE(name, guild_id) -- Optional, depends on game rules -- <-- Если раскомментировано, должна быть запятая после backstory
            );
        ''')
        # Add new columns to npcs if they don't exist (for existing databases)
        try:
            await cursor.execute("ALTER TABLE npcs ADD COLUMN archetype TEXT DEFAULT 'commoner';")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" not in str(e): raise
        try:
            await cursor.execute("ALTER TABLE npcs ADD COLUMN traits TEXT DEFAULT '[]';")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" not in str(e): raise
        try:
            await cursor.execute("ALTER TABLE npcs ADD COLUMN desires TEXT DEFAULT '[]';")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" not in str(e): raise
        try:
            await cursor.execute("ALTER TABLE npcs ADD COLUMN motives TEXT DEFAULT '[]';")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" not in str(e): raise
        try:
            await cursor.execute("ALTER TABLE npcs ADD COLUMN backstory TEXT DEFAULT '';")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" not in str(e): raise

        # Location Template Table (PER-GUILD - Modified to add guild_id)
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS location_templates (
                id TEXT NOT NULL, -- Template ID
                guild_id TEXT NOT NULL, -- <-- ДОБАВЛЕНА КОЛОНКА GUILD_ID
                name TEXT NOT NULL, -- Template name
                description TEXT NULL,
                properties TEXT DEFAULT '{}', -- JSON данные шаблона (включают initial_state, on_enter_triggers, exits и т.д.)
                -- Добавьте другие колонки шаблона здесь
                PRIMARY KEY (id, guild_id), -- <-- Первичный ключ по ID и Guild ID
                UNIQUE(name, guild_id) -- <-- Имя шаблона уникально в пределах гильдии
            );
        ''')

        # Location Instance Table
        await cursor.execute('''
             CREATE TABLE IF NOT EXISTS locations (
                 id TEXT PRIMARY KEY, -- Instance ID (UUID)
                 template_id TEXT NOT NULL, -- Link to location_templates.id (or name?)
                 name TEXT NOT NULL, -- Instance name (can be different from template name)
                 guild_id TEXT NOT NULL,
                 description TEXT NULL,
                 exits TEXT DEFAULT '{}', -- JSON: {"direction": "location_id"}
                 state_variables TEXT DEFAULT '{}', -- <-- Проверьте запятую после этой строки
                 is_active INTEGER DEFAULT 1 -- <-- ДОБАВЛЕНА КОЛОНКА is_active. БЕЗ ЗАПЯТОЙ, если это последняя колонка.
                 -- UNIQUE(name, guild_id) -- Constraint - for instance names <-- Если это есть, то is_active ДОЛЖНА БЫТЬ С ЗАПЯТОЙ перед этим.
             );
        ''')

        # Item Templates Table (global)
        await cursor.execute('''
             CREATE TABLE IF NOT EXISTS item_templates (
                 id TEXT PRIMARY KEY, -- Global ID
                 name TEXT NOT NULL UNIQUE, -- Global unique name
                 description TEXT NULL,
                 type TEXT NULL, -- e.g., 'consumable', 'equipment', 'material'
                 properties TEXT DEFAULT '{}' -- <--- Последняя колонка. БЕЗ ЗАПЯТОЙ
             );
        ''')


        # Item Instances Table
        await cursor.execute('''
              CREATE TABLE IF NOT EXISTS items (
                 id TEXT PRIMARY KEY, -- Unique ID for this item instance (UUID)
                 template_id TEXT NOT NULL, -- Links to item_templates.id
                 guild_id TEXT NOT NULL, -- Items belong to a guild's context
                 owner_id TEXT NULL, -- ID владельца (персонажа, NPC, локации, партии)
                 owner_type TEXT NULL, -- Тип владельца ('character', 'npc', 'location', 'party')
                 location_id TEXT NULL, -- Optional location ID if on the ground
                 quantity REAL DEFAULT 1.0, -- Stored as REAL
                 state_variables TEXT DEFAULT '{}', -- JSON instance-specific variables
                 is_temporary INTEGER DEFAULT 0 -- <--- Последняя колонка. БЕЗ ЗАПЯТОЙ
                 -- Indices could improve performance
                 -- CREATE INDEX IF NOT EXISTS idx_items_owner ON items (owner_type, owner_id);
                 -- CREATE INDEX IF NOT EXISTS idx_items_location ON items (location_id); -- If location_id is used for ground items
                 -- CREATE INDEX IF NOT EXISTS idx_items_guild ON items (guild_id);
              );
        ''')


        # Combat Table
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS combats (
                id TEXT PRIMARY KEY, -- Unique Combat ID (UUID)
                guild_id TEXT NOT NULL,
                location_id TEXT NULL,
                is_active INTEGER DEFAULT 1, -- 0 or 1
                channel_id INTEGER NULL, -- Channel where combat happens
                event_id TEXT NULL, -- Link to event
                current_round INTEGER DEFAULT 0,
                round_timer REAL DEFAULT 0.0, -- Timer within the round
                participants TEXT DEFAULT '{}', -- JSON
                combat_log TEXT DEFAULT '[]', -- JSON log
                state_variables TEXT DEFAULT '{}' -- <--- Последняя колонка. БЕЗ ЗАПЯТОЙ
            );
        ''')


        # Status Effect Instances Table
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS statuses (
                id TEXT PRIMARY KEY, -- Unique ID for this status effect instance (UUID)
                status_type TEXT NOT NULL, -- Type of status effect
                target_id TEXT NOT NULL, -- ID сущности
                target_type TEXT NOT NULL, -- Тип сущности ('character', 'npc', 'party', 'location')
                guild_id TEXT NOT NULL, -- Status effects belong to a guild's context
                duration REAL NULL, -- Длительность в игровых секундах
                applied_at REAL NOT NULL, -- Игровое время, когда наложен эффект
                source_id TEXT NULL,
                state_variables TEXT DEFAULT '{}' -- <--- Последняя колонка. БЕЗ ЗАПЯТОЙ
                -- Index for quick lookup by target
                -- CREATE INDEX IF NOT EXISTS idx_statuses_target ON statuses (target_type, target_id);
                -- CREATE INDEX IF NOT EXISTS idx_statuses_guild ON statuses (guild_id);
            );
        ''')

        # Global State Table (for global data not tied to a guild)
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS global_state (
                key TEXT PRIMARY KEY,
                value TEXT -- <--- Последняя колонка. БЕЗ ЗАПЯТОЙ
            );
        ''')

        # Timers Table
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS timers (
                id TEXT PRIMARY KEY, -- Unique timer ID (UUID)
                guild_id TEXT NULL, -- NULL if global timer
                type TEXT NOT NULL, -- Тип таймера
                ends_at REAL NOT NULL,
                callback_data TEXT NULL,
                is_active INTEGER DEFAULT 1, -- 0 or 1
                target_id TEXT NULL, -- ID сущности
                target_type TEXT NULL -- <--- Последняя колонка. БЕЗ ЗАПЯТОЙ
                -- Index for quick lookup of active timers
                -- CREATE INDEX IF NOT EXISTS idx_timers_active ON timers (is_active, ends_at);
                -- CREATE INDEX IF NOT EXISTS idx_timers_guild ON timers (guild_id);
            );
        ''')

        # Crafting Queues Table (tied to an entity)
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS crafting_queues (
                entity_id TEXT NOT NULL, -- ID сущности (character/npc)
                entity_type TEXT NOT NULL, -- 'character' or 'npc'
                guild_id TEXT NOT NULL,
                queue TEXT DEFAULT '[]', -- JSON список задач крафтинга
                state_variables TEXT DEFAULT '{}', -- <--- Последняя колонка. БЕЗ ЗАПЯТОЙ
                PRIMARY KEY (entity_id, entity_type, guild_id) -- <--- Последнее ограничение. БЕЗ ЗАПЯТОЙ
            );
        ''')

        # Market Inventories Table (tied to an entity)
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS market_inventories (
                entity_id TEXT NOT NULL, -- ID сущности (location/npc/etc)
                entity_type TEXT NOT NULL, -- 'location', 'npc'
                guild_id TEXT NOT NULL,
                inventory TEXT DEFAULT '{}', -- JSON {item_template_id: quantity}
                state_variables TEXT DEFAULT '{}', -- <--- Проверьте здесь
                PRIMARY KEY (entity_id, entity_type, guild_id) -- <--- Последнее ограничение. БЕЗ ЗАПЯТОЙ
            );
        ''')


        # Parties Table
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS parties (
                id TEXT PRIMARY KEY, -- Unique Party ID (UUID)
                guild_id TEXT NOT NULL,
                name TEXT NULL,
                leader_id TEXT NULL,
                member_ids TEXT DEFAULT '[]', -- JSON список ID участников
                state_variables TEXT DEFAULT '{}', -- JSON
                current_action TEXT NULL,
                current_location_id TEXT NULL -- Added in v14
                -- UNIQUE(name, guild_id) -- Optional
            );
        ''')

        # Quests Table
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS quests (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                status TEXT DEFAULT 'available',
                influence_level TEXT DEFAULT 'local',
                prerequisites TEXT DEFAULT '[]', -- JSON list
                connections TEXT DEFAULT '{}', -- JSON dict
                stages TEXT DEFAULT '{}', -- JSON dict for stages data
                rewards TEXT DEFAULT '{}', -- JSON dict
                npc_involvement TEXT DEFAULT '{}', -- JSON dict
                guild_id TEXT NOT NULL,
                created_at REAL NOT NULL DEFAULT (strftime('%s','now')),
                updated_at REAL NOT NULL DEFAULT (strftime('%s','now'))
            );
        ''')

        # Relationships Table
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS relationships (
                id TEXT PRIMARY KEY,
                entity1_id TEXT NOT NULL,
                entity1_type TEXT NOT NULL,
                entity2_id TEXT NOT NULL,
                entity2_type TEXT NOT NULL,
                relationship_type TEXT DEFAULT 'neutral',
                strength REAL DEFAULT 0.0,
                details TEXT DEFAULT '',
                guild_id TEXT NOT NULL,
                updated_at REAL NOT NULL DEFAULT (strftime('%s','now')),
                UNIQUE(entity1_id, entity1_type, entity2_id, entity2_type, guild_id)
            );
        ''')

        # Game Log Entries Table
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS game_log_entries (
                id TEXT PRIMARY KEY,
                timestamp REAL NOT NULL,
                guild_id TEXT NOT NULL,
                entry_type TEXT NOT NULL,
                actor_id TEXT,
                actor_type TEXT,
                target_id TEXT,
                target_type TEXT,
                description TEXT NOT NULL,
                details TEXT DEFAULT '{}' -- JSON dict
            );
        ''')

        # Add more tables as needed (e.g., recipes, skills, dialogue_states)

        await cursor.execute('''DROP TABLE IF EXISTS dialogues;''') # Add this drop statement too
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS dialogues (
                id TEXT PRIMARY KEY,
                template_id TEXT,
                guild_id TEXT NOT NULL,
                participants TEXT DEFAULT '[]', -- JSON list of participant IDs
                channel_id INTEGER,
                current_stage_id TEXT,
                state_variables TEXT DEFAULT '{}', -- JSON
                conversation_history TEXT DEFAULT '[]', -- Added in v2, but good to have in base for new setups
                last_activity_game_time REAL,
                event_id TEXT,
                is_active INTEGER DEFAULT 1 -- 0 or 1
            );
        ''')

        print("SqliteAdapter: v0 to v1 migration complete.")

    async def _migrate_v1_to_v2(self, cursor: Cursor) -> None:
        """Миграция с Версии 1 на Версию 2."""
        print("SqliteAdapter: Running v1 to v2 migration (adding conversation_history to dialogues)...")
        try:
            await cursor.execute("ALTER TABLE dialogues ADD COLUMN conversation_history TEXT DEFAULT '[]'")
            print("SqliteAdapter: Added 'conversation_history' to dialogues table.")
        except sqlite3.OperationalError as e:
            # Check if the error is "duplicate column name"
            if 'duplicate column name' in str(e).lower():
                print("SqliteAdapter: Column 'conversation_history' already exists in dialogues table, skipping ALTER TABLE.")
            else:
                raise # Re-raise other operational errors
        print("SqliteAdapter: v1 to v2 migration complete.")

    async def _migrate_v2_to_v3(self, cursor: Cursor) -> None:
        """Миграция с Версии 2 на Версию 3 (добавление таблицы game_logs)."""
        print("SqliteAdapter: Running v2 to v3 migration (creating game_logs table)...")
        # Optional: DROP TABLE IF EXISTS game_logs; # For clean dev, remove for prod if data should be kept across schema changes
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS game_logs (
                log_id TEXT PRIMARY KEY,
                timestamp REAL NOT NULL,
                guild_id TEXT NOT NULL,
                channel_id INTEGER,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                related_entities TEXT, -- JSON
                context_data TEXT -- JSON for extra kwargs
            );
        ''')
        await cursor.execute('''CREATE INDEX IF NOT EXISTS idx_game_logs_guild_ts ON game_logs (guild_id, timestamp DESC);''')
        await cursor.execute('''CREATE INDEX IF NOT EXISTS idx_game_logs_event_type ON game_logs (guild_id, event_type);''')
        print("SqliteAdapter: game_logs table created and indexes applied.")
        print("SqliteAdapter: v2 to v3 migration complete.")

    # Для будущих миграций:
    # async def _migrate_v3_to_v4(self, cursor: Cursor) -> None: # Example for next migration
    #    """Миграция с Версии 3 на Версию 4."""
    #    print("SqliteAdapter: Running v1 to v2 migration...")
    #    # Пример: добавить новую колонку в таблицу characters
    #    try:
    #        await cursor.execute("ALTER TABLE characters ADD COLUMN new_skill_slot INTEGER DEFAULT 0")
    #        print("SqliteAdapter: Added 'new_skill_slot' to characters table.")
    #    except sqlite3.OperationalError:
    #        print("SqliteAdapter: Column 'new_skill_slot' already exists, skipping ALTER TABLE.")
    #        pass
    #    # Пример: добавить новую таблицу
    #    # await cursor.execute("CREATE TABLE new_table (...)")
    #    print("SqliteAdapter: v1 to v2 migration complete.")

    async def _migrate_v3_to_v4(self, cursor: Cursor) -> None:
        """Миграция с Версии 3 на Версию 4."""
        print("SqliteAdapter: Running v3 to v4 migration...")

        # 1. Rename `characters` to `players`
        try:
            await cursor.execute("ALTER TABLE characters RENAME TO players;")
            print("SqliteAdapter: Renamed table 'characters' to 'players'.")
        except aiosqlite.OperationalError as e:
            # This might happen if the migration is run multiple times and 'characters' no longer exists
            # or if 'players' already exists (less likely if migrations run linearly).
            if "no such table: characters" in str(e).lower():
                print("SqliteAdapter: Table 'characters' not found, assuming already renamed to 'players'.")
            elif "table players already exists" in str(e).lower():
                 print("SqliteAdapter: Table 'players' already exists.")
            else:
                raise # Re-raise other operational errors

        # 2. Add columns to the (new) `players` table
        # Columns to add: race TEXT, mp INTEGER DEFAULT 0, attack INTEGER DEFAULT 0, defense INTEGER DEFAULT 0
        # level and experience already exist from v1.
        player_columns_to_add = [
            ("race", "TEXT"),
            ("mp", "INTEGER DEFAULT 0"),
            ("attack", "INTEGER DEFAULT 0"),
            ("defense", "INTEGER DEFAULT 0")
        ]
        for column_name, column_type in player_columns_to_add:
            try:
                await cursor.execute(f"ALTER TABLE players ADD COLUMN {column_name} {column_type};")
                print(f"SqliteAdapter: Added column '{column_name}' to 'players' table.")
            except aiosqlite.OperationalError as e:
                if "duplicate column name" in str(e).lower():
                    print(f"SqliteAdapter: Column '{column_name}' already exists in 'players' table, skipping.")
                else:
                    raise

        # 3. Create `inventory` table
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS inventory (
                inventory_id TEXT PRIMARY KEY,
                player_id TEXT,
                item_template_id TEXT,
                quantity INTEGER,
                FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE,
                FOREIGN KEY(item_template_id) REFERENCES item_templates(id) ON DELETE CASCADE
            );
        ''')
        print("SqliteAdapter: Created 'inventory' table IF NOT EXISTS.")
        await cursor.execute('''CREATE INDEX IF NOT EXISTS idx_inventory_player_id ON inventory (player_id);''')
        print("SqliteAdapter: Created index 'idx_inventory_player_id' on 'inventory' table IF NOT EXISTS.")

        # 4. Verify/Update `item_templates` table - No direct schema change needed as per plan.
        print("SqliteAdapter: 'item_templates' table structure confirmed suitable for item definitions (effects in properties).")

        # 5. Add columns to `npcs` table
        # Only 'persona' TEXT needs to be added. 'hp' and 'attack' are handled by existing fields.
        try:
            await cursor.execute("ALTER TABLE npcs ADD COLUMN persona TEXT;")
            print("SqliteAdapter: Added column 'persona' to 'npcs' table.")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                print("SqliteAdapter: Column 'persona' already exists in 'npcs' table, skipping.")
            else:
                raise

        # 6. Add `player_id` column to `game_logs` table
        try:
            await cursor.execute("ALTER TABLE game_logs ADD COLUMN player_id TEXT;")
            print("SqliteAdapter: Added column 'player_id' to 'game_logs' table.")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                print("SqliteAdapter: Column 'player_id' already exists in 'game_logs' table, skipping.")
            else:
                raise
        await cursor.execute('''CREATE INDEX IF NOT EXISTS idx_game_logs_player_id ON game_logs (player_id);''')
        print("SqliteAdapter: Created index 'idx_game_logs_player_id' on 'game_logs' table IF NOT EXISTS.")

        print("SqliteAdapter: v3 to v4 migration complete.")

    async def _migrate_v4_to_v5(self, cursor: Cursor) -> None:
        """Миграция с Версии 4 на Версию 5 (добавление is_undone в game_logs)."""
        print("SqliteAdapter: Running v4 to v5 migration (adding is_undone to game_logs)...")

        # Add is_undone column to game_logs
        try:
            await cursor.execute("ALTER TABLE game_logs ADD COLUMN is_undone INTEGER DEFAULT 0 NOT NULL;")
            print("SqliteAdapter: Added column 'is_undone' to 'game_logs' table.")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                print("SqliteAdapter: Column 'is_undone' already exists in 'game_logs' table, skipping.")
            else:
                raise

        # Add index for querying undoable actions
        # Assumes the player_id column added in v4 was named 'player_id'
        await cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_game_logs_player_undone_ts
            ON game_logs (player_id, is_undone, timestamp DESC);
        ''')
        print("SqliteAdapter: Created index 'idx_game_logs_player_undone_ts' on 'game_logs' table IF NOT EXISTS.")

        print("SqliteAdapter: v4 to v5 migration complete.")

    async def _migrate_v5_to_v6(self, cursor: Cursor) -> None:
        """Миграция с Версии 5 на Версию 6 (добавление amount в inventory)."""
        print("SqliteAdapter: Running v5 to v6 migration (adding amount to inventory)...")
        try:
            await cursor.execute("ALTER TABLE inventory ADD COLUMN amount INTEGER NOT NULL DEFAULT 1;")
            print("SqliteAdapter: Added column 'amount' to 'inventory' table.")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                print("SqliteAdapter: Column 'amount' already exists in 'inventory' table, skipping.")
            else:
                print(f"SqliteAdapter: OperationalError when adding 'amount' column: {e}")
                traceback.print_exc()
                raise
        except Exception as e:
            print(f"SqliteAdapter: Unexpected error when adding 'amount' column: {e}")
            traceback.print_exc()
            raise
        print("SqliteAdapter: v5 to v6 migration complete.")

    async def _migrate_v6_to_v7(self, cursor: Cursor) -> None:
        """Миграция с Версии 6 на Версию 7 (копирование inventory.quantity в inventory.amount и удаление inventory.quantity)."""
        print("SqliteAdapter: Running v6 to v7 migration (inventory quantity -> amount cleanup)...")
        await cursor.execute("PRAGMA busy_timeout = 5000;")

        await cursor.execute("PRAGMA table_info(inventory);")
        columns_info = await cursor.fetchall()
        columns = [row["name"] for row in columns_info if row and "name" in row.keys()]

        if 'quantity' not in columns:
            print("SqliteAdapter: Column 'quantity' not found in 'inventory' table. Assuming already migrated or not needed.")
            print("SqliteAdapter: v6 to v7 migration complete (no action taken).")
            return

        if 'amount' not in columns:
            print("SqliteAdapter: CRITICAL: Column 'amount' not found. This implies v5_to_v6 failed.")
            # This should ideally not happen if migrations run in order.
            # For robustness, attempt to add it, but this is a sign of a problem.
            try:
                print("SqliteAdapter: Attempting to add missing 'amount' column before proceeding...")
                await cursor.execute("ALTER TABLE inventory ADD COLUMN amount INTEGER NOT NULL DEFAULT 1;")
                print("SqliteAdapter: Added missing 'amount' column. Proceeding with data copy.")
            except Exception as e_add_col:
                print(f"SqliteAdapter: Failed to add missing 'amount' column: {e_add_col}. Aborting v6_to_v7 for safety.")
                traceback.print_exc()
                raise # Critical failure

        try:
            print("SqliteAdapter: Copying data from 'quantity' to 'amount' in 'inventory' table...")
            await cursor.execute("UPDATE inventory SET amount = CASE WHEN quantity IS NULL THEN 1 ELSE quantity END WHERE amount IS NOT quantity;")
            print("SqliteAdapter: Data copied from 'quantity' to 'amount' where necessary.")
        except Exception as e_copy:
            print(f"SqliteAdapter: Error copying quantity to amount: {e_copy}.")
            traceback.print_exc()
            raise # This is a critical step

        print("SqliteAdapter: Recreating 'inventory' table without 'quantity' column...")

        await cursor.execute("PRAGMA foreign_keys;")
        fk_enabled_row = await cursor.fetchone()
        fk_enabled = False
        if fk_enabled_row is not None:
            try:
                fk_enabled = bool(fk_enabled_row[0])
            except IndexError:
                print("SqliteAdapter: Warning: Could not determine foreign_key status from PRAGMA.")

        # The main transaction is handled by initialize_database()
        # if fk_enabled: # Foreign key handling might still be needed if STRICT mode is on, but usually ALTER/DROP is fine in a transaction.
        #     await cursor.execute("PRAGMA foreign_keys=OFF;") # This might not be strictly necessary if not using STRICT tables.
        #     print("SqliteAdapter: Temporarily disabled foreign keys.")

        try:
            # Ensure foreign keys are off for table manipulation if there's any doubt.
            # However, SQLite typically allows these operations within a transaction without this,
            # unless specific PRAGMAs like 'foreign_key_check' are used or tables are 'STRICT'.
            # For safety during complex rebuilds, it can be kept but ensure it's balanced.
            # Let's assume it's needed for robustness if foreign key constraints might interfere.
            original_fk_status = await cursor.execute("PRAGMA foreign_keys;")
            original_fk_enabled = await original_fk_status.fetchone()
            fk_actually_enabled = original_fk_enabled[0] == 1 if original_fk_enabled else False

            if fk_actually_enabled:
                 await cursor.execute("PRAGMA foreign_keys=OFF;")
                 print("SqliteAdapter: (migrate_v6_to_v7) Temporarily disabled foreign keys for table rebuild.")


            create_inventory_new_sql = """
                CREATE TABLE inventory_new (
                    inventory_id TEXT PRIMARY KEY,
                    player_id TEXT,
                    item_template_id TEXT,
                    amount INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE,
                    FOREIGN KEY(item_template_id) REFERENCES item_templates(id) ON DELETE CASCADE
                );
            """
            await cursor.execute(create_inventory_new_sql)
            print("SqliteAdapter: Created 'inventory_new' table.")

            insert_into_inventory_new_sql = """
                INSERT INTO inventory_new (inventory_id, player_id, item_template_id, amount)
                SELECT inventory_id, player_id, item_template_id, amount
                FROM inventory;
            """
            await cursor.execute(insert_into_inventory_new_sql)
            print("SqliteAdapter: Copied data to 'inventory_new'.")

            await cursor.execute("DROP TABLE inventory;")
            print("SqliteAdapter: Dropped old 'inventory' table.")

            await cursor.execute("ALTER TABLE inventory_new RENAME TO inventory;")
            print("SqliteAdapter: Renamed 'inventory_new' to 'inventory'.")

            await cursor.execute("CREATE INDEX IF NOT EXISTS idx_inventory_player_id ON inventory (player_id);")
            print("SqliteAdapter: Recreated index 'idx_inventory_player_id' on 'inventory' table.")

            # initialize_database() handles the commit for all migrations.
            # print("SqliteAdapter: (migrate_v6_to_v7) Table reconstruction successful within its part of the migration.")

        except Exception as e_rebuild:
            print(f"SqliteAdapter: Error during inventory table reconstruction in _migrate_v6_to_v7: {e_rebuild}. The outer transaction in initialize_database will handle rollback.")
            traceback.print_exc()
            raise # Re-raise to trigger rollback in initialize_database
        finally:
            # Restore foreign key status if it was changed
            if fk_actually_enabled: # Only if we actually turned them off
                 await cursor.execute("PRAGMA foreign_keys=ON;")
                 print("SqliteAdapter: (migrate_v6_to_v7) Re-enabled foreign keys.")
            # else:
            #      print("SqliteAdapter: (migrate_v6_to_v7) Foreign keys were not originally enabled or status unknown, not changing.")


        print("SqliteAdapter: v6 to v7 migration complete.")

    async def _migrate_v7_to_v8(self, cursor: Cursor) -> None:
        """Миграция с Версии 7 на Версию 8 (добавление hp и max_health в таблицу players, если отсутствуют)."""
        print("SqliteAdapter: Running v7 to v8 migration (ensure hp, max_health in players)...")

        # Получаем информацию о столбцах таблицы players
        await cursor.execute("PRAGMA table_info(players);")
        columns_info = await cursor.fetchall()
        column_names = [row['name'] for row in columns_info if row and 'name' in row.keys()]

        # Проверяем и добавляем столбец hp, если он отсутствует
        if 'hp' not in column_names:
            try:
                print("SqliteAdapter: Column 'hp' not found in 'players'. Adding column hp REAL DEFAULT 100.0...")
                await cursor.execute("ALTER TABLE players ADD COLUMN hp REAL DEFAULT 100.0;")
                print("SqliteAdapter: Successfully added column 'hp' to 'players' table.")
            except Exception as e_hp:
                print(f"SqliteAdapter: Error adding column 'hp' to 'players': {e_hp}")
                traceback.print_exc()
                raise
        else:
            print("SqliteAdapter: Column 'hp' already exists in 'players' table.")

        # Проверяем и добавляем столбец max_health, если он отсутствует
        if 'max_health' not in column_names:
            try:
                print("SqliteAdapter: Column 'max_health' not found in 'players'. Adding column max_health REAL DEFAULT 100.0...")
                await cursor.execute("ALTER TABLE players ADD COLUMN max_health REAL DEFAULT 100.0;")
                print("SqliteAdapter: Successfully added column 'max_health' to 'players' table.")
            except Exception as e_max_health:
                print(f"SqliteAdapter: Error adding column 'max_health' to 'players': {e_max_health}")
                traceback.print_exc()
                raise
        else:
            print("SqliteAdapter: Column 'max_health' already exists in 'players' table.")

        print("SqliteAdapter: v7 to v8 migration complete.")

    async def _migrate_v8_to_v9(self, cursor: Cursor) -> None:
        """Миграция с Версии 8 на Версию 9 (стандартизация health -> hp в таблице players)."""
        print("SqliteAdapter: Running v8 to v9 migration (standardize players.health to players.hp)...")

        await cursor.execute("PRAGMA table_info(players);")
        columns_info = await cursor.fetchall()
        column_names = [row['name'] for row in columns_info if row and 'name' in row.keys()]

        original_fk_status_query = await cursor.execute("PRAGMA foreign_keys;")
        original_fk_enabled_row = await original_fk_status_query.fetchone()
        fk_actually_enabled = original_fk_enabled_row[0] == 1 if original_fk_enabled_row else False

        if 'health' in column_names and 'hp' in column_names:
            print("SqliteAdapter: Both 'health' and 'hp' columns exist. Consolidating into 'hp' and dropping 'health'.")
            try:
                if fk_actually_enabled:
                    await cursor.execute("PRAGMA foreign_keys=OFF;")
                    print("SqliteAdapter: (migrate_v8_to_v9) Temporarily disabled foreign keys for table rebuild.")

                # Ensure hp has the values from health if health is more up-to-date or hp is default
                await cursor.execute("UPDATE players SET hp = health WHERE health IS NOT NULL AND (hp IS NULL OR hp = 100.0 OR hp != health);")
                print("SqliteAdapter: Copied 'health' data to 'hp' where appropriate.")

                # Define the schema for the new table, excluding 'health'
                # This must match the players table schema AFTER v8 migration, minus 'health'
                # And ensuring all constraints (PK, UNIQUE, NOT NULL, DEFAULT) are preserved.
                create_players_new_sql = """
                CREATE TABLE players_new (
                    id TEXT PRIMARY KEY,
                    discord_user_id INTEGER NULL,
                    name TEXT NOT NULL,
                    guild_id TEXT NOT NULL,
                    location_id TEXT NULL,
                    stats TEXT DEFAULT '{}',
                    inventory TEXT DEFAULT '[]',
                    current_action TEXT NULL,
                    action_queue TEXT DEFAULT '[]',
                    party_id TEXT NULL,
                    state_variables TEXT DEFAULT '{}',
                    max_health REAL DEFAULT 100.0,
                    is_alive INTEGER DEFAULT 1,
                    status_effects TEXT DEFAULT '[]',
                    level INTEGER DEFAULT 1,
                    experience INTEGER DEFAULT 0,
                    active_quests TEXT DEFAULT '[]',
                    created_at REAL NOT NULL DEFAULT (strftime('%s','now')),
                    last_played_at REAL NULL,
                    race TEXT,
                    mp INTEGER DEFAULT 0,
                    attack INTEGER DEFAULT 0,
                    defense INTEGER DEFAULT 0,
                    hp REAL DEFAULT 100.0,
                    UNIQUE(discord_user_id, guild_id),
                    UNIQUE(name, guild_id)
                );
                """
                await cursor.execute(create_players_new_sql)
                print("SqliteAdapter: Created 'players_new' table with standardized schema (no 'health' column).")

                # Explicitly list columns for insertion, ensuring 'hp' gets its (potentially updated) value
                # and 'health' is excluded.
                cols_to_select = "id, discord_user_id, name, guild_id, location_id, stats, inventory, current_action, action_queue, party_id, state_variables, max_health, is_alive, status_effects, level, experience, active_quests, created_at, last_played_at, race, mp, attack, defense, hp"
                insert_sql = f"INSERT INTO players_new ({cols_to_select}) SELECT {cols_to_select} FROM players;"
                await cursor.execute(insert_sql)
                print("SqliteAdapter: Copied data to 'players_new'.")

                await cursor.execute("DROP TABLE players;")
                print("SqliteAdapter: Dropped old 'players' table.")

                await cursor.execute("ALTER TABLE players_new RENAME TO players;")
                print("SqliteAdapter: Renamed 'players_new' to 'players'.")

                # Recreate indexes that might have been on the original players table
                # (Assuming these were the main ones, add others if they existed)
                await cursor.execute('''CREATE INDEX IF NOT EXISTS idx_players_guild_id ON players (guild_id);''') # Example, if it existed
                await cursor.execute('''CREATE INDEX IF NOT EXISTS idx_players_location_id ON players (location_id);''') # Example


            except Exception as e_std:
                print(f"SqliteAdapter: Error standardizing 'health' to 'hp': {e_std}")
                traceback.print_exc()
                raise # Re-raise to be caught by initialize_database for rollback
            finally:
                if fk_actually_enabled:
                    await cursor.execute("PRAGMA foreign_keys=ON;")
                    print("SqliteAdapter: (migrate_v8_to_v9) Re-enabled foreign keys.")

        elif 'hp' not in column_names and 'health' in column_names:
            print("SqliteAdapter: Only 'health' column exists. Renaming 'health' to 'hp'.")
            try:
                # Renaming column is simpler if no type change or complex data merge is needed.
                # However, ensure the default value for 'hp' is consistent if it wasn't on 'health'.
                # The v7_to_v8 migration already added 'hp' with default 100.0.
                # This path (only 'health' exists) should be unlikely if v7_to_v8 ran.
                # If this path IS taken, it means 'hp' was never created by v7_to_v8.
                # We should add 'hp' and copy 'health' then drop 'health', or rename 'health' to 'hp'.
                # Renaming is simpler if 'health' already has the right type and default.
                # For now, sticking to rename as per original user script's branch.
                await cursor.execute("ALTER TABLE players RENAME COLUMN health TO hp;")
                print("SqliteAdapter: Successfully renamed 'health' to 'hp'.")
                # Verify default for hp if it was just renamed
                # This might require further ALTER TABLE DEFAULT which is tricky in SQLite.
                # Best if 'health' column type and default were already compatible.
            except Exception as e_rename:
                print(f"SqliteAdapter: Error renaming 'health' to 'hp': {e_rename}")
                traceback.print_exc()
                raise
        elif 'hp' in column_names and 'health' not in column_names:
            print("SqliteAdapter: 'hp' column exists and 'health' column does not. Schema is already standardized.")
        else: # Neither 'hp' nor 'health' column exists. This is unexpected.
              # Or, if 'health' doesn't exist but 'hp' does (covered by previous elif)
            print("SqliteAdapter: 'hp' column seems to be correctly in place or 'health' was already handled/missing.")

        print("SqliteAdapter: v8 to v9 migration complete.")

    async def _migrate_v9_to_v10(self, cursor: Cursor) -> None:
        """Миграция с Версии 9 на Версию 10 (enhancing combats table for turn-based system)."""
        print("SqliteAdapter: Running v9 to v10 migration (enhancing combats table for turn-based system)...")

        await cursor.execute("PRAGMA table_info(combats);")
        columns_info = await cursor.fetchall()
        column_names = [row['name'] for row in columns_info if row and 'name' in row.keys()]

        # guild_id and location_id should already exist from _migrate_v0_to_v1.
        # Adding them here again would be redundant and might cause errors if run on an existing DB.
        # We will only add the new columns for turn-based combat.

        if 'turn_order' not in column_names:
            try:
                await cursor.execute("ALTER TABLE combats ADD COLUMN turn_order TEXT DEFAULT '[]';")
                print("SqliteAdapter: Added column 'turn_order' to 'combats' table.")
            except Exception as e:
                print(f"SqliteAdapter: Error adding 'turn_order' to 'combats' (column might already exist or other issue): {e}")
                # If it's "duplicate column name", that's fine. Otherwise, re-raise.
                if "duplicate column name" not in str(e).lower():
                    traceback.print_exc()
                    raise
        else:
            print("SqliteAdapter: Column 'turn_order' already exists in 'combats' table.")

        if 'current_turn_index' not in column_names:
            try:
                await cursor.execute("ALTER TABLE combats ADD COLUMN current_turn_index INTEGER DEFAULT 0;")
                print("SqliteAdapter: Added column 'current_turn_index' to 'combats' table.")
            except Exception as e:
                print(f"SqliteAdapter: Error adding 'current_turn_index' to 'combats' (column might already exist or other issue): {e}")
                if "duplicate column name" not in str(e).lower():
                    traceback.print_exc()
                    raise
        else:
            print("SqliteAdapter: Column 'current_turn_index' already exists in 'combats' table.")

        print("SqliteAdapter: v9 to v10 migration complete (combats table schema additions).")

    async def _migrate_v10_to_v11(self, cursor: Cursor) -> None:
        """Миграция с Версии 10 на Версию 11 (добавление selected_language в таблицу players)."""
        print("SqliteAdapter: Running v10 to v11 migration (adding selected_language to players)...")

        await cursor.execute("PRAGMA table_info(players);")
        columns_info = await cursor.fetchall()
        column_names = [row['name'] for row in columns_info if row and 'name' in row.keys()]

        if 'selected_language' not in column_names:
            try:
                # Добавляем столбец с значением по умолчанию 'en'
                await cursor.execute("ALTER TABLE players ADD COLUMN selected_language TEXT DEFAULT 'en';")
                print("SqliteAdapter: Added column 'selected_language' to 'players' table with DEFAULT 'en'.")

                # Обновляем существующие строки, где selected_language может быть NULL (если DEFAULT не сработал для них)
                # Обычно ALTER TABLE ... ADD COLUMN ... DEFAULT устанавливает значение для всех существующих строк.
                # Но для явности и если бы дефолт был NULL, можно было бы сделать так:
                # await cursor.execute("UPDATE players SET selected_language = 'en' WHERE selected_language IS NULL;")
                # print("SqliteAdapter: Ensured existing players have 'selected_language' set to 'en'.")
            except Exception as e:
                print(f"SqliteAdapter: Error adding 'selected_language' to 'players': {e}")
                # Если ошибка "duplicate column name", это нормально при повторном запуске.
                if "duplicate column name" not in str(e).lower():
                    traceback.print_exc()
                    raise
        else:
            print("SqliteAdapter: Column 'selected_language' already exists in 'players' table.")

        print("SqliteAdapter: v10 to v11 migration complete.")

    async def _migrate_v11_to_v12(self, cursor: Cursor) -> None:
        # Placeholder for future migration if needed, or if it was missed.
        # This ensures that if LATEST_SCHEMA_VERSION is set to 14 and current is 11,
        # the migration process doesn't break looking for this.
        print("SqliteAdapter: Running v11 to v12 migration (placeholder)...")
        # Add schema changes for v12 here
        print("SqliteAdapter: v11 to v12 migration complete (placeholder).")

    async def _migrate_v12_to_v13(self, cursor: Cursor) -> None:
        # Placeholder for future migration if needed, or if it was missed.
        print("SqliteAdapter: Running v12 to v13 migration (placeholder)...")
        # Add schema changes for v13 here
        # Example: await cursor.execute("ALTER TABLE some_table ADD COLUMN new_field_v13 TEXT;")
        print("SqliteAdapter: v12 to v13 migration complete (placeholder).")

    async def _migrate_v13_to_v14(self, cursor: Cursor) -> None:
        """Миграция с Версии 13 на Версию 14 (добавление current_location_id в таблицу parties)."""
        print("SqliteAdapter: Running v13 to v14 migration (adding current_location_id to parties)...")

        await cursor.execute("PRAGMA table_info(parties);")
        columns_info = await cursor.fetchall()
        column_names = [row['name'] for row in columns_info if row and 'name' in row.keys()]

        if 'current_location_id' not in column_names:
            try:
                await cursor.execute("ALTER TABLE parties ADD COLUMN current_location_id TEXT NULL;")
                print("SqliteAdapter: Added column 'current_location_id' to 'parties' table.")
            except Exception as e:
                print(f"SqliteAdapter: Error adding 'current_location_id' to 'parties': {e}")
                if "duplicate column name" not in str(e).lower(): # Should not happen with the check above
                    traceback.print_exc()
                    raise
        else:
            print("SqliteAdapter: Column 'current_location_id' already exists in 'parties' table.")

        print("SqliteAdapter: v13 to v14 migration complete.")

# --- Конец класса SqliteAdapter ---
print(f"DEBUG: Finished loading sqlite_adapter.py from: {__file__}")
