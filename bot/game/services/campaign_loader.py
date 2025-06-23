# bot/game/services/campaign_loader.py
from __future__ import annotations
import json
import os
import traceback
from typing import Optional, Dict, Any, List, TYPE_CHECKING

if TYPE_CHECKING:
    from bot.services.db_service import DBService # Corrected import path

class CampaignLoader:
    def __init__(self, settings: Optional[Dict[str, Any]] = None, db_service: Optional[DBService] = None):
        self._settings = settings if settings is not None else {}
        self._db_service = db_service
        self._campaign_base_path = self._settings.get('campaign_data_path', 'data/campaigns')
        self._data_base_path = self._settings.get('data_base_path', 'data') # For items.json, locations.json

        if self._db_service is None:
            # This service is critical for populating data, so it should ideally always be provided.
            print("CampaignLoader: WARNING - DBService not provided. Data population methods will fail.")
        print(f"CampaignLoader initialized. Base campaign path: '{self._campaign_base_path}', Data path: '{self._data_base_path}'")

    async def _load_json_file(self, file_path: str) -> Optional[Any]:
        """Helper to load a JSON file and handle common errors."""
        print(f"CampaignLoader: Attempting to load JSON data from '{file_path}'...")
        if not os.path.exists(file_path):
            print(f"CampaignLoader: Error - File not found at '{file_path}'.")
            return None
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            print(f"CampaignLoader: Successfully loaded and parsed JSON data from '{file_path}'.")
            return data
        except json.JSONDecodeError as e:
            print(f"CampaignLoader: Error - Failed to parse JSON from file '{file_path}': {e}")
            traceback.print_exc()
            return None
        except Exception as e:
            print(f"CampaignLoader: Error - Could not read file '{file_path}': {e}")
            traceback.print_exc()
            return None

    async def load_and_populate_items(self, guild_id: str, items_file_path: Optional[str] = None) -> None:
        if not self._db_service:
            print(f"CampaignLoader: DBService not available, skipping item population for guild '{guild_id}'.")
            return

        file_path = items_file_path or os.path.join(self._data_base_path, "items.json")
        items_data = await self._load_json_file(file_path)

        if items_data and isinstance(items_data, list):
            print(f"CampaignLoader: Populating {len(items_data)} item definitions for guild '{guild_id}'...")
            for item_def in items_data:
                item_id = item_def.get("id")
                name = item_def.get("name")
                description = item_def.get("description", "")
                item_type = item_def.get("type", "unknown")

                # Consolidate all other properties (including 'effects' and custom ones like icon, weight)
                # into a single dictionary to be passed as 'effects' to DBService,
                # which will then store it in the 'properties' JSON column.
                properties_to_store = item_def.get("effects", {}) # Start with existing effects
                for key, value in item_def.items():
                    if key not in ["id", "name", "description", "type", "effects"]:
                        properties_to_store[key] = value

                if not item_id or not name:
                    print(f"CampaignLoader: Skipping item definition due to missing id or name: {item_def}")
                    continue

                try:
                    existing_item = await self._db_service.get_item_definition(item_id)
                    if not existing_item:
                        await self._db_service.create_item_definition(
                            item_id=item_id,
                            name=name,
                            description=description,
                            item_type=item_type,
                            guild_id=guild_id,
                            effects=properties_to_store # Pass the consolidated dict here
                        )
                        print(f"CampaignLoader: Created item definition '{name}' (ID: {item_id}) for guild '{guild_id}'.")
                    else:
                        print(f"CampaignLoader: Item definition '{name}' (ID: {item_id}) already exists for guild '{guild_id}', skipping.")
                except Exception as e:
                    print(f"CampaignLoader: Error creating item definition '{name}' (ID: {item_id}) for guild '{guild_id}': {e}")
                    traceback.print_exc()
            print(f"CampaignLoader: Item definition population for guild '{guild_id}' complete.")
        else:
            print(f"CampaignLoader: No item data found or data is not a list in '{file_path}' for guild '{guild_id}'.")

    async def load_and_populate_locations(self, guild_id: str, locations_file_path: Optional[str] = None) -> None:
        if not self._db_service:
            print("CampaignLoader: DBService not available, skipping location population.")
            return

        file_path = locations_file_path or os.path.join(self._data_base_path, "locations.json")
        locations_data = await self._load_json_file(file_path)

        if locations_data and isinstance(locations_data, list):
            print(f"CampaignLoader: Populating {len(locations_data)} locations for guild '{guild_id}'...")
            default_lang = self._settings.get('game_rules', {}).get('default_bot_language', 'en')

            for loc_def in locations_data:
                loc_id = loc_def.get("id")
                if not loc_id:
                    print(f"CampaignLoader: Skipping location due to missing id: {loc_def}")
                    continue

                # Handle name_i18n
                name_i18n = loc_def.get("name_i18n")
                if not isinstance(name_i18n, dict) or not name_i18n:
                    plain_name = loc_def.get("name")
                    if plain_name:
                        name_i18n = {default_lang: plain_name}
                        print(f"CampaignLoader: Location ID '{loc_id}' missing 'name_i18n', using plain 'name' for default lang '{default_lang}'.")
                    else:
                        print(f"CampaignLoader: Skipping location ID '{loc_id}' due to missing 'name_i18n' and 'name'.")
                        continue

                display_name = name_i18n.get(default_lang, loc_id) # Use loc_id as fallback

                # Handle description_i18n (for template description)
                description_i18n = loc_def.get("description_i18n") # This should be the template's description
                if not isinstance(description_i18n, dict) or not description_i18n:
                    plain_description = loc_def.get("description")
                    if plain_description:
                        description_i18n = {default_lang: plain_description}
                    else:
                        description_i18n = {default_lang: "A place of little note."} # Default fallback

                # Handle exits/connections - assuming exits_data is prepared as needed for db_service
                # If world_map.json is used, its processing would happen here or be passed.
                # For now, using existing simple connections logic, but this is where richer exit data would be integrated.
                exits_data = {conn: conn for conn in loc_def.get("connections", [])}

                # Handle other properties that might be stored in a 'properties' JSON field in the DB
                # e.g., static_connections from world_map.json could be stored here if not directly mapped to exits.
                properties = loc_def.get("properties", {})
                if "exits" not in properties and loc_def.get("connections"): # Store raw connections if needed
                    properties["raw_connections"] = loc_def.get("connections")

                # Handle type_i18n
                type_i18n = loc_def.get("type_i18n")
                if not isinstance(type_i18n, dict) or not type_i18n:
                    type_i18n = {"en": "Unknown Type", "ru": "Неизвестный Тип"}
                    print(f"CampaignLoader: Location ID '{loc_id}' missing 'type_i18n', using default.")

                # Assuming db_service.create_location can handle name_i18n and description_i18n as dicts
                # and will serialize them to JSON strings for DB storage.
                try:
                    existing_loc = await self._db_service.get_location(loc_id, guild_id=guild_id)
                    if not existing_loc:
                        # The call to create_location needs to be updated if its signature changes for i18n
                        # For now, assuming it expects dicts for name_i18n and description_i18n
                        # and a 'properties' field for other static data.
                        created_location_data = await self._db_service.create_location(
                            loc_id=loc_id,
                            name_i18n=name_i18n,
                            description_i18n=description_i18n,
                            type_i18n=type_i18n,
                            guild_id=guild_id,
                            exits=exits_data,
                            template_id=loc_def.get("template_id", loc_id),
                            properties=properties
                        )
                        display_name = name_i18n.get(default_lang, loc_id)
                        if created_location_data:
                            print(f"CampaignLoader: Successfully created location '{display_name}' (ID: {loc_id}) for guild '{guild_id}' via DBService.")
                        else:
                            # DBService.create_location would have logged the specific FK error.
                            # CampaignLoader now acknowledges the failure.
                            print(f"CampaignLoader: ERROR - DBService failed to create location '{display_name}' (ID: {loc_id}) for guild '{guild_id}'. Check previous DBService error logs.")
                    else:
                        display_name = name_i18n.get(default_lang, loc_id)
                        print(f"CampaignLoader: Location '{display_name}' (ID: {loc_id}) already exists for guild '{guild_id}', skipping.")
                except Exception as e:
                    # This exception would be if the call to db_service.create_location itself raised an unexpected error
                    # not caught by db_service's internal try-except, or if get_location failed.
                    print(f"CampaignLoader: Exception during processing/creation of location '{display_name}' (ID: {loc_id}) for guild '{guild_id}': {e}")
                    traceback.print_exc()
            print(f"CampaignLoader: Location population for guild '{guild_id}' complete.")
        else:
            print(f"CampaignLoader: No location data found or data is not a list in '{file_path}'.")

    async def load_and_populate_npcs(self, guild_id: str, campaign_file_path: str) -> None:
        if not self._db_service:
            print("CampaignLoader: DBService not available, skipping NPC population.")
            return

        campaign_data = await self._load_json_file(campaign_file_path)
        if not campaign_data or "npc_archetypes" not in campaign_data:
            print(f"CampaignLoader: No NPC archetypes found in campaign file '{campaign_file_path}'.")
            return

        npc_archetypes = campaign_data["npc_archetypes"]
        print(f"CampaignLoader: Populating {len(npc_archetypes)} NPCs for guild '{guild_id}' from '{campaign_file_path}'...")
        default_lang = self._settings.get('game_rules', {}).get('default_bot_language', 'en')

        for npc_key, npc_def in npc_archetypes.items(): # Iterate over dictionary keys and values
            if not isinstance(npc_def, dict):
                print(f"CampaignLoader: WARNING - Skipping malformed NPC definition. Expected a dictionary, but got {type(npc_def)}. Key: '{npc_key}', Data: {npc_def}")
                continue

            npc_id_internal = npc_def.get("id")
            npc_id = npc_id_internal  # Assume internal ID is present first

            if not npc_id_internal:
                npc_id = npc_key  # Fallback to the dictionary key
                print(f"CampaignLoader: WARNING - NPC definition for key '{npc_key}' is missing an internal 'id' field. Using the key as npc_id. NPC Data: {npc_def}")
            elif npc_id_internal != npc_key:
                print(f"CampaignLoader: WARNING - NPC definition for key '{npc_key}' has an internal 'id' ('{npc_id_internal}') that differs from its key. Prioritizing internal 'id'.")
                # npc_id is already set to npc_id_internal from the initial assignment.

            # The rest of the logic uses 'npc_id'
            name_i18n = npc_def.get("name_i18n")
            display_name_log = npc_id # Default display_name_log to the determined npc_id

            if isinstance(name_i18n, dict) and name_i18n:
                display_name_log = name_i18n.get(default_lang, next(iter(name_i18n.values()), npc_id))
            elif isinstance(npc_def.get("name"), str) and npc_def.get("name"): # Check plain 'name' for logging if name_i18n is bad
                 display_name_log = npc_def.get("name")

            # This check for a valid npc_id (must not be None or empty) is crucial.
            if not npc_id:
                print(f"CampaignLoader: Skipping NPC definition due to unable to determine a valid 'id' (key: '{npc_key}'). NPC Data: {npc_def}")
                continue

            # Check for name_i18n (as it was before, using the determined npc_id for logging if name is missing)
            if not (isinstance(name_i18n, dict) and name_i18n):
                plain_name = npc_def.get("name")
                if isinstance(plain_name, str) and plain_name:
                    name_i18n = {default_lang: plain_name}
                    # display_name_log would have already been set to plain_name if name_i18n was initially missing/invalid
                    print(f"CampaignLoader: NPC '{display_name_log}' (ID: {npc_id}) missing 'name_i18n', using plain 'name' field for default lang '{default_lang}'.")
                else:
                    # If display_name_log is still just the npc_id at this point, it means no usable name was found.
                    print(f"CampaignLoader: Skipping NPC '{display_name_log}' (ID: {npc_id}) due to missing or invalid 'name_i18n' and no fallback 'name' field.")
                    continue
            # Ensure display_name_log is robustly set if name_i18n was successfully derived or found
            if isinstance(name_i18n, dict) and name_i18n:
                 current_display_name = name_i18n.get(default_lang, next(iter(name_i18n.values()), None))
                 if current_display_name:
                     display_name_log = current_display_name
                 # If after all this, display_name_log is still just npc_id, it means a name couldn't be resolved.
                 # The skip condition above for missing name_i18n and plain_name should handle this.


            # Extract other fields, assuming DBService.create_npc will be updated to handle them
            location_id = npc_def.get("location_id", "town_square")
            archetype = npc_def.get("archetype", "commoner")
            stats = npc_def.get("stats", {})
            # description_i18n and persona_i18n are now part of the broader npc_def pass-through

            try:
                existing_npc = await self._db_service.get_npc(npc_id, guild_id=guild_id)
                if not existing_npc:
                    # Updated call to self._db_service.create_npc
                    # Passing i18n fields and other structured data.
                    # The DBService.create_npc method will need to be adapted to this new signature.
                    created_npc_data = await self._db_service.create_npc(
                        npc_id=npc_id,
                        guild_id=guild_id,
                        template_id=npc_id, # Using archetype ID (npc_id from file) as template_id
                        name_i18n=name_i18n,
                        description_i18n=npc_def.get("description_i18n", {}),
                        persona_i18n=npc_def.get("persona_i18n", {}),
                        backstory_i18n=npc_def.get("backstory_i18n", {}),
                        location_id=location_id,
                        archetype=archetype,
                        stats=stats,
                        # Explicit hp and attack are removed, assuming stats dict is comprehensive
                        # and DBService.create_npc will derive health from stats.max_health.

                        # Passing other structured data fields
                        skills_data=npc_def.get("skills"),
                        equipment_data=npc_def.get("equipment_slots"),
                        abilities_data=npc_def.get("abilities"),
                        traits_data=npc_def.get("traits"),
                        desires_data=npc_def.get("desires"),
                        motives_data=npc_def.get("motives"),
                        faction_data=npc_def.get("faction"),
                        behavior_tags_data=npc_def.get("behavior_tags"),
                        loot_table_id_data=npc_def.get("loot_table_id")
                        # Note: DBService.create_npc will need to be updated to accept these,
                        # possibly via **kwargs or by adding them to its signature.
                    )
                    if created_npc_data:
                        print(f"CampaignLoader: Successfully created NPC '{display_name_log}' (ID: {npc_id}, Template: {npc_id}) for guild '{guild_id}' via DBService.")
                    else:
                        # DBService.create_npc would have logged the specific FK error.
                        print(f"CampaignLoader: ERROR - DBService failed to create NPC '{display_name_log}' (ID: {npc_id}, Template: {npc_id}) for guild '{guild_id}'. Check previous DBService error logs.")
                else:
                    print(f"CampaignLoader: NPC '{display_name_log}' (ID: {npc_id}) already exists for guild '{guild_id}', skipping.")
            except Exception as e:
                # This exception would be if the call to db_service.create_npc itself raised an unexpected error
                # not caught by db_service's internal try-except, or if get_npc failed.
                print(f"CampaignLoader: Exception during processing/creation of NPC '{display_name_log}' (ID: {npc_id}) for guild '{guild_id}': {e}")
                traceback.print_exc()
        print(f"CampaignLoader: NPC population for guild '{guild_id}' complete.")

    async def populate_all_game_data(self, guild_id: str, campaign_identifier: Optional[str] = None) -> None:
        """
        Orchestrates the loading and population of all core game data (items, locations, NPCs)
        into the database using DBService.
        """
        if not self._db_service:
            print("CampaignLoader: DBService not available. Cannot populate game data.")
            return

        print(f"CampaignLoader: Starting population of all game data for guild '{guild_id}'.")

        # 1. Populate Item Definitions (Per Guild)
        # Items are now associated with a guild.
        await self.load_and_populate_items(guild_id=guild_id)

        # 2. Populate Locations (Per Guild)
        await self.load_and_populate_locations(guild_id=guild_id)

        # 3. Populate NPCs (Per Guild, from specific campaign file)
        effective_campaign_identifier = campaign_identifier or self._settings.get('default_campaign_identifier', 'default_campaign')
        campaign_file_path = os.path.join(self._campaign_base_path, f"{effective_campaign_identifier}.json")

        if not os.path.exists(campaign_file_path):
            print(f"CampaignLoader: Campaign file '{campaign_file_path}' not found for NPC population. Skipping NPCs.")
        else:
            await self.load_and_populate_npcs(guild_id=guild_id, campaign_file_path=campaign_file_path)

        print(f"CampaignLoader: Finished population of all game data for guild '{guild_id}'.")

    async def load_campaign_data_from_source(self, campaign_identifier: Optional[str] = None) -> Dict[str, Any]:
        """
        Loads raw campaign data (e.g., quests, specific event chains, dialogue trees not directly tied to NPC archetypes)
        from a campaign JSON file. This method is now more focused on campaign-specific narratives rather than base data.
        """
        effective_campaign_identifier = campaign_identifier
        if effective_campaign_identifier is None:
            effective_campaign_identifier = self._settings.get('default_campaign_identifier', 'default_campaign')

        file_path = os.path.join(self._campaign_base_path, f"{effective_campaign_identifier}.json")

        campaign_json_data = await self._load_json_file(file_path)
        if campaign_json_data:
            # This method might still return the full JSON for other parts of the game to use,
            # like quest system, event system, etc.
            return campaign_json_data

        # Fallback for missing specific campaign file (if not default already)
        if campaign_identifier is not None and effective_campaign_identifier != 'default_campaign':
            print(f"CampaignLoader: Fallback - Attempting to load 'default_campaign.json' for raw campaign data.")
            default_campaign_path = os.path.join(self._campaign_base_path, "default_campaign.json")
            return await self._load_json_file(default_campaign_path) or {}

        return {}


    async def list_available_campaigns(self) -> List[str]:
        """
        Lists available campaign identifiers by scanning the campaign data directory.
        """
        campaigns = []
        try:
            if os.path.exists(self._campaign_base_path) and os.path.isdir(self._campaign_base_path):
                for filename_os_list in os.listdir(self._campaign_base_path):
                    if filename_os_list.endswith(".json"):
                        campaigns.append(filename_os_list[:-5]) # Remove .json extension
            if not campaigns:
                print(f"CampaignLoader: No campaign files found in '{self._campaign_base_path}'. Returning placeholder.")
                return ["default_campaign"]
            return campaigns
        except Exception as e:
            print(f"CampaignLoader: Error listing available campaigns from '{self._campaign_base_path}': {e}")
            traceback.print_exc()
            return ["default_campaign"]

