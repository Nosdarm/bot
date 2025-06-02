import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock, patch, call

from bot.game.managers.location_manager import LocationManager
# Assuming LocationManager might need these for its __init__ or for context passing
# from bot.game.models.location import Location # Or whatever model it uses for instances/templates

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


class TestLocationManagerMoveEntityParty(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # Mock all dependencies for LocationManager's __init__
        self.mock_db_adapter = AsyncMock()
        self.mock_settings = {"guilds": {"test_guild_1": {}}}
        self.mock_rule_engine = AsyncMock()
        self.mock_event_manager = AsyncMock()
        self.mock_character_manager = AsyncMock()
        self.mock_npc_manager = AsyncMock()
        self.mock_item_manager = AsyncMock()
        self.mock_combat_manager = AsyncMock()
        self.mock_status_manager = AsyncMock()
        self.mock_party_manager = AsyncMock() # This is the one we're interested in for party moves
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
            party_manager=self.mock_party_manager, # Injected mock
            time_manager=self.mock_time_manager,
            send_callback_factory=self.mock_send_callback_factory,
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
        self.party_id = "party_alpha_1"
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
            entity_id=self.party_id,
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
        self.assertEqual(args[0], self.party_id)
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
            entity_id=self.party_id,
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
            entity_id=self.party_id,
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
