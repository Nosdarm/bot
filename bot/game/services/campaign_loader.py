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

    async def load_and_populate_items(self, items_file_path: Optional[str] = None) -> None:
        if not self._db_service:
            print("CampaignLoader: DBService not available, skipping item population.")
            return

        file_path = items_file_path or os.path.join(self._data_base_path, "items.json")
        items_data = await self._load_json_file(file_path)

        if items_data and isinstance(items_data, list):
            print(f"CampaignLoader: Populating {len(items_data)} item definitions...")
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
                            effects=properties_to_store # Pass the consolidated dict here
                        )
                        print(f"CampaignLoader: Created item definition '{name}' (ID: {item_id}).")
                    else:
                        print(f"CampaignLoader: Item definition '{name}' (ID: {item_id}) already exists, skipping.")
                except Exception as e:
                    print(f"CampaignLoader: Error creating item definition '{name}' (ID: {item_id}): {e}")
                    traceback.print_exc()
            print("CampaignLoader: Item definition population complete.")
        else:
            print(f"CampaignLoader: No item data found or data is not a list in '{file_path}'.")

    async def load_and_populate_locations(self, guild_id: str, locations_file_path: Optional[str] = None) -> None:
        if not self._db_service:
            print("CampaignLoader: DBService not available, skipping location population.")
            return

        file_path = locations_file_path or os.path.join(self._data_base_path, "locations.json")
        locations_data = await self._load_json_file(file_path)

        if locations_data and isinstance(locations_data, list):
            print(f"CampaignLoader: Populating {len(locations_data)} locations for guild '{guild_id}'...")
            for loc_def in locations_data:
                loc_id = loc_def.get("id")
                name = loc_def.get("name")
                description = loc_def.get("description", "")
                # 'connections' in JSON should map to 'exits' in DBService.create_location
                exits_data = {conn: conn for conn in loc_def.get("connections", [])} # Simple mapping for now

                if not loc_id or not name:
                    print(f"CampaignLoader: Skipping location due to missing id or name: {loc_def}")
                    continue

                try:
                    existing_loc = await self._db_service.get_location(loc_id, guild_id=guild_id)
                    if not existing_loc:
                        await self._db_service.create_location(
                            loc_id=loc_id,
                            name=name,
                            description=description,
                            guild_id=guild_id,
                            exits=exits_data, # Pass connections as exits
                            template_id=loc_def.get("template_id", loc_id) # Use id as template_id if not specified
                        )
                        print(f"CampaignLoader: Created location '{name}' (ID: {loc_id}) for guild '{guild_id}'.")
                    else:
                        print(f"CampaignLoader: Location '{name}' (ID: {loc_id}) already exists for guild '{guild_id}', skipping.")
                except Exception as e:
                    print(f"CampaignLoader: Error creating location '{name}' (ID: {loc_id}) for guild '{guild_id}': {e}")
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
        for npc_def in npc_archetypes:
            npc_id = npc_def.get("id")
            name = npc_def.get("name")
            persona = npc_def.get("persona", "")
            description = npc_def.get("description", persona) # Fallback description to persona
            location_id = npc_def.get("location_id", "town_square") # Default location if not specified
            archetype = npc_def.get("archetype", "commoner")
            stats = npc_def.get("stats", {})

            hp = stats.get("max_health", 50) # Default HP
            # Attack might be derived from stats.base_damage or a specific attack stat.
            # DBService.create_npc expects an 'attack' param, which it puts into stats if not there.
            # Let's assume 'base_damage' string needs parsing or a numeric 'attack' stat exists.
            # For simplicity, let's look for 'attack' in stats or use a default.
            attack_stat = stats.get("attack", stats.get("strength", 5)) # Default attack

            if not npc_id or not name:
                print(f"CampaignLoader: Skipping NPC due to missing id or name: {npc_def}")
                continue

            try:
                existing_npc = await self._db_service.get_npc(npc_id, guild_id=guild_id)
                if not existing_npc:
                    await self._db_service.create_npc(
                        npc_id=npc_id,
                        name=name,
                        persona=persona,
                        guild_id=guild_id,
                        location_id=location_id,
                        hp=int(hp),
                        attack=int(attack_stat),
                        description=description,
                        stats=stats,
                        archetype=archetype
                    )
                    print(f"CampaignLoader: Created NPC '{name}' (ID: {npc_id}) for guild '{guild_id}'.")
                else:
                    print(f"CampaignLoader: NPC '{name}' (ID: {npc_id}) already exists for guild '{guild_id}', skipping.")
            except Exception as e:
                print(f"CampaignLoader: Error creating NPC '{name}' (ID: {npc_id}) for guild '{guild_id}': {e}")
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

        # 1. Populate Item Definitions (Global)
        # Items are global, so they are loaded once, not per guild, but function can be called per guild if needed
        # to ensure they are loaded if not already. DBService methods are idempotent.
        await self.load_and_populate_items()

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

