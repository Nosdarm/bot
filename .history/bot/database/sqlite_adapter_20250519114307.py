# bot/database/sqlite_adapter.py
print(f"DEBUG: Loading sqlite_adapter.py from: {__file__}")
import sqlite3
import traceback
# from typing import Optional, List, Tuple, Any # Already imported below from aiosqlite
from typing import Optional, List, Tuple, Any, Union # Добавляем Union для Tuple | List в аннотации execute_many params

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
    # Не увеличиваем версию здесь, просто исправляем V1
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
                # Check if DB file exists to potentially log if it's a new DB creation
                # import os
                # db_exists = os.path.exists(self._db_path)

                self._conn = await aiosqlite.connect(self._db_path)
                self._conn.row_factory = aiosqlite.Row
                await self._conn.execute('PRAGMA journal_mode=WAL')
                # if not db_exists:
                #     print("SqliteAdapter: New database file created.")
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
                # Optional: Perform a final commit before closing if there's any uncommitted data
                # await self._conn.commit()
                await self._conn.close()
                print("SqliteAdapter: Database connection closed.")
            except Exception as e:
                print(f"SqliteAdapter: ❌ Error closing database connection: {e}")
                traceback.print_exc()
            finally:
                self._conn = None # Убеждаемся, что self._conn None

    # ИСПРАВЛЕНИЕ: Аннотация params должна использовать Union[Tuple, List] для совместимости с TypeHint.
    # Хотя в runtime Python 3.10+ Tuple | List работает, для статического анализа лучше Union.
    async def execute(self, sql: str, params: Optional[Union[Tuple, List]] = None) -> Cursor:
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

    async def execute_insert(self, sql: str, params: Optional[Union[Tuple, List]] = None) -> int:
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
             # print(f"SqliteAdapter: Executing many SQL: {sql} | data count: {len(data)}") # Отладочный вывод
             await self._conn.executemany(sql, data)
             await self._conn.commit() # Коммит после пакетной операции
             # print("SqliteAdapter: Execute many committed.")
         except Exception as e:
             print(f"SqliteAdapter: ❌ Error executing many SQL: {sql} | data count: {len(data)} | {e}")
             traceback.print_exc()
             try:
                 await self._conn.rollback()
                 print("SqliteAdapter: Transaction rolled back.")
             except Exception as rb_e:
                 print(f"SqliteAdapter: Error during rollback: {rb_e}")
             raise # Перебрасываем исключение


    async def fetchall(self, sql: str, params: Optional[Union[Tuple, List]] = None) -> List[Row]:
        """Выполняет SELECT запрос и возвращает все строки."""
        if not self._conn:
            raise ConnectionError("Database connection is not established.")
        try:
            # print(f"SqliteAdapter: Fetching all SQL: {sql} | params: {params}") # Отладочный вывод
            cursor = await self._conn.execute(sql, params or ())
            rows = await cursor.fetchall()
            await cursor.close() # Закрываем курсор
            # print(f"SqliteAdapter: Fetched {len(rows)} rows.") # Отладочный вывод
            return rows
        except Exception as e:
            print(f"SqliteAdapter: ❌ Error fetching all SQL: {sql} | params: {params} | {e}")
            traceback.print_exc()
            raise # Перебрасываем исключение

    async def fetchone(self, sql: str, params: Optional[Union[Tuple, List]] = None) -> Optional[Row]:
        """Выполняет SELECT запрос и возвращает одну строку (или None)."""
        if not self._conn:
            raise ConnectionError("Database connection is not established.")
        try:
            # print(f"SqliteAdapter: Fetching one SQL: {sql} | params: {params}") # Отладочный вывод
            cursor = await self._conn.execute(sql, params or ())
            row = await cursor.fetchone()
            await cursor.close() # Закрываем курсор
            # if row: print("SqliteAdapter: Fetched one row.") # Отладочный вывод
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
                    print(f"SqliteAdapter: Running migration to version {version}...")
                    # Название метода миграции: _migrate_v<старая>_to_v<новая>
                    migrate_method_name = f'_migrate_v{version-1}_to_v{version}'
                    migrate_method = getattr(self, migrate_method_name, None)
                    if migrate_method:
                        # Вызываем метод миграции, передавая курсор
                        await migrate_method(cursor)
                        # Обновляем версию схемы в БД, передавая курсор
                        await self.set_schema_version(cursor, version) # Этот execute авто-коммитит? Aiosqlite execute не автокоммитит без with self._conn.execute.
                                                                       # В asyncio context manager, commit нужен в конце блока.
                                                                       # set_schema_version делает INSERT OR REPLACE, который должен быть закоммичен.
                                                                       # Если execute внутри context manager не автокоммитит, то коммит в конце блока migrate_vX_to_vY нужен.
                                                                       # А лучше - коммит в конце async with self._conn.cursor() блока.

                        print(f"SqliteAdapter: Successfully migrated to version {version}.")
                    else:
                        # Это критическая ошибка: версия в LATEST_SCHEMA_VERSION есть, но нет метода миграции
                        print(f"SqliteAdapter: ❌ No migration method found: {migrate_method_name}.")
                        raise NotImplementedError(f"Migration method {migrate_method_name} not implemented.")

                if current_version == self.LATEST_SCHEMA_VERSION:
                    print("SqliteAdapter: Database schema is up to date.")
                else:
                     print(f"SqliteAdapter: Database schema initialization/migration finished. Final version: {self.LATEST_SCHEMA_VERSION}")


            # Коммит ВСЕЙ транзакции миграции после успешного выполнения всех шагов
            # В asyncio, execute внутри async with cursor() блока НЕ авто-коммитит.
            # Коммит нужен ЯВНО в конце блока context manager.
            await self._conn.commit()


        except Exception as e:
            print(f"SqliteAdapter: ❌ CRITICAL ERROR during database schema initialization or migration: {e}")
            traceback.print_exc()
            # Откатываем при ошибке инициализации/миграции
            try:
                if self._conn:
                    # Явный откат при ошибке внутри блока context manager
                    await self._conn.rollback()
                    print("SqliteAdapter: Transaction rolled back due to migration error.")

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
                UNIQUE(discord_user_id, guild_id), -- Пользователь уникален в пределах гильдии
                UNIQUE(name, guild_id) -- Имя уникально в пределах гильдии
            );
        ''')

        await cursor.execute('''
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
        ''')

        await cursor.execute('''
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
        ''')

        await cursor.execute('''
             CREATE TABLE IF NOT EXISTS locations (
                 id TEXT PRIMARY KEY,
                 name TEXT NOT NULL, -- Имя локации не обязательно уникально
                 guild_id TEXT NOT NULL, -- <-- ДОБАВЛЕНА КОЛОНКА GUILD_ID для локаций
                 description TEXT NULL,
                 exits TEXT DEFAULT '{}', -- JSON: {"direction": "location_id"}
                 state_variables TEXT DEFAULT '{}', -- JSON
                 UNIQUE(name, guild_id) -- <-- ДОБАВЛЕНО UNIQUE(name, guild_id)
             );
        ''')

        # Item templates (definitions) are often global, but items (instances) are per-guild or owned
        await cursor.execute('''
             CREATE TABLE IF NOT EXISTS item_templates (
                 id TEXT PRIMARY KEY, -- Global ID
                 name TEXT NOT NULL UNIQUE, -- Global unique name
                 description TEXT NULL,
                 type TEXT NULL,
                 properties TEXT DEFAULT '{}' -- JSON
             );
        ''')

        # Items (instances) belong to a guild or an owner (character/npc/location)
        await cursor.execute('''
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
        ''')
        # Явно указываем owner_id и owner_type, чтобы легче было искать инвентарь персонажа/NPC
        # WHERE guild_id = ? AND owner_id = ? AND owner_type = 'character'


        await cursor.execute('''
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
        ''')

        await cursor.execute('''
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
        ''')

        # global_state остается глобальным
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS global_state (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        ''')

        # Timers могут быть глобальными или пер-гильдийными. Если привязаны к конкретной гильдии/событию/персонажу, нужна guild_id.
        # Предположим, что таймеры могут быть привязаны к гильдии (напр., игровой день/ночь, квесты)
        await cursor.execute('''
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
        ''')

        # crafting_queues привязаны к персонажу, у которого есть guild_id
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS crafting_queues (
                character_id TEXT PRIMARY KEY, -- ID персонажа как PRIMARY KEY
                guild_id TEXT NOT NULL, -- <-- ДОБАВЛЕНА КОЛОНКА GUILD_ID
                queue TEXT DEFAULT '[]', -- JSON список задач крафтинга
                state_variables TEXT DEFAULT '{}', -- JSON
                -- NOTE: Если char_id уникален глобально, то UNIQUE(character_id) достаточно.
                -- Если char_id уникален per-guild (менее вероятно, но возможно), то UNIQUE(character_id, guild_id).
                -- Сейчас PartyManager предполагает глобальный char_id (member_ids - список строк). CharacterManager кеширует per-guild.
                -- Давайте пока оставим character_id PRIMARY KEY, что подразумевает глобальную уникальность character_id.
                -- Если character_id уникален per-guild, то PRIMARY KEY должен быть составным (character_id, guild_id).
            );
        ''')


        # market_inventories привязаны к локации, у которой есть guild_id
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS market_inventories (
                location_id TEXT PRIMARY KEY, -- ID локации как PRIMARY KEY
                guild_id TEXT NOT NULL, -- <-- ДОБАВЛЕНА КОЛОНКА GUILD_ID
                inventory TEXT DEFAULT '{}', -- JSON {item_id: {quantity: ..., price: ...}}
                state_variables TEXT DEFAULT '{}', -- JSON
                -- NOTE: Если location_id уникален глобально, то UNIQUE(location_id) достаточно.
                -- Если location_id уникален per-guild, то PRIMARY KEY должен быть составным (location_id, guild_id).
                -- Пока предполагаем глобальную уникальность location_id для PRIMARY KEY.
            );
        ''')

        # Parties принадлежат гильдии
        await cursor.execute('''
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
        ''')


        # ВСЕ CREATE TABLE IF NOT EXISTS ДОЛЖНЫ БЫТЬ ВЫШЕ И ВНУТРИ ЭТОГО МЕТОДА МИГРАЦИИ

        print("SqliteAdapter: v0 to v1 migration complete.")

    # Для будущих миграций:
    # async def _migrate_v1_to_v2(self, cursor: Cursor) -> None:
    #    """Миграция с Версии 1 на Версию 2."""
    #    print("SqliteAdapter: Running v1 to v2 migration...")
    #    # Пример: добавить новую колонку в таблицу characters
    #    try:
    #        # ALTER TABLE characters ADD COLUMN guild_id TEXT NOT NULL DEFAULT 'default_guild_id'; -- Этот ALTER TABLE должен был быть здесь, но мы его добавляем в CREATE TABLE в v1.
    #        # В v1->v2 добавляются НОВЫЕ колонки или другие изменения.
    #        await cursor.execute("ALTER TABLE characters ADD COLUMN new_skill_slot INTEGER DEFAULT 0")
    #        print("SqliteAdapter: Added 'new_skill_slot' to characters table.")
    #    except sqlite3.OperationalError:
    #        pass # Колонка уже существует (если миграция запускалась повторно)
    #    # Пример: добавить новую таблицу
    #    # await cursor.execute("CREATE TABLE new_table (...)")
    #    print("SqliteAdapter: v1 to v2 migration complete.")


# --- Конец класса SqliteAdapter ---
