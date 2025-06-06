import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import uuid

from bot.game.managers.character_manager import CharacterManager
from bot.game.models.character import Character
from bot.game.constants import DEFAULT_BASE_STATS, GUILD_DEFAULT_INITIAL_LOCATION_ID


class TestCharacterManager(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.mock_db_adapter = AsyncMock()
        self.mock_settings = {
            "default_initial_location_id": GUILD_DEFAULT_INITIAL_LOCATION_ID,
            "default_base_stats": DEFAULT_BASE_STATS
        }
        self.mock_rule_engine = AsyncMock()
        self.mock_location_manager = AsyncMock()
        self.mock_status_manager = AsyncMock()
        self.mock_combat_manager = AsyncMock()
        self.mock_party_manager = AsyncMock()

        self.char_manager = CharacterManager(
            db_adapter=self.mock_db_adapter,
            settings=self.mock_settings,
            rule_engine=self.mock_rule_engine,
            location_manager=self.mock_location_manager,
            status_manager=self.mock_status_manager,
            combat_manager=self.mock_combat_manager,
            party_manager=self.mock_party_manager
        )

    async def test_init_with_all_dependencies(self):
        self.assertEqual(self.char_manager._db_adapter, self.mock_db_adapter)
        self.assertEqual(self.char_manager._settings, self.mock_settings)
        self.assertEqual(self.char_manager._rule_engine, self.mock_rule_engine)
        self.assertEqual(self.char_manager._location_manager, self.mock_location_manager)
        self.assertEqual(self.char_manager._status_manager, self.mock_status_manager)
        self.assertEqual(self.char_manager._combat_manager, self.mock_combat_manager)
        self.assertEqual(self.char_manager._party_manager, self.mock_party_manager)
        self.assertEqual(self.char_manager._characters, {})
        self.assertEqual(self.char_manager._discord_to_char_map, {})
        self.assertEqual(self.char_manager._dirty_characters, {})
        self.assertEqual(self.char_manager._deleted_characters_ids, {})

    async def test_init_without_optional_dependencies(self):
        char_manager = CharacterManager(db_adapter=self.mock_db_adapter, settings=self.mock_settings)
        self.assertEqual(char_manager._db_adapter, self.mock_db_adapter)
        self.assertEqual(char_manager._settings, self.mock_settings)
        self.assertIsNone(char_manager._rule_engine)
        self.assertIsNone(char_manager._location_manager)
        self.assertIsNone(char_manager._status_manager)
        self.assertIsNone(char_manager._combat_manager)
        self.assertIsNone(char_manager._party_manager)
        self.assertEqual(char_manager._characters, {})
        self.assertEqual(char_manager._discord_to_char_map, {})
        self.assertEqual(char_manager._dirty_characters, {})
        self.assertEqual(char_manager._deleted_characters_ids, {})

    async def test_create_character_success(self):
        guild_id = "guild1"
        discord_id = "discord1"
        name = "CharacterName"

        # Ensure guild specific caches are initialized
        self.char_manager._characters[guild_id] = {}
        self.char_manager._discord_to_char_map[guild_id] = {}
        self.char_manager._dirty_characters[guild_id] = set()

        # Mock LocationManager to return a default location
        if self.char_manager._location_manager:
            self.char_manager._location_manager.get_default_location_id.return_value = GUILD_DEFAULT_INITIAL_LOCATION_ID

        # Mock RuleEngine to return default stats
        if self.char_manager._rule_engine:
            self.char_manager._rule_engine.get_default_character_stats.return_value = DEFAULT_BASE_STATS

        with patch('uuid.uuid4', return_value=uuid.UUID('12345678-1234-5678-1234-567812345678')):
            created_char = await self.char_manager.create_character(guild_id, discord_id, name)

        self.assertIsInstance(created_char, Character)
        self.assertEqual(created_char.name, name)
        self.assertEqual(created_char.discord_id, discord_id)
        self.assertEqual(created_char.guild_id, guild_id)
        self.assertEqual(created_char.id, '12345678-1234-5678-1234-567812345678')

        if self.char_manager._location_manager:
            self.assertEqual(created_char.location_id, GUILD_DEFAULT_INITIAL_LOCATION_ID)
            self.char_manager._location_manager.get_default_location_id.assert_called_once_with(guild_id)
        else:
            self.assertEqual(created_char.location_id, self.mock_settings["default_initial_location_id"])

        if self.char_manager._rule_engine:
            self.assertEqual(created_char.stats, DEFAULT_BASE_STATS)
            self.char_manager._rule_engine.get_default_character_stats.assert_called_once()
        else:
            self.assertEqual(created_char.stats, self.mock_settings["default_base_stats"])

        self.assertIn(created_char.id, self.char_manager._characters[guild_id])
        self.assertEqual(self.char_manager._characters[guild_id][created_char.id], created_char)
        self.assertIn(discord_id, self.char_manager._discord_to_char_map[guild_id])
        self.assertEqual(self.char_manager._discord_to_char_map[guild_id][discord_id], created_char.id)
        self.assertIn(created_char.id, self.char_manager._dirty_characters[guild_id])

        self.mock_db_adapter.execute.assert_called_once()
        args, _ = self.mock_db_adapter.execute.call_args
        self.assertIn("INSERT INTO characters", args[0])
        self.assertEqual(args[1][:5], [created_char.id, guild_id, discord_id, name, 100]) # Max health check

    async def test_create_character_already_exists_discord_id(self):
        guild_id = "guild1"
        discord_id = "discord1"
        name = "CharacterName"

        self.char_manager._characters[guild_id] = {}
        self.char_manager._discord_to_char_map[guild_id] = {"discord1": "existing_char_id"}

        with self.assertRaisesRegex(ValueError, "Character with this Discord ID already exists in this guild."):
            await self.char_manager.create_character(guild_id, discord_id, name)
        self.mock_db_adapter.execute.assert_not_called()

    async def test_create_character_already_exists_name(self):
        guild_id = "guild1"
        discord_id = "discord2" # Different discord_id
        name = "CharacterName"

        # Setup: one character already exists with that name
        existing_char = Character(
            id="char1", guild_id=guild_id, discord_user_id=12345, name=name, name_i18n={"en": name, "ru": name},
            stats={}, inventory=[], location_id="loc1"
        )
        self.char_manager._characters[guild_id] = {existing_char.id: existing_char}
        self.char_manager._discord_to_char_map[guild_id] = {existing_char.discord_id: existing_char.id}

        with self.assertRaisesRegex(ValueError, "Character with this name already exists in this guild."):
            await self.char_manager.create_character(guild_id, discord_id, name)
        self.mock_db_adapter.execute.assert_not_called()

    async def test_create_character_initial_location_provided(self):
        guild_id = "guild1"
        discord_id = "discord1"
        name = "CharacterName"
        initial_location_id = "custom_location_1"

        self.char_manager._characters[guild_id] = {}
        self.char_manager._discord_to_char_map[guild_id] = {}
        self.char_manager._dirty_characters[guild_id] = set()

        if self.char_manager._rule_engine:
            self.char_manager._rule_engine.get_default_character_stats.return_value = DEFAULT_BASE_STATS

        with patch('uuid.uuid4', return_value=uuid.UUID('12345678-1234-5678-1234-567812345678')):
            created_char = await self.char_manager.create_character(
                guild_id, discord_id, name, initial_location_id=initial_location_id
            )

        self.assertEqual(created_char.location_id, initial_location_id)
        if self.char_manager._location_manager:
            self.char_manager._location_manager.get_default_location_id.assert_not_called()

    async def test_create_character_initial_stats_provided(self):
        guild_id = "guild1"
        discord_id = "discord1"
        name = "CharacterName"
        custom_stats = {"strength": 15, "dexterity": 12}

        self.char_manager._characters[guild_id] = {}
        self.char_manager._discord_to_char_map[guild_id] = {}
        self.char_manager._dirty_characters[guild_id] = set()

        if self.char_manager._location_manager:
            self.char_manager._location_manager.get_default_location_id.return_value = GUILD_DEFAULT_INITIAL_LOCATION_ID

        with patch('uuid.uuid4', return_value=uuid.UUID('12345678-1234-5678-1234-567812345678')):
            created_char = await self.char_manager.create_character(
                guild_id, discord_id, name, stats=custom_stats
            )

        self.assertEqual(created_char.stats, custom_stats)
        if self.char_manager._rule_engine:
            self.char_manager._rule_engine.get_default_character_stats.assert_not_called()

    async def test_get_character_exists(self):
        guild_id = "guild1"
        char_id = "char1"
        char_name = "TestChar"
        expected_char = Character(
            id=char_id, guild_id=guild_id, discord_user_id=12345, name=char_name, name_i18n={"en": char_name, "ru": char_name},
            stats={}, inventory=[], location_id="loc1", hp=100, max_health=100 # Added hp/max_health for consistency if tests rely on it
        )
        self.char_manager._characters[guild_id] = {char_id: expected_char}

        retrieved_char = self.char_manager.get_character(guild_id, char_id)
        self.assertIsNotNone(retrieved_char)
        if retrieved_char:
            self.assertEqual(retrieved_char, expected_char)

    async def test_get_character_non_existent(self):
        guild_id = "guild1"
        char_id = "non_existent_char"
        self.char_manager._characters[guild_id] = {}

        retrieved_char = self.char_manager.get_character(guild_id, char_id)
        self.assertIsNone(retrieved_char)

    async def test_get_character_different_guild(self):
        guild_id_1 = "guild1"
        guild_id_2 = "guild2"
        char_id = "char1"
        char_name = "TestChar"
        expected_char_guild1 = Character(
            id=char_id, guild_id=guild_id_1, discord_user_id=12345, name=char_name, name_i18n={"en": char_name, "ru": char_name},
            stats={}, inventory=[], location_id="loc1", hp=100, max_health=100
        )
        # Char exists in guild1
        self.char_manager._characters[guild_id_1] = {char_id: expected_char_guild1}
        # Guild2 has no characters, or different characters
        self.char_manager._characters[guild_id_2] = {}


        # Try to get char1 from guild2
        retrieved_char = self.char_manager.get_character(guild_id_2, char_id)
        self.assertIsNone(retrieved_char)

    async def test_get_character_guild_not_loaded(self):
        # guild_id has no entry in self.char_manager._characters
        guild_id = "unloaded_guild"
        char_id = "char1"
        retrieved_char = self.char_manager.get_character(guild_id, char_id)
        self.assertIsNone(retrieved_char)

    async def test_get_character_by_discord_id_exists(self):
        guild_id = "guild1"
        discord_id_int = 12345 # Use int for discord_user_id
        char_id = "char1"
        char_name = "TestChar"
        expected_char = Character(
            id=char_id, guild_id=guild_id, discord_user_id=discord_id_int, name=char_name, name_i18n={"en": char_name, "ru": char_name},
            stats={}, inventory=[], location_id="loc1", hp=100, max_health=100
        )
        self.char_manager._characters[guild_id] = {char_id: expected_char}
        self.char_manager._discord_to_char_map[guild_id] = {str(discord_id_int): char_id} # Map uses str

        retrieved_char = self.char_manager.get_character_by_discord_id(guild_id, str(discord_id_int))
        self.assertIsNotNone(retrieved_char)
        if retrieved_char:
            self.assertEqual(retrieved_char, expected_char)

    async def test_get_character_by_discord_id_non_existent(self):
        guild_id = "guild1"
        discord_id = "non_existent_discord_id"
        self.char_manager._discord_to_char_map[guild_id] = {}
        self.char_manager._characters[guild_id] = {}


        retrieved_char = self.char_manager.get_character_by_discord_id(guild_id, discord_id)
        self.assertIsNone(retrieved_char)

    async def test_get_character_by_discord_id_guild_not_loaded(self):
        guild_id = "unloaded_guild"
        discord_id = "discord1"
        # No setup for unloaded_guild in _discord_to_char_map or _characters
        retrieved_char = self.char_manager.get_character_by_discord_id(guild_id, discord_id)
        self.assertIsNone(retrieved_char)

    async def test_get_character_by_discord_id_char_not_in_main_cache(self):
        # Edge case: char_id exists in discord_to_char_map but not in _characters
        guild_id = "guild1"
        discord_id = "discord1"
        char_id = "char1"
        self.char_manager._discord_to_char_map[guild_id] = {discord_id: char_id}
        self.char_manager._characters[guild_id] = {} # char_id is missing here

        retrieved_char = self.char_manager.get_character_by_discord_id(guild_id, discord_id)
        self.assertIsNone(retrieved_char)

    async def test_get_character_by_name_exists(self):
        guild_id = "guild1"
        char_name = "TestChar"
        char_id = "char1"
        expected_char = Character(
            id=char_id, guild_id=guild_id, discord_user_id=12345, name=char_name, name_i18n={"en": char_name, "ru": char_name},
            stats={}, inventory=[], location_id="loc1", hp=100, max_health=100
        )
        # Multiple characters can exist, ensure we find the right one
        other_char_name = "OtherChar"
        other_char = Character(
            id="char2", guild_id=guild_id, discord_user_id=67890, name=other_char_name, name_i18n={"en": other_char_name, "ru": other_char_name},
            stats={}, inventory=[], location_id="loc1", hp=100, max_health=100
        )
        self.char_manager._characters[guild_id] = {char_id: expected_char, "char2": other_char}
        # _discord_to_char_map is not directly used by get_character_by_name but good to keep consistent
        self.char_manager._discord_to_char_map[guild_id] = {"12345": char_id, "67890": "char2"}


        retrieved_char = self.char_manager.get_character_by_name(guild_id, char_name)
        self.assertIsNotNone(retrieved_char)
        if retrieved_char:
            self.assertEqual(retrieved_char, expected_char)

    async def test_get_character_by_name_non_existent(self):
        guild_id = "guild1"
        char_name = "NonExistentName"
        self.char_manager._characters[guild_id] = {}

        retrieved_char = self.char_manager.get_character_by_name(guild_id, char_name)
        self.assertIsNone(retrieved_char)

    async def test_get_character_by_name_case_insensitive(self):
        guild_id = "guild1"
        char_name_original = "TestChar"
        char_name_lookup = "testchar"
        char_id = "char1"
        expected_char = Character(
            id=char_id, guild_id=guild_id, discord_user_id=12345, name=char_name_original, name_i18n={"en": char_name_original, "ru": char_name_original},
            stats={}, inventory=[], location_id="loc1", hp=100, max_health=100
        )
        self.char_manager._characters[guild_id] = {char_id: expected_char}
        self.char_manager._discord_to_char_map[guild_id] = {"12345": char_id}


        retrieved_char = self.char_manager.get_character_by_name(guild_id, char_name_lookup)
        self.assertIsNotNone(retrieved_char)
        if retrieved_char:
            self.assertEqual(retrieved_char, expected_char)

    async def test_get_character_by_name_guild_not_loaded(self):
        guild_id = "unloaded_guild"
        char_name = "TestChar"
        retrieved_char = self.char_manager.get_character_by_name(guild_id, char_name)
        self.assertIsNone(retrieved_char)

    async def test_update_character_location_success(self):
        guild_id = "guild1"
        char_id = "char1"
        new_location_id = "new_loc_id"
        char_name = "TestChar"
        character = Character(
            id=char_id, guild_id=guild_id, discord_user_id=12345, name=char_name, name_i18n={"en": char_name, "ru": char_name},
            location_id="old_loc_id", stats={}, hp=100, max_health=100
        )
        self.char_manager._characters[guild_id] = {char_id: character}
        self.char_manager._dirty_characters[guild_id] = set()

        await self.char_manager.update_character_location(guild_id, char_id, new_location_id)

        self.assertEqual(character.location_id, new_location_id)
        self.assertIn(char_id, self.char_manager._dirty_characters[guild_id])

    async def test_update_character_location_non_existent_character(self):
        guild_id = "guild1"
        char_id = "non_existent_char"
        new_location_id = "new_loc_id"

        self.char_manager._characters[guild_id] = {}
        self.char_manager._dirty_characters[guild_id] = set()

        await self.char_manager.update_character_location(guild_id, char_id, new_location_id)

        # Ensure no character was added and no character was marked dirty
        self.assertNotIn(char_id, self.char_manager._characters.get(guild_id, {}))
        self.assertEqual(len(self.char_manager._dirty_characters.get(guild_id, set())), 0)

    async def test_update_character_location_guild_not_loaded(self):
        guild_id = "unloaded_guild"
        char_id = "char1"
        new_location_id = "new_loc_id"

        # No setup for guild_id in _characters or _dirty_characters
        await self.char_manager.update_character_location(guild_id, char_id, new_location_id)
        # Check that caches for the guild were not created
        self.assertNotIn(guild_id, self.char_manager._characters)
        self.assertNotIn(guild_id, self.char_manager._dirty_characters)

    async def test_add_item_to_inventory_new_item(self):
        guild_id = "guild1"
        char_id = "char1"
        item_id = "item1"
        quantity = 2
        char_name = "TestChar"
        character = Character(
            id=char_id, guild_id=guild_id, discord_user_id=12345, name=char_name, name_i18n={"en": char_name, "ru": char_name},
            inventory=[], stats={}, hp=100, max_health=100 # Empty inventory
        )
        self.char_manager._characters[guild_id] = {char_id: character}
        self.char_manager._dirty_characters[guild_id] = set()

        await self.char_manager.add_item_to_inventory(guild_id, char_id, item_id, quantity)

        self.assertEqual(len(character.inventory), 1)
        self.assertEqual(character.inventory[0]['item_id'], item_id)
        self.assertEqual(character.inventory[0]['quantity'], quantity)
        self.assertIn(char_id, self.char_manager._dirty_characters[guild_id])

    async def test_add_item_to_inventory_existing_item(self):
        guild_id = "guild1"
        char_id = "char1"
        item_id = "item1"
        initial_quantity = 1
        additional_quantity = 2
        char_name = "TestChar"
        character = Character(
            id=char_id, guild_id=guild_id, discord_user_id=12345, name=char_name, name_i18n={"en": char_name, "ru": char_name},
            stats={}, inventory=[{'item_id': item_id, 'quantity': initial_quantity}], hp=100, max_health=100
        )
        self.char_manager._characters[guild_id] = {char_id: character}
        self.char_manager._dirty_characters[guild_id] = set()

        await self.char_manager.add_item_to_inventory(guild_id, char_id, item_id, additional_quantity)

        self.assertEqual(len(character.inventory), 1)
        self.assertEqual(character.inventory[0]['item_id'], item_id)
        self.assertEqual(character.inventory[0]['quantity'], initial_quantity + additional_quantity)
        self.assertIn(char_id, self.char_manager._dirty_characters[guild_id])

    async def test_add_item_to_inventory_non_existent_character(self):
        guild_id = "guild1"
        char_id = "non_existent_char"
        item_id = "item1"
        quantity = 1

        self.char_manager._characters[guild_id] = {}
        self.char_manager._dirty_characters[guild_id] = set()

        await self.char_manager.add_item_to_inventory(guild_id, char_id, item_id, quantity)
        self.assertEqual(len(self.char_manager._dirty_characters.get(guild_id, set())), 0)

    async def test_add_item_to_inventory_invalid_quantity(self):
        guild_id = "guild1"
        char_id = "char1"
        item_id = "item1"
        char_name = "TestChar"
        character = Character(
            id=char_id, guild_id=guild_id, discord_user_id=12345, name=char_name, name_i18n={"en": char_name, "ru": char_name},
            stats={}, inventory=[], hp=100, max_health=100
        )
        self.char_manager._characters[guild_id] = {char_id: character}
        self.char_manager._dirty_characters[guild_id] = set()

        await self.char_manager.add_item_to_inventory(guild_id, char_id, item_id, 0) # Quantity 0
        self.assertEqual(len(character.inventory), 0) # Inventory should remain unchanged
        self.assertNotIn(char_id, self.char_manager._dirty_characters.get(guild_id, set()))

        await self.char_manager.add_item_to_inventory(guild_id, char_id, item_id, -1) # Negative quantity
        self.assertEqual(len(character.inventory), 0) # Inventory should remain unchanged
        self.assertNotIn(char_id, self.char_manager._dirty_characters.get(guild_id, set()))

    async def test_add_item_to_inventory_guild_not_loaded(self):
        guild_id = "unloaded_guild"
        char_id = "char1"
        item_id = "item1"
        quantity = 1

        await self.char_manager.add_item_to_inventory(guild_id, char_id, item_id, quantity)
        self.assertNotIn(guild_id, self.char_manager._characters)
        self.assertNotIn(guild_id, self.char_manager._dirty_characters)

    async def test_remove_item_from_inventory_decrease_quantity(self):
        guild_id = "guild1"
        char_id = "char1"
        item_id = "item1"
        initial_quantity = 5
        quantity_to_remove = 2
        char_name = "TestChar"
        character = Character(
            id=char_id, guild_id=guild_id, discord_user_id=12345, name=char_name, name_i18n={"en": char_name, "ru": char_name},
            stats={}, inventory=[{'item_id': item_id, 'quantity': initial_quantity}], hp=100, max_health=100
        )
        self.char_manager._characters[guild_id] = {char_id: character}
        self.char_manager._dirty_characters[guild_id] = set()

        await self.char_manager.remove_item_from_inventory(guild_id, char_id, item_id, quantity_to_remove)

        self.assertEqual(len(character.inventory), 1)
        self.assertEqual(character.inventory[0]['item_id'], item_id)
        self.assertEqual(character.inventory[0]['quantity'], initial_quantity - quantity_to_remove)
        self.assertIn(char_id, self.char_manager._dirty_characters[guild_id])

    async def test_remove_item_from_inventory_remove_completely(self):
        guild_id = "guild1"
        char_id = "char1"
        item_id = "item1"
        initial_quantity = 3
        quantity_to_remove = 3 # Remove all
        char_name = "TestChar"
        character = Character(
            id=char_id, guild_id=guild_id, discord_user_id=12345, name=char_name, name_i18n={"en": char_name, "ru": char_name},
            stats={}, inventory=[{'item_id': item_id, 'quantity': initial_quantity}, {'item_id': 'item2', 'quantity': 1}], hp=100, max_health=100
        )
        self.char_manager._characters[guild_id] = {char_id: character}
        self.char_manager._dirty_characters[guild_id] = set()

        await self.char_manager.remove_item_from_inventory(guild_id, char_id, item_id, quantity_to_remove)

        self.assertEqual(len(character.inventory), 1) # item1 should be removed
        self.assertEqual(character.inventory[0]['item_id'], 'item2') # Only item2 remains
        self.assertIn(char_id, self.char_manager._dirty_characters[guild_id])

    async def test_remove_item_from_inventory_remove_more_than_available(self):
        guild_id = "guild1"
        char_id = "char1"
        item_id = "item1"
        initial_quantity = 2
        quantity_to_remove = 5 # More than available
        char_name = "TestChar"
        character = Character(
            id=char_id, guild_id=guild_id, discord_user_id=12345, name=char_name, name_i18n={"en": char_name, "ru": char_name},
            stats={}, inventory=[{'item_id': item_id, 'quantity': initial_quantity}], hp=100, max_health=100
        )
        self.char_manager._characters[guild_id] = {char_id: character}
        self.char_manager._dirty_characters[guild_id] = set()

        await self.char_manager.remove_item_from_inventory(guild_id, char_id, item_id, quantity_to_remove)

        self.assertEqual(len(character.inventory), 0) # Item should be completely removed
        self.assertIn(char_id, self.char_manager._dirty_characters[guild_id])

    async def test_remove_item_from_inventory_item_not_in_inventory(self):
        guild_id = "guild1"
        char_id = "char1"
        item_id_to_remove = "non_existent_item"
        char_name = "TestChar"
        character = Character(
            id=char_id, guild_id=guild_id, discord_user_id=12345, name=char_name, name_i18n={"en": char_name, "ru": char_name},
            stats={}, inventory=[{'item_id': "item1", 'quantity': 1}], hp=100, max_health=100 # Character has item1
        )
        self.char_manager._characters[guild_id] = {char_id: character}
        self.char_manager._dirty_characters[guild_id] = set()

        await self.char_manager.remove_item_from_inventory(guild_id, char_id, item_id_to_remove, 1)

        self.assertEqual(len(character.inventory), 1) # Inventory should remain unchanged
        self.assertNotIn(char_id, self.char_manager._dirty_characters.get(guild_id, set())) # Not marked dirty

    async def test_remove_item_from_inventory_non_existent_character(self):
        guild_id = "guild1"
        char_id = "non_existent_char"
        item_id = "item1"

        self.char_manager._characters[guild_id] = {}
        self.char_manager._dirty_characters[guild_id] = set()

        await self.char_manager.remove_item_from_inventory(guild_id, char_id, item_id, 1)
        self.assertEqual(len(self.char_manager._dirty_characters.get(guild_id, set())), 0)

    async def test_remove_item_from_inventory_invalid_quantity(self):
        guild_id = "guild1"
        char_id = "char1"
        item_id = "item1"
        initial_quantity = 5
        char_name = "TestChar"
        character = Character(
            id=char_id, guild_id=guild_id, discord_user_id=12345, name=char_name, name_i18n={"en": char_name, "ru": char_name},
            stats={}, inventory=[{'item_id': item_id, 'quantity': initial_quantity}], hp=100, max_health=100
        )
        self.char_manager._characters[guild_id] = {char_id: character}
        self.char_manager._dirty_characters[guild_id] = set()

        await self.char_manager.remove_item_from_inventory(guild_id, char_id, item_id, 0)
        self.assertEqual(character.inventory[0]['quantity'], initial_quantity) # Unchanged
        self.assertNotIn(char_id, self.char_manager._dirty_characters.get(guild_id, set()))

        await self.char_manager.remove_item_from_inventory(guild_id, char_id, item_id, -1)
        self.assertEqual(character.inventory[0]['quantity'], initial_quantity) # Unchanged
        self.assertNotIn(char_id, self.char_manager._dirty_characters.get(guild_id, set()))

    async def test_remove_item_from_inventory_guild_not_loaded(self):
        guild_id = "unloaded_guild"
        char_id = "char1"
        item_id = "item1"

        await self.char_manager.remove_item_from_inventory(guild_id, char_id, item_id, 1)
        self.assertNotIn(guild_id, self.char_manager._characters)
        self.assertNotIn(guild_id, self.char_manager._dirty_characters)

    async def test_update_health_deal_damage(self):
        guild_id = "guild1"
        char_id = "char1"
        char_name = "TestChar"
        character = Character(
            id=char_id, guild_id=guild_id, discord_user_id=12345, name=char_name, name_i18n={"en": char_name, "ru": char_name},
            hp=80.0, max_health=100.0, stats={}, inventory=[], is_alive=True # Ensure float for hp/max_health
        )
        self.char_manager._characters[guild_id] = {char_id: character}
        self.char_manager._dirty_characters[guild_id] = set()
        self.char_manager.handle_character_death = AsyncMock() # Mock death handler

        await self.char_manager.update_health(guild_id, char_id, -20) # Deal 20 damage

        self.assertEqual(character.current_health, 60)
        self.assertTrue(character.is_alive)
        self.assertIn(char_id, self.char_manager._dirty_characters[guild_id])
        self.char_manager.handle_character_death.assert_not_called()

    async def test_update_health_heal_character(self):
        guild_id = "guild1"
        char_id = "char1"
        char_name = "TestChar"
        character = Character(
            id=char_id, guild_id=guild_id, discord_user_id=12345, name=char_name, name_i18n={"en": char_name, "ru": char_name},
            hp=50.0, max_health=100.0, stats={}, inventory=[], is_alive=True
        )
        self.char_manager._characters[guild_id] = {char_id: character}
        self.char_manager._dirty_characters[guild_id] = set()

        await self.char_manager.update_health(guild_id, char_id, 30) # Heal 30

        self.assertEqual(character.current_health, 80)
        self.assertIn(char_id, self.char_manager._dirty_characters[guild_id])

    async def test_update_health_heal_above_max(self):
        guild_id = "guild1"
        char_id = "char1"
        char_name = "TestChar"
        character = Character(
            id=char_id, guild_id=guild_id, discord_user_id=12345, name=char_name, name_i18n={"en": char_name, "ru": char_name},
            hp=90.0, max_health=100.0, stats={}, inventory=[], is_alive=True
        )
        self.char_manager._characters[guild_id] = {char_id: character}
        self.char_manager._dirty_characters[guild_id] = set()

        await self.char_manager.update_health(guild_id, char_id, 20) # Heal 20, should cap at 100

        self.assertEqual(character.current_health, 100) # Capped at max_health
        self.assertIn(char_id, self.char_manager._dirty_characters[guild_id])

    async def test_update_health_deal_lethal_damage(self):
        guild_id = "guild1"
        char_id = "char1"
        char_name = "TestChar"
        character = Character(
            id=char_id, guild_id=guild_id, discord_user_id=12345, name=char_name, name_i18n={"en": char_name, "ru": char_name},
            hp=20.0, max_health=100.0, stats={}, inventory=[], is_alive=True
        )
        self.char_manager._characters[guild_id] = {char_id: character}
        self.char_manager._dirty_characters[guild_id] = set()
        self.char_manager.handle_character_death = AsyncMock() # Mock death handler

        await self.char_manager.update_health(guild_id, char_id, -50) # Deal 50 damage (20 - 50 = -30)

        self.assertEqual(character.current_health, 0) # Health should be 0
        # self.assertFalse(character.is_alive) # This will be set by handle_character_death
        self.assertIn(char_id, self.char_manager._dirty_characters[guild_id])
        self.char_manager.handle_character_death.assert_called_once_with(guild_id, char_id)

    async def test_update_health_non_existent_character(self):
        guild_id = "guild1"
        char_id = "non_existent_char"
        self.char_manager._characters[guild_id] = {}
        self.char_manager._dirty_characters[guild_id] = set()
        self.char_manager.handle_character_death = AsyncMock()

        await self.char_manager.update_health(guild_id, char_id, -10)

        self.assertEqual(len(self.char_manager._dirty_characters.get(guild_id, set())), 0)
        self.char_manager.handle_character_death.assert_not_called()

    async def test_update_health_guild_not_loaded(self):
        guild_id = "unloaded_guild"
        char_id = "char1"
        self.char_manager.handle_character_death = AsyncMock()

        await self.char_manager.update_health(guild_id, char_id, -10)
        self.assertNotIn(guild_id, self.char_manager._characters)
        self.assertNotIn(guild_id, self.char_manager._dirty_characters)
        self.char_manager.handle_character_death.assert_not_called()

    async def test_update_health_already_dead_character(self):
        guild_id = "guild1"
        char_id = "char1"
        char_name = "TestChar"
        character = Character(
            id=char_id, guild_id=guild_id, discord_user_id=12345, name=char_name, name_i18n={"en": char_name, "ru": char_name},
            hp=0.0, max_health=100.0, stats={}, inventory=[], is_alive=False # Already dead
        )
        self.char_manager._characters[guild_id] = {char_id: character}
        self.char_manager._dirty_characters[guild_id] = set()
        self.char_manager.handle_character_death = AsyncMock()

        await self.char_manager.update_health(guild_id, char_id, -10) # More damage
        self.assertEqual(character.current_health, 0) # Should remain 0
        self.assertFalse(character.is_alive)
        self.assertNotIn(char_id, self.char_manager._dirty_characters.get(guild_id, set())) # No change, not dirty
        self.char_manager.handle_character_death.assert_not_called()

        await self.char_manager.update_health(guild_id, char_id, 20) # Healing a dead character
        self.assertEqual(character.current_health, 0) # Should remain 0 and dead
        self.assertFalse(character.is_alive)
        self.assertNotIn(char_id, self.char_manager._dirty_characters.get(guild_id, set())) # No change, not dirty
        self.char_manager.handle_character_death.assert_not_called()

    async def test_handle_character_death_success(self):
        guild_id = "guild1"
        char_id = "char1"
        char_name = "TestChar"
        character = Character(
            id=char_id, guild_id=guild_id, discord_user_id=12345, name=char_name, name_i18n={"en": char_name, "ru": char_name},
            hp=0.0, max_health=100.0, stats={}, inventory=[], is_alive=True # Still marked alive
        )
        self.char_manager._characters[guild_id] = {char_id: character}
        self.char_manager._dirty_characters[guild_id] = set()

        # Ensure managers are mocked if they exist
        if self.char_manager._status_manager:
            self.char_manager._status_manager.clean_up_for_character = AsyncMock()
        if self.char_manager._combat_manager:
            self.char_manager._combat_manager.remove_participant_from_combat = AsyncMock()
        if self.char_manager._party_manager:
            self.char_manager._party_manager.handle_character_death = AsyncMock()
        if self.char_manager._rule_engine:
            self.char_manager._rule_engine.trigger_death = AsyncMock()

        await self.char_manager.handle_character_death(guild_id, char_id)

        self.assertFalse(character.is_alive)
        self.assertIn(char_id, self.char_manager._dirty_characters[guild_id])

        if self.char_manager._status_manager:
            self.char_manager._status_manager.clean_up_for_character.assert_called_once_with(guild_id, char_id)
        if self.char_manager._combat_manager:
            self.char_manager._combat_manager.remove_participant_from_combat.assert_called_once_with(guild_id, char_id)
        if self.char_manager._party_manager:
            self.char_manager._party_manager.handle_character_death.assert_called_once_with(guild_id, char_id)
        if self.char_manager._rule_engine:
            self.char_manager._rule_engine.trigger_death.assert_called_once_with(character)

    async def test_handle_character_death_non_existent_character(self):
        guild_id = "guild1"
        char_id = "non_existent_char"
        self.char_manager._characters[guild_id] = {}
        self.char_manager._dirty_characters[guild_id] = set()

        # Mock dependent managers to ensure they are NOT called
        if self.char_manager._status_manager:
            self.char_manager._status_manager.clean_up_for_character = AsyncMock()
        if self.char_manager._combat_manager:
            self.char_manager._combat_manager.remove_participant_from_combat = AsyncMock()
        # ... (mock other managers as needed)

        await self.char_manager.handle_character_death(guild_id, char_id)

        self.assertEqual(len(self.char_manager._dirty_characters.get(guild_id, set())), 0)
        if self.char_manager._status_manager:
            self.char_manager._status_manager.clean_up_for_character.assert_not_called()
        if self.char_manager._combat_manager:
            self.char_manager._combat_manager.remove_participant_from_combat.assert_not_called()
        # ... (assert other managers not called)

    async def test_handle_character_death_guild_not_loaded(self):
        guild_id = "unloaded_guild"
        char_id = "char1"

        if self.char_manager._status_manager:
            self.char_manager._status_manager.clean_up_for_character = AsyncMock()
        # ... (mock other managers)

        await self.char_manager.handle_character_death(guild_id, char_id)

        self.assertNotIn(guild_id, self.char_manager._characters)
        self.assertNotIn(guild_id, self.char_manager._dirty_characters)
        if self.char_manager._status_manager:
            self.char_manager._status_manager.clean_up_for_character.assert_not_called()
        # ... (assert other managers not called)

    async def test_save_state_dirty_characters(self):
        guild_id = "guild1"
        char1_id = "char1"
        char2_id = "char2"
        char1_name = "Char1"
        char2_name = "Char2"
        char1 = Character(id=char1_id, guild_id=guild_id, discord_user_id=1, name=char1_name, name_i18n={"en": char1_name, "ru": char1_name}, max_health=100.0, hp=100.0, stats={"str":10}, inventory=[{"item_id":"potion","quantity":1}], location_id="loc1", status_effects=["poisoned"], is_alive=True, level=1, experience=10)
        char2 = Character(id=char2_id, guild_id=guild_id, discord_user_id=2, name=char2_name, name_i18n={"en": char2_name, "ru": char2_name}, max_health=120.0, hp=50.0, stats={"dex":12}, inventory=[], location_id="loc2", status_effects=[], is_alive=False, level=2, experience=150)

        self.char_manager._characters[guild_id] = {char1_id: char1, char2_id: char2}
        self.char_manager._dirty_characters[guild_id] = {char1_id, char2_id}
        self.char_manager._deleted_characters_ids[guild_id] = set() # No deleted characters for this test

        await self.char_manager.save_state(guild_id)

        self.mock_db_adapter.execute_many.assert_called_once()
        args, _ = self.mock_db_adapter.execute_many.call_args
        self.assertIn("REPLACE INTO characters", args[0]) # Assuming REPLACE INTO for updates

        # Construct expected data for execute_many based on char1 and char2
        # Note: The exact order and content of db_params in save_character needs to be matched
        expected_data = [
            tuple(self.char_manager._character_to_db_params(char1).values()),
            tuple(self.char_manager._character_to_db_params(char2).values())
        ]
        # Order of data might vary, so check contents
        self.assertCountEqual(args[1], expected_data)

        self.assertEqual(len(self.char_manager._dirty_characters.get(guild_id, set())), 0) # Should be cleared
        self.mock_db_adapter.execute.assert_not_called() # No deletions in this case

    async def test_save_state_deleted_characters(self):
        guild_id = "guild1"
        deleted_id1 = "del_char1"
        deleted_id2 = "del_char2"

        self.char_manager._deleted_characters_ids[guild_id] = {deleted_id1, deleted_id2}
        self.char_manager._dirty_characters[guild_id] = set() # No dirty characters for this test
        self.char_manager._characters[guild_id] = {} # Deleted chars are already removed from main cache

        await self.char_manager.save_state(guild_id)

        self.mock_db_adapter.execute.assert_called_once()
        args, _ = self.mock_db_adapter.execute.call_args
        self.assertIn("DELETE FROM characters WHERE guild_id = ? AND id IN", args[0])
        self.assertEqual(args[1][0], guild_id)
        self.assertCountEqual(list(args[1][1]), [deleted_id1, deleted_id2])

        self.assertEqual(len(self.char_manager._deleted_characters_ids.get(guild_id, set())), 0) # Should be cleared
        self.mock_db_adapter.execute_many.assert_not_called() # No updates in this case

    async def test_save_state_dirty_and_deleted_characters(self):
        guild_id = "guild1"
        char1_id = "char1"
        char1_name = "Char1"
        char1 = Character(id=char1_id, guild_id=guild_id, discord_user_id=1, name=char1_name, name_i18n={"en": char1_name, "ru": char1_name}, stats={}, hp=100, max_health=100)
        deleted_id1 = "del_char1"

        self.char_manager._characters[guild_id] = {char1_id: char1}
        self.char_manager._dirty_characters[guild_id] = {char1_id}
        self.char_manager._deleted_characters_ids[guild_id] = {deleted_id1}

        await self.char_manager.save_state(guild_id)

        self.mock_db_adapter.execute_many.assert_called_once() # For dirty char
        self.mock_db_adapter.execute.assert_called_once() # For deleted char

        self.assertEqual(len(self.char_manager._dirty_characters.get(guild_id, set())), 0)
        self.assertEqual(len(self.char_manager._deleted_characters_ids.get(guild_id, set())), 0)

    async def test_save_state_no_changes(self):
        guild_id = "guild1"
        self.char_manager._dirty_characters[guild_id] = set()
        self.char_manager._deleted_characters_ids[guild_id] = set()
        self.char_manager._characters[guild_id] = {}


        await self.char_manager.save_state(guild_id)

        self.mock_db_adapter.execute_many.assert_not_called()
        self.mock_db_adapter.execute.assert_not_called()
        # Caches should remain empty
        self.assertEqual(len(self.char_manager._dirty_characters.get(guild_id, set())), 0)
        self.assertEqual(len(self.char_manager._deleted_characters_ids.get(guild_id, set())), 0)

    async def test_save_state_guild_not_loaded(self):
        guild_id = "unloaded_guild"
        # No setup for this guild in any cache

        await self.char_manager.save_state(guild_id)

        self.mock_db_adapter.execute_many.assert_not_called()
        self.mock_db_adapter.execute.assert_not_called()
        # Ensure caches were not created for this guild
        self.assertNotIn(guild_id, self.char_manager._dirty_characters)
        self.assertNotIn(guild_id, self.char_manager._deleted_characters_ids)

    async def test_load_state_success(self):
        guild_id = "guild1"
        # Sample data from DB
        db_data = [
            ('char1', guild_id, 'discord1', 'Char1Name', 100, 80, '{"str": 10, "hp": 100}', '[{"item_id": "potion", "quantity": 3}]', 'loc_start', '["buffed"]', True, 1, 0, 0),
            ('char2', guild_id, 'discord2', 'Char2Name', 120, 120, '{"dex": 12, "hp": 120}', '[]', 'loc_town', '[]', False, 2, 50, 0)
        ]
        self.mock_db_adapter.fetchall.return_value = db_data

        # Pre-populate dirty/deleted to ensure they are cleared
        self.char_manager._dirty_characters[guild_id] = {"some_dirty_char"}
        self.char_manager._deleted_characters_ids[guild_id] = {"some_deleted_char"}

        await self.char_manager.load_state(guild_id)

        self.mock_db_adapter.fetchall.assert_called_once()
        args, _ = self.mock_db_adapter.fetchall.call_args
        self.assertIn("SELECT id, guild_id, discord_id, name, max_health, current_health, stats, inventory, location_id, effects, is_alive, level, experience,_rowid_ FROM characters WHERE guild_id = ?", args[0])
        self.assertEqual(args[1], (guild_id,))

        # Verify caches are populated correctly
        self.assertIn(guild_id, self.char_manager._characters)
        self.assertEqual(len(self.char_manager._characters[guild_id]), 2)
        self.assertIn(guild_id, self.char_manager._discord_to_char_map)
        self.assertEqual(len(self.char_manager._discord_to_char_map[guild_id]), 2)

        # Verify char1 details
        char1 = self.char_manager.get_character(guild_id, 'char1')
        self.assertIsNotNone(char1)
        if char1:
            self.assertEqual(char1.name, 'Char1Name')
            self.assertEqual(char1.discord_id, 'discord1')
            self.assertEqual(char1.max_health, 100)
            self.assertEqual(char1.current_health, 80)
            self.assertEqual(char1.stats, {"str": 10, "hp": 100})
            self.assertEqual(char1.inventory, [{"item_id": "potion", "quantity": 3}])
            self.assertEqual(char1.location_id, 'loc_start')
            self.assertEqual(char1.effects, ["buffed"])
            self.assertTrue(char1.is_alive)
            self.assertEqual(char1.level, 1)
            self.assertEqual(char1.experience, 0)


        # Verify char2 details
        char2 = self.char_manager.get_character_by_discord_id(guild_id, 'discord2')
        self.assertIsNotNone(char2)
        if char2:
            self.assertEqual(char2.name, 'Char2Name')
            self.assertEqual(char2.id, 'char2')
            self.assertFalse(char2.is_alive)
            self.assertEqual(char2.stats, {"dex": 12, "hp": 120})

        # Verify dirty and deleted lists are cleared for the guild
        self.assertNotIn(guild_id, self.char_manager._dirty_characters) # Should be removed entirely or be empty set
        self.assertNotIn(guild_id, self.char_manager._deleted_characters_ids)


    async def test_load_state_no_characters_in_db(self):
        guild_id = "guild2"
        self.mock_db_adapter.fetchall.return_value = [] # No characters for this guild

        # Pre-populate to ensure clearing
        self.char_manager._characters[guild_id] = {"dummy_id": MagicMock()}
        self.char_manager._discord_to_char_map[guild_id] = {"dummy_discord_id": "dummy_id"}
        self.char_manager._dirty_characters[guild_id] = {"some_dirty_char"}
        self.char_manager._deleted_characters_ids[guild_id] = {"some_deleted_char"}

        await self.char_manager.load_state(guild_id)

        self.mock_db_adapter.fetchall.assert_called_once_with("SELECT id, guild_id, discord_id, name, max_health, current_health, stats, inventory, location_id, effects, is_alive, level, experience,_rowid_ FROM characters WHERE guild_id = ?", (guild_id,))

        self.assertNotIn(guild_id, self.char_manager._characters) # Cleared
        self.assertNotIn(guild_id, self.char_manager._discord_to_char_map) # Cleared
        self.assertNotIn(guild_id, self.char_manager._dirty_characters)
        self.assertNotIn(guild_id, self.char_manager._deleted_characters_ids)

    async def test_load_state_json_parsing_error(self):
        guild_id = "guild_json_error"
        # Malformed JSON for stats
        db_data = [
            ('char_err', guild_id, 'discord_err', 'CharErr', 100, 80, '{"str": 10, "hp": 100', '[]', 'loc1', '[]', True, 1, 0, 0)
        ]
        self.mock_db_adapter.fetchall.return_value = db_data

        with self.assertLogs(level='ERROR') as log: # Expect an error to be logged
            await self.char_manager.load_state(guild_id)
            self.assertTrue(any("Failed to parse JSON" in message for message in log.output))

        # Character should still be loaded, but with default/empty for the bad field
        # Depending on Character model's __init__ robustness, this might vary.
        # For this test, we'll assume it attempts to load, logs error, and continues.
        # The character might be partially loaded or skipped based on implementation.
        # Let's assume it gets loaded with default stats if JSON fails.
        char_err = await self.char_manager.get_character(guild_id, 'char_err')
        if char_err: # If it was loaded despite error
             # This depends on how Character handles invalid JSON.
             # It might default to empty dict or raise error during Character init.
             # For CharacterManager, the key is that it logs and continues.
            self.assertIn(guild_id, self.char_manager._characters)
            self.assertEqual(char_err.stats, {}) # Assuming it defaults to {} on parse error

    async def test_remove_character_success(self):
        guild_id = "guild1"
        char_id = "char1"
        discord_id_int = 12345
        char_name = "TestChar"
        character = Character(
            id=char_id, guild_id=guild_id, discord_user_id=discord_id_int, name=char_name, name_i18n={"en": char_name, "ru": char_name},
            stats={}, hp=100, max_health=100
        )
        self.char_manager._characters[guild_id] = {char_id: character}
        self.char_manager._discord_to_char_map[guild_id] = {str(discord_id_int): char_id}
        self.char_manager._dirty_characters[guild_id] = set() # Ensure it's not marked dirty by removal itself
        self.char_manager._deleted_characters_ids[guild_id] = set()

        # Mock dependent managers
        if self.char_manager._status_manager:
            self.char_manager._status_manager.clean_up_for_character = AsyncMock()
        if self.char_manager._combat_manager:
            self.char_manager._combat_manager.remove_participant_from_combat = AsyncMock()
        if self.char_manager._party_manager:
            self.char_manager._party_manager.handle_character_death = AsyncMock() # remove_character might also trigger this if char was in party

        await self.char_manager.remove_character(guild_id, char_id)

        self.assertNotIn(char_id, self.char_manager._characters.get(guild_id, {}))
        discord_id = str(discord_id_int) # Add this line
        self.assertNotIn(discord_id, self.char_manager._discord_to_char_map.get(guild_id, {}))
        self.assertIn(char_id, self.char_manager._deleted_characters_ids[guild_id])
        # Ensure char is removed from dirty set if it was there (though remove_character itself shouldn't add it)
        self.assertNotIn(char_id, self.char_manager._dirty_characters.get(guild_id, set()))


        if self.char_manager._status_manager:
            self.char_manager._status_manager.clean_up_for_character.assert_called_once_with(guild_id, char_id)
        if self.char_manager._combat_manager:
            self.char_manager._combat_manager.remove_participant_from_combat.assert_called_once_with(guild_id, char_id)
        if self.char_manager._party_manager:
            # Depending on implementation, character removal might also trigger party cleanup
            self.char_manager._party_manager.handle_character_death.assert_called_once_with(guild_id, char_id)


    async def test_remove_character_non_existent(self):
        guild_id = "guild1"
        char_id = "non_existent_char"

        self.char_manager._characters[guild_id] = {}
        self.char_manager._discord_to_char_map[guild_id] = {}
        self.char_manager._deleted_characters_ids[guild_id] = set()

        # Mock dependent managers to ensure they are NOT called
        if self.char_manager._status_manager:
            self.char_manager._status_manager.clean_up_for_character = AsyncMock()
        if self.char_manager._combat_manager:
            self.char_manager._combat_manager.remove_participant_from_combat = AsyncMock()

        await self.char_manager.remove_character(guild_id, char_id)

        self.assertNotIn(char_id, self.char_manager._deleted_characters_ids.get(guild_id, set())) # Should not be added
        if self.char_manager._status_manager:
            self.char_manager._status_manager.clean_up_for_character.assert_not_called()
        if self.char_manager._combat_manager:
            self.char_manager._combat_manager.remove_participant_from_combat.assert_not_called()

    async def test_remove_character_already_marked_dirty(self):
        # Test that if a character was dirty, removing it clears it from dirty list
        # and adds to deleted list.
        guild_id = "guild1"
        char_id = "char1"
        discord_id_int = 12345
        char_name = "TestChar"
        character = Character(id=char_id, guild_id=guild_id, discord_user_id=discord_id_int, name=char_name, name_i18n={"en": char_name, "ru": char_name}, stats={}, hp=100, max_health=100)

        self.char_manager._characters[guild_id] = {char_id: character}
        self.char_manager._discord_to_char_map[guild_id] = {str(discord_id_int): char_id}
        self.char_manager._dirty_characters[guild_id] = {char_id} # Mark as dirty
        self.char_manager._deleted_characters_ids[guild_id] = set()

        await self.char_manager.remove_character(guild_id, char_id)

        self.assertNotIn(char_id, self.char_manager._characters.get(guild_id, {}))
        discord_id = str(discord_id_int) # Add this line
        self.assertNotIn(discord_id, self.char_manager._discord_to_char_map.get(guild_id, {}))
        self.assertIn(char_id, self.char_manager._deleted_characters_ids[guild_id])
        self.assertNotIn(char_id, self.char_manager._dirty_characters.get(guild_id, set())) # Cleared from dirty

    async def test_remove_character_guild_not_loaded(self):
        guild_id = "unloaded_guild"
        char_id = "char1"

        if self.char_manager._status_manager:
            self.char_manager._status_manager.clean_up_for_character = AsyncMock()

        await self.char_manager.remove_character(guild_id, char_id)

        self.assertNotIn(guild_id, self.char_manager._characters)
        self.assertNotIn(guild_id, self.char_manager._discord_to_char_map)
        self.assertNotIn(guild_id, self.char_manager._deleted_characters_ids) # Cache for guild shouldn't be created
        if self.char_manager._status_manager:
            self.char_manager._status_manager.clean_up_for_character.assert_not_called()

    async def test_create_character_sets_default_language(self):
        guild_id = "test_guild_lang"
        # Ensure discord_id is an int as expected by CharacterManager.create_character
        discord_id = 123456
        name = "LangCharacter"

        # Ensure guild specific caches are initialized for this test
        # setUp might not cover this dynamic guild_id, so ensure it here.
        self.char_manager._characters[guild_id] = {}
        self.char_manager._discord_to_char_map[guild_id] = {}
        self.char_manager._dirty_characters[guild_id] = set()

        # Mock _game_manager and its get_default_bot_language method
        # Add _game_manager to the instance for this test
        # In a real scenario, _game_manager would be injected or available via other means.
        self.char_manager._game_manager = MagicMock()
        self.char_manager._game_manager.get_default_bot_language = MagicMock(return_value="ru")

        # Mock DB adapter's execute method as it's called by create_character
        self.mock_db_adapter.execute = AsyncMock()

        # Mock LocationManager to return a default location_id if that path is taken
        if self.char_manager._location_manager:
            self.char_manager._location_manager.get_default_location_id = AsyncMock(return_value=GUILD_DEFAULT_INITIAL_LOCATION_ID)

        # Mock RuleEngine to return default stats if that path is taken
        if self.char_manager._rule_engine:
            # The actual method called for stats in create_character might be different,
            # e.g., generate_initial_character_stats. Adjust if necessary.
            # Based on CharacterManager.create_character, it seems to call generate_initial_character_stats
            self.char_manager._rule_engine.generate_initial_character_stats = MagicMock(return_value=DEFAULT_BASE_STATS)

        # Patch uuid.uuid4 to control the generated character ID
        with patch('uuid.uuid4', return_value=uuid.UUID('abcdef12-1234-5678-1234-abcdef123456')):
            new_char = await self.char_manager.create_character(
                discord_id=discord_id, # Pass as int
                name=name,
                guild_id=guild_id
            )

        self.assertIsNotNone(new_char)
        # Primary assertion: selected_language on the returned Character object
        self.assertEqual(new_char.selected_language, "ru")

        # Verify that get_default_bot_language was called on the mocked game_manager
        self.char_manager._game_manager.get_default_bot_language.assert_called_once()

        # Verify that the character was saved with the correct language by checking db_params
        self.mock_db_adapter.execute.assert_called_once()
        call_args = self.mock_db_adapter.execute.call_args[0]
        sql_query = call_args[0] # The SQL query string
        sql_params = call_args[1] # The tuple of parameters for the query

        # Check if 'selected_language' column is in the query and the param matches.
        # This relies on the known structure of the INSERT query in CharacterManager.create_character.
        # The order is: id, discord_user_id, name, guild_id, location_id, stats, inventory,
        # current_action, action_queue, party_id, state_variables,
        # hp, max_health, is_alive, status_effects, level, experience, unspent_xp,
        # selected_language, collected_actions_json
        # So, selected_language is expected at index 18.
        query_cols_segment = sql_query.lower().split("values")[0]
        self.assertIn("selected_language", query_cols_segment)

        try:
            # Find the position of selected_language more dynamically if possible,
            # but direct indexing is simpler if the order is stable.
            # For now, assuming index 18 is correct based on recent CharacterManager updates.
            self.assertEqual(sql_params[18], "ru")
        except IndexError:
            self.fail(f"SQL params tuple out of bounds. Length: {len(sql_params)}, expected at least 19 for selected_language.")

    async def test_create_character_default_language_fallback_if_gm_unavailable(self):
        guild_id = "test_guild_lang_fallback"
        discord_id = 789012 # Ensure int
        name = "FallbackLangCharacter"

        self.char_manager._characters[guild_id] = {}
        self.char_manager._discord_to_char_map[guild_id] = {}
        self.char_manager._dirty_characters[guild_id] = set()

        # Simulate GameManager not being available by removing the attribute
        if hasattr(self.char_manager, '_game_manager'):
            del self.char_manager._game_manager
        # Alternatively, set to None: self.char_manager._game_manager = None
        # Or mock it without the method: self.char_manager._game_manager = MagicMock(spec=[])

        self.mock_db_adapter.execute = AsyncMock()
        if self.char_manager._location_manager:
            self.char_manager._location_manager.get_default_location_id = AsyncMock(return_value=GUILD_DEFAULT_INITIAL_LOCATION_ID)
        if self.char_manager._rule_engine:
            self.char_manager._rule_engine.generate_initial_character_stats = MagicMock(return_value=DEFAULT_BASE_STATS)

        with patch('uuid.uuid4', return_value=uuid.UUID('abcdef12-1234-5678-1234-abcdef123457')):
            new_char = await self.char_manager.create_character(
                discord_id=discord_id, # Pass as int
                name=name,
                guild_id=guild_id
            )

        self.assertIsNotNone(new_char)
        self.assertEqual(new_char.selected_language, "en") # Should fallback to 'en'

        self.mock_db_adapter.execute.assert_called_once()
        call_args = self.mock_db_adapter.execute.call_args[0]
        sql_query = call_args[0]
        sql_params = call_args[1]

        query_cols_segment = sql_query.lower().split("values")[0]
        self.assertIn("selected_language", query_cols_segment)
        try:
            self.assertEqual(sql_params[18], "en") # Expect 'en' as fallback
        except IndexError:
            self.fail(f"SQL params tuple out of bounds for fallback test. Length: {len(sql_params)}, expected at least 19.")


if __name__ == '__main__':
    unittest.main()
