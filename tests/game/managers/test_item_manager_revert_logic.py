import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
import uuid
from typing import Dict, Any, Optional, List

from bot.game.managers.item_manager import ItemManager
from bot.game.models.item import Item
# Assuming GameLogManager is not directly called by revert methods, so not mocking it here for now.
# If it were, we'd import and mock it:
# from bot.game.managers.game_log_manager import GameLogManager

class TestItemManagerRevertLogic(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.guild_id = "test_guild_revert_item"

        # Mock dependencies for ItemManager
        self.mock_db_service = MagicMock()
        self.mock_db_service.adapter = AsyncMock() # For execute, execute_many, fetchall etc.

        self.mock_rule_engine = MagicMock()
        self.mock_character_manager = MagicMock()
        self.mock_location_manager = MagicMock()
        # GameLogManager is not directly used by the revert methods themselves usually,
        # but by the methods they call (like create_item_instance if it logs).
        # For focused unit tests on revert logic, we assume the primary methods work as expected
        # or are also unit-tested elsewhere.
        self.mock_game_log_manager = AsyncMock()


        self.item_manager = ItemManager(
            db_service=self.mock_db_service,
            settings={"item_templates": {}}, # Start with empty templates, add specific ones below
            rule_engine=self.mock_rule_engine,
            character_manager=self.mock_character_manager,
            location_manager=self.mock_location_manager,
            # game_log_manager=self.mock_game_log_manager # Pass if ItemManager init takes it
        )
        # If ItemManager __init__ expects game_log_manager, it should be added here.
        # For now, assuming it's not a direct dependency of __init__ or not used by revert methods.
        # Let's add it to be safe, as the original class has it.
        self.item_manager._game_log_manager = self.mock_game_log_manager


        self.item_template = {
            "id": "tpl_sword_revert",
            "name_i18n": {"en": "Revert Sword"},
            "type": "weapon",
            "description_i18n": {"en": "A sword for testing reverts."} # Added description
        }
        # Manually load the template into the manager's cache
        self.item_manager._item_templates[self.item_template["id"]] = self.item_template

        # Clear caches for the test guild for isolation
        self.item_manager._items.pop(self.guild_id, None)
        self.item_manager._items_by_owner.pop(self.guild_id, None)
        self.item_manager._items_by_location.pop(self.guild_id, None)
        self.item_manager._dirty_items.pop(self.guild_id, None)
        self.item_manager._deleted_items.pop(self.guild_id, None)


    async def test_revert_item_creation(self):
        # Mock the DB execute for remove_item_instance (called by revert_item_creation)
        self.mock_db_service.adapter.execute = AsyncMock(return_value=None) # Simulate successful DB delete

        # Create an item instance - this will use the real create_item_instance logic
        # which internally calls save_item. We might need to mock save_item's DB part too.
        # For create_item_instance, save_item is called. Let's mock its DB interaction.
        with patch.object(self.item_manager, 'save_item', new=AsyncMock(return_value=True)) as mock_save_item:
            created_item = await self.item_manager.create_item_instance(
                self.guild_id, self.item_template["id"], quantity=1.0
            )

        self.assertIsNotNone(created_item, "Item creation failed during setup for test_revert_item_creation.")
        if created_item is None: return # For type checker

        item_id = created_item.id

        # Ensure item is in cache before revert
        self.assertIn(item_id, self.item_manager._items.get(self.guild_id, {}))

        # Call revert_item_creation
        result = await self.item_manager.revert_item_creation(self.guild_id, item_id)
        self.assertTrue(result, "revert_item_creation should return True on successful simulation of removal.")

        # Assert item is removed from main cache
        self.assertNotIn(item_id, self.item_manager._items.get(self.guild_id, {}),
                         "Item should be removed from the main cache after revert_item_creation.")

        # Assert item is marked for deletion (this is what remove_item_instance does)
        self.assertIn(item_id, self.item_manager._deleted_items.get(self.guild_id, set()),
                      "Item should be in the _deleted_items set after revert_item_creation.")

        # Assert item is not in dirty items (as it's deleted, not just modified)
        self.assertNotIn(item_id, self.item_manager._dirty_items.get(self.guild_id, set()),
                         "Item should not be in _dirty_items if it was reverted from creation (i.e., deleted).")

        # Verify DB delete was called by remove_item_instance
        self.mock_db_service.adapter.execute.assert_called_once_with(
            'DELETE FROM items WHERE id = $1 AND guild_id = $2',
            (item_id, self.guild_id)
        )

    async def test_revert_item_deletion(self):
        item_id_to_recreate = str(uuid.uuid4())
        original_item_data = {
            "id": item_id_to_recreate,
            "guild_id": self.guild_id,
            "template_id": self.item_template["id"],
            "quantity": 1.0,
            "owner_id": "player_test_owner",
            "owner_type": "Character",
            "location_id": None,
            "state_variables": {"condition": "pristine"},
            "is_temporary": False
        }

        # Ensure item is not in cache initially (simulating it was deleted)
        self.assertNotIn(item_id_to_recreate, self.item_manager._items.get(self.guild_id, {}))

        # Mock save_item because revert_item_deletion calls it.
        # We want to test revert_item_deletion's logic, not save_item's full DB interaction here.
        # The mock should simulate successful saving and caching.
        async def mock_save_item_for_revert_deletion(item_obj, guild_id_param):
            # Simulate adding to internal caches as save_item would
            self.item_manager._items.setdefault(guild_id_param, {})[item_obj.id] = item_obj
            self.item_manager._update_lookup_caches_add(guild_id_param, item_obj.to_dict())
            # No need to call mark_item_dirty if save_item itself handles DB write.
            # For this test, we assume save_item succeeds.
            return True

        with patch.object(self.item_manager, 'save_item', new=mock_save_item_for_revert_deletion):
            result = await self.item_manager.revert_item_deletion(self.guild_id, original_item_data)

        self.assertTrue(result, "revert_item_deletion should return True on successful recreation.")

        # Assert item is now in the main cache
        recreated_item = self.item_manager.get_item_instance(self.guild_id, item_id_to_recreate)
        self.assertIsNotNone(recreated_item, "Item should be in cache after revert_item_deletion.")
        if recreated_item:
            self.assertEqual(recreated_item.template_id, self.item_template["id"])
            self.assertEqual(recreated_item.quantity, 1.0)
            self.assertEqual(recreated_item.owner_id, "player_test_owner")
            self.assertEqual(recreated_item.state_variables.get("condition"), "pristine")

        # Check lookup caches (optional, but good for completeness)
        self.assertIn(item_id_to_recreate, self.item_manager._items_by_owner.get(self.guild_id, {}).get("player_test_owner", set()))


    async def test_revert_item_update(self):
        # First, create an item to update and then revert the update
        item_to_update_id = None
        with patch.object(self.item_manager, 'save_item', new=AsyncMock(return_value=True)):
            item_to_update = await self.item_manager.create_item_instance(
                self.guild_id, self.item_template["id"], quantity=5.0, owner_id="owner_before_update"
            )
        self.assertIsNotNone(item_to_update)
        if item_to_update is None: return
        item_to_update_id = item_to_update.id

        # Simulate that the item was updated (e.g., quantity changed from 5 to 10, owner changed)
        # These are the values *before* the update that we want to revert to.
        old_field_values_to_revert_to = {
            "quantity": 5.0,
            "owner_id": "owner_before_update",
            "state_variables": {"condition": "worn"}
        }

        # Manually set the item's state to simulate it *after* an update (current state)
        item_in_cache = self.item_manager.get_item_instance(self.guild_id, item_to_update_id)
        self.assertIsNotNone(item_in_cache)
        if item_in_cache is None: return

        item_in_cache.quantity = 10.0
        item_in_cache.owner_id = "owner_after_update"
        item_in_cache.state_variables = {"condition": "brand_new", "engraving": " fearless"}
        # Update lookup caches to reflect this "after_update" state
        self.item_manager._update_lookup_caches_remove(self.guild_id, {"id": item_to_update_id, "owner_id": "owner_before_update"})
        self.item_manager._update_lookup_caches_add(self.guild_id, item_in_cache.to_dict())


        # Call revert_item_update
        result = await self.item_manager.revert_item_update(self.guild_id, item_to_update_id, old_field_values_to_revert_to)
        self.assertTrue(result, "revert_item_update should return True.")

        # Assert fields are reverted
        reverted_item = self.item_manager.get_item_instance(self.guild_id, item_to_update_id)
        self.assertIsNotNone(reverted_item)
        if reverted_item:
            self.assertEqual(reverted_item.quantity, 5.0)
            self.assertEqual(reverted_item.owner_id, "owner_before_update")
            self.assertEqual(reverted_item.state_variables.get("condition"), "worn")
            # Check if other parts of state_variables that weren't in old_field_values are preserved or wiped.
            # According to current revert_item_update, it uses setattr, so other keys in state_variables would remain.
            # If state_variables should be fully replaced by old_field_values["state_variables"], the revert logic needs adjustment.
            # For now, assume setattr on 'state_variables' replaces the whole dict if 'state_variables' is a key in old_field_values.
            self.assertNotIn("engraving", reverted_item.state_variables, "Engraving should be gone if state_variables was fully reverted.")


        # Assert item is marked dirty
        self.assertIn(item_to_update_id, self.item_manager._dirty_items.get(self.guild_id, set()))

        # Check lookup caches are correct for the reverted state
        self.assertNotIn(item_to_update_id, self.item_manager._items_by_owner.get(self.guild_id, {}).get("owner_after_update", set()))
        self.assertIn(item_to_update_id, self.item_manager._items_by_owner.get(self.guild_id, {}).get("owner_before_update", set()))


if __name__ == '__main__':
    asyncio.run(unittest.main())
