# bot/services/db_service.py
import json
from typing import Optional, List, Dict, Any
import aiosqlite # Required for aiosqlite.Row type hint

from bot.database.sqlite_adapter import SqliteAdapter

class DBService:
    """
    Service layer for database operations, abstracting the SqliteAdapter.
    Handles data conversion (e.g., Row to dict, JSON string to dict).
    """

    def __init__(self, db_path: str):
        self.adapter = SqliteAdapter(db_path)

    async def connect(self) -> None:
        """Connects to the database."""
        await self.adapter.connect()

    async def close(self) -> None:
        """Closes the database connection."""
        await self.adapter.close()

    async def initialize_database(self) -> None:
        """Initializes the database schema by running migrations."""
        await self.adapter.initialize_database()

    def _row_to_dict(self, row: Optional[aiosqlite.Row]) -> Optional[Dict[str, Any]]:
        """Converts an aiosqlite.Row to a dictionary."""
        if row is None:
            return None
        return dict(row)

    def _rows_to_dicts(self, rows: List[aiosqlite.Row]) -> List[Dict[str, Any]]:
        """Converts a list of aiosqlite.Row to a list of dictionaries."""
        return [dict(row) for row in rows]

    # --- Player/Character Management ---

    async def get_player_by_discord_id(self, discord_user_id: int, guild_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a player by their Discord User ID and Guild ID."""
        # Assuming target schema has 'players' table similar to 'characters'
        sql = "SELECT * FROM players WHERE discord_user_id = ? AND guild_id = ?"
        row = await self.adapter.fetchone(sql, (discord_user_id, guild_id))
        player = self._row_to_dict(row)
        if player and player.get('stats') and isinstance(player['stats'], str):
            player['stats'] = json.loads(player['stats'])
        # Add other JSON deserializations if needed (e.g., inventory if it were a JSON column)
        return player

    async def create_player(
        self, discord_user_id: int, name: str, race: str,
        guild_id: str, location_id: str, hp: int, mp: int,
        attack: int, defense: int, stats: Optional[Dict[str, Any]] = None,
        player_id: Optional[str] = None # Allow providing an ID, e.g. UUID
    ) -> Optional[Dict[str, Any]]:
        """
        Creates a new player in the 'players' table.
        Returns the created player data including the ID.
        A unique player_id should be provided; if not, a simple one is generated.
        """
        if not player_id:
            player_id = f"{guild_id}-{discord_user_id}" # Example composite ID, consider UUIDs for production

        sql = """
            INSERT INTO players (id, discord_user_id, name, race, guild_id, location_id, hp, mp, attack, defense, stats, experience, level)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            player_id, discord_user_id, name, race, guild_id, location_id,
            hp, mp, attack, defense, json.dumps(stats) if stats else '{}',
            0, 1 # Default exp and level
        )
        # Assuming execute_insert returns the last inserted rowid, which might not be the text player_id.
        # For text PKs, execute is fine, then fetch.
        await self.adapter.execute(sql, params)
        return await self.get_player_data(player_id)


    async def update_player_location(self, player_id: str, new_location_id: str) -> None:
        """Updates the location_id for a given player."""
        sql = "UPDATE players SET location_id = ? WHERE id = ?"
        await self.adapter.execute(sql, (new_location_id, player_id))

    async def get_player_inventory(self, player_id: str) -> List[Dict[str, Any]]:
        """Retrieves a player's inventory from the 'inventory' table."""
        sql = """
            SELECT inv.item_template_id, inv.amount, it.name, it.description, it.type as item_type, it.properties
            FROM inventory inv
            JOIN item_templates it ON inv.item_template_id = it.id
            WHERE inv.player_id = ?
        """
        rows = await self.adapter.fetchall(sql, (player_id,))
        inventory_items = self._rows_to_dicts(rows)
        for item in inventory_items:
            if item.get('properties') and isinstance(item['properties'], str):
                item['properties'] = json.loads(item['properties'])
        return inventory_items

    async def add_item_to_inventory(self, player_id: str, item_template_id: str, amount: int) -> None:
        """Adds an item to a player's inventory or updates its amount if it exists."""
        # Assumes 'inventory' table: player_id, item_template_id, amount (UNIQUE constraint on player_id, item_template_id)
        # And an inventory_id as primary key (TEXT or INTEGER)
        # For this example, we'll use a placeholder inventory_id if inserting.
        import uuid
        inventory_id = str(uuid.uuid4())


        sql_select = "SELECT amount, inventory_id FROM inventory WHERE player_id = ? AND item_template_id = ?"
        row = await self.adapter.fetchone(sql_select, (player_id, item_template_id))

        if row:
            new_amount = row['amount'] + amount
            existing_inventory_id = row['inventory_id']
            sql_update = "UPDATE inventory SET amount = ? WHERE inventory_id = ?"
            await self.adapter.execute(sql_update, (new_amount, existing_inventory_id))
        else:
            sql_insert = "INSERT INTO inventory (inventory_id, player_id, item_template_id, amount) VALUES (?, ?, ?, ?)"
            await self.adapter.execute(sql_insert, (inventory_id, player_id, item_template_id, amount))

    async def remove_item_from_inventory(self, player_id: str, item_template_id: str, amount: int) -> None:
        """Removes an item from a player's inventory or reduces its amount."""
        sql_select = "SELECT amount, inventory_id FROM inventory WHERE player_id = ? AND item_template_id = ?"
        row = await self.adapter.fetchone(sql_select, (player_id, item_template_id))

        if row:
            current_amount = row['amount']
            existing_inventory_id = row['inventory_id']
            if current_amount <= amount:
                sql_delete = "DELETE FROM inventory WHERE inventory_id = ?"
                await self.adapter.execute(sql_delete, (existing_inventory_id,))
            else:
                new_amount = current_amount - amount
                sql_update = "UPDATE inventory SET amount = ? WHERE inventory_id = ?"
                await self.adapter.execute(sql_update, (new_amount, existing_inventory_id))

    async def get_player_data(self, player_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves generic player data by their internal player ID."""
        sql = "SELECT * FROM players WHERE id = ?"
        row = await self.adapter.fetchone(sql, (player_id,))
        player = self._row_to_dict(row)
        if player:
            if player.get('stats') and isinstance(player['stats'], str):
                player['stats'] = json.loads(player['stats'])
            if player.get('active_quests') and isinstance(player['active_quests'], str):
                 player['active_quests'] = json.loads(player['active_quests'])
            if player.get('status_effects') and isinstance(player['status_effects'], str):
                 player['status_effects'] = json.loads(player['status_effects'])
        return player

    # --- Item Definition Management (using 'item_templates' table) ---

    async def create_item_definition( # Renamed from create_item_template
        self, item_id: str, name: str, description: str,
        item_type: str, effects: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """Creates a new item definition in 'item_templates'."""
        properties_data = {'effects': effects} if effects else {}
        sql = """
            INSERT INTO item_templates (id, name, description, type, properties)
            VALUES (?, ?, ?, ?, ?)
        """
        params = (item_id, name, description, item_type, json.dumps(properties_data))
        await self.adapter.execute(sql, params)
        return await self.get_item_definition(item_id) # Renamed from get_item_template

    async def get_item_definition(self, item_id: str) -> Optional[Dict[str, Any]]: # Renamed from get_item_template
        """Retrieves an item definition by its ID from 'item_templates'."""
        sql = "SELECT * FROM item_templates WHERE id = ?"
        row = await self.adapter.fetchone(sql, (item_id,))
        item_def = self._row_to_dict(row)
        if item_def and item_def.get('properties') and isinstance(item_def['properties'], str):
            item_def['properties'] = json.loads(item_def['properties'])
        return item_def

    async def get_all_item_definitions(self) -> List[Dict[str, Any]]: # Renamed from get_all_item_templates
        """Retrieves all item definitions from 'item_templates'."""
        sql = "SELECT * FROM item_templates"
        rows = await self.adapter.fetchall(sql)
        item_defs = self._rows_to_dicts(rows)
        for item_def in item_defs:
            if item_def.get('properties') and isinstance(item_def['properties'], str):
                item_def['properties'] = json.loads(item_def['properties'])
        return item_defs

    # --- Location Management ---

    async def create_location(
        self, loc_id: str, name: str, description: str, guild_id: str,
        exits: Optional[Dict[str, str]] = None, template_id: str = "default"
    ) -> Optional[Dict[str, Any]]:
        """Creates a new location instance."""
        sql = """
            INSERT INTO locations (id, template_id, name, description, guild_id, exits, state_variables, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            loc_id, template_id, name, description, guild_id,
            json.dumps(exits) if exits else '{}',
            '{}', 1
        )
        await self.adapter.execute(sql, params)
        return await self.get_location(loc_id, guild_id)

    async def get_location(self, location_id: str, guild_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Retrieves a location by its ID."""
        sql = "SELECT * FROM locations WHERE id = ?"
        params = (location_id,)
        if guild_id:
            sql += " AND guild_id = ?"
            params = (location_id, guild_id)

        row = await self.adapter.fetchone(sql, params)
        location = self._row_to_dict(row)
        if location:
            if location.get('exits') and isinstance(location['exits'], str):
                location['exits'] = json.loads(location['exits'])
            if location.get('state_variables') and isinstance(location['state_variables'], str):
                location['state_variables'] = json.loads(location['state_variables'])
        return location

    async def get_all_locations(self, guild_id: str) -> List[Dict[str, Any]]:
        """Retrieves all locations for a given guild."""
        sql = "SELECT * FROM locations WHERE guild_id = ?"
        rows = await self.adapter.fetchall(sql, (guild_id,))
        locations = self._rows_to_dicts(rows)
        for loc in locations:
            if loc.get('exits') and isinstance(loc['exits'], str):
                loc['exits'] = json.loads(loc['exits'])
            if loc.get('state_variables') and isinstance(loc['state_variables'], str):
                loc['state_variables'] = json.loads(loc['state_variables'])
        return locations

    # --- NPC Management ---

    async def create_npc(
        self, npc_id: str, name: str, persona: str,
        guild_id: str, location_id: str, hp: int, attack: int,
        description: Optional[str] = None, stats: Optional[Dict[str, Any]] = None,
        archetype: str = "commoner"
    ) -> Optional[Dict[str, Any]]:
        """Creates a new NPC."""
        npc_stats = stats if stats else {}
        if 'attack' not in npc_stats: # Store attack in stats if not provided there
             npc_stats['attack'] = attack

        final_description = description if description else persona

        sql = """
            INSERT INTO npcs (id, name, description, guild_id, location_id, health, max_health, stats, archetype, is_alive)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        # Note: 'attack' column is not directly in npcs table in existing schema, it's part of stats.
        params = (
            npc_id, name, final_description, guild_id, location_id,
            hp, hp, # current health and max health
            json.dumps(npc_stats), archetype, 1 # is_alive = True
        )
        await self.adapter.execute(sql, params)
        return await self.get_npc(npc_id, guild_id)

    async def get_npc(self, npc_id: str, guild_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Retrieves an NPC by its ID."""
        sql = "SELECT * FROM npcs WHERE id = ?"
        params = (npc_id,)
        if guild_id:
            sql += " AND guild_id = ?"
            params = (npc_id, guild_id)

        row = await self.adapter.fetchone(sql, params)
        npc = self._row_to_dict(row)
        if npc:
            if npc.get('stats') and isinstance(npc['stats'], str):
                npc['stats'] = json.loads(npc['stats'])
            if npc.get('inventory') and isinstance(npc['inventory'], str):
                npc['inventory'] = json.loads(npc['inventory'])
            if npc.get('status_effects') and isinstance(npc['status_effects'], str):
                npc['status_effects'] = json.loads(npc['status_effects'])
        return npc

    async def get_npcs_in_location(self, location_id: str, guild_id: str) -> List[Dict[str, Any]]:
        """Retrieves all NPCs in a specific location within a guild."""
        sql = "SELECT * FROM npcs WHERE location_id = ? AND guild_id = ?"
        rows = await self.adapter.fetchall(sql, (location_id, guild_id))
        npcs_list = self._rows_to_dicts(rows)
        for npc_data in npcs_list:
            if npc_data.get('stats') and isinstance(npc_data['stats'], str):
                npc_data['stats'] = json.loads(npc_data['stats'])
            if npc_data.get('inventory') and isinstance(npc_data['inventory'], str):
                npc_data['inventory'] = json.loads(npc_data['inventory'])
        return npcs_list

    # --- Log Management (using 'game_logs' table) ---

    async def add_log_entry(
        self, guild_id: str, event_type: str, message: str,
        player_id_column: Optional[str] = None, # Name changed to avoid conflict with actual player_id if it's in related_entities
        related_entities: Optional[Dict[str, Any]] = None,
        context_data: Optional[Dict[str, Any]] = None,
        channel_id: Optional[int] = None
    ) -> None:
        """Adds a new entry to the game_logs table."""
        import uuid
        log_id = str(uuid.uuid4()) # Generate unique log ID

        # The schema for game_logs has player_id as a direct column.
        # The prompt had `player_id: Optional[str] = None`
        # Let's use player_id_column as the parameter that maps to the player_id column in the table.
        sql = """
            INSERT INTO game_logs (log_id, timestamp, guild_id, channel_id, player_id, event_type, message, related_entities, context_data)
            VALUES (?, strftime('%s','now'), ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            log_id, guild_id, channel_id, player_id_column, event_type, message,
            json.dumps(related_entities) if related_entities else '{}',
            json.dumps(context_data) if context_data else '{}'
        )
        await self.adapter.execute(sql, params)

    async def get_last_player_log(self, player_id: str, guild_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves the most recent game log entry for a specific player.
        Assumes 'player_id' is a direct column in 'game_logs'.
        """
        # This query assumes 'player_id' column exists in game_logs table.
        # This needs to be added via a migration if not already present.
        # Migration v3 for game_logs in SqliteAdapter does NOT include player_id.
        # This method will likely fail or return None until schema is updated.
        sql = "SELECT * FROM game_logs WHERE guild_id = ? AND player_id = ? ORDER BY timestamp DESC LIMIT 1"
        row = await self.adapter.fetchone(sql, (guild_id, player_id))
        log_entry = self._row_to_dict(row)
        if log_entry:
            if log_entry.get('related_entities') and isinstance(log_entry['related_entities'], str):
                log_entry['related_entities'] = json.loads(log_entry['related_entities'])
            if log_entry.get('context_data') and isinstance(log_entry['context_data'], str):
                log_entry['context_data'] = json.loads(log_entry['context_data'])
        return log_entry

    # --- Item Instance Management ---

    async def get_item_instances_in_location(self, location_id: str, guild_id: str) -> List[Dict[str, Any]]:
        """
        Retrieves item instances present in a specific location.
        Items in a location are designated by owner_type='location' and owner_id=location_id.
        (Alternatively, a direct location_id column on the items table if denormalized).
        This example assumes items table has owner_id (location_id) and owner_type ('location').
        """
        # The items table schema from migration v0_to_v1:
        # id TEXT PRIMARY KEY (instance_id)
        # template_id TEXT NOT NULL (links to item_templates.id)
        # guild_id TEXT NOT NULL
        # owner_id TEXT NULL (this would be the location_id)
        # owner_type TEXT NULL (this would be 'location')
        # location_id TEXT NULL (this is redundant if owner_id/owner_type is used for location items)
        # quantity REAL DEFAULT 1.0
        # state_variables TEXT DEFAULT '{}'
        # For items on the ground, let's use owner_id = location_id and owner_type = 'location'.
        # The `location_id` column on `items` table is for when an item instance might be *inside* a container
        # that itself is in a location, while the item still belongs to a player, for example.
        # Or, if items can just be "at" a location without a specific owner entity.
        # For simplicity, let's assume items directly in a location have:
        # owner_id = location_id, owner_type = 'location', AND location_id = location_id.
        # Or more simply, just use the dedicated `location_id` column if items are "loose".
        # The prompt suggested: Filters by location_id, guild_id, and potentially owner_type='location'
        # Let's use `items.location_id` for items on the ground, and assume `owner_id` would be NULL for such items.

        sql = """
            SELECT i.id as item_instance_id, i.template_id, i.quantity, i.state_variables,
                   it.name, it.description, it.type as item_type, it.properties
            FROM items i
            JOIN item_templates it ON i.template_id = it.id
            WHERE i.location_id = ? AND i.guild_id = ?
        """
        # Add more specific conditions if needed, e.g., AND i.owner_id IS NULL
        # This implies items with a location_id are "on the ground".

        rows = await self.adapter.fetchall(sql, (location_id, guild_id))
        items_in_location = self._rows_to_dicts(rows)

        for item in items_in_location:
            if item.get('properties') and isinstance(item['properties'], str):
                item['properties'] = json.loads(item['properties'])
            if item.get('state_variables') and isinstance(item['state_variables'], str):
                item['state_variables'] = json.loads(item['state_variables'])
        return items_in_location

    async def delete_item_instance(self, item_instance_id: str, guild_id: str) -> bool:
        """
        Deletes an item instance from the 'items' table by its unique instance ID.
        Ensures the item belongs to the correct guild for an extra layer of safety,
        though item_instance_id should be globally unique (e.g., UUID).
        """
        # The `items` table PK is `id`.
        sql_check = "SELECT id FROM items WHERE id = ? AND guild_id = ?"
        row = await self.adapter.fetchone(sql_check, (item_instance_id, guild_id))
        if not row:
            print(f"DBService: Item instance {item_instance_id} not found in guild {guild_id} for deletion.")
            return False

        sql_delete = "DELETE FROM items WHERE id = ?"
        try:
            await self.adapter.execute(sql_delete, (item_instance_id,))
            # Check if deletion was successful (optional, execute would raise error on failure)
            # For example, by checking cursor.rowcount if the adapter exposed it easily.
            # For now, assume success if no exception.
            print(f"DBService: Deleted item instance {item_instance_id} from guild {guild_id}.")
            return True
        except Exception as e:
            print(f"DBService: Error deleting item instance {item_instance_id}: {e}")
            # Consider logging the error more formally
            return False
