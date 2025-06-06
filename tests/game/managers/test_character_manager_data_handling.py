import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import json

import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import json

from bot.game.models.character import Character
from bot.game.managers.character_manager import CharacterManager
from bot.database.postgres_adapter import PostgresAdapter # Corrected path

class TestCharacterManagerActionPersistence(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # self.mock_db_adapter = MagicMock()
        # If SqliteAdapter is a class that needs instantiation:
        self.mock_db_adapter = MagicMock(spec=PostgresAdapter) # Use spec for better mocking
        # If SqliteAdapter methods are async, use AsyncMock for them:
        self.mock_db_adapter.execute = AsyncMock()
        self.mock_db_adapter.fetchone = AsyncMock()
        self.mock_db_adapter.fetchall = AsyncMock()
        self.mock_db_adapter.execute_insert = AsyncMock(return_value=1) # Assuming returns lastrowid

        self.character_manager = CharacterManager(db_adapter=self.mock_db_adapter)

        # Default character data for tests
        self.character_id = "test_char_123"
        self.guild_id = "test_guild_789"
        self.discord_user_id = 1234567890
        self.base_char_data = {
            "id": self.character_id,
            "guild_id": self.guild_id,
            "discord_user_id": self.discord_user_id,
            "name": "Test Character",
            "stats": json.dumps({"strength": 10, "dexterity": 12}),
            "inventory": json.dumps(["item1", "item2"]),
            "location_id": "start_town",
            "party_id": None,
            "hp": 100.0,
            "max_health": 100.0,
            "is_alive": 1,
            # Add other fields as per your Character model and DB schema
            "collected_actions_json": None # Default to None for loading tests
        }

    async def test_save_character_with_collected_actions(self):
        """
        Test that save_character correctly serializes collected_actions_json
        and includes it in the SQL query.
        """
        char = Character.from_dict({
            **self.base_char_data,
            # No need to set collected_actions_json here, set it on the object
        })
        sample_actions = [{"action": "move", "target": "north"}, {"action": "search"}]
        char.collected_actions_json = sample_actions # Store as Python object

        # The save_character method in CharacterManager should handle the to_dict() and serialization
        # We need to mock the Character.to_dict method to ensure it includes collected_actions_json
        # or trust that CharacterManager's save logic correctly calls json.dumps on this field.

        # Let's assume CharacterManager.save_character constructs the SQL and params
        # based on the character object's attributes directly or via a to_db_dict method.

        # For this test, we'll focus on the CharacterManager's responsibility to pass it to DB.
        # The save_character method is not defined in the provided CharacterManager snippet,
        # so we'll assume a general structure for it.
        # Let's assume `save_character` calls `_db_adapter.execute` with appropriate SQL.

        # We need to find which method in CharacterManager does the actual saving.
        # Based on previous files, it's likely save_state which calls save_character.
        # Let's assume `self.character_manager.save_character(char, self.guild_id)` exists and works.

        # If save_character is the direct method:
        # await self.character_manager.save_character(char)

        # If it's through save_state (more likely for batching):
        self.character_manager._characters[self.guild_id] = {char.id: char} # Add to cache
        self.character_manager.mark_character_dirty(self.guild_id, char.id) # Mark as dirty
        await self.character_manager.save_state(self.guild_id)

        self.mock_db_adapter.execute.assert_called()

        # Get the arguments of the last call to db_adapter.execute
        args, kwargs = self.mock_db_adapter.execute.call_args
        sql_query = args[0]
        params = args[1]

        self.assertIn("collected_actions_json", sql_query.lower())

        # Find the index of collected_actions_json in the SQL query's column list
        # This is a bit brittle and depends on the exact SQL query structure.
        # A more robust way would be to check if the serialized JSON is in params,
        # and its corresponding placeholder is in the SQL.

        # Example: Assuming collected_actions_json is one of the later params.
        # And that params is a tuple.
        serialized_actions = json.dumps(sample_actions)
        self.assertIn(serialized_actions, params)

    async def test_load_character_with_collected_actions(self):
        """
        Test that load_character (or its internal DB fetch) correctly parses
        collected_actions_json from the DB into a Python object.
        """
        sample_actions_json_str = json.dumps([{"action": "attack", "target_id": "mob1"}])
        db_row_data = {**self.base_char_data, "collected_actions_json": sample_actions_json_str}

        # Mock the DB response
        self.mock_db_adapter.fetchone.return_value = db_row_data # Direct dict if row_factory is good

        # Call the method in CharacterManager that loads a single character by ID.
        # This method might be `load_character(id, guild_id)` or similar.
        # Or, if load_state populates the cache, we can check the cache.
        # Let's assume a direct load method for simplicity or that load_state calls such a method.

        # If CharacterManager.load_state populates the cache after fetching:
        self.mock_db_adapter.fetchall.return_value = [db_row_data] # fetchall for load_state
        await self.character_manager.load_state(self.guild_id)

        loaded_char = self.character_manager.get_character(self.guild_id, self.character_id)

        self.assertIsNotNone(loaded_char)
        self.assertIsInstance(loaded_char.collected_actions_json, list)
        self.assertEqual(loaded_char.collected_actions_json, json.loads(sample_actions_json_str))

    async def test_load_character_with_null_collected_actions(self):
        """
        Test loading a character where collected_actions_json is NULL/None in the DB.
        """
        db_row_data_null_actions = {**self.base_char_data, "collected_actions_json": None}

        self.mock_db_adapter.fetchone.return_value = db_row_data_null_actions

        # Assuming load_state is the entry point for loading from DB
        self.mock_db_adapter.fetchall.return_value = [db_row_data_null_actions]
        await self.character_manager.load_state(self.guild_id)

        loaded_char = self.character_manager.get_character(self.guild_id, self.character_id)

        self.assertIsNotNone(loaded_char)
        # The Character model's from_dict should handle None and default it,
        # typically to None or an empty list/dict based on its definition.
        # If Character.collected_actions_json defaults to None if the DB field is NULL:
        self.assertIsNone(loaded_char.collected_actions_json)
        # Or, if it defaults to an empty list:
        # self.assertEqual(loaded_char.collected_actions_json, [])

    async def test_save_character_with_empty_collected_actions(self):
        """
        Test that save_character correctly serializes an empty list for collected_actions_json.
        """
        char = Character.from_dict(self.base_char_data) # base_char_data has collected_actions_json: None
        empty_actions_str = json.dumps([])
        char.collected_actions_json = empty_actions_str # Model expects string

        self.character_manager._characters[self.guild_id] = {char.id: char}
        self.character_manager.mark_character_dirty(self.guild_id, char.id)
        await self.character_manager.save_state(self.guild_id)

        self.mock_db_adapter.execute.assert_called()
        args, kwargs = self.mock_db_adapter.execute.call_args
        sql_query = args[0]
        params = args[1]

        self.assertIn("collected_actions_json", sql_query.lower())
        # The CharacterManager's save logic should pull `char.collected_actions_json` (which is already a string)
        self.assertIn(empty_actions_str, params)

    async def test_save_character_with_null_collected_actions(self):
        """
        Test that save_character correctly handles None for collected_actions_json,
        serializing it as SQL NULL (json.dumps(None) is 'null').
        """
        char = Character.from_dict(self.base_char_data)
        char.collected_actions_json = None # Model attribute is Optional[str]

        self.character_manager._characters[self.guild_id] = {char.id: char}
        self.character_manager.mark_character_dirty(self.guild_id, char.id)
        await self.character_manager.save_state(self.guild_id)

        self.mock_db_adapter.execute.assert_called()
        args, kwargs = self.mock_db_adapter.execute.call_args
        sql_query = args[0]
        params = args[1]

        self.assertIn("collected_actions_json", sql_query.lower())
        # When CharacterManager calls to_dict(), it gets None for collected_actions_json.
        # The save logic in CharacterManager should then pass json.dumps(None) or SQL NULL.
        # Assuming it passes json.dumps(None) which results in the string 'null'.
        self.assertIn(json.dumps(None), params)


    async def test_save_character_all_complex_fields(self):
        """Test saving character with all new i18n and JSON fields."""
        char_data_py_objects = {
            "id": self.character_id,
            "discord_user_id": self.discord_user_id,
            "name_i18n": {"en": "Complex Hero", "ru": "Сложный Герой"}, # attribute on model
            "guild_id": self.guild_id,
            "skills_data": [{"skill": "alchemy", "level": 15}],       # attribute on model
            "abilities_data": [{"ability": "double_strike", "rank": 2}],# attribute on model
            "spells_data": [{"spell": "invisibility", "duration": 60}],# attribute on model
            "character_class": "Rogue",                                # attribute on model
            "flags": {"is_hidden": True, "can_fly": False},            # attribute on model
            "collected_actions_json": json.dumps([{"action": "hide"}]),# model expects string
            # Fill other required fields for Character.from_dict
            "stats": json.dumps({"hp":100}), "inventory": json.dumps([]), "hp":100, "max_health":100,
        }
        char = Character.from_dict(char_data_py_objects)

        self.character_manager._characters[self.guild_id] = {char.id: char}
        self.character_manager.mark_character_dirty(self.guild_id, char.id)
        await self.character_manager.save_state(self.guild_id)

        self.mock_db_adapter.execute.assert_called_once()
        args, _ = self.mock_db_adapter.execute.call_args
        sql_query_lower = args[0].lower()
        params = args[1]

        # Check that JSON serialized versions are in params
        # The CharacterManager's save_character_to_db (or similar) should handle this.
        # It typically gets these from character.to_dict() and then json.dumps them.
        # Character.to_dict() returns Python objects for these complex fields.

        # For name_i18n (saved in 'name' column as JSON string)
        self.assertIn("name", sql_query_lower) # DB column is 'name'
        self.assertIn(json.dumps(char_data_py_objects["name_i18n"]), params)

        self.assertIn("skills_data_json", sql_query_lower)
        self.assertIn(json.dumps(char_data_py_objects["skills_data"]), params)

        self.assertIn("abilities_data_json", sql_query_lower)
        self.assertIn(json.dumps(char_data_py_objects["abilities_data"]), params)

        self.assertIn("spells_data_json", sql_query_lower)
        self.assertIn(json.dumps(char_data_py_objects["spells_data"]), params)

        self.assertIn("character_class", sql_query_lower) # direct column
        self.assertIn(char_data_py_objects["character_class"], params)

        self.assertIn("flags_json", sql_query_lower)
        self.assertIn(json.dumps(char_data_py_objects["flags"]), params)

        self.assertIn("collected_actions_json", sql_query_lower)
        self.assertIn(char_data_py_objects["collected_actions_json"], params) # Already a string

    async def test_load_character_all_complex_fields(self):
        """Test loading character with all new i18n and JSON fields from DB."""
        name_i18n_obj = {"en": "Loaded Hero", "ru": "Загруженный Герой"}
        skills_data_obj = [{"skill": "herbalism", "level": 5}]
        abilities_data_obj = [{"ability": "quick_shot", "rank": 1}]
        spells_data_obj = [{"spell": "heal_light", "cost": 10}]
        flags_obj = {"is_leader": True, "is_merchant": False}
        coll_actions_list = [{"action": "trade", "item": "potion"}]

        db_row_data = {
            **self.base_char_data, # from setUp, but override specific fields
            "name": json.dumps(name_i18n_obj), # name_i18n stored in 'name' column as JSON
            "skills_data_json": json.dumps(skills_data_obj),
            "abilities_data_json": json.dumps(abilities_data_obj),
            "spells_data_json": json.dumps(spells_data_obj),
            "character_class": "Archer",
            "flags_json": json.dumps(flags_obj),
            "collected_actions_json": json.dumps(coll_actions_list),
        }

        self.mock_db_adapter.fetchall.return_value = [db_row_data] # For load_state
        await self.character_manager.load_state(self.guild_id)

        loaded_char = self.character_manager.get_character(self.guild_id, self.character_id)
        self.assertIsNotNone(loaded_char)

        self.assertEqual(loaded_char.name_i18n, name_i18n_obj)
        self.assertEqual(loaded_char.skills_data, skills_data_obj)
        self.assertEqual(loaded_char.abilities_data, abilities_data_obj)
        self.assertEqual(loaded_char.spells_data, spells_data_obj)
        self.assertEqual(loaded_char.character_class, "Archer")
        self.assertEqual(loaded_char.flags, flags_obj)
        # Character model stores collected_actions_json as string, manager should provide it as string to model
        self.assertEqual(loaded_char.collected_actions_json, json.dumps(coll_actions_list))


if __name__ == '__main__':
    unittest.main()
