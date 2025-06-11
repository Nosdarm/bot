import asyncio
import unittest
import json
import time
from unittest.mock import AsyncMock, MagicMock, call # Import call for checking multiple calls
from typing import Dict, List, Any, Optional, Tuple, TypedDict

# Assuming NLUDataService is in bot.services.nlu_data_service
from bot.services.nlu_data_service import NLUDataService, GameEntity # GameEntity might need to be defined here if not easily importable

# Re-define GameEntity if not imported, for clarity in tests
class GameEntity(TypedDict, total=False): # total=False if parent_location_id is optional
    id: str
    name: str
    type: str
    lang: str
    parent_location_id: Optional[str]

# ENTITY_CONFIG needs to be accessible to the tests for verification against its structure.
# It's better to import it from nlu_data_service if possible, or redefine it here for stability.
# For this test, let's redefine a minimal version or assume its structure.
# To avoid divergence, it's best if the test can import the actual ENTITY_CONFIG.
# For now, I'll proceed as if its structure is known.
# from bot.services.nlu_data_service import ENTITY_CONFIG # Ideal if possible

# Simplified ENTITY_CONFIG for testing structure, real one is in NLUDataService
TEST_ENTITY_CONFIG: Dict[str, Dict[str, Any]] = {
    "location": {"table": "locations", "name_field": "name_i18n", "type_name": "location", "guild_column": "guild_id", "tags_field": "tags_i18n", "tag_type_name": "location_tag", "features_field": "features_i18n", "feature_type_name": "location_feature"},
    "location_template": {"table": "location_templates", "name_field": "name", "type_name": "location_template", "guild_column": "guild_id", "nullable_guild": True},
    "item_template": {"table": "item_templates", "name_field": "name_i18n", "type_name": "item_template", "guild_column": "guild_id", "nullable_guild": True},
    "item": {"table": "items", "name_field": "name_i18n", "type_name": "item", "guild_column": "guild_id"},
    "npc": {"table": "npcs", "name_field": "name_i18n", "type_name": "npc", "guild_column": "guild_id"},
    "skill": {"table": "skills", "name_field": "name_i18n", "type_name": "skill", "guild_column": None},
    # Add other minimal configs as needed for tests
}


class TestNLUDataService(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.mock_db_service = AsyncMock()
        self.nlu_service = NLUDataService(db_service=self.mock_db_service)
        # Reset cache for each test
        self.nlu_service._cache = {}
        # Original CACHE_TTL_SECONDS for restoration if a test modifies it
        self.original_cache_ttl = NLUDataService.CACHE_TTL_SECONDS

    async def asyncTearDown(self):
        # Restore original cache TTL after tests that modify it
        NLUDataService.CACHE_TTL_SECONDS = self.original_cache_ttl

    def _mock_db_fetchall(self, query_to_data_map: Dict[str, List[Dict[str, Any]]]):
        """
        Configures mock_db_service.fetchall to return specific data for queries
        containing certain substrings (e.g., table names).
        """
        async def side_effect(query: str, params: Tuple = ()):
            # print(f"Mock DB Fetchall: Query='{query}', Params='{params}'") # Debugging
            for key_substring, data in query_to_data_map.items():
                if key_substring in query:
                    # Apply guild_id filtering if params are present (simplified)
                    if params and len(params) > 0 and isinstance(params[0], str) and "guild" in params[0]:
                        guild_id_to_filter = params[0]

                        # Simulate (guild_id = ? OR guild_id IS NULL) for fetch_global_too=True
                        if "OR guild_id IS NULL" in query.upper():
                             return [row for row in data if row.get("guild_id") == guild_id_to_filter or row.get("guild_id") is None]
                        # Simulate guild_id = ?
                        return [row for row in data if row.get("guild_id") == guild_id_to_filter]
                    return data # Return all data if no guild_id param or not filtering by it
            return [] # Default empty result
        self.mock_db_service.fetchall.side_effect = side_effect

    async def test_load_all_entity_types_and_i18n_name_extraction(self):
        guild_id = "test_guild_1"
        lang = "en"

        mock_data = {
            "FROM locations": [{"id": "loc1", "name_i18n": json.dumps({"en": "Tavern", "ru": "Таверна"}), "guild_id": guild_id, "tags_i18n": json.dumps({"en": ["building"]}), "features_i18n": json.dumps({"en": ["bar"]})}],
            "FROM location_templates": [{"id": "ltpl1", "name": "Dungeon Template", "guild_id": None}], # Non-i18n name
            "FROM items": [{"id": "item1", "name_i18n": json.dumps({"ru": "Меч"}), "guild_id": guild_id}], # Only RU, should fallback to EN if default is EN, or be None if only RU
            "FROM npcs": [{"id": "npc1", "name_i18n": json.dumps({"en": "Guard"}), "guild_id": guild_id}],
            "FROM skills": [{"id": "skill1", "name_i18n": json.dumps({"en": "Sneak", "ru": "Скрытность"})}] # Global
        }
        self._mock_db_fetchall(mock_data)

        entities = await self.nlu_service.get_game_entities(guild_id, lang, fetch_global_too=True)

        self.assertEqual(entities["location"][0]["name"], "Tavern")
        self.assertEqual(entities["location_template"][0]["name"], "Dungeon Template") # Non-i18n
        self.assertIsNone(entities["item"][0]["name"]) # No 'en' name, default is 'en'
        self.assertEqual(entities["npc"][0]["name"], "Guard")
        self.assertEqual(entities["skill"][0]["name"], "Sneak")

        self.assertTrue(len(entities["location_tag"]) == 1)
        self.assertEqual(entities["location_tag"][0]["name"], "building")
        self.assertEqual(entities["location_tag"][0]["parent_location_id"], "loc1")
        self.assertTrue(len(entities["location_feature"]) == 1)
        self.assertEqual(entities["location_feature"][0]["name"], "bar")

    async def test_guild_filtering_specific_guild_only(self):
        guild_id_1 = "guild1"
        guild_id_2 = "guild2"
        lang = "en"

        mock_data = {
            "FROM items": [
                {"id": "item_g1", "name_i18n": json.dumps({"en": "Guild1 Item"}), "guild_id": guild_id_1},
                {"id": "item_g2", "name_i18n": json.dumps({"en": "Guild2 Item"}), "guild_id": guild_id_2},
            ],
            "FROM item_templates": [ # Has nullable_guild: True
                {"id": "item_tpl_g1", "name_i18n": json.dumps({"en": "Guild1 Template"}), "guild_id": guild_id_1},
                {"id": "item_tpl_global", "name_i18n": json.dumps({"en": "Global Template"}), "guild_id": None},
            ]
        }
        self._mock_db_fetchall(mock_data)

        # Fetch for guild1, no globals for item_templates
        entities_g1_local = await self.nlu_service.get_game_entities(guild_id_1, lang, fetch_global_too=False)

        self.assertEqual(len(entities_g1_local["item"]), 1)
        self.assertEqual(entities_g1_local["item"][0]["id"], "item_g1")
        self.assertEqual(len(entities_g1_local["item_template"]), 1) # Only guild1's template
        self.assertEqual(entities_g1_local["item_template"][0]["id"], "item_tpl_g1")

    async def test_guild_filtering_with_globals(self):
        guild_id_1 = "guild1"
        lang = "en"
        mock_data = {
            "FROM item_templates": [
                {"id": "item_tpl_g1", "name_i18n": json.dumps({"en": "Guild1 Template"}), "guild_id": guild_id_1},
                {"id": "item_tpl_global", "name_i18n": json.dumps({"en": "Global Template"}), "guild_id": None},
                {"id": "item_tpl_g2", "name_i18n": json.dumps({"en": "Guild2 Template"}), "guild_id": "guild2"},
            ]
        }
        self._mock_db_fetchall(mock_data)

        # Fetch for guild1, WITH globals for item_templates
        entities_g1_global = await self.nlu_service.get_game_entities(guild_id_1, lang, fetch_global_too=True)

        self.assertEqual(len(entities_g1_global["item_template"]), 2) # Guild1's + Global
        template_ids = {e["id"] for e in entities_g1_global["item_template"]}
        self.assertIn("item_tpl_g1", template_ids)
        self.assertIn("item_tpl_global", template_ids)
        self.assertNotIn("item_tpl_g2", template_ids)

    async def test_caching_logic(self):
        guild_id = "cache_guild"
        lang = "en"
        mock_data = {"FROM skills": [{"id": "skill1", "name_i18n": json.dumps({"en": "TestSkill"})}]}
        self._mock_db_fetchall(mock_data)

        # First call - should hit DB
        await self.nlu_service.get_game_entities(guild_id, lang)
        self.mock_db_service.fetchall.assert_called() # Called at least once for skills table
        initial_call_count = self.mock_db_service.fetchall.call_count

        # Second call - should use cache
        await self.nlu_service.get_game_entities(guild_id, lang)
        self.assertEqual(self.mock_db_service.fetchall.call_count, initial_call_count) # No new DB calls

        # Expire cache and test again
        self.nlu_service.CACHE_TTL_SECONDS = 0.01
        await asyncio.sleep(0.02)

        await self.nlu_service.get_game_entities(guild_id, lang)
        self.assertGreater(self.mock_db_service.fetchall.call_count, initial_call_count) # DB called again

    async def test_empty_db_results(self):
        guild_id = "empty_guild"
        lang = "en"
        self._mock_db_fetchall({}) # No data for any query key

        entities = await self.nlu_service.get_game_entities(guild_id, lang)

        for entity_type in TEST_ENTITY_CONFIG.keys(): # Check all configured types
            self.assertEqual(len(entities.get(TEST_ENTITY_CONFIG[entity_type]["type_name"], [])), 0)
        self.assertEqual(len(entities.get("location_tag", [])), 0)
        self.assertEqual(len(entities.get("location_feature", [])), 0)


    async def test_malformed_json_in_name_field(self):
        guild_id = "json_err_guild"
        lang = "en"
        mock_data = {
            "FROM items": [
                {"id": "item_ok", "name_i18n": json.dumps({"en": "Good Item"}), "guild_id": guild_id},
                {"id": "item_bad_json", "name_i18n": "{'en': 'Bad JSON, no quotes'}", "guild_id": guild_id},
                {"id": "item_not_dict", "name_i18n": json.dumps(["List", "not dict"]), "guild_id": guild_id},
            ],
            "FROM locations": [
                {"id": "loc_bad_tags", "name_i18n": json.dumps({"en":"Bad Tags Loc"}), "guild_id": guild_id, "tags_i18n": "not a json list", "features_i18n": json.dumps(["valid_feature"])}
            ]
        }
        self._mock_db_fetchall(mock_data)

        # Patch print to capture error logs if any (NLUDataService uses print for errors)
        with patch('builtins.print') as mock_print:
            entities = await self.nlu_service.get_game_entities(guild_id, lang)

        self.assertEqual(len(entities["item"]), 1) # Only Good Item should load with a name
        self.assertEqual(entities["item"][0]["name"], "Good Item")

        # Check that bad items either have no name or are skipped (current _get_i18n_name returns None)
        # The current NLUDataService skips entities if name is None after _get_i18n_name.
        # So, item_bad_json and item_not_dict will not be in the list.

        self.assertEqual(len(entities["location"]), 1) # Bad Tags Loc should load
        self.assertEqual(entities["location"][0]["name"], "Bad Tags Loc")
        self.assertEqual(len(entities["location_tag"]), 0) # Tags should fail to parse
        self.assertEqual(len(entities["location_feature"]), 1) # Feature should be fine

        # Example: check if print was called with error messages (optional, depends on exact logging)
        # self.assertTrue(any("Error parsing" in call_args[0][0] for call_args in mock_print.call_args_list))


if __name__ == '__main__':
    unittest.main()
