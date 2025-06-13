# bot/services/db_service.py
import json
import logging # Added
import traceback # Will be removed where logger.error(exc_info=True) is used
from typing import Optional, List, Dict, Any

from bot.database.postgres_adapter import PostgresAdapter

logger = logging.getLogger(__name__) # Added

class DBService:
    """
    Service layer for database operations, abstracting the PostgresAdapter.
    Handles data conversion (e.g., JSON string to dict) where necessary.
    PostgresAdapter methods fetchone/fetchall now return dicts directly.
    """

    def __init__(self):
        self.adapter = PostgresAdapter()
        logger.info("DBService initialized.") # Added

    async def connect(self) -> None:
        """Connects to the database."""
        await self.adapter.connect()
        logger.info("Database connection established.") # Added

    async def close(self) -> None:
        """Closes the database connection."""
        await self.adapter.close()
        logger.info("Database connection closed.") # Added

    async def initialize_database(self) -> None:
        """Initializes the database schema by running migrations."""
        logger.info("Initializing database schema...") # Added
        await self.adapter.initialize_database()
        logger.info("Database schema initialization complete.") # Added

    async def get_global_state_value(self, key: str) -> Optional[str]:
        """Fetches a single value from the global_state table."""
        if not self.adapter:
            logger.warning("DBService: Adapter not available for get_global_state_value.") # Changed
            return None
        sql = "SELECT value FROM global_state WHERE key = $1"
        try:
            row = await self.adapter.fetchone(sql, (key,))
            if row and row.get('value') is not None:
                return str(row['value'])
        except Exception as e:
            logger.error("DBService: Error fetching global state for key '%s': %s", key, e, exc_info=True) # Changed
        return None

    async def get_player_by_discord_id(self, discord_user_id: int, guild_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a player by their Discord User ID and Guild ID."""
        sql = "SELECT * FROM players WHERE discord_user_id = $1 AND guild_id = $2"
        try: # Added try-except
            player = await self.adapter.fetchone(sql, (discord_user_id, guild_id))
            if player:
                if player.get('stats') and isinstance(player['stats'], str):
                    player['stats'] = json.loads(player['stats'])
            return player
        except Exception as e: # Added
            logger.error("Error fetching player by discord_id %s for guild %s: %s", discord_user_id, guild_id, e, exc_info=True)
            return None


    async def update_player_field(self, player_id: str, field_name: str, value: Any, guild_id: str) -> bool:
        """
        Updates a specific field for a player in the 'players' table.
        Ensures the player belongs to the correct guild.
        Handles JSON serialization for dict/list values.
        """
        if not self.adapter:
            logger.warning("DBService: Adapter not available. Cannot update player field for %s in guild %s.", player_id, guild_id) # Changed
            return False

        valid_fields = [
            'name', 'race', 'location_id', 'hp', 'mp', 'attack', 'defense', 'stats',
            'inventory', 'current_action', 'action_queue', 'party_id', 'state_variables',
            'is_alive', 'status_effects', 'level', 'experience', 'unspent_xp',
            'active_quests', 'known_spells', 'spell_cooldowns',
            'skills_data_json', 'abilities_data_json', 'spells_data_json', 'character_class', 'flags_json',
            'selected_language', 'current_game_status', 'collected_actions_json', 'current_party_id'
        ]
        if field_name not in valid_fields:
            logger.warning("DBService: Invalid field_name '%s' for player update in guild %s.", field_name, guild_id) # Changed
            return False

        processed_value = value
        if isinstance(value, (dict, list)):
            processed_value = json.dumps(value)

        sql_check = "SELECT id FROM players WHERE id = $1 AND guild_id = $2"
        try:
            player_exists = await self.adapter.fetchone(sql_check, (player_id, guild_id))
            if not player_exists:
                logger.warning("DBService: Player %s not found in guild %s for field update.", player_id, guild_id) # Changed
                return False

            sql_update = f"UPDATE players SET {field_name} = $1 WHERE id = $2 AND guild_id = $3"
            status = await self.adapter.execute(sql_update, (processed_value, player_id, guild_id))

            if isinstance(status, str) and status.startswith("UPDATE ") and int(status.split(" ")[1]) > 0:
                logger.info("DBService: Successfully updated field '%s' for player %s in guild %s.", field_name, player_id, guild_id) # Changed
                return True
            elif isinstance(status, str) and status == "UPDATE 0":
                logger.info("DBService: Field update for player %s (field %s) in guild %s ran, but no rows affected.", player_id, field_name, guild_id) # Changed
                return True
            else:
                logger.info("DBService: Player field update for %s (field %s) in guild %s completed with status: %s.", player_id, field_name, guild_id, status) # Changed
                return True
        except Exception as e:
            logger.error("DBService: Error updating field '%s' for player %s in guild %s: %s", field_name, player_id, guild_id, e, exc_info=True) # Changed
            return False

    async def create_player(
        self, discord_user_id: int, name: str, race: str,
        guild_id: str, location_id: str, hp: int, mp: int,
        attack: int, defense: int, stats: Optional[Dict[str, Any]] = None,
        player_id: Optional[str] = None,
        level: int = 1, experience: int = 0, unspent_xp: int = 0
    ) -> Optional[Dict[str, Any]]:
        if not player_id:
            player_id = f"{guild_id}-{discord_user_id}"

        sql = """
            INSERT INTO players (id, discord_user_id, name, race, guild_id, location_id, hp, mp, attack, defense, stats, experience, level, unspent_xp)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
            RETURNING id;
        """
        params = (
            player_id, discord_user_id, name, race, guild_id, location_id,
            hp, mp, attack, defense, json.dumps(stats) if stats else '{}',
            experience, level, unspent_xp
        )
        try:
            inserted_id = await self.adapter.execute_insert(sql, params)
            if inserted_id:
                logger.info("DBService: Created player %s for discord_user_id %s in guild %s.", player_id, discord_user_id, guild_id) # Added
                return await self.get_player_data(player_id)
            else: # Added else
                logger.error("DBService: Failed to create player for discord_user_id %s in guild %s (no ID returned).", discord_user_id, guild_id)
                return None
        except Exception as e: # Added
            logger.error("DBService: Error creating player for discord_user_id %s in guild %s: %s", discord_user_id, guild_id, e, exc_info=True)
            return None


    async def update_player_location(self, player_id: str, new_location_id: str) -> None:
        sql = "UPDATE players SET location_id = $1 WHERE id = $2"
        try: # Added
            await self.adapter.execute(sql, (new_location_id, player_id))
            logger.info("DBService: Updated location for player %s to %s.", player_id, new_location_id) # Added
        except Exception as e: # Added
            logger.error("DBService: Error updating location for player %s: %s", player_id, e, exc_info=True)


    async def get_player_inventory(self, player_id: str) -> List[Dict[str, Any]]:
        sql = """
            SELECT inv.item_template_id, inv.amount, it.name, it.description, it.type as item_type, it.properties
            FROM inventory inv
            JOIN item_templates it ON inv.item_template_id = it.id
            WHERE inv.player_id = $1
        """
        try: # Added
            inventory_items = await self.adapter.fetchall(sql, (player_id,))
            for item in inventory_items:
                if item.get('properties') and isinstance(item['properties'], str):
                    item['properties'] = json.loads(item['properties'])
            return inventory_items
        except Exception as e: # Added
            logger.error("DBService: Error fetching inventory for player %s: %s", player_id, e, exc_info=True)
            return []


    async def add_item_to_inventory(self, player_id: str, item_template_id: str, amount: int) -> None:
        import uuid
        inventory_id = str(uuid.uuid4())
        try: # Added
            sql_select = "SELECT amount, inventory_id FROM inventory WHERE player_id = $1 AND item_template_id = $2"
            row = await self.adapter.fetchone(sql_select, (player_id, item_template_id))

            if row:
                new_amount = row['amount'] + amount
                existing_inventory_id = row['inventory_id']
                sql_update = "UPDATE inventory SET amount = $1 WHERE inventory_id = $2"
                await self.adapter.execute(sql_update, (new_amount, existing_inventory_id))
                logger.info("DBService: Updated item %s amount to %s for player %s.", item_template_id, new_amount, player_id) # Added
            else:
                sql_insert = "INSERT INTO inventory (inventory_id, player_id, item_template_id, amount) VALUES ($1, $2, $3, $4)"
                await self.adapter.execute(sql_insert, (inventory_id, player_id, item_template_id, amount))
                logger.info("DBService: Added %s of item %s to player %s inventory.", amount, item_template_id, player_id) # Added
        except Exception as e: # Added
            logger.error("DBService: Error adding item %s to player %s inventory: %s", item_template_id, player_id, e, exc_info=True)

    async def remove_item_from_inventory(self, player_id: str, item_template_id: str, amount: int) -> None:
        try: # Added
            sql_select = "SELECT amount, inventory_id FROM inventory WHERE player_id = $1 AND item_template_id = $2"
            row = await self.adapter.fetchone(sql_select, (player_id, item_template_id))

            if row:
                current_amount = row['amount']
                existing_inventory_id = row['inventory_id']
                if current_amount <= amount:
                    sql_delete = "DELETE FROM inventory WHERE inventory_id = $1"
                    await self.adapter.execute(sql_delete, (existing_inventory_id,))
                    logger.info("DBService: Removed item %s from player %s inventory.", item_template_id, player_id) # Added
                else:
                    new_amount = current_amount - amount
                    sql_update = "UPDATE inventory SET amount = $1 WHERE inventory_id = $2"
                    await self.adapter.execute(sql_update, (new_amount, existing_inventory_id))
                    logger.info("DBService: Reduced item %s amount to %s for player %s.", item_template_id, new_amount, player_id) # Added
            else: # Added
                logger.warning("DBService: Attempted to remove item %s from player %s, but item not found in inventory.", item_template_id, player_id)
        except Exception as e: # Added
            logger.error("DBService: Error removing item %s from player %s inventory: %s", item_template_id, player_id, e, exc_info=True)


    async def get_player_data(self, player_id: str) -> Optional[Dict[str, Any]]:
        sql = "SELECT * FROM players WHERE id = $1"
        try: # Added
            player = await self.adapter.fetchone(sql, (player_id,))
            if player:
                if player.get('stats') and isinstance(player['stats'], str):
                    player['stats'] = json.loads(player['stats'])
                if player.get('active_quests') and isinstance(player['active_quests'], str):
                    player['active_quests'] = json.loads(player['active_quests'])
                if player.get('status_effects') and isinstance(player['status_effects'], str):
                    player['status_effects'] = json.loads(player['status_effects'])
            return player
        except Exception as e: # Added
            logger.error("DBService: Error fetching data for player %s: %s", player_id, e, exc_info=True)
            return None


    async def create_item_definition(
        self, item_id: str, name: str, description: str,
        item_type: str, guild_id: str, effects: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        properties_data = {'effects': effects} if effects else {}
        name_i18n_json = json.dumps({"en": name, "ru": name})
        description_i18n_json = json.dumps({"en": description, "ru": description})

        sql = """
            INSERT INTO item_templates (id, name_i18n, description_i18n, type, properties, guild_id)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id;
        """
        params = (item_id, name_i18n_json, description_i18n_json, item_type, json.dumps(properties_data), guild_id)
        try: # Added
            inserted_id = await self.adapter.execute_insert(sql, params)
            if inserted_id:
                logger.info("DBService: Created item definition %s for guild %s.", item_id, guild_id) # Added
                return await self.get_item_definition(item_id) # Assuming get_item_definition might also need guild_id
            else: # Added
                logger.error("DBService: Failed to create item definition %s for guild %s (no ID returned).", item_id, guild_id)
                return None
        except Exception as e: # Added
            logger.error("DBService: Error creating item definition %s: %s", item_id, e, exc_info=True)
            return None

    async def get_item_definition(self, item_id: str) -> Optional[Dict[str, Any]]:
        sql = "SELECT * FROM item_templates WHERE id = $1"
        try: # Added
            item_def = await self.adapter.fetchone(sql, (item_id,))
            if item_def and item_def.get('properties') and isinstance(item_def['properties'], str):
                item_def['properties'] = json.loads(item_def['properties'])
            return item_def
        except Exception as e: # Added
            logger.error("DBService: Error fetching item definition %s: %s", item_id, e, exc_info=True)
            return None


    async def get_all_item_definitions(self) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM item_templates"
        try: # Added
            item_defs = await self.adapter.fetchall(sql)
            for item_def in item_defs:
                if item_def.get('properties') and isinstance(item_def['properties'], str):
                    item_def['properties'] = json.loads(item_def['properties'])
            return item_defs
        except Exception as e: # Added
            logger.error("DBService: Error fetching all item definitions: %s", e, exc_info=True)
            return []


    async def create_location(
        self, loc_id: str, name_i18n: Dict[str, str], description_i18n: Dict[str, str], type_i18n: Dict[str, str], guild_id: str,
        exits: Optional[Dict[str, str]] = None, template_id: str = "default",
        properties: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        sql = """
            INSERT INTO locations (id, template_id, name_i18n, descriptions_i18n, type_i18n, guild_id, exits, state_variables, is_active)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id;
        """
        params = (
            loc_id, template_id, json.dumps(name_i18n), json.dumps(description_i18n), json.dumps(type_i18n), guild_id,
            json.dumps(exits) if exits else '{}',
            json.dumps(properties) if properties else '{}', True
        )
        try: # Added
            inserted_id = await self.adapter.execute_insert(sql, params)
            if inserted_id:
                logger.info("DBService: Created location %s in guild %s.", loc_id, guild_id) # Added
                return await self.get_location(loc_id, guild_id)
            else: # Added
                logger.error("DBService: Failed to create location %s in guild %s (no ID returned).", loc_id, guild_id)
                return None
        except Exception as e: # Added
            logger.error("DBService: Error creating location %s in guild %s: %s", loc_id, guild_id, e, exc_info=True)
            return None


    async def get_location(self, location_id: str, guild_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        sql = "SELECT * FROM locations WHERE id = $1"
        params_list = [location_id]
        if guild_id:
            sql += " AND guild_id = $2"
            params_list.append(guild_id)

        try: # Added
            location = await self.adapter.fetchone(sql, tuple(params_list))
            if location:
                if location.get('exits') and isinstance(location['exits'], str):
                    location['exits'] = json.loads(location['exits'])
                if location.get('state_variables') and isinstance(location['state_variables'], str):
                    location['state_variables'] = json.loads(location['state_variables'])
            return location
        except Exception as e: # Added
            log_msg = f"DBService: Error fetching location {location_id}"
            if guild_id:
                log_msg += f" in guild {guild_id}"
            logger.error("%s: %s", log_msg, e, exc_info=True)
            return None

    async def get_all_locations(self, guild_id: str) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM locations WHERE guild_id = $1"
        try: # Added
            locations = await self.adapter.fetchall(sql, (guild_id,))
            for loc in locations:
                if loc.get('exits') and isinstance(loc['exits'], str):
                    loc['exits'] = json.loads(loc['exits'])
                if loc.get('state_variables') and isinstance(loc['state_variables'], str):
                    loc['state_variables'] = json.loads(loc['state_variables'])
            return locations
        except Exception as e: # Added
            logger.error("DBService: Error fetching all locations for guild %s: %s", guild_id, e, exc_info=True)
            return []


    async def create_npc(
        self, npc_id: str, guild_id: str, template_id: str,
        name_i18n: Dict[str, str], stats: Dict[str, Any],
        location_id: Optional[str] = None,
        description_i18n: Optional[Dict[str, str]] = None,
        persona_i18n: Optional[Dict[str, str]] = None,
        backstory_i18n: Optional[Dict[str, str]] = None,
        archetype: Optional[str] = "commoner",
        inventory: Optional[List[str]] = None,
        current_action: Optional[Dict[str, Any]] = None,
        action_queue: Optional[List[Any]] = None,
        party_id: Optional[str] = None,
        state_variables: Optional[Dict[str, Any]] = None,
        status_effects: Optional[List[str]] = None,
        is_temporary: bool = False,
        traits: Optional[List[str]] = None,
        desires: Optional[List[str]] = None,
        motives: Optional[List[str]] = None,
        **kwargs
    ) -> Optional[Dict[str, Any]]:
        max_health = float(stats.get('max_health', 50.0))
        current_health = float(stats.get('health', max_health))

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

        name_i18n_json = json.dumps(name_i18n or {})
        description_i18n_json = json.dumps(description_i18n or {})
        persona_i18n_json = json.dumps(persona_i18n or {})
        backstory_i18n_json = json.dumps(backstory_i18n or {})
        stats_json = json.dumps(stats or {})
        inventory_json = json.dumps(inventory or [])
        current_action_json = json.dumps(current_action) if current_action is not None else None
        action_queue_json = json.dumps(action_queue or [])
        state_variables_json = json.dumps(state_variables or {})
        status_effects_json = json.dumps(status_effects or [])
        traits_json = json.dumps(traits or [])
        desires_json = json.dumps(desires or [])
        motives_json = json.dumps(motives or [])

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
        try: # Added
            inserted_id = await self.adapter.execute_insert(sql, params)
            if inserted_id:
                logger.info("DBService: Created NPC %s (template: %s) in guild %s.", npc_id, template_id, guild_id) # Added
                if kwargs:
                    logger.debug("DBService: NPC %s created with additional kwargs: %s", npc_id, kwargs) # Added
                return await self.get_npc(npc_id, guild_id)
            else: # Added
                logger.error("DBService: Failed to create NPC %s in guild %s (no ID returned).", npc_id, guild_id)
                return None
        except Exception as e: # Added
            logger.error("DBService: Error creating NPC %s in guild %s: %s", npc_id, guild_id, e, exc_info=True)
            return None


    async def get_npc(self, npc_id: str, guild_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        sql = "SELECT * FROM npcs WHERE id = $1"
        params_list = [npc_id]
        if guild_id:
            sql += " AND guild_id = $2"
            params_list.append(guild_id)

        try: # Added
            npc = await self.adapter.fetchone(sql, tuple(params_list))
            if npc:
                if npc.get('stats') and isinstance(npc['stats'], str):
                    npc['stats'] = json.loads(npc['stats'])
                if npc.get('inventory') and isinstance(npc['inventory'], str):
                    npc['inventory'] = json.loads(npc['inventory'])
                if npc.get('status_effects') and isinstance(npc['status_effects'], str):
                    npc['status_effects'] = json.loads(npc['status_effects'])
            return npc
        except Exception as e: # Added
            log_msg = f"DBService: Error fetching NPC {npc_id}"
            if guild_id:
                log_msg += f" in guild {guild_id}"
            logger.error("%s: %s", log_msg, e, exc_info=True)
            return None


    async def get_npcs_in_location(self, location_id: str, guild_id: str) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM npcs WHERE location_id = $1 AND guild_id = $2"
        try: # Added
            npcs_list = await self.adapter.fetchall(sql, (location_id, guild_id))
            for npc_data in npcs_list:
                if npc_data.get('stats') and isinstance(npc_data['stats'], str):
                    npc_data['stats'] = json.loads(npc_data['stats'])
                if npc_data.get('inventory') and isinstance(npc_data['inventory'], str):
                    npc_data['inventory'] = json.loads(npc_data['inventory'])
            return npcs_list
        except Exception as e: # Added
            logger.error("DBService: Error fetching NPCs in location %s for guild %s: %s", location_id, guild_id, e, exc_info=True)
            return []


    async def add_log_entry(
        self, guild_id: str, event_type: str, message: str,
        player_id_column: Optional[str] = None,
        related_entities: Optional[Dict[str, Any]] = None,
        context_data: Optional[Dict[str, Any]] = None,
        channel_id: Optional[int] = None # Changed from str to int based on schema
    ) -> None:
        import uuid
        log_id = str(uuid.uuid4())

        sql = """
            INSERT INTO game_logs (log_id, timestamp, guild_id, channel_id, player_id, event_type, message, related_entities, context_data)
            VALUES ($1, NOW(), $2, $3, $4, $5, $6, $7, $8)
        """
        params = (
            log_id, guild_id, channel_id, player_id_column, event_type, message,
            json.dumps(related_entities) if related_entities else '{}',
            json.dumps(context_data) if context_data else '{}'
        )
        try: # Added
            await self.adapter.execute(sql, params)
            logger.info("DBService: Added log entry %s (type: %s) for guild %s.", log_id, event_type, guild_id) # Added
        except Exception as e: # Added
            logger.error("DBService: Error adding log entry for guild %s (type: %s): %s", guild_id, event_type, e, exc_info=True)


    async def get_last_player_log(self, player_id: str, guild_id: str) -> Optional[Dict[str, Any]]:
        sql = "SELECT * FROM game_logs WHERE guild_id = $1 AND player_id = $2 ORDER BY timestamp DESC LIMIT 1"
        try: # Added
            log_entry = await self.adapter.fetchone(sql, (guild_id, player_id))
            if log_entry:
                if log_entry.get('related_entities') and isinstance(log_entry['related_entities'], str):
                    log_entry['related_entities'] = json.loads(log_entry['related_entities'])
                if log_entry.get('context_data') and isinstance(log_entry['context_data'], str):
                    log_entry['context_data'] = json.loads(log_entry['context_data'])
            return log_entry
        except Exception as e: # Added
            logger.error("DBService: Error fetching last log for player %s in guild %s: %s", player_id, guild_id, e, exc_info=True)
            return None


    async def get_item_instances_in_location(self, location_id: str, guild_id: str) -> List[Dict[str, Any]]:
        sql = """
            SELECT i.id as item_instance_id, i.template_id, i.quantity, i.state_variables,
                   it.name, it.description, it.type as item_type, it.properties
            FROM items i
            JOIN item_templates it ON i.template_id = it.id
            WHERE i.location_id = $1 AND i.guild_id = $2
        """
        try: # Added
            items_in_location = await self.adapter.fetchall(sql, (location_id, guild_id))
            for item in items_in_location:
                if item.get('properties') and isinstance(item['properties'], str):
                    item['properties'] = json.loads(item['properties'])
                if item.get('state_variables') and isinstance(item['state_variables'], str):
                    item['state_variables'] = json.loads(item['state_variables'])
            return items_in_location
        except Exception as e: # Added
            logger.error("DBService: Error fetching items in location %s for guild %s: %s", location_id, guild_id, e, exc_info=True)
            return []


    async def delete_item_instance(self, item_instance_id: str, guild_id: str) -> bool:
        try: # Added
            sql_check = "SELECT id FROM items WHERE id = $1 AND guild_id = $2"
            row = await self.adapter.fetchone(sql_check, (item_instance_id, guild_id))
            if not row:
                logger.warning("DBService: Item instance %s not found in guild %s for deletion.", item_instance_id, guild_id) # Changed
                return False

            sql_delete = "DELETE FROM items WHERE id = $1"
            await self.adapter.execute(sql_delete, (item_instance_id,))
            logger.info("DBService: Deleted item instance %s from guild %s.", item_instance_id, guild_id) # Changed
            return True
        except Exception as e:
            logger.error("DBService: Error deleting item instance %s in guild %s: %s", item_instance_id, guild_id, e, exc_info=True) # Changed
            return False

    async def update_npc_hp(self, npc_id: str, new_hp: float, guild_id: str) -> bool: # Changed new_hp to float
        try: # Added
            sql_check = "SELECT id FROM npcs WHERE id = $1 AND guild_id = $2"
            row = await self.adapter.fetchone(sql_check, (npc_id, guild_id))
            if not row:
                logger.warning("DBService: NPC %s not found in guild %s for HP update.", npc_id, guild_id) # Changed
                return False

            sql = "UPDATE npcs SET health = $1 WHERE id = $2 AND guild_id = $3"
            await self.adapter.execute(sql, (max(0, new_hp), npc_id, guild_id))
            logger.info("DBService: Updated NPC %s HP to %s in guild %s.", npc_id, new_hp, guild_id) # Changed
            return True
        except Exception as e:
            logger.error("DBService: Error updating NPC %s HP in guild %s: %s", npc_id, guild_id, e, exc_info=True) # Changed
            return False

    async def update_player_hp(self, player_id: str, new_hp: float, guild_id: str) -> bool: # Changed new_hp to float
        try: # Added
            sql_check = "SELECT id FROM players WHERE id = $1 AND guild_id = $2"
            row = await self.adapter.fetchone(sql_check, (player_id, guild_id))
            if not row:
                logger.warning("DBService: Player %s not found in guild %s for HP update.", player_id, guild_id) # Changed
                return False

            sql = "UPDATE players SET hp = $1 WHERE id = $2 AND guild_id = $3"
            await self.adapter.execute(sql, (max(0, new_hp), player_id, guild_id))
            logger.info("DBService: Updated Player %s HP to %s in guild %s.", player_id, new_hp, guild_id) # Changed
            return True
        except Exception as e:
            logger.error("DBService: Error updating Player %s HP in guild %s: %s", player_id, guild_id, e, exc_info=True) # Changed
            return False

    async def get_or_create_dialogue_session(
        self, player_id: str, npc_id: str, guild_id: str, channel_id: int # Changed channel_id to int
    ) -> Optional[Dict[str, Any]]: # Added Optional return
        participant_list = sorted([player_id, npc_id])
        participants_json = json.dumps(participant_list)

        sql_find = """
            SELECT id, conversation_history, state_variables, current_stage_id, template_id, is_active
            FROM dialogues
            WHERE participants = $1 AND guild_id = $2 AND is_active = TRUE
            ORDER BY last_activity_game_time DESC LIMIT 1
        """
        try: # Added
            session_row = await self.adapter.fetchone(sql_find, (participants_json, guild_id))

            if session_row:
                session = dict(session_row) # Ensure it's a mutable dict
                if session.get('conversation_history') and isinstance(session['conversation_history'], str):
                    session['conversation_history'] = json.loads(session['conversation_history'])
                else:
                    session['conversation_history'] = []

                if session.get('state_variables') and isinstance(session['state_variables'], str):
                    session['state_variables'] = json.loads(session['state_variables'])
                else:
                    session['state_variables'] = {}
                logger.info("DBService: Found active dialogue session %s for player %s, NPC %s in guild %s.", session.get('id'), player_id, npc_id, guild_id) # Added
                return session

            import uuid
            import time
            dialogue_id = str(uuid.uuid4())
            current_time = time.time()

            sql_create = """
                INSERT INTO dialogues (
                    id, guild_id, participants, channel_id,
                    conversation_history, state_variables, is_active,
                    last_activity_game_time, current_stage_id, template_id
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING id;
            """
            initial_history = []
            initial_state_vars = {}
            params = (
                dialogue_id, guild_id, participants_json, channel_id,
                json.dumps(initial_history), json.dumps(initial_state_vars), True,
                current_time, None, None
            )
            await self.adapter.execute_insert(sql_create, params)
            logger.info("DBService: Created new dialogue session %s for player %s, NPC %s in guild %s.", dialogue_id, player_id, npc_id, guild_id) # Added
            return {
                "id": dialogue_id, "guild_id": guild_id, "participants": participant_list,
                "channel_id": channel_id, "conversation_history": initial_history,
                "state_variables": initial_state_vars, "is_active": True, # Changed to boolean
                "last_activity_game_time": current_time, "current_stage_id": None, "template_id": None
            }
        except Exception as e: # Added
            logger.error("DBService: Error getting or creating dialogue session for player %s, NPC %s, guild %s: %s", player_id, npc_id, guild_id, e, exc_info=True)
            return None


    async def update_dialogue_history(self, dialogue_id: str, new_history_entry: Dict[str, str]) -> bool:
        try: # Added
            sql_get_history = "SELECT conversation_history FROM dialogues WHERE id = $1"
            dialogue_data = await self.adapter.fetchone(sql_get_history, (dialogue_id,))

            if not dialogue_data:
                logger.warning("DBService: Dialogue session %s not found for history update.", dialogue_id) # Changed
                return False

            current_history_json = dialogue_data['conversation_history']
            try:
                current_history = json.loads(current_history_json) if current_history_json and isinstance(current_history_json, str) else (current_history_json if isinstance(current_history_json, list) else [])
            except json.JSONDecodeError:
                logger.warning("DBService: Corrupted JSON history for dialogue %s, starting fresh.", dialogue_id) # Added
                current_history = []

            if not isinstance(current_history, list):
                current_history = []

            current_history.append(new_history_entry)
            import time
            current_time = time.time()
            sql_update = "UPDATE dialogues SET conversation_history = $1, last_activity_game_time = $2 WHERE id = $3"
            await self.adapter.execute(sql_update, (json.dumps(current_history), current_time, dialogue_id))
            logger.info("DBService: Updated dialogue history for session %s.", dialogue_id) # Changed
            return True
        except Exception as e:
            logger.error("DBService: Error updating dialogue history for session %s: %s", dialogue_id, e, exc_info=True) # Changed
            return False

    async def set_dialogue_history(self, dialogue_id: str, full_history: List[Dict[str, str]]) -> bool:
        import time
        current_time = time.time()
        sql_update = "UPDATE dialogues SET conversation_history = $1, last_activity_game_time = $2 WHERE id = $3"
        try:
            await self.adapter.execute(sql_update, (json.dumps(full_history), current_time, dialogue_id))
            logger.info("DBService: Set (overwrote) dialogue history for session %s.", dialogue_id) # Changed
            return True
        except Exception as e:
            logger.error("DBService: Error setting (overwriting) dialogue history for session %s: %s", dialogue_id, e, exc_info=True) # Changed
            return False

    async def get_last_undoable_player_action(self, player_id: str, guild_id: str) -> Optional[Dict[str, Any]]:
        sql = """
            SELECT log_id, event_type, context_data, related_entities, message, timestamp
            FROM game_logs
            WHERE player_id = $1 AND guild_id = $2 AND is_undone = FALSE
            ORDER BY timestamp DESC
            LIMIT 1
        """
        try: # Added
            log_entry = await self.adapter.fetchone(sql, (player_id, guild_id))
            if log_entry:
                if log_entry.get('context_data') and isinstance(log_entry['context_data'], str):
                    log_entry['context_data'] = json.loads(log_entry['context_data'])
                if log_entry.get('related_entities') and isinstance(log_entry['related_entities'], str):
                    log_entry['related_entities'] = json.loads(log_entry['related_entities'])
            return log_entry
        except Exception as e: # Added
            logger.error("DBService: Error fetching last undoable action for player %s in guild %s: %s", player_id, guild_id, e, exc_info=True)
            return None


    async def mark_log_as_undone(self, log_id: str, guild_id: str) -> bool:
        try: # Added
            sql_check = "SELECT log_id FROM game_logs WHERE log_id = $1 AND guild_id = $2"
            row = await self.adapter.fetchone(sql_check, (log_id, guild_id))
            if not row:
                logger.warning("DBService: Log entry %s not found in guild %s to mark as undone.", log_id, guild_id) # Changed
                return False

            sql = "UPDATE game_logs SET is_undone = TRUE WHERE log_id = $1 AND guild_id = $2"
            await self.adapter.execute(sql, (log_id, guild_id))
            logger.info("DBService: Marked log entry %s as undone for guild %s.", log_id, guild_id) # Changed
            return True
        except Exception as e:
            logger.error("DBService: Error marking log entry %s as undone in guild %s: %s", log_id, guild_id, e, exc_info=True) # Changed
            return False

    async def create_item_instance(
        self, template_id: str, guild_id: str, quantity: int,
        location_id: Optional[str] = None, owner_id: Optional[str] = None,
        owner_type: Optional[str] = None, state_variables: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        import uuid
        item_instance_id = str(uuid.uuid4())
        sql = """
            INSERT INTO items (id, template_id, guild_id, owner_id, owner_type, location_id, quantity, state_variables, is_temporary)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id;
        """
        params = (
            item_instance_id, template_id, guild_id, owner_id, owner_type,
            location_id, quantity,
            json.dumps(state_variables) if state_variables else '{}',
            False
        )
        try:
            inserted_id = await self.adapter.execute_insert(sql, params)
            if inserted_id == item_instance_id:
                logger.info("DBService: Created item instance %s (template: %s) for guild %s.", item_instance_id, template_id, guild_id) # Changed
                return item_instance_id
            else:
                logger.warning("DBService: Created item instance for template %s in guild %s, but ID mismatch: expected %s, got %s.", template_id, guild_id, item_instance_id, inserted_id) # Changed
                return inserted_id
        except Exception as e:
            logger.error("DBService: Error creating item instance for template %s in guild %s: %s", template_id, guild_id, e, exc_info=True) # Changed
            return None

    async def save_pending_conflict(self, conflict_id: str, guild_id: str, conflict_data: str) -> None:
        if not isinstance(conflict_data, str):
             # This should ideally be a specific error type like ValueError or TypeError
             logger.error("DBService: conflict_data must be a JSON string for conflict %s in guild %s.", conflict_id, guild_id)
             raise TypeError("conflict_data must be a JSON string.")
        try: # Added
            await self.adapter.save_pending_conflict(conflict_id, guild_id, conflict_data)
            logger.info("DBService: Saved pending conflict %s for guild %s.", conflict_id, guild_id) # Added
        except Exception as e: # Added
            logger.error("DBService: Error saving pending conflict %s for guild %s: %s", conflict_id, guild_id, e, exc_info=True)
            # Re-raise or handle as appropriate for the application flow
            raise

    async def get_pending_conflict(self, conflict_id: str) -> Optional[Dict[str, Any]]:
        try: # Added
            return await self.adapter.get_pending_conflict(conflict_id)
        except Exception as e: # Added
            logger.error("DBService: Error getting pending conflict %s: %s", conflict_id, e, exc_info=True)
            return None


    async def delete_pending_conflict(self, conflict_id: str) -> None:
        try: # Added
            await self.adapter.delete_pending_conflict(conflict_id)
            logger.info("DBService: Deleted pending conflict %s.", conflict_id) # Added
        except Exception as e: # Added
            logger.error("DBService: Error deleting pending conflict %s: %s", conflict_id, e, exc_info=True)
            # Re-raise or handle
            raise


    async def create_entity(self, table_name: str, data: Dict[str, Any], id_field: str = 'id') -> Optional[str]:
        import uuid
        # import json # Already imported

        original_guild_id = data.get('guild_id', 'N/A') # For logging

        if id_field == 'id' and 'id' not in data:
            data['id'] = str(uuid.uuid4())

        processed_data = {}
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                processed_data[key] = json.dumps(value)
            else:
                processed_data[key] = value
        
        columns = ', '.join(processed_data.keys())
        placeholders = ', '.join([f'${i+1}' for i in range(len(processed_data))])
        sql = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})"
        if id_field in data:
            sql += f" RETURNING {id_field}"
        
        entity_id_to_log = data.get(id_field, 'N/A')
        try:
            if id_field in data and " RETURNING " in sql:
                returned_val = await self.adapter.execute_insert(sql, tuple(processed_data.values()))
                logger.info("DBService: Created entity in table '%s' with ID '%s' (Guild: %s).", table_name, returned_val, original_guild_id) # Added
                return returned_val
            else:
                await self.adapter.execute(sql, tuple(processed_data.values()))
                logger.info("DBService: Created entity in table '%s' with ID '%s' (Guild: %s, no RETURNING used).", table_name, entity_id_to_log, original_guild_id) # Added
                return data.get(id_field)
        except Exception as e:
            logger.error("DBService: Error creating entity in table '%s' (ID: %s, Guild: %s): %s", table_name, entity_id_to_log, original_guild_id, e, exc_info=True) # Changed
            return None

    async def get_entity(self, table_name: str, entity_id: str, guild_id: Optional[str] = None, id_field: str = 'id') -> Optional[Dict[str, Any]]:
        # import json # Already imported
        sql = f"SELECT * FROM {table_name} WHERE {id_field} = $1"
        params_list = [entity_id]
        param_idx = 2
        if guild_id:
            sql += f" AND guild_id = ${param_idx}"
            params_list.append(guild_id)
            param_idx +=1

        log_guild_id = guild_id if guild_id else "N/A"
        try: # Added
            entity = await self.adapter.fetchone(sql, tuple(params_list))
            if entity:
                for key, value in entity.items():
                    if isinstance(value, str):
                        try:
                            if value.startswith('{') and value.endswith('}'):
                                entity[key] = json.loads(value)
                            elif value.startswith('[') and value.endswith(']'):
                                entity[key] = json.loads(value)
                        except json.JSONDecodeError:
                            pass
            return entity
        except Exception as e: # Added
            logger.error("DBService: Error fetching entity '%s' from table '%s' (Guild: %s): %s", entity_id, table_name, log_guild_id, e, exc_info=True)
            return None


    async def update_entity(self, table_name: str, entity_id: str, data: Dict[str, Any], guild_id: Optional[str] = None, id_field: str = 'id') -> bool:
        # import json # Already imported
        if not data:
            logger.warning("DBService: No data provided for updating entity '%s' in table '%s'.", entity_id, table_name) # Added
            return False

        processed_data = {}
        param_idx = 1
        set_clauses = []
        params_list = []

        for key, value in data.items():
            if isinstance(value, (dict, list)):
                set_clauses.append(f"{key} = ${param_idx}::jsonb")
                params_list.append(json.dumps(value))
            else:
                set_clauses.append(f"{key} = ${param_idx}")
                params_list.append(value)
            param_idx += 1
        
        set_clause_str = ', '.join(set_clauses)
        sql = f"UPDATE {table_name} SET {set_clause_str} WHERE {id_field} = ${param_idx}"
        params_list.append(entity_id)
        param_idx +=1

        log_guild_id = guild_id if guild_id else "N/A (or not applicable)"
        if guild_id:
            sql += f" AND guild_id = ${param_idx}"
            params_list.append(guild_id)
            # param_idx +=1 # Not needed after this

        try:
            result_status = await self.adapter.execute(sql, tuple(params_list))
            if isinstance(result_status, str) and "UPDATE" in result_status.upper():
                parts = result_status.upper().split()
                if len(parts) > 1 and parts[0] == "UPDATE":
                    try:
                        affected_rows = int(parts[1])
                        if affected_rows > 0:
                            logger.info("DBService: Successfully updated entity '%s' in table '%s' (Guild: %s). %s rows affected.", entity_id, table_name, log_guild_id, affected_rows) # Added
                            return True
                        else:
                            logger.info("DBService: Update for entity '%s' in table '%s' (Guild: %s) affected 0 rows (already correct value or ID not found).", entity_id, table_name, log_guild_id) # Added
                            return True
                    except ValueError:
                        logger.info("DBService: Update for entity '%s' in table '%s' (Guild: %s) completed with status: %s.", entity_id, table_name, log_guild_id, result_status) # Added
                        return True
                logger.info("DBService: Update for entity '%s' in table '%s' (Guild: %s) completed with status: %s.", entity_id, table_name, log_guild_id, result_status) # Added
                return True
            logger.warning("DBService: Update for entity '%s' in table '%s' (Guild: %s) resulted in unexpected status: %s.", entity_id, table_name, log_guild_id, result_status) # Added
            return True
        except Exception as e:
            logger.error("DBService: Error updating entity '%s' in table '%s' (Guild: %s): %s", entity_id, table_name, log_guild_id, e, exc_info=True) # Changed
            return False

    async def delete_entity(self, table_name: str, entity_id: str, guild_id: Optional[str] = None, id_field: str = 'id') -> bool:
        sql = f"DELETE FROM {table_name} WHERE {id_field} = $1"
        params_list = [entity_id]
        param_idx = 2
        log_guild_id = guild_id if guild_id else "N/A (or not applicable)"

        if guild_id:
            sql += f" AND guild_id = ${param_idx}"
            params_list.append(guild_id)
            # param_idx +=1 # Not needed

        try:
            result_status = await self.adapter.execute(sql, tuple(params_list))
            if isinstance(result_status, str) and "DELETE" in result_status.upper():
                parts = result_status.upper().split()
                if len(parts) > 1 and parts[0] == "DELETE":
                    try:
                        affected_rows = int(parts[1])
                        if affected_rows > 0:
                            logger.info("DBService: Successfully deleted entity '%s' from table '%s' (Guild: %s). %s rows affected.", entity_id, table_name, log_guild_id, affected_rows) # Added
                            return True
                        else:
                            logger.info("DBService: Delete for entity '%s' from table '%s' (Guild: %s) affected 0 rows (ID not found).", entity_id, table_name, log_guild_id) # Added
                            return True # Or False if strict "something deleted" is needed
                    except ValueError:
                        logger.info("DBService: Delete for entity '%s' from table '%s' (Guild: %s) completed with status: %s.", entity_id, table_name, log_guild_id, result_status) # Added
                        return True
                logger.info("DBService: Delete for entity '%s' from table '%s' (Guild: %s) completed with status: %s.", entity_id, table_name, log_guild_id, result_status) # Added
                return True
            logger.warning("DBService: Delete for entity '%s' from table '%s' (Guild: %s) resulted in unexpected status: %s.", entity_id, table_name, log_guild_id, result_status) # Added
            return True
        except Exception as e:
            logger.error("DBService: Error deleting entity '%s' from table '%s' (Guild: %s): %s", entity_id, table_name, log_guild_id, e, exc_info=True) # Changed
            return False

    async def set_guild_setting(self, guild_id: str, setting_key: str, setting_value: Any) -> bool:
        if not self.adapter:
            logger.warning("DBService: Adapter not available. Cannot set guild setting '%s' for guild %s.", setting_key, guild_id) # Changed
            return False

        value_json = json.dumps(setting_value)
        sql = """
            INSERT INTO guild_settings (guild_id, key, value)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id, key) DO UPDATE SET
                value = EXCLUDED.value;
        """
        try:
            status = await self.adapter.execute(sql, (guild_id, setting_key, value_json))
            if isinstance(status, str) and ("INSERT" in status.upper() or "UPDATE" in status.upper()):
                 if "UPDATE" in status.upper():
                     count_str = status.upper().split("UPDATE")[1].strip()
                     if count_str.isdigit() and int(count_str) > 0:
                         logger.info("DBService: Successfully updated setting '%s' for guild %s.", setting_key, guild_id) # Changed
                         return True
                     elif count_str.isdigit() and int(count_str) == 0:
                         logger.info("DBService: Setting '%s' for guild %s was not updated (no change or key not found for update part of upsert).", setting_key, guild_id) # Changed
                         return True
                 elif "INSERT" in status.upper():
                      parts = status.upper().split()
                      if len(parts) == 3 and parts[0] == "INSERT" and parts[1] == "0" and parts[2] == "1":
                           logger.info("DBService: Successfully inserted setting '%s' for guild %s.", setting_key, guild_id) # Changed
                           return True
            logger.info("DBService: Setting '%s' for guild %s completed with status: %s. Assuming success if no error.", setting_key, guild_id, status) # Changed
            return True
        except Exception as e:
            logger.error("DBService: Error setting guild setting '%s' for guild %s: %s", setting_key, guild_id, e, exc_info=True) # Changed
            return False
