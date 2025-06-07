# bot/services/db_service.py
import json
import traceback # Added for update_player_field
from typing import Optional, List, Dict, Any
# import aiosqlite # No longer required for aiosqlite.Row type hint

from bot.database.postgres_adapter import PostgresAdapter

class DBService:
    """
    Service layer for database operations, abstracting the PostgresAdapter.
    Handles data conversion (e.g., JSON string to dict) where necessary.
    PostgresAdapter methods fetchone/fetchall now return dicts directly.
    """

    def __init__(self):
        self.adapter = PostgresAdapter()

    async def connect(self) -> None:
        """Connects to the database."""
        await self.adapter.connect()

    async def close(self) -> None:
        """Closes the database connection."""
        await self.adapter.close()

    async def initialize_database(self) -> None:
        """Initializes the database schema by running migrations."""
        await self.adapter.initialize_database()

    # _row_to_dict and _rows_to_dicts are no longer needed as PostgresAdapter
    # methods fetchone() and fetchall() return dicts directly.

    # --- Player/Character Management ---

    async def get_player_by_discord_id(self, discord_user_id: int, guild_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a player by their Discord User ID and Guild ID."""
        # Assuming target schema has 'players' table similar to 'characters'
        # PostgresAdapter uses $1, $2 placeholders. Adapter handles this.
        sql = "SELECT * FROM players WHERE discord_user_id = $1 AND guild_id = $2"
        player = await self.adapter.fetchone(sql, (discord_user_id, guild_id))
        # player = self._row_to_dict(row) # No longer needed
        if player and player.get('stats') and isinstance(player['stats'], str):
            player['stats'] = json.loads(player['stats'])
        # Add other JSON deserializations if needed (e.g., inventory if it were a JSON column)
        return player

    async def update_player_field(self, player_id: str, field_name: str, value: Any, guild_id: str) -> bool:
        """
        Updates a specific field for a player in the 'players' table.
        Ensures the player belongs to the correct guild.
        Handles JSON serialization for dict/list values.
        """
        if not self.adapter:
            print(f"DBService: Adapter not available. Cannot update player field for {player_id}.")
            return False

        # Basic validation for field_name to prevent SQL injection if it were less controlled.
        # Here, assuming field_name is from a predefined set and safe.
        valid_fields = [
            'name', 'race', 'location_id', 'hp', 'mp', 'attack', 'defense', 'stats',
            'inventory', 'current_action', 'action_queue', 'party_id', 'state_variables',
            'is_alive', 'status_effects', 'level', 'experience', 'unspent_xp',
            'active_quests', 'known_spells', 'spell_cooldowns',
            'skills_data_json', 'abilities_data_json', 'spells_data_json', 'character_class', 'flags_json',
            'selected_language', 'current_game_status', 'collected_actions_json', 'current_party_id'
        ]
        if field_name not in valid_fields:
            print(f"DBService: Invalid field_name '{field_name}' for player update.")
            return False

        processed_value = value
        if isinstance(value, (dict, list)):
            processed_value = json.dumps(value)

        # Check if player exists in the guild
        sql_check = "SELECT id FROM players WHERE id = $1 AND guild_id = $2"
        player_exists = await self.adapter.fetchone(sql_check, (player_id, guild_id))
        if not player_exists:
            print(f"DBService: Player {player_id} not found in guild {guild_id} for field update.")
            return False

        # Construct and execute the update query
        # Use $1 for value, $2 for player_id, $3 for guild_id to match params order
        sql_update = f"UPDATE players SET {field_name} = $1 WHERE id = $2 AND guild_id = $3"
        try:
            status = await self.adapter.execute(sql_update, (processed_value, player_id, guild_id))
            # Assuming status "UPDATE 1" means success
            if isinstance(status, str) and status.startswith("UPDATE ") and int(status.split(" ")[1]) > 0:
                print(f"DBService: Successfully updated field '{field_name}' for player {player_id} in guild {guild_id}.")
                return True
            elif isinstance(status, str) and status == "UPDATE 0":
                print(f"DBService: Field update for player {player_id} ran, but no rows affected (already correct value or race condition?).")
                return True # Or False, depending on desired strictness
            else:
                print(f"DBService: Player field update for {player_id} completed with status: {status}. Assuming success if no error.")
                return True # Default to true if command ran
        except Exception as e:
            print(f"DBService: Error updating field '{field_name}' for player {player_id}: {e}")
            traceback.print_exc()
            return False

    async def create_player(
        self, discord_user_id: int, name: str, race: str,
        guild_id: str, location_id: str, hp: int, mp: int,
        attack: int, defense: int, stats: Optional[Dict[str, Any]] = None,
        player_id: Optional[str] = None, # Allow providing an ID, e.g. UUID
        level: int = 1, experience: int = 0, unspent_xp: int = 0
    ) -> Optional[Dict[str, Any]]:
        """
        Creates a new player in the 'players' table.
        Returns the created player data including the ID.
        A unique player_id should be provided; if not, a simple one is generated.
        """
        if not player_id:
            player_id = f"{guild_id}-{discord_user_id}" # Example composite ID, consider UUIDs for production

        # PostgresAdapter uses $1, $2 placeholders.
        sql = """
            INSERT INTO players (id, discord_user_id, name, race, guild_id, location_id, hp, mp, attack, defense, stats, experience, level, unspent_xp)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
            RETURNING id;
        """ # Added RETURNING id
        params = (
            player_id, discord_user_id, name, race, guild_id, location_id,
            hp, mp, attack, defense, json.dumps(stats) if stats else '{}',
            experience, level, unspent_xp
        )
        # Use execute_insert if you expect a return value like the ID.
        # If player_id is already known and set, execute is fine.
        # Given RETURNING id, execute_insert is appropriate.
        inserted_id = await self.adapter.execute_insert(sql, params)
        if inserted_id: # Check if ID was returned
            return await self.get_player_data(player_id) # Fetch using original player_id
        return None # Or handle error if insert failed to return ID as expected


    async def update_player_location(self, player_id: str, new_location_id: str) -> None:
        """Updates the location_id for a given player."""
        sql = "UPDATE players SET location_id = $1 WHERE id = $2"
        await self.adapter.execute(sql, (new_location_id, player_id))

    async def get_player_inventory(self, player_id: str) -> List[Dict[str, Any]]:
        """Retrieves a player's inventory from the 'inventory' table."""
        # PostgresAdapter uses $1, $2 placeholders.
        sql = """
            SELECT inv.item_template_id, inv.amount, it.name, it.description, it.type as item_type, it.properties
            FROM inventory inv
            JOIN item_templates it ON inv.item_template_id = it.id
            WHERE inv.player_id = $1
        """
        inventory_items = await self.adapter.fetchall(sql, (player_id,))
        # inventory_items = self._rows_to_dicts(rows) # No longer needed
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

        # PostgresAdapter uses $1, $2 placeholders.
        sql_select = "SELECT amount, inventory_id FROM inventory WHERE player_id = $1 AND item_template_id = $2"
        row = await self.adapter.fetchone(sql_select, (player_id, item_template_id))

        if row:
            new_amount = row['amount'] + amount
            existing_inventory_id = row['inventory_id']
            sql_update = "UPDATE inventory SET amount = $1 WHERE inventory_id = $2"
            await self.adapter.execute(sql_update, (new_amount, existing_inventory_id))
        else:
            sql_insert = "INSERT INTO inventory (inventory_id, player_id, item_template_id, amount) VALUES ($1, $2, $3, $4)"
            await self.adapter.execute(sql_insert, (inventory_id, player_id, item_template_id, amount))

    async def remove_item_from_inventory(self, player_id: str, item_template_id: str, amount: int) -> None:
        """Removes an item from a player's inventory or reduces its amount."""
        # PostgresAdapter uses $1, $2 placeholders.
        sql_select = "SELECT amount, inventory_id FROM inventory WHERE player_id = $1 AND item_template_id = $2"
        row = await self.adapter.fetchone(sql_select, (player_id, item_template_id))

        if row:
            current_amount = row['amount']
            existing_inventory_id = row['inventory_id']
            if current_amount <= amount:
                sql_delete = "DELETE FROM inventory WHERE inventory_id = $1"
                await self.adapter.execute(sql_delete, (existing_inventory_id,))
            else:
                new_amount = current_amount - amount
                sql_update = "UPDATE inventory SET amount = $1 WHERE inventory_id = $2"
                await self.adapter.execute(sql_update, (new_amount, existing_inventory_id))

    async def get_player_data(self, player_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves generic player data by their internal player ID."""
        # PostgresAdapter uses $1 placeholder.
        sql = "SELECT * FROM players WHERE id = $1"
        player = await self.adapter.fetchone(sql, (player_id,))
        # player = self._row_to_dict(row) # No longer needed
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
        # PostgresAdapter uses $1, $2 placeholders.
        sql = """
            INSERT INTO item_templates (id, name, description, type, properties)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id;
        """ # Added RETURNING id
        params = (item_id, name, description, item_type, json.dumps(properties_data))
        inserted_id = await self.adapter.execute_insert(sql, params)
        if inserted_id:
            return await self.get_item_definition(item_id) # Fetch using original item_id
        return None

    async def get_item_definition(self, item_id: str) -> Optional[Dict[str, Any]]: # Renamed from get_item_template
        """Retrieves an item definition by its ID from 'item_templates'."""
        # PostgresAdapter uses $1 placeholder.
        sql = "SELECT * FROM item_templates WHERE id = $1"
        item_def = await self.adapter.fetchone(sql, (item_id,))
        # item_def = self._row_to_dict(row) # No longer needed
        if item_def and item_def.get('properties') and isinstance(item_def['properties'], str):
            item_def['properties'] = json.loads(item_def['properties'])
        return item_def

    async def get_all_item_definitions(self) -> List[Dict[str, Any]]: # Renamed from get_all_item_templates
        """Retrieves all item definitions from 'item_templates'."""
        sql = "SELECT * FROM item_templates"
        item_defs = await self.adapter.fetchall(sql)
        # item_defs = self._rows_to_dicts(rows) # No longer needed
        for item_def in item_defs:
            if item_def.get('properties') and isinstance(item_def['properties'], str):
                item_def['properties'] = json.loads(item_def['properties'])
        return item_defs

    # --- Location Management ---

    async def create_location(
        self, loc_id: str, name_i18n: Dict[str, str], description_i18n: Dict[str, str], guild_id: str,
        exits: Optional[Dict[str, str]] = None, template_id: str = "default",
        properties: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """Creates a new location instance."""
        # PostgresAdapter uses $1, $2 placeholders.
        # Assuming 'name_i18n' column exists or will be added, and 'descriptions_i18n' for description.
        sql = """
            INSERT INTO locations (id, template_id, name_i18n, descriptions_i18n, guild_id, exits, state_variables, is_active)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id;
        """ # Added RETURNING id
        params = (
            loc_id, template_id, json.dumps(name_i18n), json.dumps(description_i18n), guild_id,
            json.dumps(exits) if exits else '{}',
            json.dumps(properties) if properties else '{}', True  # Changed 1 to True for PostgreSQL boolean
        )
        inserted_id = await self.adapter.execute_insert(sql, params)
        if inserted_id:
            return await self.get_location(loc_id, guild_id) # Fetch using original loc_id
        return None

    async def get_location(self, location_id: str, guild_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Retrieves a location by its ID."""
        # PostgresAdapter uses $1, $2 placeholders.
        sql = "SELECT * FROM locations WHERE id = $1"
        params_list = [location_id]
        if guild_id:
            sql += " AND guild_id = $2"
            params_list.append(guild_id)

        location = await self.adapter.fetchone(sql, tuple(params_list))
        # location = self._row_to_dict(row) # No longer needed
        if location:
            if location.get('exits') and isinstance(location['exits'], str):
                location['exits'] = json.loads(location['exits'])
            if location.get('state_variables') and isinstance(location['state_variables'], str):
                location['state_variables'] = json.loads(location['state_variables'])
        return location

    async def get_all_locations(self, guild_id: str) -> List[Dict[str, Any]]:
        """Retrieves all locations for a given guild."""
        # PostgresAdapter uses $1 placeholder.
        sql = "SELECT * FROM locations WHERE guild_id = $1"
        locations = await self.adapter.fetchall(sql, (guild_id,))
        # locations = self._rows_to_dicts(rows) # No longer needed
        for loc in locations:
            if loc.get('exits') and isinstance(loc['exits'], str):
                loc['exits'] = json.loads(loc['exits'])
            if loc.get('state_variables') and isinstance(loc['state_variables'], str):
                loc['state_variables'] = json.loads(loc['state_variables'])
        return locations

    # --- NPC Management ---

    async def create_npc(
        self, npc_id: str, guild_id: str, template_id: str,
        name_i18n: Dict[str, str], stats: Dict[str, Any],
        location_id: Optional[str] = None,
        description_i18n: Optional[Dict[str, str]] = None,
        persona_i18n: Optional[Dict[str, str]] = None,
        backstory_i18n: Optional[Dict[str, str]] = None,
        archetype: Optional[str] = "commoner",
        inventory: Optional[List[str]] = None, # Simple list of item IDs
        current_action: Optional[Dict[str, Any]] = None, # Changed from str to Dict
        action_queue: Optional[List[Any]] = None,
        party_id: Optional[str] = None,
        state_variables: Optional[Dict[str, Any]] = None,
        status_effects: Optional[List[str]] = None,
        is_temporary: bool = False,
        traits: Optional[List[str]] = None,
        desires: Optional[List[str]] = None,
        motives: Optional[List[str]] = None,
        **kwargs # For other potential fields like skills_data, equipment_data etc. from CampaignLoader
    ) -> Optional[Dict[str, Any]]:
        """Creates a new NPC, aligning with the updated npcs table schema."""

        max_health = float(stats.get('max_health', 50.0))
        current_health = float(stats.get('health', max_health)) # Current health can also be in stats or default to max

        skills_data = kwargs.get('skills_data')
        equipment_data = kwargs.get('equipment_data')
        abilities_data = kwargs.get('abilities_data')
        faction = kwargs.get('faction')
        behavior_tags = kwargs.get('behavior_tags')
        loot_table_id = kwargs.get('loot_table_id')

        skills_data_json = json.dumps(skills_data) if skills_data is not None else None
        equipment_data_json = json.dumps(equipment_data) if equipment_data is not None else None
        abilities_data_json = json.dumps(abilities_data) if abilities_data is not None else None
        faction_json = json.dumps(faction) if faction is not None else None
        behavior_tags_json = json.dumps(behavior_tags) if behavior_tags is not None else None
        # loot_table_id is a string, so no json.dumps needed if it's directly passed

        # Prepare data for JSON fields, ensuring None becomes empty JSON object/array
        name_i18n_json = json.dumps(name_i18n or {})
        description_i18n_json = json.dumps(description_i18n or {})
        persona_i18n_json = json.dumps(persona_i18n or {}) # Assuming persona_i18n is a new field
        backstory_i18n_json = json.dumps(backstory_i18n or {})
        stats_json = json.dumps(stats or {})
        inventory_json = json.dumps(inventory or [])
        current_action_json = json.dumps(current_action) if current_action is not None else None # Can be NULL in DB
        action_queue_json = json.dumps(action_queue or [])
        state_variables_json = json.dumps(state_variables or {})
        status_effects_json = json.dumps(status_effects or [])
        traits_json = json.dumps(traits or [])
        desires_json = json.dumps(desires or [])
        motives_json = json.dumps(motives or [])

        # Note: 'name' and 'description' simple text columns are no longer primary for i18n.
        # The 'npcs' table schema from migration 6d887g92h0f1 uses i18n columns.
        # Old 'name' and 'description' columns might be removed by a future migration if fully unused.
        # For now, this create_npc will not populate them.

        sql = """
            INSERT INTO npcs (
                id, template_id, guild_id, location_id,
                name_i18n, description_i18n, persona_i18n, backstory_i18n,
                stats, inventory, current_action, action_queue, party_id,
                state_variables, health, max_health, is_alive, status_effects,
                is_temporary, archetype, traits, desires, motives, skills_data, equipment_data, abilities_data, faction, behavior_tags, loot_table_id
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25, $26, $27, $28, $29)
            RETURNING id;
        """
        params = (
            npc_id, template_id, guild_id, location_id,
            name_i18n_json, description_i18n_json, persona_i18n_json, backstory_i18n_json,
            stats_json, inventory_json, current_action_json, action_queue_json, party_id,
            state_variables_json, current_health, max_health, True, status_effects_json,
            is_temporary, archetype, traits_json, desires_json, motives_json, skills_data_json, equipment_data_json, abilities_data_json, faction_json, behavior_tags_json, loot_table_id
        )

        inserted_id = await self.adapter.execute_insert(sql, params)
        if inserted_id:
            # Ensure that the other fields passed in kwargs (like skills_data)
            # are handled if they need to be stored in separate tables or processes.
            # For now, this method only saves to the 'npcs' table.
            # Example: if 'skills_data' was in kwargs, it's ignored by this direct INSERT.
            if kwargs:
                pass

            return await self.get_npc(npc_id, guild_id)
        return None

    async def get_npc(self, npc_id: str, guild_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Retrieves an NPC by its ID."""
        # PostgresAdapter uses $1, $2 placeholders.
        sql = "SELECT * FROM npcs WHERE id = $1"
        params_list = [npc_id]
        if guild_id:
            sql += " AND guild_id = $2"
            params_list.append(guild_id)

        npc = await self.adapter.fetchone(sql, tuple(params_list))
        # npc = self._row_to_dict(row) # No longer needed
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
        # PostgresAdapter uses $1, $2 placeholders.
        sql = "SELECT * FROM npcs WHERE location_id = $1 AND guild_id = $2"
        npcs_list = await self.adapter.fetchall(sql, (location_id, guild_id))
        # npcs_list = self._rows_to_dicts(rows) # No longer needed
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
        # PostgresAdapter uses $1, $2 placeholders. For timestamp, use NOW() or equivalent.
        sql = """
            INSERT INTO game_logs (log_id, timestamp, guild_id, channel_id, player_id, event_type, message, related_entities, context_data)
            VALUES ($1, NOW(), $2, $3, $4, $5, $6, $7, $8)
        """
        # Note: strftime('%s','now') is SQLite specific. NOW() is standard SQL for current timestamp.
        # asyncpg will handle Python datetime objects correctly if passed for timestamp fields.
        # For simplicity, letting the DB handle timestamp with NOW().
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
        # PostgresAdapter uses $1, $2 placeholders.
        sql = "SELECT * FROM game_logs WHERE guild_id = $1 AND player_id = $2 ORDER BY timestamp DESC LIMIT 1"
        log_entry = await self.adapter.fetchone(sql, (guild_id, player_id))
        # log_entry = self._row_to_dict(row) # No longer needed
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
            WHERE i.location_id = $1 AND i.guild_id = $2
        """
        # Add more specific conditions if needed, e.g., AND i.owner_id IS NULL
        # This implies items with a location_id are "on the ground".

        items_in_location = await self.adapter.fetchall(sql, (location_id, guild_id))
        # items_in_location = self._rows_to_dicts(rows) # No longer needed

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
        # PostgresAdapter uses $1, $2 placeholders.
        sql_check = "SELECT id FROM items WHERE id = $1 AND guild_id = $2"
        row = await self.adapter.fetchone(sql_check, (item_instance_id, guild_id))
        if not row:
            print(f"DBService: Item instance {item_instance_id} not found in guild {guild_id} for deletion.")
            return False

        sql_delete = "DELETE FROM items WHERE id = $1" # Use $1 for placeholder
        try:
            # Pass parameters as a tuple
            await self.adapter.execute(sql_delete, (item_instance_id,))
            # Check if deletion was successful (optional, execute would raise error on failure)
            # For example, by checking status string from adapter.execute if it provides row count like "DELETE 1"
            # For now, assume success if no exception.
            print(f"DBService: Deleted item instance {item_instance_id} from guild {guild_id}.")
            return True
        except Exception as e:
            print(f"DBService: Error deleting item instance {item_instance_id}: {e}")
            # Consider logging the error more formally
            return False

    # --- HP Update Methods ---
    async def update_npc_hp(self, npc_id: str, new_hp: int, guild_id: str) -> bool:
        """Updates the current health of an NPC."""
        # Ensure HP doesn't go below 0 or above max_health if that logic is here
        # For now, just setting it. Max health check might be in game logic.
        # Also, ensure NPC belongs to the guild for safety.
        # PostgresAdapter uses $1, $2 placeholders.
        sql_check = "SELECT id FROM npcs WHERE id = $1 AND guild_id = $2"
        row = await self.adapter.fetchone(sql_check, (npc_id, guild_id))
        if not row:
            print(f"DBService: NPC {npc_id} not found in guild {guild_id} for HP update.")
            return False

        sql = "UPDATE npcs SET health = $1 WHERE id = $2 AND guild_id = $3"
        try:
            await self.adapter.execute(sql, (max(0, new_hp), npc_id, guild_id)) # Prevent negative HP in DB
            # Check status from execute if it indicates rows affected, e.g., "UPDATE 1"
            print(f"DBService: Updated NPC {npc_id} HP to {new_hp} in guild {guild_id}.")
            return True
        except Exception as e:
            print(f"DBService: Error updating NPC {npc_id} HP: {e}")
            return False

    async def update_player_hp(self, player_id: str, new_hp: int, guild_id: str) -> bool:
        """Updates the current HP of a player."""
        # Ensure HP doesn't go below 0 or above max_hp if that logic is here
        # players table has 'hp' column from migration v4
        # PostgresAdapter uses $1, $2 placeholders.
        sql_check = "SELECT id FROM players WHERE id = $1 AND guild_id = $2"
        row = await self.adapter.fetchone(sql_check, (player_id, guild_id))
        if not row:
            print(f"DBService: Player {player_id} not found in guild {guild_id} for HP update.")
            return False

        sql = "UPDATE players SET hp = $1 WHERE id = $2 AND guild_id = $3"
        try:
            await self.adapter.execute(sql, (max(0, new_hp), player_id, guild_id)) # Prevent negative HP
            # Check status from execute if it indicates rows affected
            print(f"DBService: Updated Player {player_id} HP to {new_hp} in guild {guild_id}.")
            return True
        except Exception as e:
            print(f"DBService: Error updating Player {player_id} HP: {e}")
            return False

    # --- Dialogue Session Management ---

    async def get_or_create_dialogue_session(
        self, player_id: str, npc_id: str, guild_id: str, channel_id: int
    ) -> Dict[str, Any]:
        """
        Retrieves an active dialogue session or creates a new one if none exists.
        A session is identified by the participants (player and NPC) and guild.
        The 'participants' field in the DB should store a sorted list of IDs as a JSON string
        to ensure (player_id, npc_id) and (npc_id, player_id) map to the same session.
        """
        # Sort participant IDs to ensure consistent lookup/storage
        participant_list = sorted([player_id, npc_id])
        participants_json = json.dumps(participant_list)

        sql_find = """
            SELECT id, conversation_history, state_variables, current_stage_id, template_id, is_active
            FROM dialogues
            WHERE participants = $1 AND guild_id = $2 AND is_active = TRUE
            ORDER BY last_activity_game_time DESC LIMIT 1
        """ # Changed is_active = 1 to is_active = TRUE for PostgreSQL boolean type
        # Or, if a session is strictly 1 player + 1 NPC and you want to ensure only one active:
        # WHERE ( (participants LIKE '%' || ? || '%') AND (participants LIKE '%' || ? || '%') ) ...
        # But storing sorted JSON list is cleaner for exact match.

        session = await self.adapter.fetchone(sql_find, (participants_json, guild_id))
        # session = self._row_to_dict(row) # No longer needed

        if session: # row is now session (already a dict)
            if session.get('conversation_history') and isinstance(session['conversation_history'], str):
                session['conversation_history'] = json.loads(session['conversation_history'])
            else:
                session['conversation_history'] = [] # Ensure it's a list

            if session.get('state_variables') and isinstance(session['state_variables'], str):
                session['state_variables'] = json.loads(session['state_variables'])
            else:
                session['state_variables'] = {}

            # Update last activity time (optional, could be separate method)
            # For now, let's assume it's handled by update_dialogue_history or another mechanism
            return session

        # No active session found, create a new one
        import uuid
        import time
        dialogue_id = str(uuid.uuid4())
        current_time = time.time() # Using real time for last_activity for now

        sql_create = """
            INSERT INTO dialogues (
                id, guild_id, participants, channel_id,
                conversation_history, state_variables, is_active,
                last_activity_game_time, current_stage_id, template_id
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING id;
        """ # Added RETURNING id, changed placeholders, is_active = TRUE
        # template_id and current_stage_id might come from NPC's default dialogue or be None initially
        initial_history = []
        initial_state_vars = {}

        params = (
            dialogue_id, guild_id, participants_json, channel_id,
            json.dumps(initial_history), json.dumps(initial_state_vars), True, # is_active = True (boolean)
            current_time, None, None # current_stage_id, template_id (can be set later)
        )
        # Use execute_insert if RETURNING id is important, otherwise execute is fine
        await self.adapter.execute_insert(sql_create, params) # Assuming we want the ID for some reason, or just use execute

        return {
            "id": dialogue_id,
            "guild_id": guild_id,
            "participants": participant_list, # Return as list
            "channel_id": channel_id,
            "conversation_history": initial_history,
            "state_variables": initial_state_vars,
            "is_active": 1,
            "last_activity_game_time": current_time,
            "current_stage_id": None,
            "template_id": None
        }

    async def update_dialogue_history(self, dialogue_id: str, new_history_entry: Dict[str, str]) -> bool:
        """
        Appends a new entry to the conversation_history of a dialogue session.
        Also updates last_activity_game_time.
        """
        # PostgresAdapter uses $1 placeholder.
        sql_get_history = "SELECT conversation_history FROM dialogues WHERE id = $1"
        dialogue_data = await self.adapter.fetchone(sql_get_history, (dialogue_id,))

        if not dialogue_data:
            print(f"DBService: Dialogue session {dialogue_id} not found for history update.")
            return False

        current_history_json = dialogue_data['conversation_history']
        try:
            current_history = json.loads(current_history_json) if current_history_json and isinstance(current_history_json, str) else (current_history_json if isinstance(current_history_json, list) else [])
        except json.JSONDecodeError:
            current_history = [] # Start fresh if JSON is corrupted

        if not isinstance(current_history, list): # Ensure it's a list
            current_history = []

        current_history.append(new_history_entry)

        import time # Using real time for simplicity
        current_time = time.time() # Consider using database's NOW() for consistency

        # PostgresAdapter uses $1, $2, $3 placeholders.
        sql_update = "UPDATE dialogues SET conversation_history = $1, last_activity_game_time = $2 WHERE id = $3"
        try:
            # For PostgreSQL, last_activity_game_time should ideally be a timestamp column.
            # If current_time is float (epoch), ensure DB column type is compatible (e.g., numeric or timestamp correctly handled by asyncpg).
            # Using NOW() in the query itself might be better: last_activity_game_time = NOW()
            await self.adapter.execute(sql_update, (json.dumps(current_history), current_time, dialogue_id))
            # Check status from execute if it indicates rows affected
            print(f"DBService: Updated dialogue history for session {dialogue_id}.")
            return True
        except Exception as e:
            print(f"DBService: Error updating dialogue history for session {dialogue_id}: {e}")
            return False

    async def set_dialogue_history(self, dialogue_id: str, full_history: List[Dict[str, str]]) -> bool:
        """
        Overwrites the entire conversation_history of a dialogue session with a new list.
        Also updates last_activity_game_time.
        Useful for operations like undo where the history is manipulated externally.
        """
        import time # Using real time for simplicity
        current_time = time.time() # Or NOW()

        # PostgresAdapter uses $1, $2, $3 placeholders.
        sql_update = "UPDATE dialogues SET conversation_history = $1, last_activity_game_time = $2 WHERE id = $3"
        try:
            await self.adapter.execute(sql_update, (json.dumps(full_history), current_time, dialogue_id))
            # Check status from execute
            print(f"DBService: Set (overwrote) dialogue history for session {dialogue_id}.")
            return True
        except Exception as e:
            print(f"DBService: Error setting (overwriting) dialogue history for session {dialogue_id}: {e}")
            return False

    # --- Undo Functionality Methods ---

    async def get_last_undoable_player_action(self, player_id: str, guild_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetches the most recent log entry for a player that has not been undone.
        The player_id here refers to the 'player_id' column in 'game_logs' table.
        """
        # PostgresAdapter uses $1, $2 placeholders.
        sql = """
            SELECT log_id, event_type, context_data, related_entities, message, timestamp
            FROM game_logs
            WHERE player_id = $1 AND guild_id = $2 AND is_undone = FALSE
            ORDER BY timestamp DESC
            LIMIT 1
        """ # Changed is_undone = 0 to is_undone = FALSE for PostgreSQL boolean
        log_entry = await self.adapter.fetchone(sql, (player_id, guild_id))
        # log_entry = self._row_to_dict(row) # No longer needed
        if log_entry:
            if log_entry.get('context_data') and isinstance(log_entry['context_data'], str):
                log_entry['context_data'] = json.loads(log_entry['context_data'])
            if log_entry.get('related_entities') and isinstance(log_entry['related_entities'], str):
                log_entry['related_entities'] = json.loads(log_entry['related_entities'])
        return log_entry

    async def mark_log_as_undone(self, log_id: str, guild_id: str) -> bool:
        """Marks a specific log entry as undone."""
        # PostgresAdapter uses $1, $2 placeholders.
        sql_check = "SELECT log_id FROM game_logs WHERE log_id = $1 AND guild_id = $2"
        row = await self.adapter.fetchone(sql_check, (log_id, guild_id))
        if not row:
            print(f"DBService: Log entry {log_id} not found in guild {guild_id} to mark as undone.")
            return False

        sql = "UPDATE game_logs SET is_undone = TRUE WHERE log_id = $1 AND guild_id = $2" # is_undone = TRUE
        try:
            await self.adapter.execute(sql, (log_id, guild_id))
            # Check status from execute
            print(f"DBService: Marked log entry {log_id} as undone for guild {guild_id}.")
            return True
        except Exception as e:
            print(f"DBService: Error marking log entry {log_id} as undone: {e}")
            return False

    async def create_item_instance(
        self,
        template_id: str,
        guild_id: str,
        quantity: int,
        location_id: Optional[str] = None,
        owner_id: Optional[str] = None,
        owner_type: Optional[str] = None,
        state_variables: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        Creates a new item instance in the 'items' table.
        Generates a new UUID for the item instance's id.
        Returns the new item instance id or None on failure.
        """
        import uuid
        item_instance_id = str(uuid.uuid4())

        # PostgresAdapter uses $1, $2, etc. placeholders.
        sql = """
            INSERT INTO items (id, template_id, guild_id, owner_id, owner_type, location_id, quantity, state_variables, is_temporary)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id;
        """ # Added RETURNING id
        # is_temporary defaults to FALSE (0 for SQLite) as per schema if not specified
        params = (
            item_instance_id, template_id, guild_id, owner_id, owner_type,
            location_id, quantity,
            json.dumps(state_variables) if state_variables else '{}',
            False # Default is_temporary to False (boolean for PostgreSQL)
        )
        try:
            # Use execute_insert as we have RETURNING id
            inserted_id = await self.adapter.execute_insert(sql, params)
            if inserted_id == item_instance_id: # Check if returned ID matches generated one
                print(f"DBService: Created item instance {item_instance_id} (template: {template_id}) for guild {guild_id}.")
                return item_instance_id
            else:
                # This case should ideally not happen if DB is consistent
                print(f"DBService: Created item instance for template {template_id}, but ID mismatch: expected {item_instance_id}, got {inserted_id}.")
                return inserted_id # Return the actual ID from DB
        except Exception as e:
            print(f"DBService: Error creating item instance for template {template_id}: {e}")
            return None

    # --- Pending Conflict Management ---

    async def save_pending_conflict(self, conflict_id: str, guild_id: str, conflict_data: str) -> None:
        if not isinstance(conflict_data, str):
             raise TypeError("conflict_data must be a JSON string.")
        # This method will be called by ConflictResolver, which prepares conflict_data as JSON string.
        # The adapter's method (PostgresAdapter) handles specific SQL and placeholders.
        await self.adapter.save_pending_conflict(conflict_id, guild_id, conflict_data)

    async def get_pending_conflict(self, conflict_id: str) -> Optional[Dict[str, Any]]:
        # The adapter's method (PostgresAdapter) returns a dict or None.
        return await self.adapter.get_pending_conflict(conflict_id)

    async def delete_pending_conflict(self, conflict_id: str) -> None:
        await self.adapter.delete_pending_conflict(conflict_id)

    # --- Generic CRUD Operations ---

    async def create_entity(self, table_name: str, data: Dict[str, Any], id_field: str = 'id') -> Optional[str]:
        """
        Creates an entity in the specified table.
        Generates a UUID for the id_field if it's 'id' and not in data.
        Handles JSON serialization for dict/list values.
        Returns the ID of the newly created entity.
        """
        import uuid
        import json

        if id_field == 'id' and 'id' not in data:
            data['id'] = str(uuid.uuid4())

        processed_data = {}
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                processed_data[key] = json.dumps(value)
            else:
                processed_data[key] = value
        
        columns = ', '.join(processed_data.keys())
        placeholders = ', '.join([f'${i+1}' for i in range(len(processed_data))]) # $1, $2, ...
        sql = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})"
        if id_field in data: # If primary key is part of data, add RETURNING clause for it
            sql += f" RETURNING {id_field}"
        
        try:
            # If RETURNING is used, execute_insert is better
            if id_field in data and " RETURNING " in sql:
                returned_val = await self.adapter.execute_insert(sql, tuple(processed_data.values()))
                return returned_val # This will be the ID
            else: # If no RETURNING or not expecting a specific ID back from this call
                await self.adapter.execute(sql, tuple(processed_data.values()))
                return data.get(id_field) # Return pre-generated or provided ID
        except Exception as e:
            # TODO: Log the error appropriately
            print(f"Error creating entity in {table_name}: {e}")
            return None

    async def get_entity(self, table_name: str, entity_id: str, guild_id: Optional[str] = None, id_field: str = 'id') -> Optional[Dict[str, Any]]:
        """
        Retrieves an entity by its ID from the specified table.
        Handles JSON deserialization for string values that are valid JSON.
        """
        import json
        # PostgresAdapter uses $1, $2 placeholders.
        sql = f"SELECT * FROM {table_name} WHERE {id_field} = $1"
        params_list = [entity_id]
        param_idx = 2
        if guild_id:
            sql += f" AND guild_id = ${param_idx}"
            params_list.append(guild_id)
            param_idx +=1

        entity = await self.adapter.fetchone(sql, tuple(params_list))
        # entity = self._row_to_dict(row) # No longer needed

        if entity:
            for key, value in entity.items():
                if isinstance(value, str):
                    try:
                        # Attempt to parse if it looks like a JSON object or array
                        if value.startswith('{') and value.endswith('}'):
                            entity[key] = json.loads(value)
                        elif value.startswith('[') and value.endswith(']'):
                            entity[key] = json.loads(value)
                    except json.JSONDecodeError:
                        # Not a JSON string, leave as is
                        pass
        return entity

    async def update_entity(self, table_name: str, entity_id: str, data: Dict[str, Any], guild_id: Optional[str] = None, id_field: str = 'id') -> bool:
        """
        Updates an entity in the specified table.
        Handles JSON serialization for dict/list values.
        Returns True on success, False otherwise.
        """
        import json
        if not data:
            return False # Nothing to update

        processed_data = {}
        param_idx = 1
        set_clauses = []
        params_list = []

        for key, value in data.items():
            if isinstance(value, (dict, list)):
                set_clauses.append(f"{key} = ${param_idx}::jsonb") # Use ::jsonb for PostgreSQL
                params_list.append(json.dumps(value))
            else:
                set_clauses.append(f"{key} = ${param_idx}")
                params_list.append(value)
            param_idx += 1
        
        set_clause_str = ', '.join(set_clauses)
        sql = f"UPDATE {table_name} SET {set_clause_str} WHERE {id_field} = ${param_idx}"
        params_list.append(entity_id)
        param_idx +=1

        if guild_id:
            sql += f" AND guild_id = ${param_idx}"
            params_list.append(guild_id)
            param_idx +=1

        try:
            result_status = await self.adapter.execute(sql, tuple(params_list))
            # PostgresAdapter.execute returns a status string like "UPDATE 1"
            # We can check this status to see if any row was actually updated.
            # For generic update, let's assume "UPDATE" is in the status if successful,
            # and the number of rows affected is non-zero.
            # For simplicity, we'll check if "UPDATE" is in the status.
            # A more precise check would parse the number of affected rows.
            if isinstance(result_status, str) and "UPDATE" in result_status.upper():
                # Check if the count is non-zero, e.g., "UPDATE 1" vs "UPDATE 0"
                parts = result_status.upper().split()
                if len(parts) > 1 and parts[0] == "UPDATE":
                    try:
                        if int(parts[1]) > 0:
                            return True # Rows were updated
                        else:
                            # Command succeeded but no rows matched the WHERE clause
                            # This might or might not be considered a "successful update"
                            # depending on expectations. For now, let's say True if command ran.
                            return True # Or False, if strict "something changed" is needed
                    except ValueError: # If the part after UPDATE is not a number
                        return True # Fallback: command ran
                return True # Fallback: command ran
            # If result_status is not as expected, or indicates 0 rows updated,
            # it means the command ran but didn't change anything or the status format is different.
            # Consider it True if no exception, as per original logic for aiosqlite.
            return True # Assuming success if execute completes without error
        except Exception as e:
            # TODO: Log the error appropriately
            print(f"Error updating entity {entity_id} in {table_name}: {e}")
            return False

    async def delete_entity(self, table_name: str, entity_id: str, guild_id: Optional[str] = None, id_field: str = 'id') -> bool:
        """
        Deletes an entity by its ID from the specified table.
        Returns True on success, False otherwise.
        """
        # PostgresAdapter uses $1, $2 placeholders.
        sql = f"DELETE FROM {table_name} WHERE {id_field} = $1"
        params_list = [entity_id]
        param_idx = 2

        if guild_id:
            sql += f" AND guild_id = ${param_idx}"
            params_list.append(guild_id)
            param_idx +=1

        try:
            result_status = await self.adapter.execute(sql, tuple(params_list))
            # Check status from execute if it indicates rows affected, e.g., "DELETE 1"
            if isinstance(result_status, str) and "DELETE" in result_status.upper():
                parts = result_status.upper().split()
                if len(parts) > 1 and parts[0] == "DELETE":
                    try:
                        if int(parts[1]) > 0:
                            return True # Rows were deleted
                        else:
                             # Command succeeded but no rows matched
                            return True # Or False if strict "something deleted" is needed
                    except ValueError:
                        return True # Fallback: command ran
                return True # Fallback: command ran
            return True # Assuming success if execute completes without error
        except Exception as e:
            # TODO: Log the error appropriately
            print(f"Error deleting entity {entity_id} from {table_name}: {e}")
            return False

    async def set_guild_setting(self, guild_id: str, setting_key: str, setting_value: Any) -> bool:
        """
        Sets or updates a specific setting for a guild.
        Settings are stored as key-value pairs, with value stored as JSON string.
        """
        if not self.adapter:
            print(f"DBService: Adapter not available. Cannot set guild setting for {guild_id}.")
            return False

        # import json # Already imported at the top
        # import traceback # Already imported at the top

        value_json = json.dumps(setting_value)

        sql = """
            INSERT INTO guild_settings (guild_id, key, value)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id, key) DO UPDATE SET
                value = EXCLUDED.value;
        """
        try:
            status = await self.adapter.execute(sql, (guild_id, setting_key, value_json))
            # Example status strings from asyncpg: "INSERT 0 1", "UPDATE 1"
            if isinstance(status, str) and ("INSERT" in status.upper() or "UPDATE" in status.upper()):
                 if "UPDATE" in status.upper():
                     count_str = status.upper().split("UPDATE")[1].strip()
                     if count_str.isdigit() and int(count_str) > 0:
                         print(f"DBService: Successfully updated setting '{setting_key}' for guild {guild_id}.")
                         return True
                     elif count_str.isdigit() and int(count_str) == 0: # UPSERT did nothing as value was the same
                         print(f"DBService: Setting '{setting_key}' for guild {guild_id} was not updated (no change or key not found for update part of upsert).")
                         return True # Still considered a success as the state is as intended
                 elif "INSERT" in status.upper(): # Check for "INSERT 0 1" specifically for new row
                      parts = status.upper().split()
                      if len(parts) == 3 and parts[0] == "INSERT" and parts[1] == "0" and parts[2] == "1":
                           print(f"DBService: Successfully inserted setting '{setting_key}' for guild {guild_id}.")
                           return True
            # Fallback for other statuses or if parsing status string is too complex/brittle
            print(f"DBService: Setting '{setting_key}' for guild {guild_id} completed with status: {status}. Assuming success if no error and not 'UPDATE 0'.")
            return True
        except Exception as e:
            print(f"DBService: Error setting guild setting '{setting_key}' for guild {guild_id}: {e}")
            traceback.print_exc()
            return False
