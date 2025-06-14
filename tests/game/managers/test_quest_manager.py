import unittest
from unittest.mock import AsyncMock, patch, MagicMock
import uuid
import json
import time

from bot.game.managers.quest_manager import QuestManager
from bot.game.models.quest import Quest
from bot.ai.ai_data_models import GenerationContext # Import the actual GenerationContext

class TestQuestManager(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self): # Changed from setUp to asyncSetUp for IsolatedAsyncioTestCase
        self.mock_db_service = MagicMock() # For QuestManager's _db_service
        self.mock_db_service.adapter = AsyncMock() # For adapter calls like save_generated_quest

        self.mock_settings = {
            "campaign_data": {"quest_templates": []},
            "default_language": "en" # For name derivation in QuestManager
        }
        self.mock_npc_manager = AsyncMock()
        self.mock_character_manager = AsyncMock()
        self.mock_item_manager = AsyncMock()
        self.mock_rule_engine = AsyncMock()
        self.mock_relationship_manager = AsyncMock()
        self.mock_consequence_processor = AsyncMock()
        self.mock_game_log_manager = AsyncMock()
        self.mock_prompt_generator = AsyncMock()
        self.mock_openai_service = AsyncMock()
        self.mock_ai_validator = AsyncMock()
        self.mock_notification_service = AsyncMock() # Though not used in all methods here

        self.quest_manager = QuestManager(
            db_service=self.mock_db_service, # Pass the MagicMock for db_service
            settings=self.mock_settings,
            npc_manager=self.mock_npc_manager,
            character_manager=self.mock_character_manager,
            item_manager=self.mock_item_manager,
            rule_engine=self.mock_rule_engine,
            relationship_manager=self.mock_relationship_manager,
            consequence_processor=self.mock_consequence_processor,
            game_log_manager=self.mock_game_log_manager,
            multilingual_prompt_generator=self.mock_prompt_generator,
            openai_service=self.mock_openai_service,
            ai_validator=self.mock_ai_validator,
            notification_service=self.mock_notification_service # Added
        )

        # Mock character existence for tests that need it
        # Ensure this mock is consistent with how CharacterManager returns objects
        self.mock_player_instance = MagicMock()
        self.mock_player_instance.id = "test_char_id"
        self.mock_player_instance.name = "Test Character" # For logging/debug or if QuestManager uses it
        self.mock_character_manager.get_character.return_value = self.mock_player_instance # Changed to get_character


    async def test_start_quest_ai_pending_moderation(self):
        guild_id = "test_guild_q_ai_success"
        character_id = "test_char_id" # This is player's character_id, not discord_id here
        quest_template_id = "AI:generate_epic_quest"
        user_id = "test_user_quest_mod" # This is discord_id
        mock_validated_quest_data = {
            "name_i18n": {"en": "The Grand AI Quest"},
            "description_i18n": {"en": "An epic journey awaits."},
            "objectives": [{"id": "obj1", "description_i18n": {"en": "Slay the dragon"}}],
            "template_id": "AI_epic_quest_1"
        }

        self.quest_manager.generate_quest_details_from_ai = AsyncMock(return_value=mock_validated_quest_data)
        self.mock_db_service.adapter.save_pending_moderation_request.return_value = None # Simulate success

        # Mock player status update dependencies
        self.mock_character_manager.get_character_by_discord_id.return_value = self.mock_player_instance
        self.quest_manager._status_manager = AsyncMock() # Ensure StatusManager is on QuestManager if used directly
        self.quest_manager._notification_service = self.mock_notification_service # Ensure NotificationService is available


        expected_request_id_obj = uuid.uuid4()
        with patch('uuid.uuid4', return_value=expected_request_id_obj):
            result = await self.quest_manager.start_quest(
                guild_id, character_id, quest_template_id, user_id=user_id # user_id is discord_id
            )

        expected_request_id_str = str(expected_request_id_obj)
        self.assertEqual(result, {"status": "pending_moderation", "request_id": expected_request_id_str})

        self.mock_db_service.adapter.save_pending_moderation_request.assert_called_once()
        call_args = self.mock_db_service.adapter.save_pending_moderation_request.call_args[0]
        self.assertEqual(call_args[0], expected_request_id_str)
        self.assertEqual(call_args[1], guild_id)
        self.assertEqual(call_args[2], user_id) # user_id (discord_id) for moderation request
        self.assertEqual(call_args[3], "quest")
        self.assertEqual(json.loads(call_args[4]), mock_validated_quest_data)

        # Verify player status update and notification (added in previous subtask)
        self.mock_character_manager.get_character_by_discord_id.assert_called_once_with(guild_id, user_id)
        # Assuming QuestManager now has self._status_manager if it's directly calling it.
        # If it's passed via context, then this mock setup needs adjustment.
        # For now, assuming it's an attribute from __init__ or mocked directly.
        # self.quest_manager._status_manager.add_status_effect_to_entity.assert_called_once()
        self.mock_notification_service.send_moderation_request_alert.assert_called_once()


    async def test_start_quest_ai_generation_fails(self):
        guild_id = "test_guild_q_ai_fail"
        character_id = "test_char_id"
        quest_template_id = "AI:generate_failed_quest"
        user_id = "test_user_q_fail"

        self.quest_manager.generate_quest_details_from_ai = AsyncMock(return_value=None)

        result = await self.quest_manager.start_quest(
            guild_id, character_id, quest_template_id, user_id=user_id
        )

        self.assertIsNone(result)
        self.mock_db_service.adapter.save_pending_moderation_request.assert_not_called()

    async def test_start_quest_ai_no_user_id(self):
        guild_id = "test_guild_q_ai_no_user"
        character_id = "test_char_id"
        quest_template_id = "AI:generate_quest_no_user"
        mock_validated_data = {"name_i18n": {"en": "Quest No User"}}
        self.quest_manager.generate_quest_details_from_ai = AsyncMock(return_value=mock_validated_data)

        result = await self.quest_manager.start_quest(
            guild_id, character_id, quest_template_id # No user_id in kwargs
        )
        self.assertIsNone(result)
        self.mock_db_service.adapter.save_pending_moderation_request.assert_not_called()


    async def test_start_quest_non_ai_from_template(self):
        guild_id = "test_guild_q_template"
        character_id = "test_char_id"
        quest_template_id = "sample_quest_001"

        # Mock character existence check in start_quest
        self.mock_character_manager.get_character.return_value = MagicMock(id=character_id)


        template_data = {
            "id": quest_template_id,
            "name_i18n": {"en": "Sample Quest"},
            "description_i18n": {"en": "A simple task."},
            "objectives": [{"id": "obj1", "description_i18n": {"en": "Do something."}}], # objectives should be list of dicts
            "rewards_i18n": {}, # Should be dict
            "data": {} # Should be dict
        }
        self.quest_manager._quest_templates.setdefault(guild_id, {})[quest_template_id] = template_data

        result = await self.quest_manager.start_quest(
            guild_id, character_id, quest_template_id
        )

        self.assertIsNotNone(result)
        self.assertIsInstance(result, dict)
        self.assertNotIn("status", result)
        self.assertEqual(result["template_id"], quest_template_id)
        self.assertEqual(result["character_id"], character_id)
        self.assertTrue(result["id"] is not None)
        self.mock_db_service.adapter.save_pending_moderation_request.assert_not_called()
        self.assertIn(character_id, self.quest_manager._dirty_quests.get(guild_id, set()))


    async def test_generate_quest_details_from_ai_success(self):
        guild_id = "test_guild_gen_q_success"
        quest_idea = "a quest about finding a lost cat"
        expected_data = {"name_i18n": {"en": "Find Mittens!"}, "objectives": []}

        self.mock_prompt_generator.generate_quest_prompt.return_value = {"system": "sys", "user": "usr"}
        self.mock_openai_service.generate_structured_multilingual_content = AsyncMock(return_value={"json_string": json.dumps(expected_data)})
        self.mock_ai_validator.validate_ai_response = AsyncMock(return_value={
            "overall_status": "success",
            "entities": [{"validated_data": expected_data}]
        })

        # Create a dummy GenerationContext instance
        dummy_event_data = {"type": "test_event"}
        generation_context_arg = GenerationContext(event=dummy_event_data, guild_id=guild_id, lang="en")

        result = await self.quest_manager.generate_quest_details_from_ai(guild_id, quest_idea, generation_context_arg)
        self.assertEqual(result, expected_data)

    async def test_generate_quest_details_from_ai_openai_fails(self):
        guild_id = "gid_openai_fail"
        quest_idea = "concept_openai_fail"
        self.mock_prompt_generator.generate_quest_prompt.return_value = {"system": "sys", "user": "usr"}
        self.mock_openai_service.generate_structured_multilingual_content = AsyncMock(return_value={"error": "OpenAI down"})

        dummy_event_data = {"type": "test_event"}
        generation_context_arg = GenerationContext(event=dummy_event_data, guild_id=guild_id, lang="en")

        result = await self.quest_manager.generate_quest_details_from_ai(guild_id, quest_idea, generation_context_arg)
        self.assertIsNone(result)

    async def test_generate_quest_details_from_ai_validator_fails(self):
        guild_id = "gid_validator_fail"
        quest_idea = "concept_validator_fail"
        self.mock_prompt_generator.generate_quest_prompt.return_value = {"system": "sys", "user": "usr"}
        self.mock_openai_service.generate_structured_multilingual_content = AsyncMock(return_value={"json_string": "{}"})
        self.mock_ai_validator.validate_ai_response = AsyncMock(return_value={"global_errors": ["validation failed"]})

        dummy_event_data = {"type": "test_event"}
        generation_context_arg = GenerationContext(event=dummy_event_data, guild_id=guild_id, lang="en")

        result = await self.quest_manager.generate_quest_details_from_ai(guild_id, quest_idea, generation_context_arg)
        self.assertIsNone(result)

    async def test_generate_quest_details_from_ai_validator_requires_moderation(self):
        guild_id = "gid_validator_mod"
        quest_idea = "concept_validator_mod"
        self.mock_prompt_generator.generate_quest_prompt.return_value = {"system": "sys", "user": "usr"}
        self.mock_openai_service.generate_structured_multilingual_content = AsyncMock(return_value={"json_string": "{}"})
        self.mock_ai_validator.validate_ai_response = AsyncMock(return_value={
            "overall_status": "requires_manual_review",
            "entities": [{"validated_data": {"name":"Needs Review"}, "requires_moderation": True}]
        })

        dummy_event_data = {"type": "test_event"}
        generation_context_arg = GenerationContext(event=dummy_event_data, guild_id=guild_id, lang="en")

        result = await self.quest_manager.generate_quest_details_from_ai(guild_id, quest_idea, generation_context_arg)
        self.assertIsNone(result)

    async def test_start_quest_from_moderated_data_success(self):
        """Test starting a quest from moderated, pre-validated data, ensuring save_generated_quest is called."""
        guild_id = "test_guild_mod_quest"
        character_id = "test_char_for_mod_quest"

        # Mock character existence
        self.mock_character_manager.get_character.return_value = MagicMock(id=character_id, name="TestChar")

        moderated_quest_data = {
            "id": str(uuid.uuid4()), # Ensure it has an ID for Quest.from_dict
            "name_i18n": {"en": "The Approved Adventure"},
            "description_i18n": {"en": "A quest vetted by the powers that be."},
            "objectives": [{"id": "obj_approved_1", "description_i18n": {"en": "Retrieve the artifact."}}],
            "rewards_i18n": {"items": [{"item_id": "gem_of_approval", "quantity": 1}]}, # Example structure
            "template_id": "moderated_ai_quest_001",
            "giver_entity_id": "npc_quest_giver_approved",
            "guild_id": guild_id, # Important for Quest model
            "is_ai_generated": True # Should be set by the flow before calling this
            # Other fields expected by Quest.from_dict or Quest model
        }
        context_data = {"some_context_info": "value_for_quest", "bot_language": "en"}

        # Mock save_generated_quest (which is an async method on QuestManager itself)
        # We are testing start_quest_from_moderated_data, which CALLS save_generated_quest.
        # So, we patch 'self.quest_manager.save_generated_quest'
        with patch.object(self.quest_manager, 'save_generated_quest', new_callable=AsyncMock) as mock_save_gen_quest:
            mock_save_gen_quest.return_value = True # Simulate successful save

            activated_quest_data = await self.quest_manager.start_quest_from_moderated_data(
                guild_id, character_id, moderated_quest_data, context_data
            )

        self.assertIsNotNone(activated_quest_data)
        self.assertIsInstance(activated_quest_data, dict)
        self.assertEqual(activated_quest_data["character_id"], character_id)
        self.assertEqual(activated_quest_data["name_i18n"]["en"], "The Approved Adventure")
        self.assertEqual(activated_quest_data["status"], "active")
        self.assertTrue(activated_quest_data["is_ai_generated"])
        # self.assertTrue(activated_quest_data["is_moderated"]) # Not a standard flag in Quest model/flow

        # Check if quest is in active quests cache and marked dirty
        self.assertIn(activated_quest_data["id"], self.quest_manager._active_quests.get(guild_id, {}).get(character_id, {}))
        self.assertIn(character_id, self.quest_manager._dirty_quests.get(guild_id, set()))

        # Verify save_generated_quest was called
        mock_save_gen_quest.assert_called_once()
        # The argument to save_generated_quest should be a Quest object.
        # We can check its type or specific attributes if necessary.
        saved_quest_obj_arg = mock_save_gen_quest.call_args[0][0]
        self.assertIsInstance(saved_quest_obj_arg, Quest)
        self.assertEqual(saved_quest_obj_arg.id, moderated_quest_data["id"])
        self.assertEqual(saved_quest_obj_arg.name_i18n["en"], "The Approved Adventure")


        # Verify no AI services were called for this activation path
        self.mock_prompt_generator.generate_quest_prompt.assert_not_called()
        self.mock_openai_service.generate_structured_multilingual_content.assert_not_called()
        self.mock_ai_validator.validate_ai_response.assert_not_called()
        self.mock_db_service.adapter.save_pending_moderation_request.assert_not_called()

        # Verify consequences are processed if present in data
        # Create a dummy Quest object as context for consequence processing
        quest_obj_for_consequences = Quest.from_dict(moderated_quest_data)

        if "consequences" in moderated_quest_data and "on_start" in moderated_quest_data["consequences"]:
            self.mock_consequence_processor.process_consequences.assert_called_once()
            # More detailed check of consequence call args if needed
            # args_consq, _ = self.mock_consequence_processor.process_consequences.call_args
            # self.assertEqual(args_consq[0], moderated_quest_data["consequences"]["on_start"])
            # self.assertEqual(args_consq[1]['quest']['id'], quest_obj_for_consequences.id)
        else:
            self.mock_consequence_processor.process_consequences.assert_not_called()


if __name__ == '__main__':
    unittest.main()
