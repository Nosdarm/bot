# bot/services/nlu_data_service.py

import json # For parsing name_i18n JSON
from typing import Dict, List, Any
from bot.nlu.nlu_data_types import NLUEntity
# Assuming SqliteAdapter or a similar DB interface will be passed
# from bot.database.sqlite_adapter import SqliteAdapter # Example import
from bot.services.db_service import DBService

class NLUDataService:
    def __init__(self, db_service: DBService): # Changed from db_adapter: Any
        self.db_service = db_service # Changed from self.db_adapter
        if not self.db_service: # Changed from self.db_adapter
            # Potentially log a warning or raise an error if db_adapter is crucial
            print("Warning: NLUDataService initialized without a database service.") # Changed message

    async def get_game_entities(self, guild_id: str, language: str) -> Dict[str, List[NLUEntity]]:
        """
        Fetches relevant game entities (locations, NPCs, items, skills) from the database
        for a specific guild and language.

        Args:
            guild_id (str): The ID of the guild to fetch entities for.
            language (str): The language for i18n names.
        
        Returns:
            Dict[str, List[NLUEntity]]: A dictionary where keys are entity types
                                         (e.g., "location", "npc", "item") and values are lists
                                         of NLUEntity objects.
        """
        if not self.db_service: # Changed from self.db_adapter
            print("Error: NLUDataService cannot fetch entities without a database service.") # Changed message
            return {}

        # Placeholder implementation:
        # In a real scenario, this would involve complex SQL queries.
        # For now, returning dummy data or an empty dict.
        
        # TODO: Implement actual database queries for:
        # 1. Locations (from `locations` table, using `name_i18n` if available)
        #    - Filter by guild_id if locations are guild-specific or link to a game_session_id tied to guild_id
        # 2. NPCs (from `npcs` or `generated_npcs` table, using `name_i18n`)
        #    - Filter by guild_id similarly
        # 3. Items (from `item_templates` table, using `name_i18n`)
        #    - Items are usually global, but check if any link to guild/session specifically.
        # 4. Skills (from `skills` table, using `name_i18n`)
        #    - Skills are generally global.

        all_entities: Dict[str, List[NLUEntity]] = {
            "location": [],
            "npc": [],
            "item": [],
            "skill": []
        }

        # --- Fetch Locations ---
        # Assuming locations might be guild-specific or linked via a game session.
        # This query assumes a `guild_id` column directly in the `locations` table.
        # Adjust if your schema links locations to guilds through another table (e.g., `game_sessions`).
        sql_locations = "SELECT id, name_i18n FROM locations WHERE guild_id = ?;"
        try:
            locations_data = await self.db_service.fetchall(sql_locations, (guild_id,)) # Changed from self.db_adapter
            for loc_row in locations_data:
                try:
                    names = json.loads(loc_row['name_i18n']) if isinstance(loc_row['name_i18n'], str) else loc_row['name_i18n']
                    loc_name = names.get(language, names.get('en')) # Fallback to English
                    if loc_name:
                        all_entities["location"].append(NLUEntity(id=str(loc_row['id']), name=loc_name, type="location", lang=language))
                except (json.JSONDecodeError, TypeError, AttributeError) as e:
                    print(f"Error processing location name_i18n for ID {loc_row['id']}: {e}. Data: {loc_row['name_i18n']}")
        except Exception as e:
            print(f"NLUDataService: Database error fetching locations for guild {guild_id}: {e}")

        # --- Fetch NPCs ---
        # Assuming NPCs are guild-specific.
        # Updated table name to generated_npcs based on models.py
        sql_npcs = "SELECT id, name_i18n FROM generated_npcs WHERE guild_id = ?;"
        # Also consider `generated_npcs` if they are separate and relevant for NLU matching.
        # If so, you might UNION ALL results from both tables.
        try:
            npcs_data = await self.db_service.fetchall(sql_npcs, (guild_id,)) # Changed from self.db_adapter
            for npc_row in npcs_data:
                try:
                    names = json.loads(npc_row['name_i18n']) if isinstance(npc_row['name_i18n'], str) else npc_row['name_i18n']
                    npc_name = names.get(language, names.get('en'))
                    if npc_name:
                        all_entities["npc"].append(NLUEntity(id=str(npc_row['id']), name=npc_name, type="npc", lang=language))
                except (json.JSONDecodeError, TypeError, AttributeError) as e:
                    print(f"Error processing NPC name_i18n for ID {npc_row['id']}: {e}. Data: {npc_row['name_i18n']}")
        except Exception as e:
            print(f"NLUDataService: Database error fetching NPCs for guild {guild_id}: {e}")
            
        # --- Fetch Items (from item_templates) ---
        # Assuming item templates are global.
        sql_items = "SELECT id, name_i18n FROM item_templates;"
        try:
            items_data = await self.db_service.fetchall(sql_items, ()) # Changed from self.db_adapter
            for item_row in items_data:
                try:
                    names = json.loads(item_row['name_i18n']) if isinstance(item_row['name_i18n'], str) else item_row['name_i18n']
                    item_name = names.get(language, names.get('en'))
                    if item_name:
                       all_entities["item"].append(NLUEntity(id=str(item_row['id']), name=item_name, type="item", lang=language))
                except (json.JSONDecodeError, TypeError, AttributeError) as e:
                    print(f"Error processing item name_i18n for ID {item_row['id']}: {e}. Data: {item_row['name_i18n']}")
        except Exception as e:
            print(f"NLUDataService: Database error fetching items: {e}")

        # --- Fetch Skills ---
        # Assuming skills are global.
        sql_skills = "SELECT id, name_i18n FROM skills;"
        try:
            skills_data = await self.db_service.fetchall(sql_skills, ()) # Changed from self.db_adapter
            for skill_row in skills_data:
                try:
                    names = json.loads(skill_row['name_i18n']) if isinstance(skill_row['name_i18n'], str) else skill_row['name_i18n']
                    skill_name = names.get(language, names.get('en'))
                    if skill_name:
                        all_entities["skill"].append(NLUEntity(id=str(skill_row['id']), name=skill_name, type="skill", lang=language))
                except (json.JSONDecodeError, TypeError, AttributeError) as e:
                    print(f"Error processing skill name_i18n for ID {skill_row['id']}: {e}. Data: {skill_row['name_i18n']}")
        except Exception as e:
            print(f"NLUDataService: Database error fetching skills: {e}")
        
        if not any(all_entities.values()): # Check if any list in the dict is non-empty
             print(f"NLUDataService: No game entities found for guild {guild_id}, lang {language}. This might be expected or indicate an issue with data or queries.")
             
        return all_entities

# Example Usage (conceptual, would be in GameManager or RPGBot)
# async def main():
#     # Mock db_adapter
#     class MockDbAdapter:
#         async def fetchall(self, query, params):
#             print(f"Mock DB Query: {query} with {params}")
#             if "locations" in query:
#                 return [{"id": "loc1", "name_i18n": '{"en": "Old Mill", "ru": "Старая Мельница"}'}]
#             if "npcs" in query:
#                 return [{"id": "npc1", "name_i18n": '{"en": "Guard Tom", "ru": "Стражник Том"}'}]
#             if "item_templates" in query:
#                 return [{"id": "item1", "name_i18n": '{"en": "Health Potion", "ru": "Зелье Здоровья"}'}]
#             return []

#     db_adapter = MockDbAdapter()
#     nlu_data_service = NLUDataService(db_adapter)
#     entities = await nlu_data_service.get_game_entities(guild_id="test_guild", language="en")
#     print(entities)
#     entities_ru = await nlu_data_service.get_game_entities(guild_id="test_guild", language="ru")
#     print(entities_ru)

# if __name__ == "__main__":
#     import asyncio
#     asyncio.run(main())


