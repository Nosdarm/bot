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


class TestLocationManagerAICreation(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.mock_db_adapter = AsyncMock()
        self.mock_settings = {"campaign_data": {"location_templates": []}} # Basic settings
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
        # Ensure internal caches are initialized as dicts
        self.location_manager._location_templates = {}
        self.location_manager._location_instances = {}
        self.location_manager._dirty_instances = {}
        self.location_manager._deleted_instances = {}

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
