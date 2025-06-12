import unittest
import asyncio
from typing import Dict, Any, Optional, List

from bot.game.managers.character_manager import CharacterManager
from bot.game.models.character import Character

class TestCharacterManagerRevertLogic(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # Initialize CharacterManager with mock dependencies for unit testing
        # We are primarily testing in-memory object manipulation here.
        self.char_manager = CharacterManager(
            db_service=None,
            settings={},
            item_manager=None,
            location_manager=None,
            rule_engine=None,
            status_manager=None,
            party_manager=None,
            combat_manager=None,
            dialogue_manager=None,
            relationship_manager=None,
            game_log_manager=None, # GameLogManager might be needed if methods log directly
            npc_manager=None,
            game_manager=None
        )

        self.guild_id = "test_guild_123"
        self.char_id = "char_uuid_123"
        self.discord_user_id = 1234567890

        # Create a sample Character object
        self.char_data = {
            "id": self.char_id,
            "discord_user_id": self.discord_user_id,
            "name": "Test Character",
            "name_i18n": {"en": "Test Character"},
            "guild_id": self.guild_id,
            "current_location_id": "initial_location",
            "stats": {"health": 100, "max_health": 100},
            "inventory": [],
            "status_effects": [],
            "action_queue": [],
            "current_action": None,
            "party_id": None,
            "current_party_id": None,
            "state_variables": {},
            "hp": 100.0,
            "max_health": 100.0,
            "is_alive": True,
            "level": 1,
            "experience": 0,
            "unspent_xp": 0,
            "selected_language": "en",
            "collected_actions_json": None,
            "skills_data": [],
            "abilities_data": [],
            "spells_data": [],
            "character_class": "Warrior",
            "flags": {}
        }
        self.char = Character.from_dict(self.char_data)

        # Manually add character to manager's cache for testing
        # Ensure per-guild structure is respected
        if self.guild_id not in self.char_manager._characters:
            self.char_manager._characters[self.guild_id] = {}
        self.char_manager._characters[self.guild_id][self.char.id] = self.char

        # Clear dirty/deleted sets for the test guild for isolated testing
        self.char_manager._dirty_characters.pop(self.guild_id, None)
        self.char_manager._deleted_characters_ids.pop(self.guild_id, None)


    async def test_revert_location_change(self):
        # Retrieve the character object from the manager's cache
        # This ensures we are testing the object instance that the manager would operate on
        char_in_manager_cache = self.char_manager.get_character(self.guild_id, self.char.id)
        self.assertIsNotNone(char_in_manager_cache, "Character not found in manager cache during setup.")
        if char_in_manager_cache is None: return # Should not happen due to assert

        # Set an initial "new" location that we will revert from
        char_in_manager_cache.current_location_id = "location_new"

        old_location_id = "location_original"

        # Call the revert method
        revert_success = await self.char_manager.revert_location_change(self.guild_id, self.char.id, old_location_id)
        self.assertTrue(revert_success, "revert_location_change should return True on success.")

        # Assert that the character's location is now the old_location_id
        self.assertEqual(char_in_manager_cache.current_location_id, old_location_id,
                         f"Character location should be '{old_location_id}' but is '{char_in_manager_cache.current_location_id}'")

        # Assert that the character was marked as dirty
        self.assertIn(self.char.id, self.char_manager._dirty_characters.get(self.guild_id, set()),
                      "Character should be marked as dirty after location revert.")

    async def test_revert_hp_change(self):
        char_in_manager_cache = self.char_manager.get_character(self.guild_id, self.char.id)
        self.assertIsNotNone(char_in_manager_cache)
        if char_in_manager_cache is None: return

        char_in_manager_cache.hp = 50.0
        char_in_manager_cache.is_alive = False # Simulate having died

        old_hp = 100.0
        old_is_alive = True

        revert_success = await self.char_manager.revert_hp_change(self.guild_id, self.char.id, old_hp, old_is_alive)
        self.assertTrue(revert_success)

        self.assertEqual(char_in_manager_cache.hp, old_hp)
        self.assertEqual(char_in_manager_cache.is_alive, old_is_alive)
        self.assertIn(self.char.id, self.char_manager._dirty_characters.get(self.guild_id, set()))

    async def test_revert_stat_changes(self):
        char_in_manager_cache = self.char_manager.get_character(self.guild_id, self.char.id)
        self.assertIsNotNone(char_in_manager_cache)
        if char_in_manager_cache is None: return

        # Initial state for these tests
        char_in_manager_cache.level = 5
        char_in_manager_cache.xp = 5000
        if char_in_manager_cache.stats is None: char_in_manager_cache.stats = {} # Ensure stats dict exists
        char_in_manager_cache.stats["strength"] = 15
        char_in_manager_cache.stats["mana"] = 50

        stat_changes_to_revert = [
            {"stat": "level", "old_value": 3},
            {"stat": "xp", "old_value": 3000},
            {"stat": "strength", "old_value": 12}, # Generic stat in char.stats
            {"stat": "mana", "old_value": 40}      # Generic stat in char.stats
        ]

        revert_success = await self.char_manager.revert_stat_changes(self.guild_id, self.char.id, stat_changes_to_revert)
        self.assertTrue(revert_success)

        self.assertEqual(char_in_manager_cache.level, 3)
        self.assertEqual(char_in_manager_cache.xp, 3000)
        self.assertIsNotNone(char_in_manager_cache.stats)
        if char_in_manager_cache.stats: # To satisfy mypy
            self.assertEqual(char_in_manager_cache.stats.get("strength"), 12)
            self.assertEqual(char_in_manager_cache.stats.get("mana"), 40)
        self.assertIn(self.char.id, self.char_manager._dirty_characters.get(self.guild_id, set()))

    async def test_revert_party_id_change(self):
        char_in_manager_cache = self.char_manager.get_character(self.guild_id, self.char.id)
        self.assertIsNotNone(char_in_manager_cache)
        if char_in_manager_cache is None: return

        char_in_manager_cache.party_id = "new_party_123"
        char_in_manager_cache.current_party_id = "new_party_123"

        old_party_id = "original_party_abc"

        revert_success = await self.char_manager.revert_party_id_change(self.guild_id, self.char.id, old_party_id)
        self.assertTrue(revert_success)

        self.assertEqual(char_in_manager_cache.party_id, old_party_id)
        self.assertEqual(char_in_manager_cache.current_party_id, old_party_id)
        self.assertIn(self.char.id, self.char_manager._dirty_characters.get(self.guild_id, set()))

    async def test_revert_status_effect_change_lost_to_add_back(self):
        char_in_manager_cache = self.char_manager.get_character(self.guild_id, self.char.id)
        self.assertIsNotNone(char_in_manager_cache)
        if char_in_manager_cache is None: return

        char_in_manager_cache.status_effects = [] # Start with no effects

        status_effect_to_add_back = {"id": "eff_regen", "name": "Regeneration", "duration": 60}

        revert_success = await self.char_manager.revert_status_effect_change(
            self.guild_id, self.char.id,
            action_taken="lost",
            status_effect_id="eff_regen",
            full_status_effect_data=status_effect_to_add_back
        )
        self.assertTrue(revert_success)
        self.assertIn(status_effect_to_add_back, char_in_manager_cache.status_effects)
        self.assertIn(self.char.id, self.char_manager._dirty_characters.get(self.guild_id, set()))

    async def test_revert_status_effect_change_gained_to_remove(self):
        char_in_manager_cache = self.char_manager.get_character(self.guild_id, self.char.id)
        self.assertIsNotNone(char_in_manager_cache)
        if char_in_manager_cache is None: return

        effect_to_remove = {"id": "eff_poison", "name": "Poisoned", "duration": 30}
        char_in_manager_cache.status_effects = [effect_to_remove, {"id": "eff_other", "name": "Other"}]

        revert_success = await self.char_manager.revert_status_effect_change(
            self.guild_id, self.char.id,
            action_taken="gained",
            status_effect_id="eff_poison"
            # full_status_effect_data is not needed for removal
        )
        self.assertTrue(revert_success)
        self.assertNotIn(effect_to_remove, char_in_manager_cache.status_effects)
        # Check if "eff_other" is still there
        self.assertTrue(any(se.get("id") == "eff_other" for se in char_in_manager_cache.status_effects if isinstance(se, dict)))
        self.assertIn(self.char.id, self.char_manager._dirty_characters.get(self.guild_id, set()))

    async def test_revert_inventory_changes(self):
        char_in_manager_cache = self.char_manager.get_character(self.guild_id, self.char.id)
        self.assertIsNotNone(char_in_manager_cache)
        if char_in_manager_cache is None: return

        # Initial state: one potion (qty 5), one sword (qty 1)
        char_in_manager_cache.inventory = [
            {"item_id": "potion_heal", "quantity": 5},
            {"item_id": "sword_basic", "quantity": 1}
        ]

        inventory_changes_to_revert = [
            {"action": "added", "item_id": "potion_heal", "quantity": 2}, # Player picked up 2 more potions (new total 7, revert should go to 5)
            {"action": "removed", "item_id": "sword_basic", "quantity": 1}, # Player dropped the sword (revert should add it back)
            {"action": "added", "item_id": "gem_ruby", "quantity": 3}      # Player picked up 3 new gems (revert should remove them)
        ]

        # Simulate state *after* these actions happened, before revert
        # potion_heal becomes 7, sword_basic is gone, gem_ruby is 3
        self.char_manager.get_character(self.guild_id, self.char.id).inventory = [
            {"item_id": "potion_heal", "quantity": 7},
            {"item_id": "gem_ruby", "quantity": 3}
        ]


        revert_success = await self.char_manager.revert_inventory_changes(self.guild_id, self.char.id, inventory_changes_to_revert)
        self.assertTrue(revert_success)

        # Check final inventory state
        potion_entry = next((item for item in char_in_manager_cache.inventory if item.get("item_id") == "potion_heal"), None)
        sword_entry = next((item for item in char_in_manager_cache.inventory if item.get("item_id") == "sword_basic"), None)
        gem_entry = next((item for item in char_in_manager_cache.inventory if item.get("item_id") == "gem_ruby"), None)

        self.assertIsNotNone(potion_entry)
        if potion_entry: self.assertEqual(potion_entry.get("quantity"), 5)

        self.assertIsNotNone(sword_entry)
        if sword_entry: self.assertEqual(sword_entry.get("quantity"), 1)

        self.assertIsNone(gem_entry, f"Gem entry should be None (removed), but was: {gem_entry}")

        self.assertIn(self.char.id, self.char_manager._dirty_characters.get(self.guild_id, set()))

    async def test_revert_xp_change(self):
        # 1. Setup: Get character, define old values
        #    char = self.character_manager.get_character(self.guild_id, self.char_id)
        #    char.experience = 200; char.level = 3; char.unspent_xp = 5 # Current state
        #    old_xp, old_level, old_unspent_xp = 100, 2, 10
        #
        # 2. Action: Call revert_xp_change
        #    success = await self.character_manager.revert_xp_change(
        #        self.guild_id, self.char_id, old_xp, old_level, old_unspent_xp
        #    )
        #
        # 3. Assert: Check success, character attributes, and mark_dirty call
        #    self.assertTrue(success)
        #    self.assertEqual(char.experience, old_xp)
        #    self.assertEqual(char.level, old_level)
        #    self.assertEqual(char.unspent_xp, old_unspent_xp)
        #    self.assertIn(self.char_id, self.character_manager._dirty_characters.get(self.guild_id, set()))
        pass

    async def test_revert_gold_change(self):
        # 1. Setup: Get character, define old gold
        #    char = self.character_manager.get_character(self.guild_id, self.char_id)
        #    char.gold = 100 # Current state
        #    old_gold = 50
        #
        # 2. Action: Call revert_gold_change
        #    success = await self.character_manager.revert_gold_change(
        #        self.guild_id, self.char_id, old_gold
        #    )
        #
        # 3. Assert: Check success, character gold, and mark_dirty
        #    self.assertTrue(success)
        #    self.assertEqual(char.gold, old_gold)
        #    self.assertIn(self.char_id, self.character_manager._dirty_characters.get(self.guild_id, set()))
        pass

    async def test_revert_action_queue_change(self):
        # 1. Setup: Get character, define old action queue JSON
        #    char = self.character_manager.get_character(self.guild_id, self.char_id)
        #    char.action_queue = [{"action": "new_action"}] # Current state (Python list)
        #    old_action_queue_json = json.dumps([{"action": "old_action"}])
        #
        # 2. Action: Call revert_action_queue_change
        #    success = await self.character_manager.revert_action_queue_change(
        #        self.guild_id, self.char_id, old_action_queue_json
        #    )
        #
        # 3. Assert: Check success, character action_queue, and mark_dirty
        #    self.assertTrue(success)
        #    self.assertEqual(char.action_queue, json.loads(old_action_queue_json))
        #    self.assertIn(self.char_id, self.character_manager._dirty_characters.get(self.guild_id, set()))
        pass

    async def test_revert_collected_actions_change(self):
        # 1. Setup: Get character, define old collected_actions_json
        #    char = self.character_manager.get_character(self.guild_id, self.char_id)
        #    char.collected_actions_json = '{"new_key": "new_value"}' # Current state
        #    old_collected_actions_json = '{"old_key": "old_value"}'
        #
        # 2. Action: Call revert_collected_actions_change
        #    success = await self.character_manager.revert_collected_actions_change(
        #        self.guild_id, self.char_id, old_collected_actions_json
        #    )
        #
        # 3. Assert: Check success, character collected_actions_json, and mark_dirty
        #    self.assertTrue(success)
        #    self.assertEqual(char.collected_actions_json, old_collected_actions_json)
        #    self.assertIn(self.char_id, self.character_manager._dirty_characters.get(self.guild_id, set()))
        pass

    async def test_revert_character_creation(self):
        # 1. Setup: Character already exists from setUp
        #    char_exists_before = self.character_manager.get_character(self.guild_id, self.char_id)
        #    self.assertIsNotNone(char_exists_before)
        #
        # 2. Action: Call revert_character_creation
        #    # Mock mark_character_deleted if it's complex or has side effects not tested here
        #    # self.character_manager.mark_character_deleted = AsyncMock(return_value=None)
        #    success = await self.character_manager.revert_character_creation(
        #        self.guild_id, self.char_id
        #    )
        #
        # 3. Assert: Check success and that character is marked for deletion
        #    self.assertTrue(success)
        #    self.assertIn(self.char_id, self.character_manager._deleted_characters_ids.get(self.guild_id, set()))
        #    # self.character_manager.mark_character_deleted.assert_called_with(self.guild_id, self.char_id)
        pass

    async def test_recreate_character_from_data(self):
        # 1. Setup: Ensure character does NOT exist or is different before recreation
        #    # For example, delete the one from setUp first if IDs clash
        #    # self.character_manager._characters.get(self.guild_id, {}).pop(self.char_id, None)
        #    # self.character_manager._discord_to_char_map.get(self.guild_id, {}).pop(self.discord_user_id, None)
        #
        #    recreate_char_id = "recreated_char_id_456"
        #    recreate_discord_id = 987654321
        #    character_data_to_recreate = {
        #        "id": recreate_char_id, "discord_id": recreate_discord_id, "guild_id": self.guild_id,
        #        "name": "Recreated Char", "level": 5, "xp": 500, "unspent_xp": 50, "gold": 10,
        #        "current_location_id": "some_other_location",
        #        "stats": {"strength": 12}, "inventory": [{"item_id": "test_item", "quantity": 1}],
        #        # ... other fields that recreate_character_from_data would set ...
        #    }
        #    # Mock create_character or ensure it works with these params
        #    # self.character_manager.create_character = AsyncMock(return_value=Character.from_dict(character_data_to_recreate))
        #
        # 2. Action: Call recreate_character_from_data
        #    success = await self.character_manager.recreate_character_from_data(
        #        self.guild_id, character_data_to_recreate
        #    )
        #
        # 3. Assert: Check success, and that character exists with correct data
        #    self.assertTrue(success)
        #    recreated_char = self.character_manager.get_character(self.guild_id, recreate_char_id)
        #    self.assertIsNotNone(recreated_char)
        #    self.assertEqual(recreated_char.name, "Recreated Char")
        #    self.assertEqual(recreated_char.level, 5)
        #    self.assertEqual(recreated_char.stats.get("strength"), 12)
        #    self.assertIn(recreate_char_id, self.character_manager._dirty_characters.get(self.guild_id, set()))
        pass


if __name__ == '__main__':
    unittest.main()
