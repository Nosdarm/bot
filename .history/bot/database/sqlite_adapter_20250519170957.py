# bot/database/sqlite_adapter.py
print(f"DEBUG: Loading sqlite_adapter.py from: {__file__}")
import sqlite3 # Keep for sqlite3.OperationalError
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
    LATEST_SCHEMA_VERSION = 1 # Увеличьте это число, если добавляете новые миграции (_migrate_v1_to_v2 и т.д.)

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
                             await migrate_method(cursor)
                             await self.set_schema_version(cursor, version)
                             print(f"SqliteAdapter: Successfully migrated to version {version}.")
                         else:
                             print(f"SqliteAdapter: ❌ No migration method found: {migrate_method_name}.")
                             raise NotImplementedError(f"Migration method {migrate_method_name} not implemented.")
                else:
                    print("SqliteAdapter: Database schema is up to date.")

            # Коммит ВСЕЙ транзакции миграции после успешного выполнения всех шагов
            await self._conn.commit()
            print("SqliteAdapter: Database schema initialization/migration finished.")

        except Exception as e:
            print(f"SqliteAdapter: ❌ CRITICAL ERROR during database schema initialization or migration: {e}")
            traceback.print_exc()
            try:
                if self._conn:
                    await self._conn.rollback()
                    print("SqliteAdapter: Transaction rolled back due to migration error.")
            except Exception as rb_e:
                print(f"SqliteAdapter: Error during rollback after schema init/migration error: {rb_e}")
            raise # Перебрасываем исключение, так как без правильной схемы бот не может работать


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
                -- Дополнительные колонки по необходимости
                created_at REAL NOT NULL DEFAULT (CAST(strftime('%s', 'now') AS REAL)), -- Unix timestamp
                last_played_at REAL NULL,
                -- UNIQUE ограничения в пределах гильдии
                UNIQUE(discord_user_id, guild_id),
                UNIQUE(name, guild_id)
            );
        ''')

        # Event Table
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                template_id TEXT NOT NULL,
                name TEXT NOT NULL,
                is_active INTEGER DEFAULT 1, -- 0 or 1
                channel_id INTEGER NULL, -- Канал, где проходит событие (не обязательно уникален, если событие может быть в нескольких каналах или использовать один канал на гильдию)
                guild_id TEXT NOT NULL,
                current_stage_id TEXT NOT NULL,
                -- players TEXT DEFAULT '[]', -- Список player_id - лучше хранить через связь или в таблице Party
                state_variables TEXT DEFAULT '{}', -- JSON
                stages_data TEXT DEFAULT '{}', -- JSON определение стадий события (возможно, лучше хранить в шаблоне)
                end_message_template TEXT NULL,
                started_at REAL NOT NULL DEFAULT (CAST(strftime('%s', 'now') AS REAL)),
                UNIQUE(channel_id, guild_id) -- Ограничение: одно активное событие на канал в гильдии
                -- NOTE: Если одно событие может быть в разных каналах, убрать UNIQUE(channel_id, guild_id).
                -- Если несколько событий могут быть в одном канале, убрать UNIQUE(channel_id).
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
                owner_id TEXT NULL, -- ID владельца (персонажа, партии, локации и т.д.)
                owner_type TEXT NULL, -- Тип владельца ('character', 'party', 'location')
                stats TEXT DEFAULT '{}', -- JSON
                inventory TEXT DEFAULT '[]', -- JSON [{item_id: ..., quantity: ...}, ...]
                current_action TEXT NULL, -- JSON
                action_queue TEXT DEFAULT '[]', -- JSON
                party_id TEXT NULL, -- ID партии
                state_variables TEXT DEFAULT '{}', -- JSON
                health REAL DEFAULT 100.0,
                max_health REAL DEFAULT 100.0,
                is_alive INTEGER DEFAULT 1, -- 0 or 1
                status_effects TEXT DEFAULT '[]', -- JSON
                is_temporary INTEGER DEFAULT 0 -- 0 or 1 (для временно созданных NPC)
                -- UNIQUE(name, guild_id) -- Если имена NPC должны быть уникальны per-guild, раскомментируйте
            );
        ''')

        # Location Table (for instances)
        await cursor.execute('''
             CREATE TABLE IF NOT EXISTS locations (
                 id TEXT PRIMARY KEY,
                 name TEXT NOT NULL,
                 guild_id TEXT NOT NULL,
                 description TEXT NULL,
                 exits TEXT DEFAULT '{}', -- JSON: {"direction": "location_id"}
                 state_variables TEXT DEFAULT '{}', -- JSON
                 -- Если имена локаций должны быть уникальны per-guild
                 UNIQUE(name, guild_id)
             );
        ''')

        # Item Templates Table (global)
        await cursor.execute('''
             CREATE TABLE IF NOT EXISTS item_templates (
                 id TEXT PRIMARY KEY, -- Global ID
                 name TEXT NOT NULL UNIQUE, -- Global unique name
                 description TEXT NULL,
                 type TEXT NULL, -- e.g., 'consumable', 'equipment', 'material'
                 properties TEXT DEFAULT '{}' -- JSON {stat_bonus: {...}, usable: true, craftable: {...}}
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
                 quantity INTEGER DEFAULT 1,
                 state_variables TEXT DEFAULT '{}', -- JSON instance-specific variables
                 -- name TEXT NULL, -- Consider if name is needed per-instance or always from template
                 is_temporary INTEGER DEFAULT 0 -- 0 or 1
                 -- NOTE: Чтобы найти все предметы в локации, искать WHERE owner_type = 'location' AND owner_id = location_id
                 -- Чтобы найти все предметы в инвентаре персонажа, искать WHERE owner_type = 'character' AND owner_id = character_id
                 -- Индексы могут помочь с поиском по owner_id/owner_type
                 -- CREATE INDEX IF NOT EXISTS idx_items_owner ON items (owner_type, owner_id);
                 -- CREATE INDEX IF NOT EXISTS idx_items_location ON items (location_id); -- If location_id is a separate column for ground items
              );
        ''')


        # Combat Table
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS combats (
                id TEXT PRIMARY KEY, -- Unique Combat ID (UUID)
                guild_id TEXT NOT NULL,
                location_id TEXT NULL, -- <--- КОЛОНКА location_id ДОБАВЛЕНА СЮДА
                is_active INTEGER DEFAULT 1, -- 0 or 1
                channel_id INTEGER NULL, -- Канал, где идет бой (может совпадать с location_id channel)
                event_id TEXT NULL, -- Связь с событием
                current_round INTEGER DEFAULT 0,
                time_in_current_phase REAL DEFAULT 0.0,
                participants TEXT DEFAULT '{}', -- JSON {entity_id: {role: 'player'/'npc', team: 'A'/'B', initial_health: ..., current_health: ...}, ...}
                state_variables TEXT DEFAULT '{}' -- JSON
            );
        ''')


        # Status Effect Instances Table
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS statuses (
                id TEXT PRIMARY KEY, -- Unique ID for this status effect instance (UUID)
                status_type TEXT NOT NULL, -- Type of status effect (e.g., 'poison', 'stun', 'blessed')
                target_id TEXT NOT NULL, -- ID сущности, на которую наложен эффект
                target_type TEXT NOT NULL, -- Тип сущности ('character', 'npc', 'party', 'location')
                guild_id TEXT NOT NULL, -- Status effects belong to a guild's context
                duration REAL NULL, -- Длительность в игровых секундах (NULL для постоянных)
                applied_at REAL NOT NULL, -- Игровое время, когда наложен эффект (из TimeManager)
                source_id TEXT NULL, -- ID источника эффекта (напр., персонажа, предмета)
                state_variables TEXT DEFAULT '{}' -- JSON instance-specific variables
                -- Индекс для быстрого поиска статусов по цели
                -- CREATE INDEX IF NOT EXISTS idx_statuses_target ON statuses (target_type, target_id);
            );
        ''')

        # Global State Table (for global data not tied to a guild)
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS global_state (
                key TEXT PRIMARY KEY,
                value TEXT -- Store value as JSON string or simple string
            );
        ''')

        # Timers Table
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS timers (
                id TEXT PRIMARY KEY, -- Unique timer ID (UUID)
                guild_id TEXT NULL, -- NULL if global timer
                type TEXT NOT NULL, -- Тип таймера (напр., 'world_tick', 'status_duration', 'event_phase', 'respawn')
                ends_at REAL NOT NULL, -- Игровое время, когда таймер истекает
                callback_data TEXT NULL, -- JSON данные, передаваемые в колбэк
                is_active INTEGER DEFAULT 1, -- 0 or 1
                target_id TEXT NULL, -- ID сущности, связанной с таймером (опционально)
                target_type TEXT NULL -- Тип сущности (опционально)
                -- Индекс для быстрого поиска активных таймеров
                -- CREATE INDEX IF NOT EXISTS idx_timers_active ON timers (is_active, ends_at);
                -- CREATE INDEX IF NOT EXISTS idx_timers_guild ON timers (guild_id);
            );
        ''')

        # Crafting Queues Table (tied to a character/entity)
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS crafting_queues (
                entity_id TEXT PRIMARY KEY, -- ID сущности (character/npc)
                entity_type TEXT NOT NULL, -- 'character' or 'npc'
                guild_id TEXT NOT NULL,
                queue TEXT DEFAULT '[]', -- JSON список задач крафтинга [{recipe_id: ..., quantity: ..., started_at: ..., estimated_completion: ...}, ...]
                state_variables TEXT DEFAULT '{}' -- JSON
            );
        ''')

        # Market Inventories Table (tied to a location/entity)
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS market_inventories (
                entity_id TEXT PRIMARY KEY, -- ID сущности (location/npc/etc)
                entity_type TEXT NOT NULL, -- 'location', 'npc'
                guild_id TEXT NOT NULL,
                inventory TEXT DEFAULT '{}', -- JSON {item_id: {quantity: ..., price: ...}, ...}
                state_variables TEXT DEFAULT '{}' -- JSON
            );
        ''')

        # Parties Table
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS parties (
                id TEXT PRIMARY KEY, -- Unique Party ID (UUID)
                guild_id TEXT NOT NULL,
                name TEXT NULL, -- Имя партии
                leader_id TEXT NULL, -- ID лидера (character/npc)
                member_ids TEXT DEFAULT '[]', -- JSON список ID участников [entity_id, ...]
                state_variables TEXT DEFAULT '{}', -- JSON
                current_action TEXT NULL, -- JSON
                -- UNIQUE(name, guild_id) -- Если имена партий должны быть уникальны per-guild, раскомментируйте.
                -- Индекс для поиска партии по лидеру
                -- CREATE INDEX IF NOT EXISTS idx_parties_leader ON parties (leader_id);
            );
        ''')

        # Add more tables as needed (e.g., recipes, skills, quests, dialogue_states)

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
    #        # Ловим ошибку, если колонка уже существует (например, при повторном запуске миграции на уже мигрировавшей БД)
    #        # В реальной системе миграций, возможно, захочется более сложную логику
    #        print("SqliteAdapter: Column 'new_skill_slot' already exists, skipping ALTER TABLE.")
    #        pass # Колонка уже существует
    #    # Пример: добавить новую таблицу
    #    # await cursor.execute("CREATE TABLE new_table (...)")
    #    print("SqliteAdapter: v1 to v2 migration complete.")

# --- Конец класса SqliteAdapter ---
print(f"DEBUG: Finished loading sqlite_adapter.py from: {__file__}")
