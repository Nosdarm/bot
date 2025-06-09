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


if __name__ == '__main__':
    unittest.main()
