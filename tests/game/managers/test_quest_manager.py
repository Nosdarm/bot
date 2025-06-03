import unittest
from unittest.mock import AsyncMock, patch, MagicMock
import uuid
import json
import time

from bot.game.managers.quest_manager import QuestManager
# Assuming Quest model is not directly used, but data dicts are.

class TestQuestManager(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.mock_db_adapter = AsyncMock()
        self.mock_settings = {"campaign_data": {"quest_templates": []}} # Basic settings
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
        # Mock CampaignLoader if QuestManager uses it directly for templates,
        # otherwise QuestManager's own _quest_templates cache is loaded from settings.

        self.quest_manager = QuestManager(
            db_adapter=self.mock_db_adapter,
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
            ai_validator=self.mock_ai_validator
        )
        # Mock character existence for tests that need it
        self.mock_character_manager.get_character_by_id = AsyncMock(return_value=MagicMock(id="test_char_id"))


    async def test_start_quest_ai_pending_moderation(self):
        guild_id = "test_guild_q_ai_success"
        character_id = "test_char_id"
        quest_template_id = "AI:generate_epic_quest"
        user_id = "test_user_quest_mod"
        mock_validated_quest_data = {
            "name_i18n": {"en": "The Grand AI Quest"},
            "description_i18n": {"en": "An epic journey awaits."},
            "objectives": [{"id": "obj1", "description_i18n": {"en": "Slay the dragon"}}],
            "template_id": "AI_epic_quest_1" # AI might provide a template_id
        }

        self.quest_manager.generate_quest_details_from_ai = AsyncMock(return_value=mock_validated_quest_data)

        expected_request_id = str(uuid.uuid4())
        with patch('uuid.uuid4', return_value=uuid.UUID(expected_request_id)):
            result = await self.quest_manager.start_quest(
                guild_id, character_id, quest_template_id, user_id=user_id
            )

        self.assertEqual(result, {"status": "pending_moderation", "request_id": expected_request_id})
        self.mock_db_adapter.save_pending_moderation_request.assert_called_once()
        call_args = self.mock_db_adapter.save_pending_moderation_request.call_args[0]
        self.assertEqual(call_args[0], expected_request_id)
        self.assertEqual(call_args[1], guild_id)
        self.assertEqual(call_args[2], user_id)
        self.assertEqual(call_args[3], "quest")
        self.assertEqual(json.loads(call_args[4]), mock_validated_quest_data)

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
        self.mock_db_adapter.save_pending_moderation_request.assert_not_called()

    async def test_start_quest_ai_no_user_id(self):
        guild_id = "test_guild_q_ai_no_user"
        character_id = "test_char_id"
        quest_template_id = "AI:generate_quest_no_user"
        mock_validated_data = {"name_i18n": {"en": "Quest No User"}}
        self.quest_manager.generate_quest_details_from_ai = AsyncMock(return_value=mock_validated_data)

        result = await self.quest_manager.start_quest(
            guild_id, character_id, quest_template_id # No user_id in kwargs
        )
        self.assertIsNone(result) # Should fail because user_id is required for moderation
        self.mock_db_adapter.save_pending_moderation_request.assert_not_called()


    async def test_start_quest_non_ai_from_template(self):
        guild_id = "test_guild_q_template"
        character_id = "test_char_id"
        quest_template_id = "sample_quest_001"

        template_data = {
            "id": quest_template_id,
            "name_i18n": {"en": "Sample Quest"},
            "description_i18n": {"en": "A simple task."},
            "objectives": [{"id": "obj1", "description": "Do something."}],
            "rewards_i18n": {},
            "data": {}
        }
        # Setup QuestManager's internal template cache or mock get_quest_template
        self.quest_manager._quest_templates[guild_id] = {quest_template_id: template_data}

        result = await self.quest_manager.start_quest(
            guild_id, character_id, quest_template_id
        )

        self.assertIsNotNone(result)
        self.assertIsInstance(result, dict)
        self.assertNotIn("status", result) # Should be the quest data dict directly
        self.assertEqual(result["template_id"], quest_template_id)
        self.assertEqual(result["character_id"], character_id)
        self.assertTrue(result["id"] is not None) # New quest instance ID
        self.mock_db_adapter.save_pending_moderation_request.assert_not_called()
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

        result = await self.quest_manager.generate_quest_details_from_ai(guild_id, quest_idea)
        self.assertEqual(result, expected_data)

    async def test_generate_quest_details_from_ai_openai_fails(self):
        self.mock_prompt_generator.generate_quest_prompt.return_value = {"system": "sys", "user": "usr"}
        self.mock_openai_service.generate_structured_multilingual_content = AsyncMock(return_value={"error": "OpenAI down"})

        result = await self.quest_manager.generate_quest_details_from_ai("gid", "concept")
        self.assertIsNone(result)

    async def test_generate_quest_details_from_ai_validator_fails(self):
        self.mock_prompt_generator.generate_quest_prompt.return_value = {"system": "sys", "user": "usr"}
        self.mock_openai_service.generate_structured_multilingual_content = AsyncMock(return_value={"json_string": "{}"})
        self.mock_ai_validator.validate_ai_response = AsyncMock(return_value={"global_errors": ["validation failed"]})

        result = await self.quest_manager.generate_quest_details_from_ai("gid", "concept")
        self.assertIsNone(result)

    async def test_generate_quest_details_from_ai_validator_requires_moderation(self):
        self.mock_prompt_generator.generate_quest_prompt.return_value = {"system": "sys", "user": "usr"}
        self.mock_openai_service.generate_structured_multilingual_content = AsyncMock(return_value={"json_string": "{}"})
        self.mock_ai_validator.validate_ai_response = AsyncMock(return_value={
            "overall_status": "requires_manual_review",
            "entities": [{"validated_data": {"name":"Needs Review"}, "requires_moderation": True}]
        })
        # generate_quest_details_from_ai returns None if requires_moderation is True
        result = await self.quest_manager.generate_quest_details_from_ai("gid", "concept")
        self.assertIsNone(result)

    async def test_start_quest_from_moderated_data(self):
        """Test starting a quest from moderated, pre-validated data."""
        guild_id = "test_guild_mod_quest"
        character_id = "test_char_for_mod_quest"

        # Mock that the character exists
        self.mock_character_manager.get_character_by_id.return_value = MagicMock(id=character_id)

        moderated_quest_data = {
            "name_i18n": {"en": "The Approved Adventure"},
            "description_i18n": {"en": "A quest vetted by the powers that be."},
            "objectives": [{"id": "obj_approved_1", "description_i18n": {"en": "Retrieve the artifact."}}],
            "rewards_i18n": {"items": [{"item_id": "gem_of_approval", "quantity": 1}]},
            "template_id": "moderated_ai_quest_001", # Could be original AI template or a new one
            "giver_entity_id": "npc_quest_giver_approved",
            # ... any other fields that QuestManager expects from validated AI data
        }
        context_data = {"some_context_info": "value_for_quest"}

        # The method being tested
        activated_quest_data = await self.quest_manager.start_quest_from_moderated_data(
            guild_id, character_id, moderated_quest_data, context_data
        )

        self.assertIsNotNone(activated_quest_data)
        self.assertIsInstance(activated_quest_data, dict)
        self.assertEqual(activated_quest_data["character_id"], character_id)
        self.assertEqual(activated_quest_data["name_i18n"]["en"], "The Approved Adventure")
        self.assertEqual(activated_quest_data["status"], "active")
        self.assertTrue(activated_quest_data["is_ai_generated"]) # Should be marked as AI originated
        self.assertTrue(activated_quest_data["is_moderated"])   # Should be marked as moderated

        # Check if quest is in active quests cache and marked dirty
        self.assertIn(activated_quest_data["id"], self.quest_manager._active_quests.get(guild_id, {}).get(character_id, {}))
        self.assertIn(character_id, self.quest_manager._dirty_quests.get(guild_id, set()))

        # Verify no AI services were called for this activation path
        self.mock_prompt_generator.generate_quest_prompt.assert_not_called()
        self.mock_openai_service.generate_structured_multilingual_content.assert_not_called()
        self.mock_ai_validator.validate_ai_response.assert_not_called()
        self.mock_db_adapter.save_pending_moderation_request.assert_not_called()

        # Verify consequences are processed if present in data
        if "consequences" in moderated_quest_data and "on_start" in moderated_quest_data["consequences"]:
            self.mock_consequence_processor.process_consequences.assert_called_once()
        else: # If no consequences in test data, ensure it wasn't called
            self.mock_consequence_processor.process_consequences.assert_not_called()


if __name__ == '__main__':
    unittest.main()
