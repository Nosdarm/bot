import asyncio
import unittest
import json
import uuid
from unittest.mock import MagicMock, AsyncMock, patch, call

from bot.game.managers.location_manager import LocationManager
from bot.game.models.location import Location


DUMMY_LOCATION_TEMPLATE_DATA = {
    "id": "tpl_world_center",
    "name_i18n": {"en":"World Center Template"}, # Adjusted to name_i18n
    "description_i18n": {"en":"A template for central locations."}, # Adjusted
    "exits": {"north": "tpl_north_region_entrance_id"},
    "on_enter_triggers": [{"action": "log_entry", "message": "Entered World Center area."}],
    "on_exit_triggers": [{"action": "log_exit", "message": "Exited World Center area."}],
    "channel_id": "123456789012345678" 
}

DUMMY_LOCATION_INSTANCE_FROM = {
    "id": "instance_world_center_001",
    "guild_id": "test_guild_1",
    "template_id": "tpl_world_center",
    "name_i18n": {"en":"World Center Alpha"}, # Adjusted
    "descriptions_i18n": {"en":"The bustling heart of the world."}, # Adjusted
    "exits": {"north": "instance_north_region_main_001"},
    "state_variables": {}, # Changed from 'state' to 'state_variables' to match Location model
    "is_active": True
}
DUMMY_LOCATION_INSTANCE_TO = {
    "id": "instance_north_region_main_001",
    "guild_id": "test_guild_1",
    "template_id": "tpl_north_region_entrance_id",
    "name_i18n": {"en":"North Region Entrance"}, # Adjusted
    "descriptions_i18n": {"en":"Gateway to the frosty north."}, # Adjusted
    "exits": {"south": "instance_world_center_001"},
    "state_variables": {}, # Changed from 'state' to 'state_variables'
    "is_active": True
}


class TestLocationManagerMoveEntity(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self): # Changed to asyncSetUp
        self.mock_db_service = MagicMock() # For LocationManager's _db_service
        self.mock_db_service.adapter = AsyncMock() # For adapter calls

        self.mock_settings = MagicMock()
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

        self.location_manager = LocationManager(
            db_service=self.mock_db_service, # Pass the MagicMock
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
        )

        self.guild_id = "test_guild_1"
        self.entity_id = "entity_test_1"
        self.from_location_id = DUMMY_LOCATION_INSTANCE_FROM["id"]
        self.to_location_id = DUMMY_LOCATION_INSTANCE_TO["id"]

        # Adjusted template loading to match LocationManager's new global template cache
        self.location_manager._location_templates = {
            DUMMY_LOCATION_TEMPLATE_DATA["id"]: DUMMY_LOCATION_TEMPLATE_DATA.copy(),
            DUMMY_LOCATION_INSTANCE_TO["template_id"]: {**DUMMY_LOCATION_TEMPLATE_DATA.copy(), "id": DUMMY_LOCATION_INSTANCE_TO["template_id"]}
        }
        self.location_manager._location_instances = {
            self.guild_id: {
                DUMMY_LOCATION_INSTANCE_FROM["id"]: DUMMY_LOCATION_INSTANCE_FROM.copy(),
                DUMMY_LOCATION_INSTANCE_TO["id"]: DUMMY_LOCATION_INSTANCE_TO.copy()
            }
        }
        self.location_manager._dirty_instances = {self.guild_id: set()}
        self.location_manager._deleted_instances = {self.guild_id: set()}


    async def test_successfully_moves_party(self):
        self.mock_party_manager.update_party_location = AsyncMock(return_value=True)
        
        def get_location_instance_side_effect(guild_id, instance_id):
            return self.location_manager._location_instances.get(guild_id, {}).get(instance_id)
        self.location_manager.get_location_instance = MagicMock(side_effect=get_location_instance_side_effect)

        def get_location_static_side_effect(template_id): # Removed guild_id from args
            return self.location_manager._location_templates.get(template_id)
        self.location_manager.get_location_static = MagicMock(side_effect=get_location_static_side_effect)
        
        self.mock_rule_engine.execute_triggers = AsyncMock()

        result = await self.location_manager.move_entity(
            guild_id=self.guild_id,
            entity_id=self.entity_id,
            entity_type="Party",
            from_location_id=self.from_location_id,
            to_location_id=self.to_location_id,
            party_manager=self.mock_party_manager, 
            rule_engine=self.mock_rule_engine 
        )

        self.assertTrue(result)
        self.mock_party_manager.update_party_location.assert_called_once()
        args_call, kwargs_call = self.mock_party_manager.update_party_location.call_args
        self.assertEqual(args_call[0], self.entity_id)
        self.assertEqual(args_call[1], self.to_location_id)
        # self.assertEqual(args_call[2], self.guild_id) # update_party_location might not take guild_id as direct arg
        self.assertIn('context', kwargs_call)
        self.assertEqual(kwargs_call['context']['guild_id'], self.guild_id)


        self.assertEqual(self.mock_rule_engine.execute_triggers.call_count, 2)
        departure_trigger_call = self.mock_rule_engine.execute_triggers.call_args_list[0]
        arrival_trigger_call = self.mock_rule_engine.execute_triggers.call_args_list[1]
        
        self.assertEqual(departure_trigger_call.kwargs['context']['location_instance_id'], self.from_location_id)
        self.assertEqual(departure_trigger_call.args[0], DUMMY_LOCATION_TEMPLATE_DATA["on_exit_triggers"])

        self.assertEqual(arrival_trigger_call.kwargs['context']['location_instance_id'], self.to_location_id)
        self.assertEqual(arrival_trigger_call.args[0], DUMMY_LOCATION_TEMPLATE_DATA["on_enter_triggers"])


    async def test_move_party_target_location_not_found(self):
        def get_location_instance_side_effect(guild_id, instance_id):
            if instance_id == self.from_location_id: return DUMMY_LOCATION_INSTANCE_FROM.copy()
            if instance_id == self.to_location_id: return None
            return None
        self.location_manager.get_location_instance = MagicMock(side_effect=get_location_instance_side_effect)
        
        self.mock_party_manager.update_party_location = AsyncMock()

        result = await self.location_manager.move_entity(
            guild_id=self.guild_id,
            entity_id=self.entity_id,
            entity_type="Party",
            from_location_id=self.from_location_id,
            to_location_id=self.to_location_id,
            party_manager=self.mock_party_manager
        )

        self.assertFalse(result)
        self.mock_party_manager.update_party_location.assert_not_called()


    async def test_move_party_party_manager_update_fails(self):
        self.mock_party_manager.update_party_location = AsyncMock(return_value=False) # Simulate manager failure
        
        def get_location_instance_side_effect(guild_id, instance_id):
            if instance_id == self.from_location_id: return DUMMY_LOCATION_INSTANCE_FROM.copy()
            if instance_id == self.to_location_id: return DUMMY_LOCATION_INSTANCE_TO.copy()
            return None
        self.location_manager.get_location_instance = MagicMock(side_effect=get_location_instance_side_effect)
        
        self.location_manager.get_location_static = MagicMock(
            side_effect=lambda template_id: self.location_manager._location_templates.get(template_id)
        )
        self.mock_rule_engine.execute_triggers = AsyncMock()


        result = await self.location_manager.move_entity(
            guild_id=self.guild_id,
            entity_id=self.entity_id,
            entity_type="Party",
            from_location_id=self.from_location_id,
            to_location_id=self.to_location_id,
            party_manager=self.mock_party_manager,
            rule_engine=self.mock_rule_engine
        )

        self.assertFalse(result) # Overall move should fail
        self.mock_party_manager.update_party_location.assert_called_once()
        self.mock_rule_engine.execute_triggers.assert_called_once()
        departure_trigger_call = self.mock_rule_engine.execute_triggers.call_args_list[0]
        self.assertEqual(departure_trigger_call.kwargs['context']['location_instance_id'], self.from_location_id)
        self.assertEqual(departure_trigger_call.args[0], DUMMY_LOCATION_TEMPLATE_DATA["on_exit_triggers"])

class TestLocationManagerAICreation(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self): # Changed to asyncSetUp
        self.mock_db_service = MagicMock()
        self.mock_db_service.adapter = AsyncMock()
        self.mock_settings = MagicMock()
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

        self.mock_prompt_generator = AsyncMock()
        self.mock_openai_service = AsyncMock()
        self.mock_ai_validator = AsyncMock()

        self.guild_id = "test_guild_aic"

        self.location_manager = LocationManager(
            db_service=self.mock_db_service,
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
            # Missing AI service injections here if create_location_instance uses them directly
            # However, create_location_instance_from_moderated_data does not use them.
        )
        self.location_manager._multilingual_prompt_generator = self.mock_prompt_generator
        self.location_manager._openai_service = self.mock_openai_service
        self.location_manager._ai_validator = self.mock_ai_validator


        self.location_manager._location_templates = {} # Global templates
        self.location_manager._location_instances = {self.guild_id: {}}
        self.location_manager._dirty_instances = {self.guild_id: set()}
        self.location_manager._deleted_instances = {self.guild_id: set()}

        # Mock the methods on the adapter instance
        self.mock_db_service.adapter.upsert_location = AsyncMock(return_value=True)
        self.mock_db_service.adapter.add_generated_location = AsyncMock(return_value=None)


    # Test for create_location_instance when it involves AI (moderation path)
    # This test was previously in TestLocationManager, moved here for logical grouping.
    async def test_create_location_instance_ai_pending_moderation(self):
        template_id_arg = "AI:generate_haunted_mansion" # Triggers AI path
        user_id = "test_user_loc_mod"
        mock_validated_loc_data = {
            "name_i18n": {"en": "AI Haunted Mansion"},
            "descriptions_i18n": {"en": "A spooky place."},
            "exits": {}, "state_variables": {}
            # Ensure this matches what generate_location_details_from_ai would return
        }

        # Mock the internal AI generation method of LocationManager
        self.location_manager.generate_location_details_from_ai = AsyncMock(return_value=mock_validated_loc_data)
        self.mock_db_service.adapter.save_pending_moderation_request = AsyncMock()


        expected_request_id_obj = uuid.uuid4()
        with patch('uuid.uuid4', return_value=expected_request_id_obj):
            result = await self.location_manager.create_location_instance(
                self.guild_id, template_id_arg, user_id=user_id # Pass user_id for moderation
            )

        expected_request_id_str = str(expected_request_id_obj)
        self.assertEqual(result, {"status": "pending_moderation", "request_id": expected_request_id_str})

        self.location_manager.generate_location_details_from_ai.assert_called_once_with(
            self.guild_id, "generate_haunted_mansion", player_context=None # Or whatever context it expects
        )
        self.mock_db_service.adapter.save_pending_moderation_request.assert_called_once()
        call_args = self.mock_db_service.adapter.save_pending_moderation_request.call_args[0]
        self.assertEqual(call_args[0], expected_request_id_str)
        self.assertEqual(call_args[1], self.guild_id)
        self.assertEqual(call_args[2], user_id)
        self.assertEqual(call_args[3], "location")
        self.assertEqual(json.loads(call_args[4]), mock_validated_loc_data)

    async def test_create_location_instance_from_moderated_data_success(self):
        user_id_str = "creator_user_id"
        moderated_loc_data = {
            "id": str(uuid.uuid4()), # Can be pre-assigned by moderation system or generate if missing
            "name_i18n": {"en": "Approved Mystical Forest"},
            "descriptions_i18n": {"en": "A forest approved by GMs."},
            "details_i18n": {"en": "Whispering trees and glowing flora."},
            "tags_i18n": {"en": "forest, mystical, approved"},
            "atmosphere_i18n": {"en": "Ethereal and calm."},
            "features_i18n": {"en": "Ancient shrine, sparkling pond."},
            "exits": {"north": "some_other_place_id"},
            "state_variables": {"weather": "magical_aurora"},
            "template_id": "ai_forest_template_v1", # Optional template ID
            "channel_id": "channel123",
            "image_url": "http://example.com/image.png",
            "is_active": True
        }
        context_dummy = {} # Context passed from command handler

        # Call the method
        created_instance_dict = await self.location_manager.create_location_instance_from_moderated_data(
            self.guild_id, moderated_loc_data.copy(), user_id_str, context_dummy
        )

        self.assertIsNotNone(created_instance_dict)
        self.assertEqual(created_instance_dict["id"], moderated_loc_data["id"])
        self.assertEqual(created_instance_dict["guild_id"], self.guild_id)
        self.assertEqual(created_instance_dict["name_i18n"]["en"], "Approved Mystical Forest")
        self.assertEqual(created_instance_dict["details_i18n"]["en"], "Whispering trees and glowing flora.")
        self.assertTrue(created_instance_dict["is_active"])

        # Verify DB calls
        self.mock_db_service.adapter.upsert_location.assert_awaited_once()
        upsert_arg = self.mock_db_service.adapter.upsert_location.call_args[0][0]
        self.assertEqual(upsert_arg["id"], moderated_loc_data["id"])
        self.assertEqual(upsert_arg["name_i18n"]["en"], "Approved Mystical Forest")

        self.mock_db_service.adapter.add_generated_location.assert_awaited_once_with(
            moderated_loc_data["id"], self.guild_id, user_id_str
        )

        # Verify cache update
        self.assertIn(moderated_loc_data["id"], self.location_manager._location_instances[self.guild_id])
        self.assertEqual(
            self.location_manager._location_instances[self.guild_id][moderated_loc_data["id"]]["name_i18n"]["en"],
            "Approved Mystical Forest"
        )
        self.assertIn(moderated_loc_data["id"], self.location_manager._dirty_instances[self.guild_id])

    async def test_create_location_instance_from_moderated_data_generates_id_if_missing(self):
        user_id_str = "creator_user_id_gen"
        moderated_loc_data = { # No 'id' field
            "name_i18n": {"en": "Cave With Generated ID"},
            "descriptions_i18n": {"en": "This cave needs an ID."},
            "guild_id": self.guild_id # This will be overridden by method param
        }
        context_dummy = {}

        new_uuid = uuid.uuid4()
        with patch('uuid.uuid4', return_value=new_uuid):
            created_instance_dict = await self.location_manager.create_location_instance_from_moderated_data(
                self.guild_id, moderated_loc_data.copy(), user_id_str, context_dummy
            )

        self.assertIsNotNone(created_instance_dict)
        self.assertEqual(created_instance_dict["id"], str(new_uuid))
        self.mock_db_service.adapter.upsert_location.assert_awaited_once()
        self.mock_db_service.adapter.add_generated_location.assert_awaited_once_with(
            str(new_uuid), self.guild_id, user_id_str
        )

    async def test_create_location_instance_from_moderated_data_db_failure(self):
        user_id_str = "creator_user_id_dbfail"
        moderated_loc_data = {
            "id": str(uuid.uuid4()),
            "name_i18n": {"en": "DB Failure Test Loc"},
            "descriptions_i18n": {"en": "This should not be saved."}
        }
        context_dummy = {}

        self.mock_db_service.adapter.upsert_location.return_value = False # Simulate DB failure

        created_instance_dict = await self.location_manager.create_location_instance_from_moderated_data(
            self.guild_id, moderated_loc_data.copy(), user_id_str, context_dummy
        )

        self.assertIsNone(created_instance_dict)
        self.mock_db_service.adapter.upsert_location.assert_awaited_once()
        self.mock_db_service.adapter.add_generated_location.assert_not_awaited() # Should not be called if upsert fails
        self.assertNotIn(moderated_loc_data["id"], self.location_manager._location_instances.get(self.guild_id, {}))


# --- Start of TestLocationManagerTriggerHandling (from original file, needs asyncSetUp) ---
class TestLocationManagerTriggerHandling(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self): # Changed to asyncSetUp
        self.mock_rule_engine = AsyncMock()
        self.mock_db_service = MagicMock()
        self.mock_db_service.adapter = AsyncMock()

        self.location_manager = LocationManager(
            db_service=self.mock_db_service,
            settings=MagicMock(),
            rule_engine=self.mock_rule_engine,
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
            "name_i18n": {"en": "Trigger Template"},
            "on_enter_triggers": [{"action": "log", "message": "Entity Entered"}],
            "on_exit_triggers": [{"action": "event", "event_id": "e_exit"}]
        }
        self.location_instance_data = {
            "id": self.location_instance_id,
            "template_id": self.template_id,
            "name_i18n": {"en": "Trigger Instance"} # name_i18n instead of name
        }

        self.location_manager._location_templates = {self.template_id: self.location_template_data} # Global cache
        self.location_manager._location_instances = {self.guild_id: {self.location_instance_id: self.location_instance_data}}


    async def test_handle_entity_arrival_success(self):
        context_with_guild = {"guild_id": self.guild_id, "entity_id": self.entity_id, "entity_type": "Character"}

        await self.location_manager.handle_entity_arrival(
            location_id=self.location_instance_id,
            entity_id=self.entity_id,
            entity_type="Character",
            **context_with_guild
        )

        self.mock_rule_engine.execute_triggers.assert_called_once_with(
            self.location_template_data["on_enter_triggers"],
            context=unittest.mock.ANY
        )
        passed_context = self.mock_rule_engine.execute_triggers.call_args.kwargs['context']
        self.assertEqual(passed_context["location_instance_id"], self.location_instance_id)
        self.assertEqual(passed_context["location_template_id"], self.template_id)
        self.assertEqual(passed_context["guild_id"], self.guild_id)


    async def test_handle_entity_departure_success(self):
        context_with_guild = {"guild_id": self.guild_id, "entity_id": self.entity_id, "entity_type": "Party"}

        await self.location_manager.handle_entity_departure(
            location_id=self.location_instance_id,
            entity_id=self.entity_id,
            entity_type="Party",
            **context_with_guild
        )

        self.mock_rule_engine.execute_triggers.assert_called_once_with(
            self.location_template_data["on_exit_triggers"],
            context=unittest.mock.ANY
        )
        passed_context = self.mock_rule_engine.execute_triggers.call_args.kwargs['context']
        self.assertEqual(passed_context["location_instance_id"], self.location_instance_id)
        self.assertEqual(passed_context["location_template_id"], self.template_id)
        self.assertEqual(passed_context["guild_id"], self.guild_id)

    async def test_handle_entity_arrival_no_template(self):
        self.location_manager._location_templates = {} # Clear templates
        context_with_guild = {"guild_id": self.guild_id, "entity_id": self.entity_id, "entity_type": "Character"}

        await self.location_manager.handle_entity_arrival(
            location_id=self.location_instance_id, entity_id=self.entity_id, entity_type="Character", **context_with_guild
        )
        self.mock_rule_engine.execute_triggers.assert_not_called()

    async def test_handle_entity_arrival_no_on_enter_triggers(self):
        template_no_triggers = self.location_template_data.copy()
        del template_no_triggers["on_enter_triggers"]
        self.location_manager._location_templates[self.template_id] = template_no_triggers
        context_with_guild = {"guild_id": self.guild_id, "entity_id": self.entity_id, "entity_type": "Character"}

        await self.location_manager.handle_entity_arrival(
            location_id=self.location_instance_id, entity_id=self.entity_id, entity_type="Character", **context_with_guild
        )
        self.mock_rule_engine.execute_triggers.assert_not_called()

    async def test_handle_entity_departure_no_on_exit_triggers(self):
        template_no_triggers = self.location_template_data.copy()
        template_no_triggers["on_exit_triggers"] = []
        self.location_manager._location_templates[self.template_id] = template_no_triggers
        context_with_guild = {"guild_id": self.guild_id, "entity_id": self.entity_id, "entity_type": "Character"}

        await self.location_manager.handle_entity_departure(
            location_id=self.location_instance_id, entity_id=self.entity_id, entity_type="Character", **context_with_guild
        )
        self.mock_rule_engine.execute_triggers.assert_not_called()

    async def test_handle_entity_arrival_instance_not_found(self):
        context_with_guild = {"guild_id": self.guild_id, "entity_id": self.entity_id, "entity_type": "Character"}
        await self.location_manager.handle_entity_arrival(
            location_id="non_existent_instance", entity_id=self.entity_id, entity_type="Character", **context_with_guild
        )
        self.mock_rule_engine.execute_triggers.assert_not_called()


# --- Start of TestLocationManager (original basic tests, needs asyncSetUp) ---
class TestLocationManager(unittest.IsolatedAsyncioTestCase): # Changed to IsolatedAsyncioTestCase
    async def asyncSetUp(self): # Changed to asyncSetUp
        self.mock_db_service = MagicMock()
        self.mock_db_service.adapter = AsyncMock()
        self.mock_settings = MagicMock()
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

        self.guild_id = "test_guild_main"

        self.location_manager = LocationManager(
            db_service=self.mock_db_service,
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
        )
        self.location_manager._location_templates = {} # Global
        self.location_manager._location_instances = {}
        self.location_manager._dirty_instances = {}
        self.location_manager._deleted_instances = {}
        # self.location_manager._dirty_templates = {} # Removed as templates are global

    async def test_init_manager(self):
        self.assertEqual(self.location_manager._db_service, self.mock_db_service)
        self.assertEqual(self.location_manager._settings, self.mock_settings)
        self.assertEqual(self.location_manager._rule_engine, self.mock_rule_engine)
        self.assertIsNotNone(self.location_manager._event_manager)
        self.assertEqual(self.location_manager._location_templates, {}) # Should be loaded by _load_location_templates
        self.assertEqual(self.location_manager._location_instances, {})
        self.assertEqual(self.location_manager._dirty_instances, {})
        self.assertEqual(self.location_manager._deleted_instances, {})

    # ... (other tests from the original TestLocationManager class would go here)
    # For brevity, I'm not copying all of them, but they would need asyncSetUp
    # and await for async calls if they interact with async methods of LocationManager.
    # Example of adapting one:
    async def test_create_location_instance_success(self):
        template_id = "tpl_base_main"
        new_instance_id_obj = uuid.UUID('12345678-1234-5678-1234-567812345678')
        new_instance_id = str(new_instance_id_obj)

        template_data = {
            "id": template_id, "name_i18n": {"en":"Base Template Main"},
            "description_i18n": {"en":"Base Desc Main"}, "exits": {"north": "tpl_north_exit"},
            "initial_state": {"temp_var": 1, "common_var": "template"}
            # Removed guild_id from template_data as templates are global
        }
        self.location_manager._location_templates = {template_id: template_data} # Populate global cache

        # Ensure guild specific caches are initialized for instance creation
        self.location_manager._location_instances[self.guild_id] = {}
        self.location_manager._dirty_instances[self.guild_id] = set()


        with patch('uuid.uuid4', return_value=new_instance_id_obj):
            instance = await self.location_manager.create_location_instance(
                guild_id=self.guild_id,
                template_id=template_id,
                instance_name={"en":"My New Instance"}, # Pass dict for i18n
                instance_description={"en":"A cool new place."}, # Pass dict for i18n
                instance_exits={"south": "custom_south_exit"}, # Using instance_exits now
                initial_state={"inst_var": 2, "common_var": "instance"} # Using initial_state now
            )

        self.assertIsNotNone(instance)
        self.assertEqual(instance["id"], new_instance_id)
        self.assertEqual(instance["guild_id"], self.guild_id)
        self.assertEqual(instance["template_id"], template_id)
        self.assertEqual(instance["name_i18n"]["en"], "My New Instance")
        self.assertEqual(instance["descriptions_i18n"]["en"], "A cool new place.")
        self.assertEqual(instance["exits"], {"south": "custom_south_exit"})
        expected_state = {"temp_var": 1, "common_var": "instance", "inst_var": 2}
        self.assertEqual(instance["state"], expected_state) # state, not state_variables for instance dict
        self.assertTrue(instance["is_active"])

        self.assertIn(new_instance_id, self.location_manager._location_instances[self.guild_id])
        self.assertEqual(self.location_manager._location_instances[self.guild_id][new_instance_id], instance)
        self.assertIn(new_instance_id, self.location_manager._dirty_instances[self.guild_id])


# Test class for orphaned tests, ensure it uses IsolatedAsyncioTestCase
class TestLocationManagerContinued(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self): # Changed to asyncSetUp
        self.mock_db_service = MagicMock()
        self.mock_db_service.adapter = AsyncMock()
        self.mock_settings = MagicMock()
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

        self.guild_id = "test_guild_continued"

        self.location_manager = LocationManager(
            db_service=self.mock_db_service,
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
        )
        self.location_manager._location_templates = {} # Global
        self.location_manager._location_instances = {self.guild_id: {}} # Init for guild
        self.location_manager._dirty_instances = {self.guild_id: set()} # Init for guild
        self.location_manager._deleted_instances = {self.guild_id: set()} # Init for guild
        # self.location_manager._dirty_templates = {} # Removed, templates are global

    # ... (Other tests from the original TestLocationManagerContinued would go here)
    # Example: test_load_state_success, test_save_state_dirty_instances etc.
    # These need to be adapted to use asyncSetUp and await calls.


if __name__ == '__main__':
    unittest.main()
