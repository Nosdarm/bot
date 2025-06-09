# tests/game/managers/test_npc_manager.py
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import json # Added import for json
import uuid # Added import for uuid

from bot.game.managers.npc_manager import NpcManager
# Assuming other necessary imports like NPC model, or other managers if their direct methods are called.
# from bot.game.models.npc import NPC

# If NpcManager is in a class that inherits from something providing asyncio support:
# class TestNpcManager(unittest.IsolatedAsyncioTestCase):
# Otherwise, ensure your test runner handles async tests.
class TestNpcManager(unittest.IsolatedAsyncioTestCase): # Using IsolatedAsyncioTestCase for async tests

    def setUp(self):
        # Mock services that are injected into NpcManager
        self.mock_db_service = MagicMock()
        self.mock_db_service.adapter = AsyncMock() # The adapter has async methods

        self.mock_settings = {"npc_generation_ai_settings": {}} # Basic settings mock
        self.mock_item_manager = AsyncMock()
        self.mock_status_manager = AsyncMock()
        self.mock_party_manager = AsyncMock()
        self.mock_character_manager = AsyncMock()
        self.mock_rule_engine = AsyncMock()
        self.mock_combat_manager = AsyncMock()
        self.mock_dialogue_manager = AsyncMock()
        self.mock_location_manager = AsyncMock()
        self.mock_game_log_manager = AsyncMock()
        self.mock_multilingual_prompt_generator = AsyncMock()
        self.mock_openai_service = AsyncMock()
        self.mock_ai_validator = AsyncMock()
        self.mock_campaign_loader = MagicMock() # Assuming sync methods for now
        self.mock_notification_service = AsyncMock()

        self.npc_manager = NpcManager(
            db_service=self.mock_db_service,
            settings=self.mock_settings,
            item_manager=self.mock_item_manager,
            status_manager=self.mock_status_manager,
            party_manager=self.mock_party_manager,
            character_manager=self.mock_character_manager,
            rule_engine=self.mock_rule_engine,
            combat_manager=self.mock_combat_manager,
            dialogue_manager=self.mock_dialogue_manager,
            location_manager=self.mock_location_manager,
            game_log_manager=self.mock_game_log_manager,
            multilingual_prompt_generator=self.mock_multilingual_prompt_generator,
            openai_service=self.mock_openai_service,
            ai_validator=self.mock_ai_validator,
            campaign_loader=self.mock_campaign_loader,
            notification_service=self.mock_notification_service
        )
        # Pre-load archetypes or mock _load_npc_archetypes if it interferes
        self.npc_manager._npc_archetypes = {}


    async def test_create_npc_ai_path_moderation_flow(self):
        guild_id = "test_guild_123"
        npc_template_id = "AI:Powerful Dragon" # Trigger AI path
        user_id = "test_user_456"

        # 1. Mock AI Generation and Validation
        mock_ai_generated_data = {
            "name": "Sparky the Dragon",
            "name_i18n": {"en": "Sparky the Dragon"},
            "archetype": "dragon_young",
            "level_suggestion": 10
            # Ensure this data matches what generate_npc_details_from_ai is expected to return
            # after validation (i.e., the content of validated_data)
        }
        # NpcManager.generate_npc_details_from_ai calls:
        #   - multilingual_prompt_generator.generate_npc_profile_prompt
        #   - openai_service.generate_structured_multilingual_content
        #   - ai_validator.validate_ai_response
        self.mock_multilingual_prompt_generator.generate_npc_profile_prompt.return_value = {"system": "sys_prompt", "user": "user_prompt"}
        self.mock_openai_service.generate_structured_multilingual_content.return_value = {"json_string": json.dumps(mock_ai_generated_data)}
        self.mock_ai_validator.validate_ai_response.return_value = {
            "overall_status": "success",
            "entities": [{"validated_data": mock_ai_generated_data, "errors": [], "notifications": []}],
            "global_errors": []
        }

        # 2. Mock DB save_pending_moderation_request
        self.mock_db_service.adapter.save_pending_moderation_request.return_value = None # Simulates successful execution

        # 3. Mock CharacterManager and StatusManager for player status update
        mock_player_character = MagicMock()
        mock_player_character.id = "player_char_id_789"
        # Ensure 'name' attribute exists for logging if get_character_by_discord_id returns an object with it
        mock_player_character.name = "TestPlayer"
        self.mock_character_manager.get_character_by_discord_id.return_value = mock_player_character
        self.mock_status_manager.add_status_effect_to_entity.return_value = "status_effect_id_abc"

        # 4. Mock NotificationService
        self.mock_notification_service.send_moderation_request_alert.return_value = None

        # Call the method
        result = await self.npc_manager.create_npc(
            guild_id=guild_id,
            npc_template_id=npc_template_id,
            user_id=user_id,
            # time_manager might be needed by add_status_effect_to_entity context
            time_manager=AsyncMock()
        )

        # Assertions
        self.assertIsNotNone(result)
        self.assertEqual(result.get("status"), "pending_moderation")
        self.assertTrue("request_id" in result)
        request_id = result["request_id"]

        # Verify AI generation path was taken
        self.mock_multilingual_prompt_generator.generate_npc_profile_prompt.assert_called_once()
        self.mock_openai_service.generate_structured_multilingual_content.assert_called_once()
        self.mock_ai_validator.validate_ai_response.assert_called_once_with(
            ai_json_string=json.dumps(mock_ai_generated_data),
            expected_structure="single_npc",
            existing_npc_ids=set(),
            existing_quest_ids=set(),
            existing_item_template_ids=set()
        )

        # Verify moderation save
        self.mock_db_service.adapter.save_pending_moderation_request.assert_awaited_once()
        args_save, _ = self.mock_db_service.adapter.save_pending_moderation_request.call_args
        self.assertEqual(args_save[0], request_id)
        self.assertEqual(args_save[1], guild_id)
        self.assertEqual(args_save[2], user_id)
        self.assertEqual(args_save[3], "npc")
        self.assertEqual(json.loads(args_save[4]), mock_ai_generated_data)

        # Verify player status update
        self.mock_character_manager.get_character_by_discord_id.assert_awaited_once_with(guild_id, user_id)
        self.mock_status_manager.add_status_effect_to_entity.assert_awaited_once()

        # Check the arguments of add_status_effect_to_entity more carefully
        # call_args gives a tuple (args, kwargs). We are interested in kwargs['context']
        called_args_status, called_kwargs_status = self.mock_status_manager.add_status_effect_to_entity.call_args
        self.assertEqual(called_args_status[0], mock_player_character.id) # target_id
        self.assertEqual(called_args_status[1], "Character") # target_type
        self.assertEqual(called_args_status[2], "common.awaiting_moderation") # status_type
        self.assertIn('context', called_kwargs_status)
        self.assertEqual(called_kwargs_status['context']['guild_id'], guild_id)


        # Verify notification
        self.mock_notification_service.send_moderation_request_alert.assert_awaited_once()
        args_notify, _ = self.mock_notification_service.send_moderation_request_alert.call_args
        self.assertEqual(args_notify[0], guild_id)
        self.assertEqual(args_notify[1], request_id)
        self.assertEqual(args_notify[2], "npc")
        self.assertEqual(args_notify[3], user_id)
        self.assertIn("name", args_notify[4]) # content_summary
        self.assertEqual(args_notify[4]["name"], mock_ai_generated_data["name"])
        self.assertIn("Use /approve", args_notify[5]) # moderation_interface_link

# Required for running tests if this file is executed directly
if __name__ == '__main__':
    unittest.main()
