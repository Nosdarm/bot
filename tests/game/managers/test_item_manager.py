import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock, patch, call
import uuid

from bot.game.managers.item_manager import ItemManager
from bot.game.models.item import Item
# Assuming ItemManager might need these for context or type hints
# from bot.game.models.character import Character
# from bot.game.models.npc import Npc

# Dummy item template data that might come from settings
DUMMY_ITEM_TEMPLATES = {
    "potion_health": {
        "id": "potion_health",
        "name": "Health Potion",
        "description": "Restores a small amount of health.",
        "type": "consumable",
        "properties": {"heal_amount": 25},
        "stackable": True,
        "max_stack": 10
    },
    "sword_basic": {
        "id": "sword_basic",
        "name": "Basic Sword",
        "description": "A common sword.",
        "type": "equipment",
        "slot": "weapon",
        "properties": {"damage": 5, "durability": 100},
        "stackable": False
    },
    "quest_item_orb": {
        "id": "quest_item_orb",
        "name": "Orb of Knowing",
        "description": "A mysterious orb needed for a quest.",
        "type": "quest",
        "properties": {},
        "stackable": False
    }
}

class TestItemManager(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.mock_db_adapter = AsyncMock()
        self.mock_settings = MagicMock()
        # Mock the return value for get_all_item_templates
        self.mock_settings.get_all_item_templates = MagicMock(return_value=DUMMY_ITEM_TEMPLATES)

        # Mock other managers that might be needed by some ItemManager methods
        self.mock_character_manager = AsyncMock()
        self.mock_npc_manager = AsyncMock()
        self.mock_location_manager = AsyncMock()

        # Patch _load_item_templates during __init__ for most tests,
        # so we can test it in isolation.
        with patch.object(ItemManager, '_load_item_templates', return_value=None) as self.mock_load_templates:
            self.item_manager = ItemManager(
                db_adapter=self.mock_db_adapter,
                settings=self.mock_settings,
                character_manager=self.mock_character_manager,
                npc_manager=self.mock_npc_manager,
                location_manager=self.mock_location_manager
            )

        self.guild_id = "test_guild_1"
        # Common data for creating items
        self.template_id_potion = "potion_health"
        self.item_id_obj = uuid.UUID('12345678-1234-5678-1234-567812345678')
        self.item_id = str(self.item_id_obj)


    async def test_init_manager(self):
        # Re-initialize without patching _load_item_templates to test its call
        with patch.object(ItemManager, '_load_item_templates', return_value=None) as mock_load_during_init:
            manager = ItemManager(
                db_adapter=self.mock_db_adapter,
                settings=self.mock_settings,
                character_manager=self.mock_character_manager,
                npc_manager=self.mock_npc_manager,
                location_manager=self.mock_location_manager
            )

        self.assertEqual(manager._db_adapter, self.mock_db_adapter)
        self.assertEqual(manager._settings, self.mock_settings)
        self.assertEqual(manager._item_templates, {}) # Populated by _load_item_templates
        self.assertEqual(manager._items, {})
        self.assertEqual(manager._items_by_owner, {})
        self.assertEqual(manager._items_by_location, {})
        self.assertEqual(manager._dirty_items, {})
        self.assertEqual(manager._deleted_items, {})
        mock_load_during_init.assert_called_once()

    async def test_load_item_templates_from_settings(self):
        # This test calls _load_item_templates directly
        # Create a new manager instance for this test, don't use the one from setUp
        # where _load_item_templates was patched away during its __init__
        test_manager = ItemManager(
            db_adapter=self.mock_db_adapter,
            settings=self.mock_settings, # This mock_settings has get_all_item_templates mocked in setUp
            character_manager=self.mock_character_manager,
            npc_manager=self.mock_npc_manager,
            location_manager=self.mock_location_manager
        )
        # _load_item_templates is called by __init__ of test_manager

        self.mock_settings.get_all_item_templates.assert_called_once()
        self.assertEqual(len(test_manager._item_templates), len(DUMMY_ITEM_TEMPLATES))
        self.assertIn("potion_health", test_manager._item_templates)
        self.assertEqual(test_manager._item_templates["potion_health"]["name"], "Health Potion")
        self.assertTrue(test_manager._item_templates["sword_basic"]["stackable"] is False)

    async def test_get_item_template_exists(self):
        # Ensure _load_item_templates has run for self.item_manager
        self.item_manager._item_templates = DUMMY_ITEM_TEMPLATES.copy() # Manually load for this test instance

        template = self.item_manager.get_item_template("potion_health")
        self.assertIsNotNone(template)
        self.assertEqual(template["name"], "Health Potion")

    async def test_get_item_template_non_existent(self):
        self.item_manager._item_templates = DUMMY_ITEM_TEMPLATES.copy()

        template = self.item_manager.get_item_template("non_existent_template_id")
        self.assertIsNone(template)

    async def test_get_item_instance_exists(self):
        instance_id = "instance1"
        expected_item_data = Item(id=instance_id, guild_id=self.guild_id, template_id=self.template_id_potion, quantity=1)
        self.item_manager._items[self.guild_id] = {instance_id: expected_item_data}

        retrieved_item = self.item_manager.get_item_instance(self.guild_id, instance_id)
        self.assertEqual(retrieved_item, expected_item_data)

    async def test_get_item_instance_non_existent(self):
        self.item_manager._items[self.guild_id] = {} # Guild cache exists but item is not in it

        retrieved_item = self.item_manager.get_item_instance(self.guild_id, "non_existent_instance")
        self.assertIsNone(retrieved_item)

    async def test_get_item_instance_different_guild(self):
        other_guild_id = "guild2_get_item"
        instance_id = "instance_other_guild"
        item_data_other_guild = Item(id=instance_id, guild_id=other_guild_id, template_id=self.template_id_potion, quantity=1)

        self.item_manager._items[self.guild_id] = {} # Current guild
        self.item_manager._items[other_guild_id] = {instance_id: item_data_other_guild}

        # Try to get item from self.guild_id that exists only in other_guild_id
        retrieved_item = self.item_manager.get_item_instance(self.guild_id, instance_id)
        self.assertIsNone(retrieved_item)

    async def test_get_item_instance_guild_not_loaded(self):
        unloaded_guild_id = "unloaded_guild_for_item"
        # No cache entry for unloaded_guild_id in self.item_manager._items

        retrieved_item = self.item_manager.get_item_instance(unloaded_guild_id, "some_instance_id")
        self.assertIsNone(retrieved_item)

    async def test_get_items_by_owner_multiple_items(self):
        owner_id = "owner1"
        item1 = Item(id="item_inst_1", guild_id=self.guild_id, template_id="tpl1", quantity=1, owner_id=owner_id, owner_type="Character")
        item2 = Item(id="item_inst_2", guild_id=self.guild_id, template_id="tpl2", quantity=5, owner_id=owner_id, owner_type="Character")
        # Item owned by someone else
        other_owner_item = Item(id="item_inst_3", guild_id=self.guild_id, template_id="tpl1", quantity=1, owner_id="owner2", owner_type="Character")

        self.item_manager._items[self.guild_id] = {
            item1.id: item1, item2.id: item2, other_owner_item.id: other_owner_item
        }
        # Manually populate _items_by_owner for this test
        self.item_manager._items_by_owner = {
            self.guild_id: {
                owner_id: {item1.id, item2.id}, # Using a set of item IDs
                "owner2": {other_owner_item.id}
            }
        }

        owned_items = self.item_manager.get_items_by_owner(self.guild_id, owner_id)
        self.assertEqual(len(owned_items), 2)
        self.assertIn(item1, owned_items)
        self.assertIn(item2, owned_items)
        self.assertNotIn(other_owner_item, owned_items)

    async def test_get_items_by_owner_no_items(self):
        owner_id = "owner_no_items"
        self.item_manager._items[self.guild_id] = {}
        self.item_manager._items_by_owner = {self.guild_id: {}} # Owner exists in map but has no items (empty set)
        # Or owner not in map at all:
        # self.item_manager._items_by_owner = {self.guild_id: {"another_owner": {"some_item_id"}}}


        owned_items = self.item_manager.get_items_by_owner(self.guild_id, owner_id)
        self.assertEqual(len(owned_items), 0)

    async def test_get_items_by_owner_non_existent_owner(self):
        # Owner ID is not in the _items_by_owner cache for the guild
        self.item_manager._items_by_owner = {self.guild_id: {}}
        owned_items = self.item_manager.get_items_by_owner(self.guild_id, "non_existent_owner_id")
        self.assertEqual(len(owned_items), 0)

    async def test_get_items_by_owner_guild_not_loaded(self):
        unloaded_guild = "unloaded_guild_owner_items"
        # _items_by_owner does not have unloaded_guild as a key
        owned_items = self.item_manager.get_items_by_owner(unloaded_guild, "some_owner_id")
        self.assertEqual(len(owned_items), 0)

    async def test_get_items_by_owner_item_missing_from_main_cache(self):
        # Edge case: item_id in _items_by_owner but not in _items
        owner_id = "owner_with_ghost_item"
        ghost_item_id = "ghost_item"
        self.item_manager._items_by_owner = {
            self.guild_id: {
                owner_id: {ghost_item_id}
            }
        }
        self.item_manager._items[self.guild_id] = {} # Main cache is empty for this guild

        owned_items = self.item_manager.get_items_by_owner(self.guild_id, owner_id)
        self.assertEqual(len(owned_items), 0) # Should not return a ghost item

    async def test_get_items_in_location_multiple_items(self):
        location_id = "location1"
        item1 = Item(id="item_loc_1", guild_id=self.guild_id, template_id="tpl1", quantity=1, location_id=location_id)
        item2 = Item(id="item_loc_2", guild_id=self.guild_id, template_id="tpl2", quantity=1, location_id=location_id)
        # Item in another location
        other_location_item = Item(id="item_loc_3", guild_id=self.guild_id, template_id="tpl1", quantity=1, location_id="location2")
        # Item with no location (e.g. in a character's inventory not tied to a specific world location)
        unlocated_item = Item(id="item_loc_4", guild_id=self.guild_id, template_id="tpl1", quantity=1, owner_id="char1")


        self.item_manager._items[self.guild_id] = {
            item1.id: item1, item2.id: item2, other_location_item.id: other_location_item, unlocated_item.id: unlocated_item
        }
        self.item_manager._items_by_location = {
            self.guild_id: {
                location_id: {item1.id, item2.id},
                "location2": {other_location_item.id}
            }
        }

        found_items = self.item_manager.get_items_in_location(self.guild_id, location_id)
        self.assertEqual(len(found_items), 2)
        self.assertIn(item1, found_items)
        self.assertIn(item2, found_items)
        self.assertNotIn(other_location_item, found_items)
        self.assertNotIn(unlocated_item, found_items)

    async def test_get_items_in_location_no_items(self):
        location_id = "location_empty"
        self.item_manager._items[self.guild_id] = {}
        self.item_manager._items_by_location = {self.guild_id: {}} # Location exists in map but has no items
        # Or location_id not in _items_by_location at all

        found_items = self.item_manager.get_items_in_location(self.guild_id, location_id)
        self.assertEqual(len(found_items), 0)

    async def test_get_items_in_location_non_existent_location(self):
        self.item_manager._items_by_location = {self.guild_id: {}}
        found_items = self.item_manager.get_items_in_location(self.guild_id, "non_existent_location_id")
        self.assertEqual(len(found_items), 0)

    async def test_get_items_in_location_guild_not_loaded(self):
        unloaded_guild = "unloaded_guild_location_items"
        found_items = self.item_manager.get_items_in_location(unloaded_guild, "some_location_id")
        self.assertEqual(len(found_items), 0)

    async def test_get_items_in_location_item_missing_from_main_cache(self):
        location_id = "loc_with_ghost_item"
        ghost_item_id = "ghost_item_in_loc"
        self.item_manager._items_by_location = {
            self.guild_id: {
                location_id: {ghost_item_id}
            }
        }
        self.item_manager._items[self.guild_id] = {} # Main cache is empty

        found_items = self.item_manager.get_items_in_location(self.guild_id, location_id)
        self.assertEqual(len(found_items), 0)

    async def test_create_item_instance_success_character_owner(self):
        # Ensure templates are loaded for the item_manager instance being tested
        self.item_manager._item_templates = DUMMY_ITEM_TEMPLATES.copy()

        owner_id = "char_owner_1"
        owner_type = "Character"
        quantity = 5
        state_vars = {"charge": 100}

        with patch('uuid.uuid4', return_value=self.item_id_obj):
            item_instance = await self.item_manager.create_item_instance(
                guild_id=self.guild_id,
                template_id=self.template_id_potion,
                quantity=quantity,
                owner_id=owner_id,
                owner_type=owner_type,
                state_variables=state_vars
            )

        self.assertIsNotNone(item_instance)
        self.assertEqual(item_instance.id, self.item_id)
        self.assertEqual(item_instance.guild_id, self.guild_id)
        self.assertEqual(item_instance.template_id, self.template_id_potion)
        self.assertEqual(item_instance.quantity, quantity)
        self.assertEqual(item_instance.owner_id, owner_id)
        self.assertEqual(item_instance.owner_type, owner_type)
        self.assertEqual(item_instance.state_variables, state_vars)
        self.assertIsNone(item_instance.location_id) # No location specified

        # Verify DB call
        self.mock_db_adapter.execute.assert_called_once()
        args, _ = self.mock_db_adapter.execute.call_args
        self.assertIn("INSERT INTO items", args[0])
        # (id, guild_id, template_id, quantity, owner_id, owner_type, location_id, state_variables_json)
        self.assertEqual(args[1], (self.item_id, self.guild_id, self.template_id_potion, quantity, owner_id, owner_type, None, '{"charge": 100}'))

        # Verify caches
        self.assertIn(self.item_id, self.item_manager._items[self.guild_id])
        self.assertEqual(self.item_manager._items[self.guild_id][self.item_id], item_instance)

        self.assertIn(owner_id, self.item_manager._items_by_owner[self.guild_id])
        self.assertIn(self.item_id, self.item_manager._items_by_owner[self.guild_id][owner_id])
        self.assertNotIn(self.guild_id, self.item_manager._items_by_location) # No location_id

    async def test_create_item_instance_success_location_owner(self):
        self.item_manager._item_templates = DUMMY_ITEM_TEMPLATES.copy()
        location_id = "ground_loc_1"
        quantity = 1 # Non-stackable sword

        with patch('uuid.uuid4', return_value=self.item_id_obj):
            item_instance = await self.item_manager.create_item_instance(
                guild_id=self.guild_id,
                template_id="sword_basic", # Using a different template
                quantity=quantity,
                location_id=location_id
                # owner_id/type are None
            )

        self.assertIsNotNone(item_instance)
        self.assertEqual(item_instance.id, self.item_id)
        self.assertEqual(item_instance.location_id, location_id)
        self.assertIsNone(item_instance.owner_id)
        self.assertIsNone(item_instance.owner_type)

        self.mock_db_adapter.execute.assert_called_once()
        # Verify caches
        self.assertIn(self.item_id, self.item_manager._items[self.guild_id])
        self.assertIn(location_id, self.item_manager._items_by_location[self.guild_id])
        self.assertIn(self.item_id, self.item_manager._items_by_location[self.guild_id][location_id])
        self.assertNotIn(self.guild_id, self.item_manager._items_by_owner) # No owner

    async def test_create_item_instance_template_not_found(self):
        self.item_manager._item_templates = {} # No templates loaded
        item_instance = await self.item_manager.create_item_instance(self.guild_id, "bad_template", 1)
        self.assertIsNone(item_instance)
        self.mock_db_adapter.execute.assert_not_called()

    async def test_create_item_instance_invalid_quantity(self):
        self.item_manager._item_templates = DUMMY_ITEM_TEMPLATES.copy()

        item_instance_zero = await self.item_manager.create_item_instance(self.guild_id, self.template_id_potion, 0)
        self.assertIsNone(item_instance_zero)

        item_instance_negative = await self.item_manager.create_item_instance(self.guild_id, self.template_id_potion, -1)
        self.assertIsNone(item_instance_negative)
        self.mock_db_adapter.execute.assert_not_called() # Should fail before DB call

    async def test_create_item_instance_stackable_quantity_check(self):
        # Test creating a non-stackable item with quantity > 1 (should probably default to 1 or fail)
        # Assuming ItemManager defaults to quantity 1 for non-stackable if quantity > 1 is given.
        self.item_manager._item_templates = DUMMY_ITEM_TEMPLATES.copy() # sword_basic is not stackable

        with patch('uuid.uuid4', return_value=self.item_id_obj):
            item_instance = await self.item_manager.create_item_instance(
                guild_id=self.guild_id,
                template_id="sword_basic",
                quantity=5 # Attempt to create 5 non-stackable swords as one instance
            )
        self.assertIsNotNone(item_instance)
        self.assertEqual(item_instance.quantity, 1) # Assuming it defaults to 1 for non-stackable
        self.mock_db_adapter.execute.assert_called_once() # Still proceeds to create one

    async def test_create_item_instance_guild_caches_not_initialized(self):
        new_guild_id = "new_guild_for_item_creation"
        self.item_manager._item_templates = DUMMY_ITEM_TEMPLATES.copy()

        with patch('uuid.uuid4', return_value=self.item_id_obj):
            await self.item_manager.create_item_instance(
                guild_id=new_guild_id, template_id=self.template_id_potion, quantity=1
            )

        self.assertIn(new_guild_id, self.item_manager._items)
        self.assertIn(self.item_id, self.item_manager._items[new_guild_id])
        # Depending on owner/location, other caches would also be initialized
        # For this simple case (no owner/location), only _items is guaranteed to have the guild_id key.

    async def test_remove_item_instance_success(self):
        owner_id = "owner_for_removal"
        location_id = "loc_for_removal" # Item can have both owner and location if it's e.g. an equipped item on a character in a location

        item_to_remove = Item(
            id=self.item_id, guild_id=self.guild_id, template_id=self.template_id_potion,
            quantity=1, owner_id=owner_id, owner_type="Character", location_id=location_id
        )

        # Pre-populate caches
        self.item_manager._items = {self.guild_id: {self.item_id: item_to_remove}}
        self.item_manager._items_by_owner = {self.guild_id: {owner_id: {self.item_id}}}
        self.item_manager._items_by_location = {self.guild_id: {location_id: {self.item_id}}}
        self.item_manager._deleted_items = {self.guild_id: set()}
        self.item_manager._dirty_items = {self.guild_id: set()} # Ensure it's removed from dirty if it was there

        await self.item_manager.remove_item_instance(self.guild_id, self.item_id)

        # Verify DB call
        self.mock_db_adapter.execute.assert_called_once_with(
            "DELETE FROM items WHERE guild_id = ? AND id = ?",
            (self.guild_id, self.item_id)
        )

        # Verify caches
        self.assertNotIn(self.item_id, self.item_manager._items.get(self.guild_id, {}))
        self.assertNotIn(self.item_id, self.item_manager._items_by_owner.get(self.guild_id, {}).get(owner_id, {}))
        self.assertNotIn(self.item_id, self.item_manager._items_by_location.get(self.guild_id, {}).get(location_id, {}))
        self.assertIn(self.item_id, self.item_manager._deleted_items[self.guild_id])
        self.assertNotIn(self.item_id, self.item_manager._dirty_items.get(self.guild_id, set()))


    async def test_remove_item_instance_was_dirty(self):
        # Ensure removing a dirty item clears it from dirty set and adds to deleted set
        item_to_remove = Item(id=self.item_id, guild_id=self.guild_id, template_id="tpl1", quantity=1)
        self.item_manager._items = {self.guild_id: {self.item_id: item_to_remove}}
        self.item_manager._dirty_items = {self.guild_id: {self.item_id}} # Mark as dirty
        self.item_manager._deleted_items = {self.guild_id: set()}
        # Not populating owner/location caches for simplicity, focus is on dirty/deleted interaction

        await self.item_manager.remove_item_instance(self.guild_id, self.item_id)

        self.mock_db_adapter.execute.assert_called_once()
        self.assertNotIn(self.item_id, self.item_manager._items.get(self.guild_id, {}))
        self.assertIn(self.item_id, self.item_manager._deleted_items[self.guild_id])
        self.assertNotIn(self.item_id, self.item_manager._dirty_items[self.guild_id])


    async def test_remove_item_instance_non_existent(self):
        self.item_manager._items = {self.guild_id: {}}
        self.item_manager._deleted_items = {self.guild_id: set()}

        await self.item_manager.remove_item_instance(self.guild_id, "non_existent_item_id")

        self.mock_db_adapter.execute.assert_not_called()
        self.assertEqual(len(self.item_manager._deleted_items[self.guild_id]), 0)

    async def test_remove_item_instance_guild_not_loaded(self):
        unloaded_guild = "unloaded_guild_for_removal"
        # No caches for this guild

        await self.item_manager.remove_item_instance(unloaded_guild, "some_item_id")

        self.mock_db_adapter.execute.assert_not_called()
        self.assertNotIn(unloaded_guild, self.item_manager._deleted_items)

    async def test_update_item_instance_success_quantity_and_state(self):
        item_to_update = Item(
            id=self.item_id, guild_id=self.guild_id, template_id=self.template_id_potion,
            quantity=1, state_variables={"condition": "good"}
        )
        self.item_manager._items = {self.guild_id: {self.item_id: item_to_update}}
        self.item_manager._dirty_items = {self.guild_id: set()}
        self.item_manager.mark_item_dirty = MagicMock() # Mock to verify call

        update_data = {"quantity": 5, "state_variables": {"condition": "worn", "charge": 50}}
        updated_item = await self.item_manager.update_item_instance(self.guild_id, self.item_id, update_data)

        self.assertIsNotNone(updated_item)
        self.assertEqual(updated_item.quantity, 5)
        # Assuming state_variables are merged (original ItemManager might replace or merge)
        # For this test, let's assume it merges (like dict.update())
        self.assertEqual(updated_item.state_variables, {"condition": "worn", "charge": 50})
        self.item_manager.mark_item_dirty.assert_called_once_with(self.guild_id, self.item_id)

    async def test_update_item_instance_change_owner(self):
        old_owner_id = "old_owner"
        new_owner_id = "new_owner"
        item_to_update = Item(
            id=self.item_id, guild_id=self.guild_id, template_id=self.template_id_potion,
            quantity=1, owner_id=old_owner_id, owner_type="Character"
        )
        self.item_manager._items = {self.guild_id: {self.item_id: item_to_update}}
        self.item_manager._items_by_owner = {
            self.guild_id: {
                old_owner_id: {self.item_id},
                new_owner_id: set() # New owner starts with no items in this cache
            }
        }
        self.item_manager._dirty_items = {self.guild_id: set()}
        self.item_manager.mark_item_dirty = MagicMock()

        update_data = {"owner_id": new_owner_id, "owner_type": "Npc"} # Also changing owner type
        updated_item = await self.item_manager.update_item_instance(self.guild_id, self.item_id, update_data)

        self.assertIsNotNone(updated_item)
        self.assertEqual(updated_item.owner_id, new_owner_id)
        self.assertEqual(updated_item.owner_type, "Npc")
        self.item_manager.mark_item_dirty.assert_called_once_with(self.guild_id, self.item_id)

        # Verify _items_by_owner cache update
        self.assertNotIn(self.item_id, self.item_manager._items_by_owner[self.guild_id].get(old_owner_id, set()))
        self.assertIn(self.item_id, self.item_manager._items_by_owner[self.guild_id][new_owner_id])

    async def test_update_item_instance_change_location(self):
        old_location_id = "old_loc"
        new_location_id = "new_loc"
        item_to_update = Item(
            id=self.item_id, guild_id=self.guild_id, template_id=self.template_id_potion,
            quantity=1, location_id=old_location_id
        )
        self.item_manager._items = {self.guild_id: {self.item_id: item_to_update}}
        self.item_manager._items_by_location = {
            self.guild_id: {
                old_location_id: {self.item_id},
                new_location_id: set()
            }
        }
        self.item_manager._dirty_items = {self.guild_id: set()}
        self.item_manager.mark_item_dirty = MagicMock()

        update_data = {"location_id": new_location_id}
        updated_item = await self.item_manager.update_item_instance(self.guild_id, self.item_id, update_data)

        self.assertIsNotNone(updated_item)
        self.assertEqual(updated_item.location_id, new_location_id)
        self.item_manager.mark_item_dirty.assert_called_once_with(self.guild_id, self.item_id)

        self.assertNotIn(self.item_id, self.item_manager._items_by_location[self.guild_id].get(old_location_id, set()))
        self.assertIn(self.item_id, self.item_manager._items_by_location[self.guild_id][new_location_id])

    async def test_update_item_instance_remove_owner(self):
        # Test changing from owned to unowned (e.g., dropped on ground)
        owner_id = "owner_drops_item"
        new_location_id = "ground_location" # Item is now in a location, not directly owned
        item_to_update = Item(
            id=self.item_id, guild_id=self.guild_id, template_id=self.template_id_potion,
            quantity=1, owner_id=owner_id, owner_type="Character"
        )
        self.item_manager._items = {self.guild_id: {self.item_id: item_to_update}}
        self.item_manager._items_by_owner = {self.guild_id: {owner_id: {self.item_id}}}
        self.item_manager._items_by_location = {self.guild_id: {}} # Ensure location cache exists for guild
        self.item_manager.mark_item_dirty = MagicMock()

        update_data = {"owner_id": None, "owner_type": None, "location_id": new_location_id}
        updated_item = await self.item_manager.update_item_instance(self.guild_id, self.item_id, update_data)

        self.assertIsNone(updated_item.owner_id)
        self.assertIsNone(updated_item.owner_type)
        self.assertEqual(updated_item.location_id, new_location_id)
        self.item_manager.mark_item_dirty.assert_called_once()
        self.assertNotIn(self.item_id, self.item_manager._items_by_owner[self.guild_id].get(owner_id, set()))
        self.assertIn(self.item_id, self.item_manager._items_by_location[self.guild_id][new_location_id])


    async def test_update_item_instance_non_existent(self):
        self.item_manager._items = {self.guild_id: {}}
        self.item_manager.mark_item_dirty = MagicMock()

        updated_item = await self.item_manager.update_item_instance(self.guild_id, "non_existent", {"quantity": 10})

        self.assertIsNone(updated_item)
        self.item_manager.mark_item_dirty.assert_not_called()

    async def test_update_item_instance_guild_not_loaded(self):
        unloaded_guild = "unloaded_guild_for_update"
        self.item_manager.mark_item_dirty = MagicMock()

        updated_item = await self.item_manager.update_item_instance(unloaded_guild, "some_id", {"quantity": 1})
        self.assertIsNone(updated_item)
        self.item_manager.mark_item_dirty.assert_not_called()

    async def test_load_state_success(self):
        # Sample data from DB for item instances
        db_item_data = [
            ("item1", self.guild_id, "potion_health", 5, "char1", "Character", None, '{"sticky": true}', False, 1),
            ("item2", self.guild_id, "sword_basic", 1, None, None, "loc1", '{}', False, 2),
            ("item3", self.guild_id, "quest_item_orb", 1, "npc1", "Npc", "loc1", '{}', True, 3), # Item is dirty
            ("item4", self.guild_id, "potion_health", 10, "char1", "Character", None, '{}', False, 4)
        ]
        self.mock_db_adapter.fetchall.return_value = db_item_data

        # Pre-populate caches to ensure they are cleared for the guild before loading
        self.item_manager._items[self.guild_id] = {"old_item": MagicMock()}
        self.item_manager._items_by_owner[self.guild_id] = {"old_owner": {"old_item"}}
        self.item_manager._items_by_location[self.guild_id] = {"old_loc": {"old_item"}}
        self.item_manager._dirty_items[self.guild_id] = {"old_dirty_item"}
        self.item_manager._deleted_items[self.guild_id] = {"old_deleted_item"} # Should also be cleared

        await self.item_manager.load_state(self.guild_id)

        self.mock_db_adapter.fetchall.assert_called_once_with(
            "SELECT id, guild_id, template_id, quantity, owner_id, owner_type, location_id, state_variables, is_dirty, _rowid_ FROM items WHERE guild_id = ?",
            (self.guild_id,)
        )

        # Verify main cache (_items)
        self.assertIn(self.guild_id, self.item_manager._items)
        self.assertEqual(len(self.item_manager._items[self.guild_id]), 4)
        self.assertIn("item1", self.item_manager._items[self.guild_id])
        item1_loaded = self.item_manager._items[self.guild_id]["item1"]
        self.assertEqual(item1_loaded.quantity, 5)
        self.assertEqual(item1_loaded.owner_id, "char1")
        self.assertEqual(item1_loaded.state_variables, {"sticky": True})

        # Verify lookup cache (_items_by_owner)
        self.assertIn(self.guild_id, self.item_manager._items_by_owner)
        owner_cache = self.item_manager._items_by_owner[self.guild_id]
        self.assertIn("char1", owner_cache)
        self.assertEqual(owner_cache["char1"], {"item1", "item4"})
        self.assertIn("npc1", owner_cache)
        self.assertEqual(owner_cache["npc1"], {"item3"})

        # Verify lookup cache (_items_by_location)
        self.assertIn(self.guild_id, self.item_manager._items_by_location)
        location_cache = self.item_manager._items_by_location[self.guild_id]
        self.assertIn("loc1", location_cache)
        self.assertEqual(location_cache["loc1"], {"item2", "item3"})

        # Verify dirty items list (item3 was marked dirty in DB data)
        self.assertIn(self.guild_id, self.item_manager._dirty_items)
        self.assertEqual(self.item_manager._dirty_items[self.guild_id], {"item3"})

        # Verify deleted items list is cleared/empty for the guild
        self.assertNotIn(self.guild_id, self.item_manager._deleted_items) # Or check if it's an empty set if guild key persists

    async def test_load_state_no_items_in_db(self):
        self.mock_db_adapter.fetchall.return_value = [] # No items for this guild in DB

        # Pre-populate to ensure clearing
        self.item_manager._items[self.guild_id] = {"old_item": MagicMock()}
        self.item_manager._items_by_owner[self.guild_id] = {"old_owner": {"old_item"}}
        #... and other caches

        await self.item_manager.load_state(self.guild_id)

        self.mock_db_adapter.fetchall.assert_called_once()
        self.assertNotIn(self.guild_id, self.item_manager._items) # Cleared
        self.assertNotIn(self.guild_id, self.item_manager._items_by_owner) # Cleared
        self.assertNotIn(self.guild_id, self.item_manager._items_by_location) # Cleared
        self.assertNotIn(self.guild_id, self.item_manager._dirty_items) # Cleared
        self.assertNotIn(self.guild_id, self.item_manager._deleted_items) # Cleared

    async def test_load_state_json_parsing_error(self):
        # Malformed JSON for state_variables
        db_item_data = [
            ("item_err", self.guild_id, "potion_health", 1, "char1", "Character", None, "{'bad_json':", False, 1)
        ]
        self.mock_db_adapter.fetchall.return_value = db_item_data

        with self.assertLogs(level='ERROR') as log:
            await self.item_manager.load_state(self.guild_id)
            self.assertTrue(any("Failed to parse JSON for item state_variables" in message for message in log.output))

        # Item should still be loaded, but with default state_variables
        self.assertIn("item_err", self.item_manager._items[self.guild_id])
        item_err_loaded = self.item_manager._items[self.guild_id]["item_err"]
        self.assertEqual(item_err_loaded.state_variables, {}) # Assuming it defaults to {}

    async def test_save_state_dirty_items(self):
        item1_dirty = Item(id="item_s_1", guild_id=self.guild_id, template_id="tpl1", quantity=2, owner_id="char1", state_variables={"st": "new"})
        item2_dirty = Item(id="item_s_2", guild_id=self.guild_id, template_id="tpl2", quantity=1, location_id="loc1")

        self.item_manager._items[self.guild_id] = {item1_dirty.id: item1_dirty, item2_dirty.id: item2_dirty}
        self.item_manager._dirty_items[self.guild_id] = {item1_dirty.id, item2_dirty.id}
        self.item_manager._deleted_items[self.guild_id] = set()

        await self.item_manager.save_state(self.guild_id)

        self.mock_db_adapter.execute_many.assert_called_once()
        args, _ = self.mock_db_adapter.execute_many.call_args
        self.assertIn("REPLACE INTO items", args[0]) # Assuming REPLACE INTO for updates

        expected_data = [
            (item1_dirty.id, self.guild_id, item1_dirty.template_id, item1_dirty.quantity,
             item1_dirty.owner_id, item1_dirty.owner_type, item1_dirty.location_id, '{"st": "new"}', True), # True for is_dirty
            (item2_dirty.id, self.guild_id, item2_dirty.template_id, item2_dirty.quantity,
             item2_dirty.owner_id, item2_dirty.owner_type, item2_dirty.location_id, '{}', True)
        ]
        # Order of data might vary, so check contents carefully or sort if possible
        self.assertCountEqual(args[1], expected_data)
        self.assertNotIn(self.guild_id, self.item_manager._dirty_items) # Should be cleared

    async def test_save_state_deleted_items(self):
        deleted_id1 = "del_item1"
        deleted_id2 = "del_item2"
        self.item_manager._deleted_items[self.guild_id] = {deleted_id1, deleted_id2}
        self.item_manager._dirty_items[self.guild_id] = set()
        # Items would have already been removed from _items cache by remove_item_instance

        await self.item_manager.save_state(self.guild_id)

        self.mock_db_adapter.execute.assert_called_once()
        args, _ = self.mock_db_adapter.execute.call_args
        self.assertIn("DELETE FROM items WHERE guild_id = ? AND id IN", args[0])
        self.assertEqual(args[1][0], self.guild_id)
        self.assertCountEqual(list(args[1][1]), [deleted_id1, deleted_id2])
        self.assertNotIn(self.guild_id, self.item_manager._deleted_items)

    async def test_save_state_no_changes(self):
        self.item_manager._dirty_items[self.guild_id] = set()
        self.item_manager._deleted_items[self.guild_id] = set()

        await self.item_manager.save_state(self.guild_id)

        self.mock_db_adapter.execute_many.assert_not_called()
        self.mock_db_adapter.execute.assert_not_called()
        self.assertNotIn(self.guild_id, self.item_manager._dirty_items)
        self.assertNotIn(self.guild_id, self.item_manager._deleted_items)

    async def test_save_state_guild_not_previously_loaded(self):
        unloaded_guild_save = "unloaded_guild_for_item_save"
        # No pre-existing entries for this guild_id in caches

        await self.item_manager.save_state(unloaded_guild_save)
        self.mock_db_adapter.execute_many.assert_not_called()
        self.mock_db_adapter.execute.assert_not_called()
        self.assertNotIn(unloaded_guild_save, self.item_manager._dirty_items)
        self.assertNotIn(unloaded_guild_save, self.item_manager._deleted_items)

    async def test_rebuild_runtime_caches_success(self):
        item1_owner1 = Item(id="item_rc_1", guild_id=self.guild_id, template_id="tpl1", owner_id="owner1", owner_type="Character")
        item2_owner1_loc1 = Item(id="item_rc_2", guild_id=self.guild_id, template_id="tpl2", owner_id="owner1", owner_type="Character", location_id="loc1")
        item3_loc1 = Item(id="item_rc_3", guild_id=self.guild_id, template_id="tpl1", location_id="loc1")
        item4_no_owner_no_loc = Item(id="item_rc_4", guild_id=self.guild_id, template_id="tpl3") # Neither owner nor location
        item5_owner2 = Item(id="item_rc_5", guild_id=self.guild_id, template_id="tpl1", owner_id="owner2", owner_type="Npc")

        self.item_manager._items[self.guild_id] = {
            item1_owner1.id: item1_owner1,
            item2_owner1_loc1.id: item2_owner1_loc1,
            item3_loc1.id: item3_loc1,
            item4_no_owner_no_loc.id: item4_no_owner_no_loc,
            item5_owner2.id: item5_owner2
        }
        # Pre-populate lookup caches with some old data to ensure they are cleared and rebuilt
        self.item_manager._items_by_owner[self.guild_id] = {"old_owner_data": {"old_item_id"}}
        self.item_manager._items_by_location[self.guild_id] = {"old_loc_data": {"old_item_id2"}}

        self.item_manager.rebuild_runtime_caches(self.guild_id)

        # Verify _items_by_owner
        owner_cache = self.item_manager._items_by_owner.get(self.guild_id, {})
        self.assertEqual(len(owner_cache), 2) # owner1 and owner2
        self.assertIn("owner1", owner_cache)
        self.assertEqual(owner_cache["owner1"], {item1_owner1.id, item2_owner1_loc1.id})
        self.assertIn("owner2", owner_cache)
        self.assertEqual(owner_cache["owner2"], {item5_owner2.id})
        self.assertNotIn("old_owner_data", owner_cache) # Old data should be gone

        # Verify _items_by_location
        location_cache = self.item_manager._items_by_location.get(self.guild_id, {})
        self.assertEqual(len(location_cache), 1) # Only loc1
        self.assertIn("loc1", location_cache)
        self.assertEqual(location_cache["loc1"], {item2_owner1_loc1.id, item3_loc1.id})
        self.assertNotIn("old_loc_data", location_cache) # Old data should be gone

    async def test_rebuild_runtime_caches_empty_items(self):
        self.item_manager._items[self.guild_id] = {} # No items in the main cache for this guild
        # Pre-populate to ensure clearing
        self.item_manager._items_by_owner[self.guild_id] = {"old_data": {"id"}}
        self.item_manager._items_by_location[self.guild_id] = {"old_data_loc": {"id2"}}

        self.item_manager.rebuild_runtime_caches(self.guild_id)

        self.assertIn(self.guild_id, self.item_manager._items_by_owner) # Guild key might exist
        self.assertEqual(len(self.item_manager._items_by_owner[self.guild_id]), 0) # But should be empty
        self.assertIn(self.guild_id, self.item_manager._items_by_location)
        self.assertEqual(len(self.item_manager._items_by_location[self.guild_id]), 0)

    async def test_rebuild_runtime_caches_guild_not_in_items(self):
        # Guild key itself is not in _items (e.g. manager just initialized, no load_state yet for this guild)
        unloaded_guild_rebuild = "unloaded_guild_for_rebuild"
        # Ensure lookup caches also don't have this guild, or if they do, they should be unaffected if _items doesn't have it.
        # For robustness, let's assume they might have old data for this unloaded guild.
        self.item_manager._items_by_owner[unloaded_guild_rebuild] = {"stale_owner": {"stale_id"}}
        self.item_manager._items_by_location[unloaded_guild_rebuild] = {"stale_loc": {"stale_id2"}}


        self.item_manager.rebuild_runtime_caches(unloaded_guild_rebuild)

        # The method should probably clear the caches for the guild if it processes it,
        # or simply not error if it finds no items for the guild.
        # Assuming it clears them if the guild_id is passed.
        self.assertIn(unloaded_guild_rebuild, self.item_manager._items_by_owner)
        self.assertEqual(len(self.item_manager._items_by_owner[unloaded_guild_rebuild]), 0)
        self.assertIn(unloaded_guild_rebuild, self.item_manager._items_by_location)
        self.assertEqual(len(self.item_manager._items_by_location[unloaded_guild_rebuild]), 0)

    async def test_clean_up_for_character_strategy_drop(self):
        char_id = "char_cleanup_1"
        char_location_id = "char_current_loc_1"
        item1 = Item(id="item_cu_c1", guild_id=self.guild_id, template_id="tpl1", owner_id=char_id, owner_type="Character")
        item2 = Item(id="item_cu_c2", guild_id=self.guild_id, template_id="tpl2", owner_id=char_id, owner_type="Character")

        self.item_manager.get_items_by_owner = MagicMock(return_value=[item1, item2])
        self.item_manager.update_item_instance = AsyncMock(return_value=None) # To verify calls
        self.item_manager.remove_item_instance = AsyncMock() # Should not be called for 'drop'

        # Mock context or how ItemManager gets character's location
        # For this test, let's assume cleanup strategy and location are passed in context
        context = {'character_location_id': char_location_id, 'cleanup_strategy': 'drop'}

        await self.item_manager.clean_up_for_character(self.guild_id, char_id, context)

        self.item_manager.get_items_by_owner.assert_called_once_with(self.guild_id, char_id)
        expected_update_calls = [
            call(self.guild_id, item1.id, {"owner_id": None, "owner_type": None, "location_id": char_location_id}),
            call(self.guild_id, item2.id, {"owner_id": None, "owner_type": None, "location_id": char_location_id})
        ]
        self.item_manager.update_item_instance.assert_has_calls(expected_update_calls, any_order=True)
        self.assertEqual(self.item_manager.update_item_instance.call_count, 2)
        self.item_manager.remove_item_instance.assert_not_called()

    async def test_clean_up_for_character_strategy_destroy(self):
        char_id = "char_cleanup_2"
        item1 = Item(id="item_cu_c3", guild_id=self.guild_id, template_id="tpl1", owner_id=char_id, owner_type="Character")

        self.item_manager.get_items_by_owner = MagicMock(return_value=[item1])
        self.item_manager.remove_item_instance = AsyncMock(return_value=None) # To verify calls
        self.item_manager.update_item_instance = AsyncMock() # Should not be called

        context = {'cleanup_strategy': 'destroy'} # No location needed for destroy

        await self.item_manager.clean_up_for_character(self.guild_id, char_id, context)

        self.item_manager.get_items_by_owner.assert_called_once_with(self.guild_id, char_id)
        self.item_manager.remove_item_instance.assert_called_once_with(self.guild_id, item1.id)
        self.item_manager.update_item_instance.assert_not_called()

    async def test_clean_up_for_character_no_items(self):
        char_id = "char_cleanup_no_items"
        self.item_manager.get_items_by_owner = MagicMock(return_value=[]) # Character has no items
        self.item_manager.update_item_instance = AsyncMock()
        self.item_manager.remove_item_instance = AsyncMock()

        context = {'cleanup_strategy': 'drop', 'character_location_id': 'any_loc'}
        await self.item_manager.clean_up_for_character(self.guild_id, char_id, context)

        self.item_manager.get_items_by_owner.assert_called_once_with(self.guild_id, char_id)
        self.item_manager.update_item_instance.assert_not_called()
        self.item_manager.remove_item_instance.assert_not_called()

    async def test_clean_up_for_npc_strategy_drop(self): # Similar to character
        npc_id = "npc_cleanup_1"
        npc_location_id = "npc_current_loc_1"
        item1 = Item(id="item_cu_n1", guild_id=self.guild_id, template_id="tpl1", owner_id=npc_id, owner_type="Npc")

        self.item_manager.get_items_by_owner = MagicMock(return_value=[item1])
        self.item_manager.update_item_instance = AsyncMock(return_value=None)

        context = {'npc_location_id': npc_location_id, 'cleanup_strategy': 'drop'}
        await self.item_manager.clean_up_for_npc(self.guild_id, npc_id, context)

        self.item_manager.get_items_by_owner.assert_called_once_with(self.guild_id, npc_id)
        self.item_manager.update_item_instance.assert_called_once_with(
            self.guild_id, item1.id, {"owner_id": None, "owner_type": None, "location_id": npc_location_id}
        )

    async def test_clean_up_for_npc_strategy_destroy(self):
        npc_id = "npc_cleanup_2"
        item1 = Item(id="item_cu_n2", guild_id=self.guild_id, template_id="tpl1", owner_id=npc_id, owner_type="Npc")

        self.item_manager.get_items_by_owner = MagicMock(return_value=[item1])
        self.item_manager.remove_item_instance = AsyncMock(return_value=None)

        context = {'cleanup_strategy': 'destroy'}
        await self.item_manager.clean_up_for_npc(self.guild_id, npc_id, context)

        self.item_manager.get_items_by_owner.assert_called_once_with(self.guild_id, npc_id)
        self.item_manager.remove_item_instance.assert_called_once_with(self.guild_id, item1.id)

    async def test_remove_items_by_location_success(self):
        location_id_to_clear = "loc_clear_1"
        item1 = Item(id="item_rem_loc1", guild_id=self.guild_id, template_id="tpl1", location_id=location_id_to_clear)
        item2 = Item(id="item_rem_loc2", guild_id=self.guild_id, template_id="tpl2", location_id=location_id_to_clear)

        # Mock get_items_in_location to return these items
        self.item_manager.get_items_in_location = MagicMock(return_value=[item1, item2])
        # Mock remove_item_instance to verify it's called for each item
        self.item_manager.remove_item_instance = AsyncMock()

        await self.item_manager.remove_items_by_location(self.guild_id, location_id_to_clear)

        self.item_manager.get_items_in_location.assert_called_once_with(self.guild_id, location_id_to_clear)
        expected_remove_calls = [
            call(self.guild_id, item1.id),
            call(self.guild_id, item2.id)
        ]
        self.item_manager.remove_item_instance.assert_has_calls(expected_remove_calls, any_order=True)
        self.assertEqual(self.item_manager.remove_item_instance.call_count, 2)

    async def test_remove_items_by_location_no_items_in_loc(self):
        location_id_empty = "loc_empty_for_clear"
        self.item_manager.get_items_in_location = MagicMock(return_value=[]) # Location is empty
        self.item_manager.remove_item_instance = AsyncMock()

        await self.item_manager.remove_items_by_location(self.guild_id, location_id_empty)

        self.item_manager.get_items_in_location.assert_called_once_with(self.guild_id, location_id_empty)
        self.item_manager.remove_item_instance.assert_not_called()

    async def test_remove_items_by_location_non_existent_location(self):
        # If get_items_in_location returns empty for a non-existent/invalid location_id
        non_existent_loc_id = "loc_does_not_exist_clear"
        self.item_manager.get_items_in_location = MagicMock(return_value=[])
        self.item_manager.remove_item_instance = AsyncMock()

        await self.item_manager.remove_items_by_location(self.guild_id, non_existent_loc_id)

        self.item_manager.get_items_in_location.assert_called_once_with(self.guild_id, non_existent_loc_id)
        self.item_manager.remove_item_instance.assert_not_called()

    async def test_mark_item_dirty_existing_guild_set(self):
        item_id_to_mark = "item_mark_dirty_1"
        self.item_manager._dirty_items[self.guild_id] = set() # Ensure guild's dirty set exists

        self.item_manager.mark_item_dirty(self.guild_id, item_id_to_mark)
        self.assertIn(item_id_to_mark, self.item_manager._dirty_items[self.guild_id])

    async def test_mark_item_dirty_new_guild_set(self):
        new_guild_id_mark = "new_guild_for_dirty_mark"
        item_id_to_mark = "item_mark_dirty_2"
        # _dirty_items does not contain new_guild_id_mark as a key yet

        self.item_manager.mark_item_dirty(new_guild_id_mark, item_id_to_mark)
        self.assertIn(new_guild_id_mark, self.item_manager._dirty_items)
        self.assertIn(item_id_to_mark, self.item_manager._dirty_items[new_guild_id_mark])

    async def test_save_item_new_item_with_owner_and_location(self):
        new_item_id_obj = uuid.uuid4()
        new_item_id = str(new_item_id_obj)
        owner_id = "owner_save_item"
        location_id = "loc_save_item"

        item_to_save = Item(
            id=new_item_id,
            guild_id=self.guild_id,
            template_id=self.template_id_potion,
            quantity=10,
            owner_id=owner_id,
            owner_type="Character",
            location_id=location_id,
            state_variables={"custom_effect": "potent"}
        )
        # Assume item is not yet in any caches, or this method adds/updates it
        self.item_manager._dirty_items[self.guild_id] = {new_item_id} # Mark as dirty to test clearing

        await self.item_manager.save_item(item_to_save)

        self.mock_db_adapter.execute.assert_called_once()
        args, _ = self.mock_db_adapter.execute.call_args
        self.assertIn("REPLACE INTO items", args[0]) # Assuming REPLACE for save_item

        expected_db_params = (
            new_item_id, self.guild_id, self.template_id_potion, 10,
            owner_id, "Character", location_id, '{"custom_effect": "potent"}', True # is_dirty = True
        )
        self.assertEqual(args[1], expected_db_params)

        # Verify caches are updated
        self.assertIn(new_item_id, self.item_manager._items[self.guild_id])
        self.assertEqual(self.item_manager._items[self.guild_id][new_item_id], item_to_save)

        self.assertIn(owner_id, self.item_manager._items_by_owner[self.guild_id])
        self.assertIn(new_item_id, self.item_manager._items_by_owner[self.guild_id][owner_id])

        self.assertIn(location_id, self.item_manager._items_by_location[self.guild_id])
        self.assertIn(new_item_id, self.item_manager._items_by_location[self.guild_id][location_id])

        self.assertNotIn(new_item_id, self.item_manager._dirty_items[self.guild_id]) # Should be cleared from dirty

    async def test_save_item_update_existing_item_change_owner(self):
        existing_item_id = "existing_item_to_update"
        old_owner_id = "old_owner_for_save"
        new_owner_id = "new_owner_for_save"

        existing_item = Item(
            id=existing_item_id, guild_id=self.guild_id, template_id="sword_basic",
            quantity=1, owner_id=old_owner_id, owner_type="Npc"
        )
        # Pre-populate caches as if item already exists
        self.item_manager._items[self.guild_id] = {existing_item_id: existing_item}
        self.item_manager._items_by_owner[self.guild_id] = {old_owner_id: {existing_item_id}}
        self.item_manager._items_by_location[self.guild_id] = {} # Ensure guild key exists
        self.item_manager._dirty_items[self.guild_id] = {existing_item_id}


        # Create a new Item object for the update, or modify existing_item and pass it
        item_to_save = Item(
            id=existing_item_id, guild_id=self.guild_id, template_id="sword_basic", # Same template
            quantity=1, # Quantity could change too
            owner_id=new_owner_id, owner_type="Character", # Owner changed
            location_id=None, # No location
            state_variables=existing_item.state_variables # State can be unchanged or changed
        )

        await self.item_manager.save_item(item_to_save)

        self.mock_db_adapter.execute.assert_called_once()
        # Args check similar to new_item, but with new_owner_id

        # Verify caches updated
        self.assertEqual(self.item_manager._items[self.guild_id][existing_item_id].owner_id, new_owner_id)
        self.assertNotIn(existing_item_id, self.item_manager._items_by_owner[self.guild_id].get(old_owner_id, set()))
        self.assertIn(new_owner_id, self.item_manager._items_by_owner[self.guild_id])
        self.assertIn(existing_item_id, self.item_manager._items_by_owner[self.guild_id][new_owner_id])
        self.assertNotIn(existing_item_id, self.item_manager._dirty_items[self.guild_id])

    async def test_save_item_no_owner_no_location(self):
        item_id_no_assoc = "item_no_assoc"
        item_to_save = Item(id=item_id_no_assoc, guild_id=self.guild_id, template_id=self.template_id_potion, quantity=1)

        self.item_manager._dirty_items[self.guild_id] = {item_id_no_assoc}

        await self.item_manager.save_item(item_to_save)
        self.mock_db_adapter.execute.assert_called_once()
        # DB params should have None for owner_id, owner_type, location_id

        self.assertIn(item_id_no_assoc, self.item_manager._items[self.guild_id])
        # Ensure it's not in owner/location lookup caches if they exist for the guild
        if self.guild_id in self.item_manager._items_by_owner:
            for owner_set in self.item_manager._items_by_owner[self.guild_id].values():
                self.assertNotIn(item_id_no_assoc, owner_set)
        if self.guild_id in self.item_manager._items_by_location:
            for loc_set in self.item_manager._items_by_location[self.guild_id].values():
                self.assertNotIn(item_id_no_assoc, loc_set)
        self.assertNotIn(item_id_no_assoc, self.item_manager._dirty_items[self.guild_id])


if __name__ == '__main__':
    unittest.main()
