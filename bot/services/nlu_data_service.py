import time
import json
from typing import Dict, List, Any, Optional, Tuple
# Assuming DBService is defined and provides an async interface like fetchall
# from bot.services.db_service import DBService

# For the __main__ block, we'll create a MockDBService
class MockDBService:
    async def fetchall(self, query: str, params: Tuple = ()) -> List[Dict[str, Any]]:
        print(f"MockDBService: Received query: {query} with params: {params}")
        if "FROM locations" in query:
            return [
                {"id": "loc_001", "name_i18n": json.dumps({"en": "Forest of Whispers", "ru": "Лес Шепотов"}), "features_i18n": json.dumps({"en": ["Old Tree", "Hidden Path"], "ru": ["Старое Дерево", "Тайная Тропа"]})},
                {"id": "loc_002", "name_i18n": json.dumps({"en": "Old Mill", "ru": "Старая Мельница"}), "features_i18n": json.dumps({"en": ["Grinding Stone"], "ru": ["Жернов"]})},
                {"id": "loc_003", "name_i18n": json.dumps({"en": "Town Square"}), "features_i18n": None}, # No Russian, no features
            ]
        elif "FROM npcs" in query: # Assuming table name is 'npcs'
            return [
                {"id": "npc_001", "name_i18n": json.dumps({"en": "Guard Captain", "ru": "Капитан Стражи"})},
                {"id": "npc_002", "name_i18n": json.dumps({"en": "Mysterious Stranger", "ru": "Загадочный Незнакомец"})},
            ]
        elif "FROM items" in query: # Assuming table name is 'items'
             return [
                {"id": "item_001", "name_i18n": json.dumps({"en": "Health Potion", "ru": "Зелье Здоровья"})},
                {"id": "item_002", "name_i18n": json.dumps({"en": "Steel Sword", "ru": "Стальной Меч"})},
            ]
        elif "FROM abilities" in query: # Assuming table name is 'abilities'
            return [
                {"id": "abil_001", "name_i18n": json.dumps({"en": "Fireball", "ru": "Огненный Шар"})},
            ]
        elif "FROM skills" in query: # Assuming table name is 'skills'
             return [
                {"id": "skill_001", "name_i18n": json.dumps({"en": "Lockpicking", "ru": "Взлом Замков"})},
            ]
        return []

class NLUDataService:
    """
    Service responsible for providing game-specific entity data to the NLU parser.
    This includes things like known location names, NPC names, item names, skill names, etc.,
    for the specific guild and language, with caching.
    """

    CACHE_TTL_SECONDS = 300 # 5 minutes

    def __init__(self, db_service: Any): # Type hint should be DBService when available
        if db_service is None:
            raise ValueError("NLUDataService requires a valid db_service instance.")
        self.db_service = db_service
        self._cache: Dict[Tuple[str, str], Dict[str, Any]] = {} # Key: (guild_id, language), Value: {'timestamp': float, 'data': entities}
        print("NLUDataService initialized with DBService.")

    def _get_i18n_name(self, i18n_field: Optional[str], language: str, default_lang: str = "en") -> Optional[str]:
        """Safely extracts the i18n name."""
        if not i18n_field:
            return None
        try:
            names = json.loads(i18n_field) if isinstance(i18n_field, str) else i18n_field
            if not isinstance(names, dict): return None # Malformed JSON that isn't a dict
            name = names.get(language)
            if name is None:
                name = names.get(default_lang)
            return name
        except (json.JSONDecodeError, TypeError):
            # If i18n_field is not valid JSON or not a string/dict, return None or handle error
            return None


    async def get_game_entities(self, guild_id: str, language: str) -> Dict[str, List[Dict[str, Any]]]:
        """
        Fetches game-specific entities for NLU processing, using a cache.
        Entities include Locations (and their features), NPCs, Items, Abilities, Skills.
        """
        cache_key = (guild_id, language)
        current_time = time.time()

        # Check cache first
        if cache_key in self._cache:
            cached_item = self._cache[cache_key]
            if current_time - cached_item['timestamp'] < self.CACHE_TTL_SECONDS:
                print(f"NLUDataService: Cache hit for ({guild_id}, {language}).")
                return cached_item['data']
            else:
                print(f"NLUDataService: Cache expired for ({guild_id}, {language}).")
                del self._cache[cache_key]

        print(f"NLUDataService: Cache miss for ({guild_id}, {language}). Fetching from DB.")
        all_entities: Dict[str, List[Dict[str, Any]]] = {
            "location": [], "location_feature": [], "npc": [], "item": [], "ability": [], "skill": []
        }

        # --- Fetch Locations and their Features ---
        # Assuming locations are guild-specific.
        # Table names like 'locations', 'npcs', 'items', 'abilities', 'skills' are placeholders.
        try:
            # Adjust SQL based on actual schema (e.g., `guild_id` presence)
            # For now, assuming global tables for items, abilities, skills, and guild_id for locations/npcs
            
            # Locations
            # TODO: Confirm if locations are guild_id specific in DB. Assuming they are for now.
            # If not, remove `WHERE guild_id = ?` or adjust.
            # For now, let's assume locations might not have guild_id directly and are fetched more broadly or via another link for a "game session"
            # This example will assume a direct guild_id link for simplicity if the table has it.
            # If no guild_id on locations, then they are global: `SELECT id, name_i18n, features_i18n FROM locations;`
            # Let's assume a guild_id column exists for this example.
            loc_query = "SELECT id, name_i18n, features_i18n FROM locations WHERE guild_id = ?;"
            rows = await self.db_service.fetchall(loc_query, (guild_id,))
            for row in rows:
                name = self._get_i18n_name(row['name_i18n'], language)
                if name:
                    all_entities["location"].append({"id": str(row['id']), "name": name, "type": "location", "lang": language})

                features_i18n_str = row.get('features_i18n')
                if features_i18n_str:
                    try:
                        features_map = json.loads(features_i18n_str) if isinstance(features_i18n_str, str) else features_i18n_str
                        if isinstance(features_map, dict):
                            lang_features = features_map.get(language, features_map.get("en", []))
                            for feature_name in lang_features:
                                if feature_name: # Ensure feature name is not empty
                                    all_entities["location_feature"].append({
                                        "id": f"{row['id']}_feat_{feature_name.replace(' ', '_').lower()}", # Create a pseudo-ID
                                        "name": feature_name,
                                        "type": "location_feature",
                                        "lang": language,
                                        "parent_location_id": str(row['id'])
                                    })
                    except (json.JSONDecodeError, TypeError):
                         print(f"NLUDataService: Error parsing features_i18n for location {row['id']}: {features_i18n_str}")

            # NPCs
            # TODO: Confirm if npcs are guild_id specific. Assuming they are.
            npc_query = "SELECT id, name_i18n FROM npcs WHERE guild_id = ?;"
            rows = await self.db_service.fetchall(npc_query, (guild_id,))
            for row in rows:
                name = self._get_i18n_name(row['name_i18n'], language)
                if name:
                    all_entities["npc"].append({"id": str(row['id']), "name": name, "type": "npc", "lang": language})

            # Items (assuming global from 'items' table, not 'item_templates' for instances)
            # If using templates, change table name and consider if they have guild_id.
            # For this example, assuming 'items' table holds general item definitions.
            item_query = "SELECT id, name_i18n FROM items;" # Assuming items are global
            rows = await self.db_service.fetchall(item_query, ())
            for row in rows:
                name = self._get_i18n_name(row['name_i18n'], language)
                if name:
                    all_entities["item"].append({"id": str(row['id']), "name": name, "type": "item", "lang": language})

            # Abilities (assuming global)
            ability_query = "SELECT id, name_i18n FROM abilities;"
            rows = await self.db_service.fetchall(ability_query, ())
            for row in rows:
                name = self._get_i18n_name(row['name_i18n'], language)
                if name:
                    all_entities["ability"].append({"id": str(row['id']), "name": name, "type": "ability", "lang": language})

            # Skills (assuming global)
            skill_query = "SELECT id, name_i18n FROM skills;"
            rows = await self.db_service.fetchall(skill_query, ())
            for row in rows:
                name = self._get_i18n_name(row['name_i18n'], language)
                if name:
                    all_entities["skill"].append({"id": str(row['id']), "name": name, "type": "skill", "lang": language})

        except Exception as e:
            print(f"NLUDataService: Database error while fetching entities for guild {guild_id}, lang {language}: {e}")
            # Optionally, return empty or partially filled dict, or re-raise
            # For now, we'll return whatever was fetched before the error
            # If this was a production system, more robust error handling needed.

        # Store in cache
        self._cache[cache_key] = {'timestamp': current_time, 'data': all_entities}
        if not any(all_entities.values()):
             print(f"NLUDataService: No game entities found or fetched from DB for guild {guild_id}, lang {language}.")
        return all_entities


if __name__ == '__main__':
    import asyncio

    async def test_service():
        mock_db_service = MockDBService()
        nlu_service = NLUDataService(db_service=mock_db_service)

        test_guild_id = "guild_test_123"
        test_lang_en = "en"
        test_lang_ru = "ru"

        print(f"\n--- Test Run 1: Fetching English entities for {test_guild_id} ---")
        entities_en1 = await nlu_service.get_game_entities(test_guild_id, test_lang_en)
        print(f"Entities (en, 1st call): {json.dumps(entities_en1, indent=2)}")
        assert "location" in entities_en1 and len(entities_en1["location"]) > 0
        assert "location_feature" in entities_en1 and len(entities_en1["location_feature"]) > 0
        assert "npc" in entities_en1 and len(entities_en1["npc"]) > 0
        assert entities_en1["location"][0]["name"] == "Forest of Whispers"
        assert entities_en1["location_feature"][0]["name"] == "Old Tree"


        print(f"\n--- Test Run 2: Fetching English entities for {test_guild_id} again (should hit cache) ---")
        entities_en2 = await nlu_service.get_game_entities(test_guild_id, test_lang_en)
        print(f"Entities (en, 2nd call): {json.dumps(entities_en2, indent=2)}")
        assert entities_en1 == entities_en2 # Should be identical from cache

        print(f"\n--- Test Run 3: Fetching Russian entities for {test_guild_id} ---")
        entities_ru1 = await nlu_service.get_game_entities(test_guild_id, test_lang_ru)
        print(f"Entities (ru, 1st call): {json.dumps(entities_ru1, indent=2)}")
        assert "location" in entities_ru1 and len(entities_ru1["location"]) > 0
        assert entities_ru1["location"][0]["name"] == "Лес Шепотов"
        assert "location_feature" in entities_ru1 and len(entities_ru1["location_feature"]) > 0
        assert entities_ru1["location_feature"][0]["name"] == "Старое Дерево"


        print(f"\n--- Test Run 4: Cache Expiry Demonstration ---")
        # Modify cache TTL for testing or manually expire cache entry
        nlu_service.CACHE_TTL_SECONDS = 0.1 # Very short TTL
        print(f"Cache TTL set to {nlu_service.CACHE_TTL_SECONDS}s for testing expiry.")

        # Wait for TTL to expire
        await asyncio.sleep(0.2)

        print(f"Fetching English entities for {test_guild_id} after TTL expiry (should fetch from DB again) ---")
        entities_en3 = await nlu_service.get_game_entities(test_guild_id, test_lang_en)
        print(f"Entities (en, 3rd call after expiry): {json.dumps(entities_en3, indent=2)}")
        # This call should have logged "Cache expired" and "Fetching from DB"
        # The data should be the same as entities_en1 if DB content is static
        assert entities_en3["location"][0]["name"] == "Forest of Whispers"

        # Reset TTL if needed for other tests, though __main__ exits here.
        nlu_service.CACHE_TTL_SECONDS = 300

        print("\nNLUDataService full test completed.")

    asyncio.run(test_service())
