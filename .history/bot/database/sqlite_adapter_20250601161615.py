# bot/database/sqlite_adapter.py
print(f"DEBUG: Loading sqlite_adapter.py from: {__file__}")
import sqlite3 # Keep for sqlite3.OperationalError
import traceback
import json # Needed for json.loads/dumps
import re # Needed for migration v8_to_v9
from typing import Optional, List, Tuple, Any, Union, Dict

import aiosqlite
# Типы для аннотаций
from aiosqlite import Connection, Cursor, Row


class SqliteAdapter:
    # Определяем последнюю версию схемы, которую знает этот адаптер
    LATEST_SCHEMA_VERSION = 9 # Updated to include all fixes

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn: Optional[Connection] = None
        print(f"SqliteAdapter initialized for database: {self._db_path}")

    async def connect(self) -> None:
        if self._conn is None:
            print("SqliteAdapter: Connecting to database...")
            try:
                self._conn = await aiosqlite.connect(self._db_path, check_same_thread=False)
                self._conn.row_factory = aiosqlite.Row
                await self._conn.execute('PRAGMA journal_mode=WAL')
                print("SqliteAdapter: Database connected successfully.")
            except Exception as e:
                print(f"SqliteAdapter: ❌ Error connecting to database: {e}")
                traceback.print_exc()
                self._conn = None
                raise

    async def close(self) -> None:
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

    async def get_current_schema_version(self, cursor: Cursor) -> int:
        await cursor.execute("PRAGMA user_version;")
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def set_schema_version(self, cursor: Cursor, version: int) -> None:
        await cursor.execute(f"PRAGMA user_version = {version};")

    async def initialize_database(self) -> None:
        print("SqliteAdapter: Initializing database schema...")
        if not self._conn:
            raise ConnectionError("Database connection is not established.")
        try:
            async with self._conn.cursor() as cursor:
                # Ensure foreign keys are enabled for the connection if not enabled by default by SQLite version
                await cursor.execute("PRAGMA foreign_keys=ON;")
                print("SqliteAdapter: Ensured PRAGMA foreign_keys=ON for this session.")
                
                current_version = await self.get_current_schema_version(cursor)
                print(f"SqliteAdapter: Current database schema version: {current_version}")

                if current_version < self.LATEST_SCHEMA_VERSION:
                     print(f"SqliteAdapter: Migrating from version {current_version} to {self.LATEST_SCHEMA_VERSION}...")
                     for version_step in range(current_version + 1, self.LATEST_SCHEMA_VERSION + 1):
                         print(f"SqliteAdapter: Running migration to version {version_step}...")
                         migrate_method_name = f'_migrate_v{version_step-1}_to_v{version_step}'
                         migrate_method = getattr(self, migrate_method_name, None)
                         if migrate_method:
                             await migrate_method(cursor)
                             await self.set_schema_version(cursor, version_step)
                             print(f"SqliteAdapter: Successfully migrated to version {version_step}.")
                         else:
                             print(f"SqliteAdapter: ❌ No migration method found: {migrate_method_name}.")
                             raise NotImplementedError(f"Migration method {migrate_method_name} not implemented.")
                else:
                    print("SqliteAdapter: Database schema is up to date.")
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
            raise

    async def _migrate_v0_to_v1(self, cursor: Cursor) -> None:
        print("SqliteAdapter: Running v0 to v1 migration (creating initial tables)...")
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS characters (
                id TEXT PRIMARY KEY, discord_user_id INTEGER NULL, name TEXT NOT NULL, guild_id TEXT NOT NULL,
                location_id TEXT NULL, stats TEXT DEFAULT '{}', inventory TEXT DEFAULT '[]',
                current_action TEXT NULL, action_queue TEXT DEFAULT '[]', party_id TEXT NULL,
                state_variables TEXT DEFAULT '{}', health REAL DEFAULT 100.0, max_health REAL DEFAULT 100.0,
                is_alive INTEGER DEFAULT 1, status_effects TEXT DEFAULT '[]', level INTEGER DEFAULT 1,
                experience INTEGER DEFAULT 0, active_quests TEXT DEFAULT '[]',
                created_at REAL NOT NULL DEFAULT (strftime('%s','now')), last_played_at REAL NULL,
                UNIQUE(discord_user_id, guild_id), UNIQUE(name, guild_id)
            );
        ''')
        await cursor.execute("CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, template_id TEXT NOT NULL, name TEXT NOT NULL, is_active INTEGER DEFAULT 1, channel_id INTEGER NULL, guild_id TEXT NOT NULL, current_stage_id TEXT NOT NULL, players TEXT DEFAULT '[]', state_variables TEXT DEFAULT '{}', stages_data TEXT DEFAULT '{}', end_message_template TEXT NULL, started_at REAL NOT NULL DEFAULT (strftime('%s','now')), UNIQUE(channel_id, guild_id) );")
        await cursor.execute("CREATE TABLE IF NOT EXISTS npcs (id TEXT PRIMARY KEY, template_id TEXT, name TEXT NOT NULL, guild_id TEXT NOT NULL, description TEXT NULL, location_id TEXT NULL, owner_id TEXT NULL, owner_type TEXT NULL, stats TEXT DEFAULT '{}', inventory TEXT DEFAULT '[]', current_action TEXT NULL, action_queue TEXT DEFAULT '[]', party_id TEXT NULL, state_variables TEXT DEFAULT '{}', health REAL DEFAULT 100.0, max_health REAL DEFAULT 100.0, is_alive INTEGER DEFAULT 1, status_effects TEXT DEFAULT '[]', is_temporary INTEGER DEFAULT 0, archetype TEXT DEFAULT 'commoner', traits TEXT DEFAULT '[]', desires TEXT DEFAULT '[]', motives TEXT DEFAULT '[]', backstory TEXT DEFAULT '' );")
        await cursor.execute("CREATE TABLE IF NOT EXISTS location_templates (id TEXT NOT NULL, guild_id TEXT NOT NULL, name TEXT NOT NULL, description TEXT NULL, properties TEXT DEFAULT '{}', PRIMARY KEY (id, guild_id), UNIQUE(name, guild_id) );")
        await cursor.execute("CREATE TABLE IF NOT EXISTS locations (id TEXT PRIMARY KEY, template_id TEXT NOT NULL, name TEXT NOT NULL, guild_id TEXT NOT NULL, description TEXT NULL, exits TEXT DEFAULT '{}', state_variables TEXT DEFAULT '{}', is_active INTEGER DEFAULT 1 );")
        await cursor.execute("CREATE TABLE IF NOT EXISTS item_templates (id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, description TEXT NULL, type TEXT NULL, properties TEXT DEFAULT '{}' );")
        await cursor.execute("CREATE TABLE IF NOT EXISTS items (id TEXT PRIMARY KEY, template_id TEXT NOT NULL, guild_id TEXT NOT NULL, owner_id TEXT NULL, owner_type TEXT NULL, location_id TEXT NULL, quantity REAL DEFAULT 1.0, state_variables TEXT DEFAULT '{}', is_temporary INTEGER DEFAULT 0 );")
        await cursor.execute("CREATE TABLE IF NOT EXISTS combats (id TEXT PRIMARY KEY, guild_id TEXT NOT NULL, location_id TEXT NULL, is_active INTEGER DEFAULT 1, channel_id INTEGER NULL, event_id TEXT NULL, current_round INTEGER DEFAULT 0, round_timer REAL DEFAULT 0.0, participants TEXT DEFAULT '{}', combat_log TEXT DEFAULT '[]', state_variables TEXT DEFAULT '{}' );")
        await cursor.execute("CREATE TABLE IF NOT EXISTS statuses (id TEXT PRIMARY KEY, status_type TEXT NOT NULL, target_id TEXT NOT NULL, target_type TEXT NOT NULL, guild_id TEXT NOT NULL, duration REAL NULL, applied_at REAL NOT NULL, source_id TEXT NULL, state_variables TEXT DEFAULT '{}' );")
        await cursor.execute("CREATE TABLE IF NOT EXISTS global_state (key TEXT PRIMARY KEY, value TEXT );")
        await cursor.execute("CREATE TABLE IF NOT EXISTS timers (id TEXT PRIMARY KEY, guild_id TEXT NULL, type TEXT NOT NULL, ends_at REAL NOT NULL, callback_data TEXT NULL, is_active INTEGER DEFAULT 1, target_id TEXT NULL, target_type TEXT NULL );")
        await cursor.execute("CREATE TABLE IF NOT EXISTS crafting_queues (entity_id TEXT NOT NULL, entity_type TEXT NOT NULL, guild_id TEXT NOT NULL, queue TEXT DEFAULT '[]', state_variables TEXT DEFAULT '{}', PRIMARY KEY (entity_id, entity_type, guild_id) );")
        await cursor.execute("CREATE TABLE IF NOT EXISTS market_inventories (entity_id TEXT NOT NULL, entity_type TEXT NOT NULL, guild_id TEXT NOT NULL, inventory TEXT DEFAULT '{}', state_variables TEXT DEFAULT '{}', PRIMARY KEY (entity_id, entity_type, guild_id) );")
        await cursor.execute("CREATE TABLE IF NOT EXISTS parties (id TEXT PRIMARY KEY, guild_id TEXT NOT NULL, name TEXT NULL, leader_id TEXT NULL, member_ids TEXT DEFAULT '[]', state_variables TEXT DEFAULT '{}', current_action TEXT NULL );")
        await cursor.execute("CREATE TABLE IF NOT EXISTS quests (id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT, status TEXT DEFAULT 'available', influence_level TEXT DEFAULT 'local', prerequisites TEXT DEFAULT '[]', connections TEXT DEFAULT '{}', stages TEXT DEFAULT '{}', rewards TEXT DEFAULT '{}', npc_involvement TEXT DEFAULT '{}', guild_id TEXT NOT NULL, created_at REAL NOT NULL DEFAULT (strftime('%s','now')), updated_at REAL NOT NULL DEFAULT (strftime('%s','now')) );")
        await cursor.execute("CREATE TABLE IF NOT EXISTS relationships (id TEXT PRIMARY KEY, entity1_id TEXT NOT NULL, entity1_type TEXT NOT NULL, entity2_id TEXT NOT NULL, entity2_type TEXT NOT NULL, relationship_type TEXT DEFAULT 'neutral', strength REAL DEFAULT 0.0, details TEXT DEFAULT '', guild_id TEXT NOT NULL, updated_at REAL NOT NULL DEFAULT (strftime('%s','now')), UNIQUE(entity1_id, entity1_type, entity2_id, entity2_type, guild_id) );")
        await cursor.execute("CREATE TABLE IF NOT EXISTS game_log_entries (id TEXT PRIMARY KEY, timestamp REAL NOT NULL, guild_id TEXT NOT NULL, entry_type TEXT NOT NULL, actor_id TEXT, actor_type TEXT, target_id TEXT, target_type TEXT, description TEXT NOT NULL, details TEXT DEFAULT '{}' );")
        await cursor.execute('DROP TABLE IF EXISTS dialogues;')
        await cursor.execute("CREATE TABLE IF NOT EXISTS dialogues (id TEXT PRIMARY KEY, template_id TEXT, guild_id TEXT NOT NULL, participants TEXT DEFAULT '[]', channel_id INTEGER, current_stage_id TEXT, state_variables TEXT DEFAULT '{}', conversation_history TEXT DEFAULT '[]', last_activity_game_time REAL, event_id TEXT, is_active INTEGER DEFAULT 1 );")
        print("SqliteAdapter: v0 to v1 migration complete.")

    async def _migrate_v1_to_v2(self, cursor: Cursor) -> None:
        print("SqliteAdapter: Running v1 to v2 migration (adding conversation_history to dialogues)...")
        try:
            await cursor.execute("ALTER TABLE dialogues ADD COLUMN conversation_history TEXT DEFAULT '[]'")
            print("SqliteAdapter: Added 'conversation_history' to dialogues table.")
        except sqlite3.OperationalError as e:
            if 'duplicate column name' in str(e).lower():
                print("SqliteAdapter: Column 'conversation_history' already exists in dialogues table, skipping ALTER TABLE.")
            else:
                raise 
        print("SqliteAdapter: v1 to v2 migration complete.")

    async def _migrate_v2_to_v3(self, cursor: Cursor) -> None:
        print("SqliteAdapter: Running v2 to v3 migration (creating game_logs table)...")
        await cursor.execute('CREATE TABLE IF NOT EXISTS game_logs (log_id TEXT PRIMARY KEY, timestamp REAL NOT NULL, guild_id TEXT NOT NULL, channel_id INTEGER, event_type TEXT NOT NULL, message TEXT NOT NULL, related_entities TEXT, context_data TEXT );')
        await cursor.execute('CREATE INDEX IF NOT EXISTS idx_game_logs_guild_ts ON game_logs (guild_id, timestamp DESC);')
        await cursor.execute('CREATE INDEX IF NOT EXISTS idx_game_logs_event_type ON game_logs (guild_id, event_type);')
        print("SqliteAdapter: game_logs table created and indexes applied.")
        print("SqliteAdapter: v2 to v3 migration complete.")

    async def _migrate_v3_to_v4(self, cursor: Cursor) -> None:
        print("SqliteAdapter: Running v3 to v4 migration...")
        try:
            await cursor.execute("ALTER TABLE characters RENAME TO players;")
            print("SqliteAdapter: Renamed table characters to players.")
        except aiosqlite.OperationalError as e:
            if "no such table: characters" in str(e).lower(): print("SqliteAdapter: Table characters not found, assuming already renamed.")
            elif "table players already exists" in str(e).lower(): print("SqliteAdapter: Table players already exists.")
            else: raise
        
        player_columns_to_add = [("race", "TEXT"), ("mp", "INTEGER DEFAULT 0"), ("attack", "INTEGER DEFAULT 0"), ("defense", "INTEGER DEFAULT 0")]
        for column_name, column_type in player_columns_to_add:
            try:
                await cursor.execute(f"ALTER TABLE players ADD COLUMN {column_name} {column_type};")
                print(f"SqliteAdapter: Added column {column_name} to players table.")
            except aiosqlite.OperationalError as e:
                if "duplicate column name" not in str(e).lower(): raise
                else: print(f"SqliteAdapter: Column {column_name} already exists in players.")
        
        await cursor.execute('CREATE TABLE IF NOT EXISTS inventory (inventory_id TEXT PRIMARY KEY, player_id TEXT, item_template_id TEXT, quantity INTEGER, FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE, FOREIGN KEY(item_template_id) REFERENCES item_templates(id) ON DELETE CASCADE);')
        await cursor.execute('CREATE INDEX IF NOT EXISTS idx_inventory_player_id ON inventory (player_id);')
        
        try:
            await cursor.execute("ALTER TABLE npcs ADD COLUMN persona TEXT;")
            print("SqliteAdapter: Added column persona to npcs table.")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" not in str(e).lower(): raise
            else: print("SqliteAdapter: Column persona already exists in npcs.")
        try:
            await cursor.execute("ALTER TABLE game_logs ADD COLUMN player_id TEXT;")
            print("SqliteAdapter: Added column player_id to game_logs table.")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" not in str(e).lower(): raise
            else: print("SqliteAdapter: Column player_id already exists in game_logs.")
        await cursor.execute('CREATE INDEX IF NOT EXISTS idx_game_logs_player_id ON game_logs (player_id);')
        print("SqliteAdapter: v3 to v4 migration complete.")

    async def _migrate_v4_to_v5(self, cursor: Cursor) -> None:
        print("SqliteAdapter: Running v4 to v5 migration (adding is_undone to game_logs)...")
        try:
            await cursor.execute("ALTER TABLE game_logs ADD COLUMN is_undone INTEGER DEFAULT 0 NOT NULL;")
            print("SqliteAdapter: Added column is_undone to game_logs table.")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" not in str(e).lower(): raise
            else: print("SqliteAdapter: Column is_undone already exists in game_logs.")
        await cursor.execute('CREATE INDEX IF NOT EXISTS idx_game_logs_player_undone_ts ON game_logs (player_id, is_undone, timestamp DESC);')
        print("SqliteAdapter: v4 to v5 migration complete.")

    async def _migrate_v5_to_v6(self, cursor: Cursor) -> None:
        print("SqliteAdapter: Running v5 to v6 migration (adding amount to inventory)...")
        try:
            await cursor.execute("ALTER TABLE inventory ADD COLUMN amount INTEGER NOT NULL DEFAULT 1;")
            print("SqliteAdapter: Added column amount to inventory table.")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" not in str(e).lower(): raise
            else: print("SqliteAdapter: Column amount already exists in inventory.")
        print("SqliteAdapter: v5 to v6 migration complete.")

    async def _migrate_v6_to_v7(self, cursor: Cursor) -> None:
        print("SqliteAdapter: Running v6 to v7 migration (inventory quantity -> amount cleanup)...")
        await cursor.execute("PRAGMA table_info(inventory);")
        columns = [row['name'] for row in await cursor.fetchall()]
        if 'quantity' not in columns:
            print("SqliteAdapter: Column 'quantity' not found. Migration step likely complete or not needed.")
            print("SqliteAdapter: v6 to v7 migration complete (no action taken).")
            return

        if 'amount' in columns: # Should exist from v5_to_v6
            await cursor.execute("UPDATE inventory SET amount = quantity WHERE quantity IS NOT NULL;")
            print("SqliteAdapter: Copied data from 'quantity' to 'amount'.")
        
        # Recreate table to drop 'quantity'. Foreign keys are handled by the main transaction.
        # The main transaction in initialize_database will handle BEGIN/COMMIT/ROLLBACK and foreign key state.
        
        await cursor.execute("CREATE TABLE inventory_new (inventory_id TEXT PRIMARY KEY, player_id TEXT, item_template_id TEXT, amount INTEGER NOT NULL DEFAULT 1, FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE, FOREIGN KEY(item_template_id) REFERENCES item_templates(id) ON DELETE CASCADE);")
        await cursor.execute("INSERT INTO inventory_new (inventory_id, player_id, item_template_id, amount) SELECT inventory_id, player_id, item_template_id, amount FROM inventory;")
        await cursor.execute("DROP TABLE inventory;")
        await cursor.execute("ALTER TABLE inventory_new RENAME TO inventory;")
        await cursor.execute("CREATE INDEX IF NOT EXISTS idx_inventory_player_id ON inventory (player_id);")
        print("SqliteAdapter: Recreated 'inventory' table without 'quantity' column.")
        print("SqliteAdapter: v6 to v7 migration complete.")

    async def _migrate_v7_to_v8(self, cursor: Cursor) -> None:
        print("SqliteAdapter: Running v7 to v8 migration (ensure hp, max_health in players)...")
        await cursor.execute("PRAGMA table_info(players);")
        column_names = [row['name'] for row in await cursor.fetchall()]
        if 'hp' not in column_names:
            try:
                await cursor.execute("ALTER TABLE players ADD COLUMN hp REAL DEFAULT 100.0;")
                print("SqliteAdapter: Successfully added column 'hp' to 'players' table.")
            except Exception as e_hp:
                print(f"SqliteAdapter: Error adding column 'hp' to 'players': {e_hp}")
                traceback.print_exc()
                raise
        else:
            print("SqliteAdapter: Column 'hp' already exists in 'players' table.")

        if 'max_health' not in column_names: # Should exist from v0's characters table
            try:
                await cursor.execute("ALTER TABLE players ADD COLUMN max_health REAL DEFAULT 100.0;")
                print("SqliteAdapter: Successfully added column 'max_health' to 'players' table (this was unexpected).")
            except Exception as e_max_health:
                print(f"SqliteAdapter: Error adding column 'max_health' to 'players': {e_max_health}")
                traceback.print_exc()
                raise
        else:
            print("SqliteAdapter: Column 'max_health' already exists in 'players' table.")
        print("SqliteAdapter: v7 to v8 migration complete.")
        
    async def _migrate_v8_to_v9(self, cursor: Cursor) -> None:
        print("SqliteAdapter: Running v8 to v9 migration (standardize players.health to players.hp)...")
        await cursor.execute("PRAGMA table_info(players);")
        columns_info = await cursor.fetchall()
        column_names = [row['name'] for row in columns_info]

        if 'health' in column_names and 'hp' in column_names:
            print("SqliteAdapter: Both 'health' and 'hp' exist. Consolidating into 'hp' and dropping 'health'.")
            # Copy data from 'health' to 'hp', especially if 'hp' is default and 'health' has actual data
            await cursor.execute("UPDATE players SET hp = health WHERE health IS NOT NULL AND (hp IS NULL OR hp != health);")
            print("SqliteAdapter: Copied 'health' data to 'hp' where appropriate.")
            
            # Rebuild table to drop 'health' column, preserving constraints and other columns
            await cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='players';")
            original_create_sql_row = await cursor.fetchone()
            original_create_sql = original_create_sql_row["sql"] if original_create_sql_row else None

            if not original_create_sql:
                raise Exception("Could not retrieve original schema for players table to drop 'health' column.")

            # Extract column definitions and table constraints from the original schema string
            match = re.search(r'\((.*)\)', original_create_sql, re.DOTALL)
            if not match:
                raise Exception("Could not parse column definitions from players table schema.")

            full_defs_str = match.group(1)
            # Split by comma, but be careful about commas inside parentheses (e.g., for CHECK constraints)
            defs_list = re.split(r',(?![^()]*\))', full_defs_str) 

            new_col_defs_for_create = []
            cols_for_select_list = []

            for col_def_full_stripped in defs_list:
                col_def_full_stripped = col_def_full_stripped.strip()
                # Regex to capture column name, tolerating optional quoting characters
                col_name_match = re.match(r'[`"\[]?(\w+)[`"\]]?', col_def_full_stripped)
                col_name_in_def = col_name_match.group(1).lower() if col_name_match else ""

                if col_name_in_def == 'health':
                    continue # Skip the old 'health' column for the new table definition

                new_col_defs_for_create.append(col_def_full_stripped)
                # For SELECT list, we need just the column name, ensure it is not a table constraint
                if col_name_match and not col_def_full_stripped.lower().startswith(("unique", "primary key", "foreign key", "check")):
                    cols_for_select_list.append(col_name_match.group(1)) # Use original case name

            final_cols_defs_str = ", ".join(new_col_defs_for_create)
            final_cols_for_select = ', '.join(cols_for_select_list)
            
            # The main transaction in initialize_database will handle BEGIN/COMMIT/ROLLBACK and foreign key state.
            # No need for PRAGMA foreign_keys=OFF/ON here if the outer transaction handles it.
            
            await cursor.execute(f'CREATE TABLE players_new ({final_cols_defs_str});')
            await cursor.execute(f'INSERT INTO players_new ({final_cols_for_select}) SELECT {final_cols_for_select} FROM players;')
            await cursor.execute('DROP TABLE players;')
            await cursor.execute('ALTER TABLE players_new RENAME TO players;')
            print("SqliteAdapter: Standardized to 'hp' by rebuilding table and dropping old 'health' column.")

        elif 'hp' not in column_names and 'health' in column_names:
            print("SqliteAdapter: Only 'health' column exists. Renaming 'health' to 'hp'.")
            await cursor.execute("ALTER TABLE players RENAME COLUMN health TO hp;")
            print("SqliteAdapter: Successfully renamed 'health' to 'hp'.")
        elif 'hp' in column_names and 'health' not in column_names:
            print("SqliteAdapter: 'hp' column exists and 'health' column does not. Schema is correct.")
        else: # Neither 'hp' nor 'health' exists.
            print("SqliteAdapter: Neither 'hp' nor 'health' found. This is unexpected. Migration v7_to_v8 should have added 'hp'.")
            # As a safeguard, if 'hp' is still missing, try to add it.
            if "hp" not in column_names:
                try:
                    await cursor.execute("ALTER TABLE players ADD COLUMN hp REAL DEFAULT 100.0;")
                    print("SqliteAdapter: Added 'hp' column as a fallback because it was missing.")
                except Exception as e_add_hp_fallback:
                     print(f"SqliteAdapter: Fallback attempt to add 'hp' column failed: {e_add_hp_fallback}")
                     traceback.print_exc() # Log the traceback for the fallback failure
                     raise # Re-raise as this is a critical state if 'hp' cannot be ensured

        print("SqliteAdapter: v8 to v9 migration complete.")

# --- Конец класса SqliteAdapter ---
print(f"DEBUG: Finished loading sqlite_adapter.py from: {__file__}")