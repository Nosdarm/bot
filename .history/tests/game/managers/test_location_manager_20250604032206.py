import asyncio
import unittest
import json
import uuid
from unittest.mock import MagicMock, AsyncMock, patch, call

from bot.game.managers.location_manager import LocationManager
# Assuming LocationManager might need these for its __init__ or for context passing
from bot.game.models.location import Location # Or whatever model it uses for instances/templates

# Dummy data structures for what location instances/templates might look like if needed
# These would typically come from your actual models or be mocked more elaborately.
DUMMY_LOCATION_TEMPLATE_DATA = {
    "id": "tpl_world_center",
    "name": "World Center Template",
    "description": "A template for central locations.",
    "exits": {"north": "tpl_north_region_entrance_id"},
    "on_enter_triggers": [{"action": "log_entry", "message": "Entered World Center area."}],
    "on_exit_triggers": [{"action": "log_exit", "message": "Exited World Center area."}],
    "channel_id": "123456789012345678" 
}

DUMMY_LOCATION_INSTANCE_FROM = {
    "id": "instance_world_center_001",
    "guild_id": "test_guild_1",
    "template_id": "tpl_world_center",
    "name": "World Center Alpha",
    "description": "The bustling heart of the world.",
    "exits": {"north": "instance_north_region_main_001"}, # Points to another instance ID
    "state": {},
    "is_active": True
}
DUMMY_LOCATION_INSTANCE_TO = {
    "id": "instance_north_region_main_001",
    "guild_id": "test_guild_1",
    "template_id": "tpl_north_region_entrance_id", # Assuming a different template
    "name": "North Region Entrance",
    "description": "Gateway to the frosty north.",
    "exits": {"south": "instance_world_center_001"},
    "state": {},
    "is_active": True
}


class TestLocationManagerMoveEntity(unittest.IsolatedAsyncioTestCase): # Renamed class

    def setUp(self):
        # Mock all dependencies for LocationManager's __init__
        self.mock_db_adapter = AsyncMock()
        self.mock_settings = MagicMock()
        self.mock_rule_engine = AsyncMock()
        self.mock_event_manager = AsyncMock()
        # Ensure all managers that can be involved in a move are mocked
        self.mock_character_manager = AsyncMock()
        self.mock_npc_manager = AsyncMock()
        self.mock_item_manager = AsyncMock()
        self.mock_combat_manager = AsyncMock()
        self.mock_status_manager = AsyncMock()
        self.mock_party_manager = AsyncMock()
        self.mock_time_manager = AsyncMock()
        self.mock_send_callback_factory = MagicMock()
        self.mock_event_stage_processor = AsyncMock()
        self.mock_event_action_processor = AsyncMock()
        self.mock_on_enter_action_executor = AsyncMock()
        self.mock_stage_description_generator = AsyncMock()


        self.location_manager = LocationManager(
            db_adapter=self.mock_db_adapter,
            settings=self.mock_settings,
            rule_engine=self.mock_rule_engine,
            event_manager=self.mock_event_manager,
            character_manager=self.mock_character_manager,
            npc_manager=self.mock_npc_manager,
            item_manager=self.mock_item_manager,
            combat_manager=self.mock_combat_manager,
            status_manager=self.mock_status_manager,
            party_manager=self.mock_party_manager,
            time_manager=self.mock_time_manager,
            send_callback_factory=self.mock_send_callback_factory,
            # Pass the other entity managers during LocationManager init
            event_stage_processor=self.mock_event_stage_processor,
            event_action_processor=self.mock_event_action_processor,
            on_enter_action_executor=self.mock_on_enter_action_executor,
            stage_description_generator=self.mock_stage_description_generator
        )

        # Initialize internal caches if methods rely on them being dicts
        self.location_manager._location_templates = {"test_guild_1": {"tpl_world_center": DUMMY_LOCATION_TEMPLATE_DATA.copy(), "tpl_north_region_entrance_id": DUMMY_LOCATION_TEMPLATE_DATA.copy()}} # Simplified
        self.location_manager._location_instances = {"test_guild_1": {DUMMY_LOCATION_INSTANCE_FROM["id"]: DUMMY_LOCATION_INSTANCE_FROM.copy(), DUMMY_LOCATION_INSTANCE_TO["id"]: DUMMY_LOCATION_INSTANCE_TO.copy()}}
        self.location_manager._dirty_instances = {}
        self.location_manager._deleted_instances = {}
        
        self.guild_id = "test_guild_1"
        self.entity_id = "entity_test_1" # Generic ID for testing various types
        self.from_location_id = DUMMY_LOCATION_INSTANCE_FROM["id"]
        self.to_location_id = DUMMY_LOCATION_INSTANCE_TO["id"]

    async def test_successfully_moves_party(self):
        # Setup mocks for this specific test
        self.mock_party_manager.update_party_location = AsyncMock(return_value=True)
        
        # Mock get_location_instance to return our dummy instances
        def get_location_instance_side_effect(guild_id, instance_id):
            if guild_id == self.guild_id:
                if instance_id == self.from_location_id:
                    return DUMMY_LOCATION_INSTANCE_FROM.copy()
                if instance_id == self.to_location_id:
                    return DUMMY_LOCATION_INSTANCE_TO.copy()
            return None
        self.location_manager.get_location_instance = MagicMock(side_effect=get_location_instance_side_effect)

        # Mock get_location_static to return a template with triggers
        # (handle_entity_arrival/departure uses this)
        def get_location_static_side_effect(guild_id, template_id):
            if guild_id == self.guild_id:
                if template_id == DUMMY_LOCATION_INSTANCE_FROM["template_id"]:
                    return self.location_manager._location_templates[guild_id][template_id] #DUMMY_LOCATION_TEMPLATE_DATA.copy()
                if template_id == DUMMY_LOCATION_INSTANCE_TO["template_id"]:
                     return self.location_manager._location_templates[guild_id][template_id] #DUMMY_LOCATION_TEMPLATE_DATA.copy() # Assuming same template for simplicity
            return None
        self.location_manager.get_location_static = MagicMock(side_effect=get_location_static_side_effect)
        
        self.mock_rule_engine.execute_triggers = AsyncMock() # To verify it's called

        # Action
        result = await self.location_manager.move_entity(
            guild_id=self.guild_id,
            entity_id=self.entity_id, # Use generic entity_id
            entity_type="Party",
            from_location_id=self.from_location_id,
            to_location_id=self.to_location_id,
            # Pass necessary managers in kwargs as move_entity expects them
            party_manager=self.mock_party_manager, 
            rule_engine=self.mock_rule_engine 
        )

        # Assertions
        self.assertTrue(result)
        self.mock_party_manager.update_party_location.assert_called_once()
        args, kwargs = self.mock_party_manager.update_party_location.call_args
        self.assertEqual(args[0], self.entity_id) # Check with generic entity_id
        self.assertEqual(args[1], self.to_location_id)
        self.assertEqual(args[2], self.guild_id)
        self.assertIn('context', kwargs) # Check that context dict was passed

        # Verify triggers were called (departure and arrival)
        self.assertEqual(self.mock_rule_engine.execute_triggers.call_count, 2)
        # More specific check for which triggers if needed:
        # call_args_list[0] is first call (departure), call_args_list[1] is second call (arrival)
        departure_trigger_call = self.mock_rule_engine.execute_triggers.call_args_list[0]
        arrival_trigger_call = self.mock_rule_engine.execute_triggers.call_args_list[1]
        
        self.assertEqual(departure_trigger_call.kwargs['context']['location_instance_id'], self.from_location_id)
        self.assertEqual(departure_trigger_call.args[0], DUMMY_LOCATION_TEMPLATE_DATA["on_exit_triggers"])

        self.assertEqual(arrival_trigger_call.kwargs['context']['location_instance_id'], self.to_location_id)
        self.assertEqual(arrival_trigger_call.args[0], DUMMY_LOCATION_TEMPLATE_DATA["on_enter_triggers"])


    async def test_move_party_target_location_not_found(self):
        # Setup: get_location_instance for to_location_id returns None
        def get_location_instance_side_effect(guild_id, instance_id):
            if instance_id == self.from_location_id: return DUMMY_LOCATION_INSTANCE_FROM.copy()
            if instance_id == self.to_location_id: return None # Target not found
            return None
        self.location_manager.get_location_instance = MagicMock(side_effect=get_location_instance_side_effect)
        
        self.mock_party_manager.update_party_location = AsyncMock() # Should not be called

        # Action
        result = await self.location_manager.move_entity(
            guild_id=self.guild_id,
            entity_id=self.entity_id,
            entity_type="Party",
            from_location_id=self.from_location_id,
            to_location_id=self.to_location_id,
            party_manager=self.mock_party_manager
        )

        # Assertions
        self.assertFalse(result)
        self.mock_party_manager.update_party_location.assert_not_called()
        # Ensure send_callback_factory was used to send an error if channel_id was available in kwargs
        # For this, you might need to pass channel_id and send_callback_factory to move_entity call in test
        # and then check if send_callback_factory(channel_id)("error message").called


    async def test_move_party_party_manager_update_fails(self):
        # Setup: party_manager.update_party_location returns False
        self.mock_party_manager.update_party_location = AsyncMock(return_value=False)
        
        # get_location_instance should return valid data for both from and to
        def get_location_instance_side_effect(guild_id, instance_id):
            if instance_id == self.from_location_id: return DUMMY_LOCATION_INSTANCE_FROM.copy()
            if instance_id == self.to_location_id: return DUMMY_LOCATION_INSTANCE_TO.copy()
            return None
        self.location_manager.get_location_instance = MagicMock(side_effect=get_location_instance_side_effect)
        
        # get_location_static for departure handling
        self.location_manager.get_location_static = MagicMock(return_value=DUMMY_LOCATION_TEMPLATE_DATA.copy())
        self.mock_rule_engine.execute_triggers = AsyncMock() # For departure triggers


        # Action
        result = await self.location_manager.move_entity(
            guild_id=self.guild_id,
            entity_id=self.entity_id,
            entity_type="Party",
            from_location_id=self.from_location_id,
            to_location_id=self.to_location_id,
            party_manager=self.mock_party_manager,
            rule_engine=self.mock_rule_engine
        )

        # Assertions
        self.assertFalse(result)
        self.mock_party_manager.update_party_location.assert_called_once() # It was called
        # Departure triggers should still have been called before the update_party_location failure
        self.mock_rule_engine.execute_triggers.assert_called_once() # Only departure, no arrival
        departure_trigger_call = self.mock_rule_engine.execute_triggers.call_args_list[0]
        self.assertEqual(departure_trigger_call.kwargs['context']['location_instance_id'], self.from_location_id)
        self.assertEqual(departure_trigger_call.args[0], DUMMY_LOCATION_TEMPLATE_DATA["on_exit_triggers"])

if __name__ == '__main__':
    unittest.main()


class TestLocationManagerAICreation(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.mock_db_adapter = AsyncMock()
        self.mock_settings = MagicMock() # Basic settings
        self.mock_rule_engine = AsyncMock()
        self.mock_event_manager = AsyncMock()
        self.mock_character_manager = AsyncMock()
        self.mock_npc_manager = AsyncMock()
        self.mock_item_manager = AsyncMock()
        self.mock_combat_manager = AsyncMock()
        self.mock_status_manager = AsyncMock()
        self.mock_party_manager = AsyncMock()
        self.mock_time_manager = AsyncMock()
        self.mock_send_callback_factory = MagicMock()
        self.mock_event_stage_processor = AsyncMock()
        self.mock_event_action_processor = AsyncMock()
        self.mock_on_enter_action_executor = AsyncMock()
        self.mock_stage_description_generator = AsyncMock()

        # AI Mocks
        self.mock_prompt_generator = AsyncMock()
        self.mock_openai_service = AsyncMock()
        self.mock_ai_validator = AsyncMock()

        # Basic instance variables
        self.guild_id = "test_guild_1" # Matching DUMMY_LOCATION_INSTANCE_FROM/TO guild_id
        self.entity_id = "character_for_aic_test"
        self.from_location_id = DUMMY_LOCATION_INSTANCE_FROM["id"]
        self.to_location_id = DUMMY_LOCATION_INSTANCE_TO["id"]

        # Instantiate LocationManager
        self.location_manager = LocationManager(
            db_adapter=self.mock_db_adapter,
            settings=self.mock_settings,
            rule_engine=self.mock_rule_engine,
            event_manager=self.mock_event_manager,
            character_manager=self.mock_character_manager,
            npc_manager=self.mock_npc_manager,
            item_manager=self.mock_item_manager,
            combat_manager=self.mock_combat_manager,
            status_manager=self.mock_status_manager,
            party_manager=self.mock_party_manager,
            time_manager=self.mock_time_manager,
            send_callback_factory=self.mock_send_callback_factory,
            event_stage_processor=self.mock_event_stage_processor,
            event_action_processor=self.mock_event_action_processor,
            on_enter_action_executor=self.mock_on_enter_action_executor,
            stage_description_generator=self.mock_stage_description_generator
            # AI mocks (multilingual_prompt_generator, openai_service, ai_validator) are not passed
            # to LocationManager constructor based on current understanding of its __init__.
            # Tests requiring these will set them directly on the manager instance if needed.
        )

        # Initialize LocationManager's internal caches
        # Using DUMMY_LOCATION_INSTANCE_TO["template_id"] for the second template for simplicity
        # Ensure this template_id is different from DUMMY_LOCATION_TEMPLATE_DATA["id"] if specific data matters
        # For now, just copying DUMMY_LOCATION_TEMPLATE_DATA for both.
        tpl_north_region_entrance_id = DUMMY_LOCATION_INSTANCE_TO["template_id"]
        template_data_north = DUMMY_LOCATION_TEMPLATE_DATA.copy()
        template_data_north["id"] = tpl_north_region_entrance_id # Ensure the ID is correct

        self.location_manager._location_templates = {
            self.guild_id: {
                DUMMY_LOCATION_TEMPLATE_DATA["id"]: DUMMY_LOCATION_TEMPLATE_DATA.copy(),
                tpl_north_region_entrance_id: template_data_north
            }
        }
        self.location_manager._location_instances = {
            self.guild_id: {
                DUMMY_LOCATION_INSTANCE_FROM["id"]: DUMMY_LOCATION_INSTANCE_FROM.copy(),
                DUMMY_LOCATION_INSTANCE_TO["id"]: DUMMY_LOCATION_INSTANCE_TO.copy()
            }
        }
        self.location_manager._dirty_instances = {}
        self.location_manager._deleted_instances = {}

    async def test_successfully_moves_character(self):
        # Similar to test_successfully_moves_party, but for Character
        self.mock_character_manager.update_character_location = AsyncMock(return_value=True)

        # Mocks for get_location_instance and get_location_static are important.
        # The side_effect functions will use the self.location_manager instance
        # whose caches were populated in asyncSetUp.
        def get_location_instance_side_effect(guild_id, instance_id):
            if guild_id == self.guild_id:
                return self.location_manager._location_instances[guild_id].get(instance_id)
            return None
        self.location_manager.get_location_instance = MagicMock(side_effect=get_location_instance_side_effect)

        def get_location_static_side_effect(guild_id, template_id):
            if guild_id == self.guild_id:
                return self.location_manager._location_templates[guild_id].get(template_id)
            return None
        self.location_manager.get_location_static = MagicMock(side_effect=get_location_static_side_effect)
        
        self.mock_rule_engine.execute_triggers = AsyncMock()

        result = await self.location_manager.move_entity(
            guild_id=self.guild_id,
            entity_id=self.entity_id, 
            entity_type="Character",
            from_location_id=self.from_location_id,
            to_location_id=self.to_location_id,
            character_manager=self.mock_character_manager, 
            rule_engine=self.mock_rule_engine
        )
        self.assertTrue(result)
        self.mock_character_manager.update_character_location.assert_called_once_with(
            self.guild_id,
            self.entity_id,
            self.to_location_id,
            context=unittest.mock.ANY # Updated assertion
        )
        self.assertEqual(self.mock_rule_engine.execute_triggers.call_count, 2) # Departure and arrival

    async def test_move_entity_missing_manager_in_kwargs(self):
        self.location_manager.get_location_instance = MagicMock(
            side_effect=lambda gid, iid: DUMMY_LOCATION_INSTANCE_FROM.copy() if iid == self.from_location_id else (DUMMY_LOCATION_INSTANCE_TO.copy() if iid == self.to_location_id else None)
        )
        self.location_manager.get_location_static = MagicMock(
            side_effect=lambda gid, tid: self.location_manager._location_templates[gid].get(tid)
        )
        self.mock_rule_engine.execute_triggers = AsyncMock() # For departure call

        # Attempt to move a "CustomEntity" for which no manager is passed in kwargs
        result = await self.location_manager.move_entity(
            guild_id=self.guild_id,
            entity_id="custom_entity_1",
            entity_type="CustomEntity", # Unknown type
            from_location_id=self.from_location_id,
            to_location_id=self.to_location_id,
            rule_engine=self.mock_rule_engine
            # Missing custom_entity_manager in kwargs
        )
        self.assertFalse(result)
        # Departure triggers should have been called as from_location was valid
        self.mock_rule_engine.execute_triggers.assert_called_once()
        # No update method on any manager should be called for CustomEntity
        self.mock_character_manager.update_character_location.assert_not_called()
        self.mock_party_manager.update_party_location.assert_not_called()
        # Assuming NpcManager might have update_npc_location, ensure it's not called
        if hasattr(self.mock_npc_manager, 'update_npc_location'):
            self.mock_npc_manager.update_npc_location.assert_not_called()


    async def test_move_entity_manager_lacks_update_method(self):
        # Mock a manager that exists but doesn't have the 'update_{entity_type}_location' method
        mock_faulty_manager = MagicMock() # Lacks update_faulty_entity_location
        # Remove the method if it accidentally exists due to MagicMock's nature
        if hasattr(mock_faulty_manager, 'update_faultyentity_location'):
            del mock_faulty_manager.update_faultyentity_location

        self.location_manager.get_location_instance = MagicMock(
            side_effect=lambda gid, iid: DUMMY_LOCATION_INSTANCE_FROM.copy() if iid == self.from_location_id else (DUMMY_LOCATION_INSTANCE_TO.copy() if iid == self.to_location_id else None)
        )
        self.location_manager.get_location_static = MagicMock(
            side_effect=lambda gid, tid: self.location_manager._location_templates[gid].get(tid)
        )
        self.mock_rule_engine.execute_triggers = AsyncMock()

        result = await self.location_manager.move_entity(
            guild_id=self.guild_id,
            entity_id="faulty_entity_1",
            entity_type="FaultyEntity",
            from_location_id=self.from_location_id,
            to_location_id=self.to_location_id,
            faulty_entity_manager=mock_faulty_manager, # Pass the faulty manager
            rule_engine=self.mock_rule_engine
        )
        self.assertFalse(result)
        self.mock_rule_engine.execute_triggers.assert_called_once() # Departure triggers only

    async def test_successfully_moves_npc(self):
        self.mock_npc_manager.update_npc_location = AsyncMock(return_value=True)
        self.location_manager.get_location_instance = MagicMock(
            side_effect=lambda gid, iid: DUMMY_LOCATION_INSTANCE_FROM.copy() if iid == self.from_location_id else (DUMMY_LOCATION_INSTANCE_TO.copy() if iid == self.to_location_id else None)
        )
        self.location_manager.get_location_static = MagicMock(
            side_effect=lambda gid, tid: self.location_manager._location_templates[gid].get(tid)
        )
        self.mock_rule_engine.execute_triggers = AsyncMock()

        result = await self.location_manager.move_entity(
            guild_id=self.guild_id,
            entity_id=self.entity_id,
            entity_type="Npc",
            from_location_id=self.from_location_id,
            to_location_id=self.to_location_id,
            npc_manager=self.mock_npc_manager,
            rule_engine=self.mock_rule_engine
        )
        self.assertTrue(result)
        self.mock_npc_manager.update_npc_location.assert_called_once_with(
            self.guild_id, self.entity_id, self.to_location_id
        )
        self.assertEqual(self.mock_rule_engine.execute_triggers.call_count, 2)

    async def test_successfully_moves_item(self):
        # This assumes ItemManager has an update_item_location method.
        # The concept of "moving an item" might be different (e.g., changing container_id, owner_id etc.)
        # Adjust based on actual ItemManager capabilities.
        self.mock_item_manager.update_item_location = AsyncMock(return_value=True)
        self.location_manager.get_location_instance = MagicMock(
            side_effect=lambda gid, iid: DUMMY_LOCATION_INSTANCE_FROM.copy() if iid == self.from_location_id else (DUMMY_LOCATION_INSTANCE_TO.copy() if iid == self.to_location_id else None)
        )
        self.location_manager.get_location_static = MagicMock(
            side_effect=lambda gid, tid: self.location_manager._location_templates[gid].get(tid)
        )
        self.mock_rule_engine.execute_triggers = AsyncMock()

        result = await self.location_manager.move_entity(
            guild_id=self.guild_id,
            entity_id=self.entity_id,
            entity_type="Item",
            from_location_id=self.from_location_id,
            to_location_id=self.to_location_id,
            item_manager=self.mock_item_manager,
            rule_engine=self.mock_rule_engine
        )
        self.assertTrue(result)
        self.mock_item_manager.update_item_location.assert_called_once_with(
            self.guild_id, self.entity_id, self.to_location_id
        )
        self.assertEqual(self.mock_rule_engine.execute_triggers.call_count, 2)

    async def test_move_entity_no_from_location(self):
        # Test arrival triggers only, no departure
        self.mock_character_manager.update_character_location = AsyncMock(return_value=True)
        self.location_manager.get_location_instance = MagicMock(
            # Only to_location needs to exist
            side_effect=lambda gid, iid: DUMMY_LOCATION_INSTANCE_TO.copy() if iid == self.to_location_id else None
        )
        self.location_manager.get_location_static = MagicMock(
             # Only for arrival location template
            side_effect=lambda gid, tid: self.location_manager._location_templates[gid].get(DUMMY_LOCATION_INSTANCE_TO["template_id"]) if tid == DUMMY_LOCATION_INSTANCE_TO["template_id"] else None
        )
        self.mock_rule_engine.execute_triggers = AsyncMock()

        result = await self.location_manager.move_entity(
            guild_id=self.guild_id,
            entity_id=self.entity_id,
            entity_type="Character",
            from_location_id=None, # No departure
            to_location_id=self.to_location_id,
            character_manager=self.mock_character_manager,
            rule_engine=self.mock_rule_engine
        )
        self.assertTrue(result)
        self.mock_character_manager.update_character_location.assert_called_once()
        # Only arrival triggers should be called
        self.mock_rule_engine.execute_triggers.assert_called_once()
        arrival_trigger_call = self.mock_rule_engine.execute_triggers.call_args_list[0]
        self.assertEqual(arrival_trigger_call.kwargs['context']['location_instance_id'], self.to_location_id)
        self.assertEqual(arrival_trigger_call.args[0], DUMMY_LOCATION_TEMPLATE_DATA["on_enter_triggers"])


class TestLocationManagerTriggerHandling(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mock_rule_engine = AsyncMock()
        self.location_manager = LocationManager(
            db_adapter=AsyncMock(), settings=MagicMock(), rule_engine=self.mock_rule_engine,
            event_manager=AsyncMock(), character_manager=AsyncMock(),npc_manager=AsyncMock(),
            item_manager=AsyncMock(),combat_manager=AsyncMock(),status_manager=AsyncMock(),
            party_manager=AsyncMock(),time_manager=AsyncMock(),send_callback_factory=MagicMock(),
            event_stage_processor=AsyncMock(), event_action_processor=AsyncMock(),
            on_enter_action_executor=AsyncMock(),stage_description_generator=AsyncMock()
        )
        self.guild_id = "trigger_guild"
        self.entity_id = "triggered_entity"
        self.location_instance_id = "loc_inst_triggers"
        self.template_id = "tpl_with_triggers"

        self.location_template_data = {
            "id": self.template_id,
            "name": "Trigger Template",
            "on_enter_triggers": [{"action": "log", "message": "Entity Entered"}],
            "on_exit_triggers": [{"action": "event", "event_id": "e_exit"}]
        }
        self.location_instance_data = {
            "id": self.location_instance_id,
            "template_id": self.template_id,
            "name": "Trigger Instance"
        }
        # Pre-populate internal caches for the manager
        self.location_manager._location_templates = {self.guild_id: {self.template_id: self.location_template_data}}
        self.location_manager._location_instances = {self.guild_id: {self.location_instance_id: self.location_instance_data}}


    async def test_handle_entity_arrival_success(self):
        context = {"entity_id": self.entity_id, "entity_type": "Character"}

        await self.location_manager.handle_entity_arrival(
            self.guild_id, self.entity_id, "Character", self.location_instance_id, context
        )

        self.mock_rule_engine.execute_triggers.assert_called_once_with(
            self.location_template_data["on_enter_triggers"],
            guild_id=self.guild_id,
            context=context # Ensure context is passed through
        )
        # Verify context was augmented
        self.assertEqual(context["location_instance_id"], self.location_instance_id)
        self.assertEqual(context["location_template_id"], self.template_id)


    async def test_handle_entity_departure_success(self):
        context = {"entity_id": self.entity_id, "entity_type": "Party"}

        await self.location_manager.handle_entity_departure(
            self.guild_id, self.entity_id, "Party", self.location_instance_id, context
        )

        self.mock_rule_engine.execute_triggers.assert_called_once_with(
            self.location_template_data["on_exit_triggers"],
            guild_id=self.guild_id,
            context=context
        )
        self.assertEqual(context["location_instance_id"], self.location_instance_id)
        self.assertEqual(context["location_template_id"], self.template_id)

    async def test_handle_entity_arrival_no_template(self):
        # Instance exists, but its template doesn't (data integrity issue or mid-load)
        self.location_manager._location_templates[self.guild_id] = {} # Clear templates
        context = {"entity_id": self.entity_id}

        await self.location_manager.handle_entity_arrival(
            self.guild_id, self.entity_id, "Character", self.location_instance_id, context
        )
        self.mock_rule_engine.execute_triggers.assert_not_called()

    async def test_handle_entity_arrival_no_on_enter_triggers(self):
        # Template exists, but has no on_enter_triggers
        template_no_triggers = self.location_template_data.copy()
        del template_no_triggers["on_enter_triggers"] # Or set to [] or None
        self.location_manager._location_templates[self.guild_id][self.template_id] = template_no_triggers
        context = {"entity_id": self.entity_id}

        await self.location_manager.handle_entity_arrival(
            self.guild_id, self.entity_id, "Character", self.location_instance_id, context
        )
        self.mock_rule_engine.execute_triggers.assert_not_called() # Or called with empty list

    async def test_handle_entity_departure_no_on_exit_triggers(self):
        template_no_triggers = self.location_template_data.copy()
        template_no_triggers["on_exit_triggers"] = [] # Empty list
        self.location_manager._location_templates[self.guild_id][self.template_id] = template_no_triggers
        context = {"entity_id": self.entity_id}

        await self.location_manager.handle_entity_departure(
            self.guild_id, self.entity_id, "Character", self.location_instance_id, context
        )
        # Depending on implementation, execute_triggers might be called with an empty list, or not at all.
        # If it's called with an empty list, the mock should reflect that.
        # Assuming if triggers are empty/None, it doesn't call.
        self.mock_rule_engine.execute_triggers.assert_not_called()

    async def test_handle_entity_arrival_instance_not_found(self):
        context = {"entity_id": self.entity_id}
        await self.location_manager.handle_entity_arrival(
            self.guild_id, self.entity_id, "Character", "non_existent_instance", context
        )
        self.mock_rule_engine.execute_triggers.assert_not_called()


class TestLocationManager(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mock_db_adapter = AsyncMock()
        self.mock_settings = MagicMock() # Using MagicMock for easier attribute access like self.mock_settings.guilds
        self.mock_rule_engine = AsyncMock()
        # Initialize all mock managers that LocationManager depends on
        self.mock_event_manager = AsyncMock()
        self.mock_character_manager = AsyncMock()
        self.mock_npc_manager = AsyncMock()
        self.mock_item_manager = AsyncMock()
        self.mock_combat_manager = AsyncMock()
        self.mock_status_manager = AsyncMock()
        self.mock_party_manager = AsyncMock()
        self.mock_time_manager = AsyncMock()
        self.mock_send_callback_factory = MagicMock()
        self.mock_event_stage_processor = AsyncMock()
        self.mock_event_action_processor = AsyncMock()
        self.mock_on_enter_action_executor = AsyncMock()
        self.mock_stage_description_generator = AsyncMock()
        self.mock_prompt_generator = AsyncMock()  # AI related mock
        self.mock_openai_service = AsyncMock()    # AI related mock
        self.mock_ai_validator = AsyncMock()      # AI related mock

        self.guild_id = "test_guild_1" # Added guild_id initialization

        self.location_manager = LocationManager(
            db_adapter=self.mock_db_adapter,
            settings=self.mock_settings,
            rule_engine=self.mock_rule_engine,
            event_manager=self.mock_event_manager,
            character_manager=self.mock_character_manager,
            npc_manager=self.mock_npc_manager,
            item_manager=self.mock_item_manager,
            combat_manager=self.mock_combat_manager,
            status_manager=self.mock_status_manager,
            party_manager=self.mock_party_manager,
            time_manager=self.mock_time_manager,
            send_callback_factory=self.mock_send_callback_factory,
            event_stage_processor=self.mock_event_stage_processor,
            event_action_processor=self.mock_event_action_processor,
            on_enter_action_executor=self.mock_on_enter_action_executor,
            stage_description_generator=self.mock_stage_description_generator,
            multilingual_prompt_generator=self.mock_prompt_generator,
            openai_service=self.mock_openai_service,
            ai_validator=self.mock_ai_validator
        )

        # Initialize caches for testing purposes, assuming they are dicts
        self.location_manager._location_templates = {}
        self.location_manager._location_instances = {}
        self.location_manager._dirty_instances = {}
        self.location_manager._deleted_instances = {}
        self.location_manager._dirty_templates = {} # Initialize _dirty_templates

    async def test_create_location_instance_ai_pending_moderation(self):
        guild_id = "test_guild_loc_ai_success"
        template_id_arg = "AI:generate_haunted_mansion"
        user_id = "test_user_loc_mod"
        mock_validated_loc_data = {
            "name_i18n": {"en": "AI Haunted Mansion"},
            "description_i18n": {"en": "A spooky place."},
            "exits": {}, "state_variables": {}
        }

        self.location_manager.generate_location_details_from_ai = AsyncMock(return_value=mock_validated_loc_data)

        expected_request_id = str(uuid.uuid4())
        with patch('uuid.uuid4', return_value=uuid.UUID(expected_request_id)):
            result = await self.location_manager.create_location_instance(
                guild_id, template_id_arg, user_id=user_id
            )

        self.assertEqual(result, {"status": "pending_moderation", "request_id": expected_request_id})
        self.mock_db_adapter.save_pending_moderation_request.assert_called_once()
        call_args = self.mock_db_adapter.save_pending_moderation_request.call_args[0]
        self.assertEqual(call_args[0], expected_request_id)
        self.assertEqual(call_args[1], guild_id)
        self.assertEqual(call_args[2], user_id)
        self.assertEqual(call_args[3], "location")
        self.assertEqual(json.loads(call_args[4]), mock_validated_loc_data)

    async def test_create_location_instance_ai_generation_fails(self):
        guild_id = "test_guild_loc_ai_fail"
        template_id_arg = "AI:generate_failed_dungeon"
        user_id = "test_user_loc_fail"

        self.location_manager.generate_location_details_from_ai = AsyncMock(return_value=None)

        result = await self.location_manager.create_location_instance(
            guild_id, template_id_arg, user_id=user_id
        )
        self.assertIsNone(result)
        self.mock_db_adapter.save_pending_moderation_request.assert_not_called()

    async def test_create_location_instance_ai_no_user_id(self):
        guild_id = "test_guild_loc_ai_no_user"
        template_id_arg = "AI:generate_secret_cave"
        mock_validated_data = {"name_i18n": {"en": "Secret Cave AI"}}
        self.location_manager.generate_location_details_from_ai = AsyncMock(return_value=mock_validated_data)

        result = await self.location_manager.create_location_instance(
            guild_id, template_id_arg # No user_id
        )
        self.assertIsNone(result)
        self.mock_db_adapter.save_pending_moderation_request.assert_not_called()

    async def test_create_location_instance_non_ai_from_template(self):
        guild_id = "test_guild_loc_template"
        template_id = "market_square"

        # Setup LocationManager's internal template cache
        self.location_manager._location_templates[guild_id] = {
            template_id: {
                "id": template_id, "name": "Market Square", "description": "A bustling square.",
                "exits": {}, "initial_state": {}
            }
        }

        result = await self.location_manager.create_location_instance(guild_id, template_id)

        self.assertIsNotNone(result)
        self.assertIsInstance(result, dict)
        self.assertNotIn("status", result) # Should be the location instance data
        self.assertEqual(result["template_id"], template_id)
        self.assertTrue(result["id"] is not None and result["id"] != template_id)
        self.mock_db_adapter.save_pending_moderation_request.assert_not_called()
        self.assertIn(result["id"], self.location_manager._dirty_instances.get(guild_id, set()))

    async def test_generate_location_details_from_ai_success(self):
        guild_id = "test_guild_gen_loc_success"
        location_idea = "a serene crystal cave"
        expected_data = {"name_i18n": {"en": "Crystal Cave"}, "description_i18n": {"en": "Shimmers with light."}}

        self.mock_prompt_generator.generate_location_description_prompt.return_value = {"system": "sys", "user": "usr"}
        self.mock_openai_service.generate_structured_multilingual_content = AsyncMock(return_value={"json_string": json.dumps(expected_data)})
        self.mock_ai_validator.validate_ai_response = AsyncMock(return_value={
            "overall_status": "success",
            "entities": [{"validated_data": expected_data}]
        })

        result = await self.location_manager.generate_location_details_from_ai(guild_id, location_idea)
        self.assertEqual(result, expected_data)

    async def test_generate_location_details_from_ai_openai_fails(self):
        self.mock_prompt_generator.generate_location_description_prompt.return_value = {"system": "sys", "user": "usr"}
        self.mock_openai_service.generate_structured_multilingual_content = AsyncMock(return_value={"error": "OpenAI down"})

        result = await self.location_manager.generate_location_details_from_ai("gid_loc_openai_fail", "concept")
        self.assertIsNone(result)

    async def test_generate_location_details_from_ai_validator_fails(self):
        self.mock_prompt_generator.generate_location_description_prompt.return_value = {"system": "sys", "user": "usr"}
        self.mock_openai_service.generate_structured_multilingual_content = AsyncMock(return_value={"json_string": "{}"})
        self.mock_ai_validator.validate_ai_response = AsyncMock(return_value={"global_errors": ["validation failed"]})

        result = await self.location_manager.generate_location_details_from_ai("gid_loc_val_fail", "concept")
        self.assertIsNone(result)

    async def test_generate_location_details_from_ai_validator_requires_moderation(self):
        self.mock_prompt_generator.generate_location_description_prompt.return_value = {"system": "sys", "user": "usr"}
        self.mock_openai_service.generate_structured_multilingual_content = AsyncMock(return_value={"json_string": "{}"})
        self.mock_ai_validator.validate_ai_response = AsyncMock(return_value={
            "overall_status": "requires_manual_review",
            "entities": [{"validated_data": {"name":"Needs Review Loc"}, "requires_moderation": True}]
        })
        result = await self.location_manager.generate_location_details_from_ai("gid_loc_val_mod", "concept")
        self.assertIsNone(result) # Current design returns None if validator says requires_moderation

    async def test_create_location_instance_from_moderated_data(self):
        """Test creating a location instance from moderated, pre-validated data."""
        guild_id = "test_guild_mod_loc"
        user_id = "test_user_loc_creator" # For add_generated_location

        moderated_loc_data = {
            "id": str(uuid.uuid4()), # ID might be pre-assigned
            "name_i18n": {"en": "Approved Serene Cave"},
            "description_i18n": {"en": "A beautiful cave, now approved."},
            "exits": {"out": "world_map_01"},
            "state_variables": {"crystals_mined_today": 0},
            "template_id": "ai_cave_template_xyz"
        }
        context_data = {"some_other_context": "value"}

        # The method being tested
        activated_loc_data = await self.location_manager.create_location_instance_from_moderated_data(
            guild_id, moderated_loc_data, user_id, context_data
        )

        self.assertIsNotNone(activated_loc_data)
        self.assertIsInstance(activated_loc_data, dict)
        self.assertEqual(activated_loc_data["id"], moderated_loc_data["id"])
        self.assertEqual(activated_loc_data["name_i18n"]["en"], "Approved Serene Cave")
        self.assertEqual(activated_loc_data["state"]["crystals_mined_today"], 0)

        # Check if instance is in cache and marked dirty
        self.assertIn(activated_loc_data["id"], self.location_manager._location_instances.get(guild_id, {}))
        self.assertIn(activated_loc_data["id"], self.location_manager._dirty_instances.get(guild_id, set()))

        # Verify add_generated_location was called
        self.mock_db_adapter.add_generated_location.assert_called_once_with(
            activated_loc_data["id"], guild_id, user_id
        )

        # Verify no AI services were called
        self.mock_prompt_generator.generate_location_description_prompt.assert_not_called()
        self.mock_openai_service.generate_structured_multilingual_content.assert_not_called()
        self.mock_ai_validator.validate_ai_response.assert_not_called()
        self.mock_db_adapter.save_pending_moderation_request.assert_not_called()


# This ensures if the file is run directly, tests from both classes are executed.
# However, typically you'd run tests with `python -m unittest discover` or similar.
if __name__ == '__main__':
    unittest.main()

    async def test_init_manager(self):
        self.assertEqual(self.location_manager._db_adapter, self.mock_db_adapter)
        self.assertEqual(self.location_manager._settings, self.mock_settings)
        self.assertEqual(self.location_manager._rule_engine, self.mock_rule_engine)
        self.assertIsNotNone(self.location_manager._event_manager)
        # ... assert other managers are set
        self.assertEqual(self.location_manager._location_templates, {})
        self.assertEqual(self.location_manager._location_instances, {})
        self.assertEqual(self.location_manager._dirty_instances, {})
        self.assertEqual(self.location_manager._deleted_instances, {})

    async def test_load_state_success(self):
        guild_id = self.guild_id

        # Mock data for location templates
        db_template_data = [
            ("tpl1", guild_id, "Template1", "Desc1", '{"key": "value"}', '{"north": "tpl2"}',
             '{"var1": 10}', '["trigger_on_enter"]', '["trigger_on_exit"]',
             '["action1"]', '["item_id_1"]', "channel1", False, 1),
            ("tpl2", guild_id, "Template2", "Desc2", '{}', '{}', '{}', '[]', '[]', '[]', '[]', "channel2", True, 2)
        ]
        # Mock data for location instances
        db_instance_data = [
            ("inst1", guild_id, "tpl1", "Instance1", "InstDesc1",
             '{"east": "inst2"}', '{"inst_var": "abc"}', True, False, 3),
            ("inst2", guild_id, "tpl2", "Instance2", "InstDesc2",
             '{}', '{}', False, True, 4)
        ]

        self.mock_db_adapter.fetchall.side_effect = [db_template_data, db_instance_data]

        # Pre-populate caches to ensure they are cleared for the guild
        self.location_manager._location_templates[guild_id] = {"old_tpl": {}}
        self.location_manager._location_instances[guild_id] = {"old_inst": {}}
        self.location_manager._dirty_instances[guild_id] = {"old_inst"}
        self.location_manager._deleted_instances[guild_id] = {"old_deleted_inst"}

        await self.location_manager.load_state(guild_id)

        # Check fetchall calls
        expected_calls = [
            call("SELECT id, guild_id, name, description, properties, exits, initial_state, on_enter_triggers, on_exit_triggers, available_actions, items, channel_id, is_template_dirty, _rowid_ FROM location_templates WHERE guild_id = ?", (guild_id,)),
            call("SELECT id, guild_id, template_id, name, description, exits, state_variables, is_active, is_dirty, _rowid_ FROM location_instances WHERE guild_id = ?", (guild_id,))
        ]
        self.mock_db_adapter.fetchall.assert_has_calls(expected_calls)

        # Verify templates cache
        self.assertIn(guild_id, self.location_manager._location_templates)
        self.assertEqual(len(self.location_manager._location_templates[guild_id]), 2)
        self.assertIn("tpl1", self.location_manager._location_templates[guild_id])
        self.assertEqual(self.location_manager._location_templates[guild_id]["tpl1"]["name"], "Template1")
        self.assertEqual(self.location_manager._location_templates[guild_id]["tpl1"]["properties"], {"key": "value"})
        self.assertEqual(self.location_manager._location_templates[guild_id]["tpl2"]["is_template_dirty"], True)


        # Verify instances cache
        self.assertIn(guild_id, self.location_manager._location_instances)
        self.assertEqual(len(self.location_manager._location_instances[guild_id]), 2)
        self.assertIn("inst1", self.location_manager._location_instances[guild_id])
        self.assertEqual(self.location_manager._location_instances[guild_id]["inst1"]["name"], "Instance1")
        self.assertEqual(self.location_manager._location_instances[guild_id]["inst1"]["exits"], {"east": "inst2"})
        self.assertEqual(self.location_manager._location_instances[guild_id]["inst1"]["state_variables"], {"inst_var": "abc"})
        self.assertEqual(self.location_manager._location_instances[guild_id]["inst2"]["is_dirty"], True) # is_dirty flag from DB

        # Verify dirty/deleted lists are cleared for the guild
        self.assertEqual(self.location_manager._dirty_instances.get(guild_id, set()), set())
        self.assertEqual(self.location_manager._deleted_instances.get(guild_id, set()), set())

    async def test_load_state_no_data(self):
        guild_id = self.guild_id
        self.mock_db_adapter.fetchall.side_effect = [[], []] # No templates, no instances

        # Pre-populate to ensure clearing
        self.location_manager._location_templates[guild_id] = {"old_tpl": {}}
        self.location_manager._location_instances[guild_id] = {"old_inst": {}}

        await self.location_manager.load_state(guild_id)

        self.assertNotIn(guild_id, self.location_manager._location_templates)
        self.assertNotIn(guild_id, self.location_manager._location_instances)

    async def test_load_state_malformed_json(self):
        guild_id = self.guild_id
        # Malformed JSON in properties for template
        db_template_data = [
            ("tpl_err", guild_id, "ErrTemplate", "Desc", "{'bad_json':}", '{}', '{}', '[]', '[]', '[]', '[]', "chan_err", False, 1)
        ]
        db_instance_data = [
            ("inst_err", guild_id, "tpl_err", "ErrInstance", "Desc", "{'bad_exit_json':}", '{}', True, False, 2)
        ]
        self.mock_db_adapter.fetchall.side_effect = [db_template_data, db_instance_data]

        with self.assertLogs(level='ERROR') as log:
            await self.location_manager.load_state(guild_id)
            # Expect at least two errors, one for template properties, one for instance exits
            self.assertTrue(sum("Failed to parse JSON" in message for message in log.output) >= 2)

        # Check that templates/instances might be loaded with default for bad JSON fields
        self.assertIn("tpl_err", self.location_manager._location_templates[guild_id])
        self.assertEqual(self.location_manager._location_templates[guild_id]["tpl_err"]["properties"], {}) # Default

        self.assertIn("inst_err", self.location_manager._location_instances[guild_id])
        self.assertEqual(self.location_manager._location_instances[guild_id]["inst_err"]["exits"], {}) # Default

    async def test_save_state_dirty_instances(self):
        guild_id = self.guild_id
        inst1_id = "inst_dirty1"
        inst2_id = "inst_dirty2"

        # Create Location model instances or use dicts if manager internally converts
        # For this test, assume LocationManager works with dicts internally for instances before saving
        inst1_data = {
            "id": inst1_id, "guild_id": guild_id, "template_id": "tpl1", "name": "Dirty Instance 1",
            "description": "Desc", "exits": '{"north": "some_other_inst"}',  # JSON string
            "state_variables": '{"key": "val"}', # JSON string
            "is_active": True, "is_dirty": True # is_dirty is internal to manager, not directly saved as a bool column like this
        }
        inst2_data = {
            "id": inst2_id, "guild_id": guild_id, "template_id": "tpl2", "name": "Dirty Instance 2",
            "description": "Desc2", "exits": '{}', "state_variables": '{}', "is_active": False
        }

        self.location_manager._location_instances[guild_id] = {
            inst1_id: inst1_data,
            inst2_id: inst2_data
        }
        self.location_manager._dirty_instances[guild_id] = {inst1_id, inst2_id}
        self.location_manager._deleted_instances[guild_id] = set()

        await self.location_manager.save_state(guild_id)

        self.mock_db_adapter.execute_many.assert_called_once()
        args, _ = self.mock_db_adapter.execute_many.call_args
        self.assertIn("REPLACE INTO location_instances", args[0])

        expected_db_data = [
            (inst1_data["id"], guild_id, inst1_data["template_id"], inst1_data["name"], inst1_data["description"],
             inst1_data["exits"], inst1_data["state_variables"], inst1_data["is_active"]),
            (inst2_data["id"], guild_id, inst2_data["template_id"], inst2_data["name"], inst2_data["description"],
             inst2_data["exits"], inst2_data["state_variables"], inst2_data["is_active"]),
        ]
        self.assertCountEqual(args[1], expected_db_data)
        self.assertEqual(self.location_manager._dirty_instances.get(guild_id, set()), set()) # Should be cleared
        self.assertEqual(self.location_manager._deleted_instances.get(guild_id, set()), set()) # Should remain empty

    async def test_save_state_deleted_instances(self):
        guild_id = self.guild_id
        deleted_id1 = "del_inst1"
        deleted_id2 = "del_inst2"

        self.location_manager._deleted_instances[guild_id] = {deleted_id1, deleted_id2}
        self.location_manager._dirty_instances[guild_id] = set()
        # Instances would have already been removed from _location_instances cache by delete_location_instance

        await self.location_manager.save_state(guild_id)

        self.mock_db_adapter.execute.assert_called_once()
        args, _ = self.mock_db_adapter.execute.call_args
        # The actual query might vary based on how many placeholders are generated
        # For example, for two items: "DELETE FROM location_instances WHERE guild_id = ? AND id IN (?, ?)"
        self.assertIn("DELETE FROM location_instances WHERE guild_id = ? AND id IN", args[0])
        self.assertEqual(args[1][0], guild_id) # First param is guild_id
        self.assertCountEqual(list(args[1][1:]), [deleted_id1, deleted_id2]) # Corrected: check all IDs

        self.assertEqual(self.location_manager._deleted_instances.get(guild_id, set()), set()) # Should be cleared

    async def test_save_state_no_changes(self):
        guild_id = self.guild_id
        self.location_manager._dirty_instances[guild_id] = set()
        self.location_manager._deleted_instances[guild_id] = set()

        await self.location_manager.save_state(guild_id)

        self.mock_db_adapter.execute_many.assert_not_called()
        self.mock_db_adapter.execute.assert_not_called()
        self.assertEqual(self.location_manager._dirty_instances.get(guild_id, set()), set())
        self.assertEqual(self.location_manager._deleted_instances.get(guild_id, set()), set())

    async def test_save_state_guild_not_loaded_previously(self):
        guild_id = "new_guild_save"
        # No pre-existing entries for this guild_id in caches

        await self.location_manager.save_state(guild_id)
        self.mock_db_adapter.execute_many.assert_not_called()
        self.mock_db_adapter.execute.assert_not_called()
        # Caches should not be created for this guild if there was nothing to save
        self.assertEqual(self.location_manager._dirty_instances.get(guild_id, set()), set())
        self.assertEqual(self.location_manager._deleted_instances.get(guild_id, set()), set())

    async def test_get_default_location_id_guild_specific_exists(self):
        guild_id = self.guild_id
        default_loc_id_guild = "guild_default_spawn"
        self.mock_settings.get_guild_setting = MagicMock(return_value=default_loc_id_guild)
        # Assume the location instance exists for this test
        self.location_manager._location_instances[guild_id] = {default_loc_id_guild: {"id": default_loc_id_guild, "name": "Guild Spawn"}}

        ret_id = await self.location_manager.get_default_location_id(guild_id)
        self.assertEqual(ret_id, default_loc_id_guild)
        self.mock_settings.get_guild_setting.assert_called_once_with(guild_id, "default_location_id")

    async def test_get_default_location_id_global_exists(self):
        guild_id = "guild_no_specific_default"
        default_loc_id_global = "global_default_spawn"
        # Guild specific returns None, global returns the ID
        self.mock_settings.get_guild_setting = MagicMock(return_value=None)
        self.mock_settings.get_setting = MagicMock(return_value=default_loc_id_global)
        # Assume the global default location instance exists (for the relevant guild, or is globally available if design allows)
        # For this test, assume it needs to be checked within the guild context passed
        self.location_manager._location_instances[guild_id] = {default_loc_id_global: {"id": default_loc_id_global, "name": "Global Spawn"}}

        ret_id = await self.location_manager.get_default_location_id(guild_id)
        self.assertEqual(ret_id, default_loc_id_global)
        self.mock_settings.get_guild_setting.assert_called_once_with(guild_id, "default_location_id")
        self.mock_settings.get_setting.assert_called_once_with("default_location_id")

    async def test_get_default_location_id_configured_but_instance_missing(self):
        guild_id = self.guild_id
        configured_default_id = "configured_but_missing_instance"
        self.mock_settings.get_guild_setting = MagicMock(return_value=configured_default_id)
        self.location_manager._location_instances[guild_id] = {} # Instance does NOT exist

        # The method should still return the ID; the caller is responsible for handling non-existence.
        ret_id = await self.location_manager.get_default_location_id(guild_id)
        self.assertEqual(ret_id, configured_default_id)

    async def test_get_default_location_id_none_configured(self):
        guild_id = "guild_no_defaults_at_all"
        self.mock_settings.get_guild_setting = MagicMock(return_value=None) # No guild default
        self.mock_settings.get_setting = MagicMock(return_value=None)      # No global default

        ret_id = await self.location_manager.get_default_location_id(guild_id)
        self.assertIsNone(ret_id)

    async def test_mark_location_instance_dirty(self):
        guild_id = self.guild_id
        instance_id = "inst_to_mark_dirty"
        # Ensure guild cache exists for dirty instances
        self.location_manager._dirty_instances[guild_id] = set()

        self.location_manager.mark_location_instance_dirty(guild_id, instance_id)
        self.assertIn(instance_id, self.location_manager._dirty_instances[guild_id])

    async def test_mark_location_instance_dirty_new_guild(self):
        guild_id = "new_guild_mark_dirty"
        instance_id = "inst_new_guild_dirty"
        # No pre-existing cache for this guild_id in _dirty_instances

        self.location_manager.mark_location_instance_dirty(guild_id, instance_id)
        self.assertIn(guild_id, self.location_manager._dirty_instances)
        self.assertIn(instance_id, self.location_manager._dirty_instances[guild_id])

    async def test_save_location_template_success(self): # Renamed to be specific
        guild_id = self.guild_id
        template_to_save = {
            "id": "tpl_save_me",
            "guild_id": guild_id,
            "name": "Savable Template",
            "description": "A template that can be saved.",
            "properties": {"is_special": True, "max_capacity": 10},
            "exits": {"north": "tpl_another_area", "south": "tpl_yet_another_area"},
            "initial_state": {"status": "peaceful", "ambient_sound": "birds_chirping.mp3"},
            "on_enter_triggers": [{"action": "play_sound", "sound_id": "welcome_sound"}],
            "on_exit_triggers": [{"action": "log_event", "event_name": "player_exited"}],
            "available_actions": ["look", "search", "rest"],
            "items": ["item_basic_sword", "item_healing_potion"], # List of item IDs
            "channel_id": "channel_for_template",
            "is_template_dirty": True
        }

        # Ensure the dirty_templates cache for the guild is initialized and includes the template
        if guild_id not in self.location_manager._dirty_templates:
            self.location_manager._dirty_templates[guild_id] = set()
        self.location_manager._dirty_templates[guild_id].add(template_to_save["id"])

        await self.location_manager.save_location(template_to_save)

        self.mock_db_adapter.execute.assert_called_once()
        args, _ = self.mock_db_adapter.execute.call_args

        self.assertIn("REPLACE INTO location_templates", args[0])
        expected_params = (
            template_to_save["id"],
            template_to_save["guild_id"],
            template_to_save["name"],
            template_to_save["description"],
            json.dumps(template_to_save["properties"]),
            json.dumps(template_to_save["exits"]),
            json.dumps(template_to_save["initial_state"]),
            json.dumps(template_to_save["on_enter_triggers"]),
            json.dumps(template_to_save["on_exit_triggers"]),
            json.dumps(template_to_save["available_actions"]),
            json.dumps(template_to_save["items"]),
            template_to_save["channel_id"],
            template_to_save["is_template_dirty"]
        )
        self.assertEqual(args[1], expected_params)
        self.assertNotIn(template_to_save["id"], self.location_manager._dirty_templates.get(guild_id, set()))

    async def test_save_location_instance_via_save_location(self):
        guild_id = self.guild_id
        instance_to_save = {
            "id": "inst_save_me_too",
            "guild_id": guild_id,
            "template_id": "tpl_parent",
            "name": "Savable Instance",
            "description": "An instance being saved via save_location.",
            "exits": {"west": "another_inst_id"},
            "state_variables": {"is_door_open": False, "light_level": 5},
            "is_active": True
            # No 'is_dirty' key in the dict itself, manager tracks this internally
        }

        # Ensure the instance is in _location_instances and marked in _dirty_instances
        if guild_id not in self.location_manager._location_instances:
            self.location_manager._location_instances[guild_id] = {}
        self.location_manager._location_instances[guild_id][instance_to_save["id"]] = instance_to_save
        
        if guild_id not in self.location_manager._dirty_instances:
            self.location_manager._dirty_instances[guild_id] = set()
        self.location_manager._dirty_instances[guild_id].add(instance_to_save["id"])


        await self.location_manager.save_location(instance_to_save, is_instance=True)

        self.mock_db_adapter.execute.assert_called_once()
        args, _ = self.mock_db_adapter.execute.call_args
        self.assertIn("REPLACE INTO location_instances", args[0])

        expected_instance_params = (
            instance_to_save["id"],
            instance_to_save["guild_id"],
            instance_to_save["template_id"],
            instance_to_save["name"],
            instance_to_save["description"],
            json.dumps(instance_to_save["exits"]),
            json.dumps(instance_to_save["state_variables"]),
            instance_to_save["is_active"]
        )
        self.assertEqual(args[1], expected_instance_params)
        self.assertNotIn(instance_to_save["id"], self.location_manager._dirty_instances.get(guild_id, set()))

    async def test_create_location_instance_success(self):
        guild_id = self.guild_id
        template_id = "tpl_base"
        new_instance_id_obj = uuid.UUID('12345678-1234-5678-1234-567812345678')
        new_instance_id = str(new_instance_id_obj)

        template_data = {
            "id": template_id, "guild_id": guild_id, "name": "Base Template",
            "description": "Base Desc", "exits": {"north": "tpl_north_exit"},
            "initial_state": {"temp_var": 1, "common_var": "template"},
            "properties": {}, "on_enter_triggers": [], "on_exit_triggers": [],
            "available_actions": [], "items": [], "channel_id": "ch1", "is_template_dirty": False
        }
        self.location_manager._location_templates[guild_id] = {template_id: template_data}
        self.location_manager._location_instances[guild_id] = {} # Ensure instance cache for guild exists
        self.location_manager._dirty_instances[guild_id] = set()


        with patch('uuid.uuid4', return_value=new_instance_id_obj):
            instance = await self.location_manager.create_location_instance(
                guild_id=guild_id,
                template_id=template_id,
                instance_name="My New Instance",
                instance_description="A cool new place.",
                exits_override={"south": "custom_south_exit"},
                initial_state_override={"inst_var": 2, "common_var": "instance"}
            )

        self.assertIsNotNone(instance)
        self.assertEqual(instance["id"], new_instance_id)
        self.assertEqual(instance["guild_id"], guild_id)
        self.assertEqual(instance["template_id"], template_id)
        self.assertEqual(instance["name"], "My New Instance")
        self.assertEqual(instance["description"], "A cool new place.")
        # Exits should be overridden
        self.assertEqual(instance["exits"], {"south": "custom_south_exit"})
        # Initial state should be merged, instance override takes precedence
        expected_state = {"temp_var": 1, "common_var": "instance", "inst_var": 2}
        self.assertEqual(instance["state_variables"], expected_state)
        self.assertTrue(instance["is_active"]) # Default

        self.assertIn(new_instance_id, self.location_manager._location_instances[guild_id])
        self.assertEqual(self.location_manager._location_instances[guild_id][new_instance_id], instance)
        self.assertIn(new_instance_id, self.location_manager._dirty_instances[guild_id])

    async def test_create_location_instance_template_not_found(self):
        guild_id = self.guild_id
        self.location_manager._location_templates[guild_id] = {} # No templates for this guild

        instance = await self.location_manager.create_location_instance(
            guild_id=guild_id,
            template_id="non_existent_tpl",
            instance_name="Test"
        )
        self.assertIsNone(instance)
        self.assertNotIn(guild_id, self.location_manager._dirty_instances) # Or check it's empty for guild

    async def test_create_location_instance_minimal_overrides(self):
        guild_id = self.guild_id
        template_id = "tpl_base_minimal"
        new_instance_id_obj = uuid.UUID('abcdef12-1234-5678-1234-567812345678')
        new_instance_id = str(new_instance_id_obj)

        template_data = {
            "id": template_id, "guild_id": guild_id, "name": "Base Template Min",
            "description": "Min Desc", "exits": {"default_exit": "def_target"},
            "initial_state": {"default_state": "on"}, "properties": {},
            "on_enter_triggers": [], "on_exit_triggers": [],
            "available_actions": [], "items": [], "channel_id": "ch2", "is_template_dirty": False
        }
        self.location_manager._location_templates[guild_id] = {template_id: template_data}
        self.location_manager._location_instances[guild_id] = {}
        self.location_manager._dirty_instances[guild_id] = set()

        with patch('uuid.uuid4', return_value=new_instance_id_obj):
            instance = await self.location_manager.create_location_instance(
                guild_id=guild_id,
                template_id=template_id
                # No overrides for name, desc, exits, initial_state
            )

        self.assertIsNotNone(instance)
        self.assertEqual(instance["id"], new_instance_id)
        self.assertEqual(instance["name"], template_data["name"]) # Should use template name
        self.assertEqual(instance["description"], template_data["description"]) # Should use template desc
        self.assertEqual(instance["exits"], template_data["exits"]) # Should use template exits
        self.assertEqual(instance["state_variables"], template_data["initial_state"]) # Should use template initial_state

        self.assertIn(new_instance_id, self.location_manager._location_instances[guild_id])
        self.assertIn(new_instance_id, self.location_manager._dirty_instances[guild_id])

    async def test_create_location_instance_guild_caches_not_initialized(self):
        guild_id = "new_guild_create" # Guild not seen before by this manager instance
        template_id = "tpl_new_guild"
        new_instance_id_obj = uuid.UUID('fedcba98-4321-8765-4321-876543210abc')
        new_instance_id = str(new_instance_id_obj)

        # We need to ensure template exists for this "new" guild
        template_data = {"id": template_id, "name": "T", "description": "D", "exits": {}, "initial_state": {}}
        self.location_manager._location_templates[guild_id] = {template_id: template_data}
        # DO NOT initialize _location_instances[guild_id] or _dirty_instances[guild_id] here

        with patch('uuid.uuid4', return_value=new_instance_id_obj):
            instance = await self.location_manager.create_location_instance(guild_id, template_id)

        self.assertIsNotNone(instance)
        self.assertEqual(instance["id"], new_instance_id)
        self.assertIn(guild_id, self.location_manager._location_instances) # Cache should be created
        self.assertIn(new_instance_id, self.location_manager._location_instances[guild_id])
        self.assertIn(guild_id, self.location_manager._dirty_instances) # Cache should be created
        self.assertIn(new_instance_id, self.location_manager._dirty_instances[guild_id])

    async def test_get_location_instance_exists(self):
        guild_id = self.guild_id
        instance_id = "inst1"
        expected_instance_data = {"id": instance_id, "name": "Test Instance", "guild_id": guild_id}
        self.location_manager._location_instances[guild_id] = {instance_id: expected_instance_data}

        instance = await self.location_manager.get_location_instance(guild_id, instance_id)
        self.assertEqual(instance, expected_instance_data)

    async def test_get_location_instance_non_existent(self):
        guild_id = self.guild_id
        self.location_manager._location_instances[guild_id] = {} # Ensure cache for guild exists but is empty

        instance = await self.location_manager.get_location_instance(guild_id, "non_existent_inst")
        self.assertIsNone(instance)

    async def test_get_location_instance_different_guild(self):
        guild_id_1 = "guild1_get"
        guild_id_2 = "guild2_get"
        instance_id = "inst_cross"
        instance_data_guild1 = {"id": instance_id, "name": "Instance Guild1", "guild_id": guild_id_1}

        self.location_manager._location_instances[guild_id_1] = {instance_id: instance_data_guild1}
        self.location_manager._location_instances[guild_id_2] = {} # Cache for guild2 exists but is empty or has other instances

        # Try to get instance_id from guild_id_2
        instance = await self.location_manager.get_location_instance(guild_id_2, instance_id)
        self.assertIsNone(instance)

    async def test_get_location_instance_guild_not_loaded(self):
        # No cache entry for "unloaded_guild_get" in self.location_manager._location_instances
        guild_id = "unloaded_guild_get"
        instance_id = "some_inst"

        instance = await self.location_manager.get_location_instance(guild_id, instance_id)
        self.assertIsNone(instance)

    async def test_get_location_static_exists(self):
        guild_id = self.guild_id
        template_id = "tpl_static1"
        expected_template_data = {"id": template_id, "name": "Test Template Static", "guild_id": guild_id}
        self.location_manager._location_templates[guild_id] = {template_id: expected_template_data}

        template = await self.location_manager.get_location_static(guild_id, template_id)
        self.assertEqual(template, expected_template_data)

    async def test_get_location_static_non_existent(self):
        guild_id = self.guild_id
        self.location_manager._location_templates[guild_id] = {} # Ensure cache for guild exists but is empty

        template = await self.location_manager.get_location_static(guild_id, "non_existent_tpl_static")
        self.assertIsNone(template)

    async def test_get_location_static_guild_not_loaded(self):
        # No cache entry for "unloaded_guild_static" in self.location_manager._location_templates
        guild_id = "unloaded_guild_static"
        template_id = "some_tpl_static"

        template = await self.location_manager.get_location_static(guild_id, template_id)
        self.assertIsNone(template)

    async def test_delete_location_instance_success(self):
        guild_id = self.guild_id
        instance_id = "inst_to_delete"
        instance_data = {"id": instance_id, "name": "To Delete", "guild_id": guild_id, "template_id": "tpl1"}

        self.location_manager._location_instances[guild_id] = {instance_id: instance_data}
        self.location_manager._dirty_instances[guild_id] = set()
        self.location_manager._deleted_instances[guild_id] = set()
        self.location_manager.clean_up_location_contents = AsyncMock() # Mock the cleanup method

        await self.location_manager.delete_location_instance(guild_id, instance_id)

        self.assertNotIn(instance_id, self.location_manager._location_instances.get(guild_id, {}))
        self.assertIn(instance_id, self.location_manager._deleted_instances.get(guild_id, set()))
        self.assertNotIn(instance_id, self.location_manager._dirty_instances.get(guild_id, set())) # Should not be in dirty
        self.location_manager.clean_up_location_contents.assert_called_once_with(guild_id, instance_id, instance_data)

    async def test_delete_location_instance_was_dirty(self):
        guild_id = self.guild_id
        instance_id = "inst_dirty_delete"
        instance_data = {"id": instance_id, "name": "Dirty Delete", "guild_id": guild_id, "template_id": "tpl1"}

        self.location_manager._location_instances[guild_id] = {instance_id: instance_data}
        self.location_manager._dirty_instances[guild_id] = {instance_id} # Mark as dirty
        self.location_manager._deleted_instances[guild_id] = set()
        self.location_manager.clean_up_location_contents = AsyncMock()

        await self.location_manager.delete_location_instance(guild_id, instance_id)

        self.assertNotIn(instance_id, self.location_manager._location_instances.get(guild_id, {}))
        self.assertIn(instance_id, self.location_manager._deleted_instances.get(guild_id, set()))
        # Crucially, it should be removed from the dirty set
        self.assertNotIn(instance_id, self.location_manager._dirty_instances.get(guild_id, set()))
        self.location_manager.clean_up_location_contents.assert_called_once_with(guild_id, instance_id, instance_data)

    async def test_delete_location_instance_non_existent(self):
        guild_id = self.guild_id
        instance_id = "non_existent_delete"

        self.location_manager._location_instances[guild_id] = {}
        self.location_manager._dirty_instances[guild_id] = set()
        self.location_manager._deleted_instances[guild_id] = set()
        self.location_manager.clean_up_location_contents = AsyncMock()

        await self.location_manager.delete_location_instance(guild_id, instance_id)

        self.assertNotIn(instance_id, self.location_manager._deleted_instances.get(guild_id, set()))
        self.location_manager.clean_up_location_contents.assert_not_called()

    async def test_delete_location_instance_guild_not_loaded(self):
        guild_id = "unloaded_guild_delete"
        instance_id = "inst_del_unloaded"
        self.location_manager.clean_up_location_contents = AsyncMock()

        await self.location_manager.delete_location_instance(guild_id, instance_id)

        self.assertNotIn(guild_id, self.location_manager._location_instances)
        self.assertNotIn(guild_id, self.location_manager._deleted_instances)
        self.location_manager.clean_up_location_contents.assert_not_called()

    async def test_clean_up_location_contents(self):
        guild_id = self.guild_id
        location_id_to_clean = "loc_to_clean"
        # Location data is passed but not strictly needed by the mocks in this example
        location_data = {"id": location_id_to_clean, "name": "Cleaning Test Loc", "template_id": "tpl_clean"}

        # Mock CharacterManager
        mock_char_manager = AsyncMock()
        char1 = MagicMock()
        char1.id = "char1_in_loc"
        char1.guild_id = guild_id
        char2 = MagicMock()
        char2.id = "char2_in_loc"
        char2.guild_id = guild_id
        mock_char_manager.get_characters_in_location.return_value = [char1, char2]
        self.location_manager._character_manager = mock_char_manager # Inject mock

        # Mock NpcManager
        mock_npc_manager = AsyncMock()
        npc1 = MagicMock()
        npc1.id = "npc1_in_loc"
        npc1.guild_id = guild_id
        mock_npc_manager.get_npcs_in_location.return_value = [npc1]
        self.location_manager._npc_manager = mock_npc_manager

        # Mock ItemManager (assuming items might be directly in a location instance, or associated)
        # This depends heavily on ItemManager's design. For simplicity, let's assume a similar pattern.
        mock_item_manager = AsyncMock()
        item1 = MagicMock()
        item1.id = "item1_in_loc"
        item1.guild_id = guild_id
        mock_item_manager.get_items_in_location.return_value = [item1] # Fictional method for example
        mock_item_manager.remove_item_from_world = AsyncMock() # Fictional method
        self.location_manager._item_manager = mock_item_manager

        # Mock PartyManager
        mock_party_manager = AsyncMock()
        party1 = MagicMock()
        party1.id = "party1_in_loc"
        party1.guild_id = guild_id
        mock_party_manager.get_parties_in_location.return_value = [party1]
        # Parties might be moved to a default location or disbanded. Let's assume moved.
        self.location_manager._party_manager = mock_party_manager

        # Assume a default location ID for moving entities
        default_loc_id = "default_spawn_loc"
        self.location_manager.get_default_location_id = AsyncMock(return_value=default_loc_id)


        await self.location_manager.clean_up_location_contents(guild_id, location_id_to_clean, location_data)

        # Verify CharacterManager calls
        mock_char_manager.get_characters_in_location.assert_called_once_with(guild_id, location_id_to_clean)
        # Assuming characters are moved to a default location
        mock_char_manager.update_character_location.assert_has_calls([
            call(guild_id, char1.id, default_loc_id),
            call(guild_id, char2.id, default_loc_id)
        ], any_order=True)
        # Or if they are simply removed:
        # mock_char_manager.remove_character.assert_has_calls(...)

        # Verify NpcManager calls
        mock_npc_manager.get_npcs_in_location.assert_called_once_with(guild_id, location_id_to_clean)
        # Assuming NPCs are simply removed (or could be moved too)
        mock_npc_manager.remove_npc.assert_called_once_with(guild_id, npc1.id)

        # Verify ItemManager calls (fictional methods used here for illustration)
        mock_item_manager.get_items_in_location.assert_called_once_with(guild_id, location_id_to_clean)
        mock_item_manager.remove_item_from_world.assert_called_once_with(guild_id, item1.id)

        # Verify PartyManager calls
        mock_party_manager.get_parties_in_location.assert_called_once_with(guild_id, location_id_to_clean)
        mock_party_manager.update_party_location.assert_called_once_with(party1.id, default_loc_id, guild_id=guild_id, context=unittest.mock.ANY)

        self.location_manager.get_default_location_id.assert_called_with(guild_id)

    async def test_update_location_state_success(self):
        guild_id = self.guild_id
        instance_id = "inst_update_state"
        original_instance_data = {
            "id": instance_id, "name": "State Update Loc", "guild_id": guild_id,
            "template_id": "tpl1", "state_variables": {"initial_key": "initial_value", "counter": 0}
        }
        self.location_manager._location_instances[guild_id] = {instance_id: original_instance_data.copy()} # Use .copy() if dict might be mutated by manager
        self.location_manager._dirty_instances[guild_id] = set()

        new_state = {"counter": 1, "new_key": "added_value"}
        # Update_location_state is expected to merge, not replace, unless specified otherwise
        expected_merged_state = {"initial_key": "initial_value", "counter": 1, "new_key": "added_value"}


        await self.location_manager.update_location_state(guild_id, instance_id, new_state)

        updated_instance = self.location_manager._location_instances[guild_id][instance_id]
        self.assertEqual(updated_instance["state_variables"], expected_merged_state)
        self.assertIn(instance_id, self.location_manager._dirty_instances[guild_id])

    async def test_update_location_state_non_existent_instance(self):
        guild_id = self.guild_id
        instance_id = "non_existent_state_update"

        self.location_manager._location_instances[guild_id] = {} # Ensure guild cache exists
        self.location_manager._dirty_instances[guild_id] = set()

        await self.location_manager.update_location_state(guild_id, instance_id, {"some_state": "value"})

        self.assertNotIn(instance_id, self.location_manager._location_instances.get(guild_id, {}))
        self.assertEqual(len(self.location_manager._dirty_instances.get(guild_id, set())), 0)

    async def test_update_location_state_guild_not_loaded(self):
        guild_id = "unloaded_guild_state_update"
        instance_id = "inst_unloaded_state"

        await self.location_manager.update_location_state(guild_id, instance_id, {"state": "new"})

        self.assertNotIn(guild_id, self.location_manager._location_instances)
        self.assertNotIn(guild_id, self.location_manager._dirty_instances)
