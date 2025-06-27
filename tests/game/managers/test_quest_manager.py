import unittest
from unittest.mock import AsyncMock, patch, MagicMock, ANY
import uuid
import json
import time
from typing import Dict, Any, List, Optional, cast

from bot.game.managers.quest_manager import QuestManager
from bot.game.models.quest import Quest, QuestStep
# Removed QuestCompletionValidationResult, ValidatedQuestData as they are not actual return types of validator
from bot.ai.ai_data_models import GenerationContext, ValidationIssue
from bot.database.models import Player # Corrected import
from bot.database.models import GeneratedQuest as DBGeneratedQuest # Corrected import path
from bot.database.models import QuestStepTable as DBQuestStepTable # Corrected import path
from sqlalchemy.ext.asyncio import AsyncSession
from bot.game.managers.game_manager import GameManager # For spec

class TestQuestManager(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.mock_db_service = AsyncMock(spec_set=['adapter', 'get_session']) # More specific spec
        self.mock_db_service.adapter = AsyncMock()

        self.mock_settings = {
            "campaign_data": {"quest_templates": {}}, # Ensure it's a dict
            "default_language": "en"
        }
        self.mock_npc_manager = AsyncMock()
        self.mock_character_manager = AsyncMock(spec_set=['get_character', 'get_character_by_discord_id']) # More specific spec
        self.mock_item_manager = AsyncMock()
        self.mock_rule_engine = AsyncMock()
        self.mock_relationship_manager = AsyncMock()
        self.mock_consequence_processor = AsyncMock()
        self.mock_game_log_manager = AsyncMock(spec_set=['log_event']) # More specific spec
        self.mock_prompt_generator = AsyncMock(spec_set=['generate_quest_prompt']) # More specific spec
        self.mock_openai_service = AsyncMock(spec_set=['generate_structured_multilingual_content']) # More specific spec
        self.mock_ai_validator = AsyncMock(spec_set=['validate_ai_response']) # More specific spec
        self.mock_notification_service = AsyncMock(spec_set=['send_moderation_request_alert']) # More specific spec
        self.mock_game_manager = AsyncMock(spec=GameManager) # Mock GameManager for QuestManager init
        self.mock_game_manager.db_service = self.mock_db_service # Attach mocked services to game_manager
        self.mock_game_manager.character_manager = self.mock_character_manager
        self.mock_game_manager.notification_service = self.mock_notification_service
        self.mock_game_manager.game_log_manager = self.mock_game_log_manager


        self.quest_manager = QuestManager(
            db_service=self.mock_db_service,
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
            notification_service=self.mock_notification_service,
            game_manager=self.mock_game_manager
        )
        self.quest_manager._all_quests = {} # Initialize internal caches
        self.quest_manager._active_quests = {}
        self.quest_manager._dirty_quests = {}


        self.mock_player_instance = MagicMock(spec=Player)
        self.mock_player_instance.id = "test_char_id"
        self.mock_player_instance.name = "Test Character"
        self.mock_player_instance.discord_id = "test_user_id"
        self.mock_player_instance.selected_language = "en"
        self.mock_character_manager.get_character = AsyncMock(return_value=self.mock_player_instance)


    async def test_start_quest_ai_pending_moderation(self):
        guild_id = "test_guild_q_ai_success"
        character_id = "test_char_id"
        quest_template_id = "AI:generate_epic_quest"
        user_id = "test_user_quest_mod"

        # Mock generate_quest_details_from_ai to return a Quest object
        mock_generated_quest_obj = Quest(id=str(uuid.uuid4()), guild_id=guild_id, name_i18n={"en": "The Grand AI Quest"}, description_i18n={"en": "An epic journey awaits."}, steps=[], status="template", is_ai_generated=True, template_id="AI_epic_quest_1")
        self.quest_manager.generate_quest_details_from_ai = AsyncMock(return_value=mock_generated_quest_obj)

        self.mock_character_manager.get_character_by_discord_id = AsyncMock(return_value=self.mock_player_instance)

        # Mock _save_pending_moderation_for_quest
        with patch.object(self.quest_manager, '_save_pending_moderation_for_quest', new_callable=AsyncMock) as mock_save_pending:
            mock_save_pending.return_value = "dummy_request_id" # Assume it returns the request ID string
            result = await self.quest_manager.start_quest(
                guild_id, character_id, quest_template_id, user_id=user_id
            )

        self.assertEqual(result, {"status": "pending_moderation", "request_id": "dummy_request_id", "quest_data_preview": mock_generated_quest_obj.model_dump(exclude_none=True)})
        mock_save_pending.assert_awaited_once_with(guild_id, user_id, character_id, mock_generated_quest_obj, ANY) # ANY for context
        self.mock_character_manager.get_character_by_discord_id.assert_called_once_with(guild_id, user_id)
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

        self.assertEqual(result, {"status": "error", "message": "Failed to generate AI quest details."})

    async def test_start_quest_ai_no_user_id(self):
        guild_id = "test_guild_q_ai_no_user"
        character_id = "test_char_id"
        quest_template_id = "AI:generate_quest_no_user"

        mock_generated_quest_obj = Quest(id=str(uuid.uuid4()), guild_id=guild_id, name_i18n={"en": "Quest No User"}, description_i18n={"en": "Desc"}, steps=[], status="template", is_ai_generated=True)
        self.quest_manager.generate_quest_details_from_ai = AsyncMock(return_value=mock_generated_quest_obj)

        with patch.object(self.quest_manager, '_save_pending_moderation_for_quest', new_callable=AsyncMock) as mock_save_pending:
            mock_save_pending.return_value = "dummy_request_id_no_user"
            result = await self.quest_manager.start_quest(
                guild_id, character_id, quest_template_id # No user_id
            )
        self.assertEqual(result, {"status": "pending_moderation", "request_id": "dummy_request_id_no_user", "quest_data_preview": mock_generated_quest_obj.model_dump(exclude_none=True)})
        mock_save_pending.assert_awaited_once()


    async def test_accept_quest_success(self):
        guild_id = "guild_accept_q1"
        player_pk = "player_pk_for_accept"
        quest_db_id = "db_quest_to_accept_1"
        first_step_id = "step_1_of_db_quest_1"

        mock_player_db = MagicMock(spec=Player)
        mock_player_db.id = player_pk; mock_player_db.guild_id = guild_id; mock_player_db.level = 5
        mock_player_db.active_quests = None; mock_player_db.selected_language = "en"

        mock_quest_to_accept_db = MagicMock(spec=DBGeneratedQuest)
        mock_quest_to_accept_db.id = quest_db_id; mock_quest_to_accept_db.guild_id = guild_id
        mock_quest_to_accept_db.prerequisites_json = json.dumps({"min_level": 3})
        mock_quest_to_accept_db.title_i18n = {"en": "The Grand Test Quest"}; mock_quest_to_accept_db.suggested_level = 1

        mock_first_step_db = MagicMock(spec=DBQuestStepTable)
        mock_first_step_db.id = first_step_id; mock_first_step_db.quest_id = quest_db_id
        mock_first_step_db.guild_id = guild_id; mock_first_step_db.step_order = 0
        mock_first_step_db.title_i18n = {"en": "First Objective"}

        mock_session = AsyncMock(spec=AsyncSession)
        async def mock_get_side_effect(model_class, pk_value):
            if model_class == Player and pk_value == player_pk: return mock_player_db
            if model_class == DBGeneratedQuest and pk_value == quest_db_id: return mock_quest_to_accept_db
            return None
        mock_session.get = AsyncMock(side_effect=mock_get_side_effect)

        mock_execute_result_for_steps = AsyncMock()
        mock_execute_result_for_steps.scalars.return_value.all.return_value = [mock_first_step_db]
        mock_session.execute.return_value = mock_execute_result_for_steps
        mock_session.add = MagicMock(); mock_session.commit = AsyncMock()

        mock_session_cm = AsyncMock(); mock_session_cm.__aenter__.return_value = mock_session
        self.mock_db_service.get_session = MagicMock(return_value=mock_session_cm)

        success, message = await self.quest_manager.accept_quest(guild_id, player_pk, quest_db_id)

        self.assertTrue(success)
        self.assertIn("Quest 'The Grand Test Quest' accepted!", message)
        self.assertIn("First Objective", message)
        mock_session.get.assert_any_call(Player, player_pk)
        mock_session.get.assert_any_call(DBGeneratedQuest, quest_db_id)
        mock_session.execute.assert_awaited_once()
        mock_session.add.assert_called_once_with(mock_player_db)
        self.assertIsNotNone(mock_player_db.active_quests)
        active_quests_list = json.loads(cast(str, mock_player_db.active_quests)) # Cast to str
        self.assertEqual(len(active_quests_list), 1)
        self.assertEqual(active_quests_list[0]["quest_id"], quest_db_id)
        self.assertEqual(active_quests_list[0]["current_step_id"], first_step_id)
        self.assertEqual(active_quests_list[0]["status"], "in_progress")
        mock_session.commit.assert_awaited_once()
        self.mock_game_log_manager.log_event.assert_awaited_once()

    async def test_accept_quest_already_active(self):
        guild_id = "guild_accept_q_active"; player_pk = "player_pk_active"; quest_db_id = "db_quest_active_1"
        active_quest_entry = {"quest_id": quest_db_id, "status": "in_progress", "current_step_id": "s1"}
        mock_player_db = MagicMock(spec=Player)
        mock_player_db.id = player_pk; mock_player_db.guild_id = guild_id
        mock_player_db.active_quests = json.dumps([active_quest_entry])

        mock_quest_to_accept_db = MagicMock(spec=DBGeneratedQuest)
        mock_quest_to_accept_db.id = quest_db_id; mock_quest_to_accept_db.guild_id = guild_id

        mock_session = AsyncMock(spec=AsyncSession)
        async def mock_get_side_effect_active(model_class, pk_value):
            if model_class == Player: return mock_player_db
            if model_class == DBGeneratedQuest: return mock_quest_to_accept_db
            return None
        mock_session.get = AsyncMock(side_effect=mock_get_side_effect_active)
        mock_session_cm = AsyncMock(); mock_session_cm.__aenter__.return_value = mock_session
        self.mock_db_service.get_session = MagicMock(return_value=mock_session_cm)

        success, message = await self.quest_manager.accept_quest(guild_id, player_pk, quest_db_id)
        self.assertFalse(success)
        self.assertEqual(message, "You are already on this quest.")
        mock_session.commit.assert_not_called()


    async def _setup_quest_for_event_handling(self, guild_id: str, char_id: str, quest_id: str, steps_data: list, initial_status: str = "active") -> Quest:
        pydantic_steps: List[QuestStep] = []
        for i, step_d in enumerate(steps_data):
            step_d.setdefault("id", f"step_{quest_id}_{i}")
            step_d.setdefault("guild_id", guild_id)
            step_d.setdefault("quest_id", quest_id)
            step_d.setdefault("step_order", i)
            step_d.setdefault("status", "pending")
            pydantic_steps.append(QuestStep(**step_d)) # Use direct instantiation

        quest_obj = Quest(
            id=quest_id, guild_id=guild_id, name_i18n={"en": f"Test Quest {quest_id}"},
            description_i18n={"en": "A quest for testing events."}, steps=pydantic_steps,
            status=initial_status, is_ai_generated=False
        )
        self.quest_manager._all_quests.setdefault(guild_id, {})[quest_id] = quest_obj
        active_quest_dict_for_cache = quest_obj.model_dump()
        active_quest_dict_for_cache.update({ "character_id": char_id, "start_time": time.time() })
        self.quest_manager._active_quests.setdefault(guild_id, {}).setdefault(char_id, {})[quest_id] = active_quest_dict_for_cache
        return quest_obj

    @patch('bot.game.managers.quest_manager.QuestManager._evaluate_abstract_goal', new_callable=AsyncMock)
    @patch('bot.game.managers.quest_manager.QuestManager._mark_step_complete', new_callable=AsyncMock)
    @patch('bot.game.managers.quest_manager.QuestManager.complete_quest', new_callable=AsyncMock)
    async def test_handle_event_completes_step_not_quest(self, mock_complete_quest: AsyncMock, mock_mark_step_complete: AsyncMock, mock_evaluate_goal: AsyncMock):
        guild_id = "event_guild1"; char_id = "event_char1"; quest_id = "event_quest_step_done"
        steps_data = [{"title_i18n": {"en": "Step 1"}, "abstract_goal_json": json.dumps({"type": "EVENT_A"})}, {"title_i18n": {"en": "Step 2"}, "abstract_goal_json": json.dumps({"type": "EVENT_B"})}]
        quest_obj = await self._setup_quest_for_event_handling(guild_id, char_id, quest_id, steps_data)
        mock_evaluate_goal.return_value = True; mock_mark_step_complete.return_value = True
        event_data = {"event_type": "EVENT_A_TRIGGER", "details": {}}
        await self.quest_manager.handle_player_event_for_quest(guild_id, char_id, event_data)
        mock_evaluate_goal.assert_awaited_once_with(guild_id, char_id, quest_obj, quest_obj.steps[0], event_data)
        mock_mark_step_complete.assert_awaited_once_with(guild_id, char_id, quest_id, 0)
        mock_complete_quest.assert_not_called()
        self.assertEqual(quest_obj.steps[0].status, "completed")
        self.assertEqual(quest_obj.steps[1].status, "pending")

    @patch('bot.game.managers.quest_manager.QuestManager._evaluate_abstract_goal', new_callable=AsyncMock)
    @patch('bot.game.managers.quest_manager.QuestManager._mark_step_complete', new_callable=AsyncMock)
    @patch('bot.game.managers.quest_manager.QuestManager.complete_quest', new_callable=AsyncMock)
    async def test_handle_event_completes_last_step_and_quest(self, mock_complete_quest: AsyncMock, mock_mark_step_complete: AsyncMock, mock_evaluate_goal: AsyncMock):
        guild_id = "event_guild2"; char_id = "event_char2"; quest_id = "event_quest_all_done"
        steps_data = [{"title_i18n": {"en": "Final Step"}, "abstract_goal_json": json.dumps({"type": "FINAL_EVENT"})}]
        quest_obj = await self._setup_quest_for_event_handling(guild_id, char_id, quest_id, steps_data)
        mock_evaluate_goal.return_value = True; mock_mark_step_complete.return_value = True
        with patch.object(self.quest_manager, '_are_all_objectives_complete', return_value=True) as mock_are_all_complete:
            event_data = {"event_type": "FINAL_EVENT_TRIGGER"}
            await self.quest_manager.handle_player_event_for_quest(guild_id, char_id, event_data)
            mock_evaluate_goal.assert_awaited_once_with(guild_id, char_id, quest_obj, quest_obj.steps[0], event_data)
            mock_mark_step_complete.assert_awaited_once_with(guild_id, char_id, quest_id, 0)
            mock_are_all_complete.assert_called_once_with(quest_obj)
            mock_complete_quest.assert_awaited_once_with(guild_id, char_id, quest_id)

    async def test_start_quest_non_ai_from_template(self):
        guild_id = "test_guild_q_template"; character_id = "test_char_id"; quest_template_id = "sample_quest_001"
        self.mock_character_manager.get_character = AsyncMock(return_value=MagicMock(id=character_id))
        template_data: Dict[str, Any] = {
            "id": quest_template_id, "name_i18n": {"en": "Sample Quest"}, "description_i18n": {"en": "A simple task."},
            "steps": [{"id": "obj1", "title_i18n": {"en": "Do something."}}], # Changed objectives to steps
            "rewards_json_str": "{}", "data": {} # Changed rewards_i18n to rewards_json_str
        }
        self.quest_manager._quest_templates.setdefault(guild_id, {})[quest_template_id] = template_data
        result = await self.quest_manager.start_quest(guild_id, character_id, quest_template_id)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("status"), "active")
        self.assertEqual(result.get("template_id"), quest_template_id)
        self.assertEqual(result.get("character_id"), character_id)
        quest_instance_id = result.get("id")
        self.assertTrue(quest_instance_id is not None)
        active_quests_for_char = self.quest_manager._active_quests.get(guild_id, {}).get(character_id, {})
        self.assertIn(quest_instance_id, active_quests_for_char) # Check if ID is in the active quests
        self.assertIn(character_id, self.quest_manager._dirty_quests.get(guild_id, set()))

    async def test_generate_quest_details_from_ai_success(self):
        guild_id = "test_guild_gen_q_success"; quest_idea = "a quest about finding a lost cat"
        expected_data_dict: Dict[str, Any] = {"name_i18n": {"en": "Find Mittens!"}, "steps": []} # Changed objectives to steps

        self.mock_prompt_generator.generate_quest_prompt = AsyncMock(return_value={"system": "sys", "user": "usr"})
        self.mock_openai_service.generate_structured_multilingual_content = AsyncMock(return_value={"json_string": json.dumps(expected_data_dict)})

        # Mock validate_ai_response to return tuple: (Optional[Dict[str, Any]], Optional[List[ValidationIssue]])
        # For success, issues is None
        self.mock_ai_validator.validate_ai_response = AsyncMock(return_value=(expected_data_dict, None))

        dummy_player_context: Dict[str, Any] = {"player_level": 5, "current_location_name": "Town Square"}
        generation_context_arg = GenerationContext(
            guild_id=guild_id, main_language="en", target_languages=["en", "ru"], request_type="quest_idea",
            request_params={"idea_prompt": quest_idea, "difficulty": "medium"}, game_rules_summary={},
            lore_snippets=[], world_state={}, game_terms_dictionary=[], scaling_parameters=[],
            player_context=dummy_player_context, faction_data=[], relationship_data=[], active_quests_summary=[]
        )
        result_quest_obj = await self.quest_manager.generate_quest_details_from_ai(guild_id, quest_idea, generation_context_arg)
        self.assertIsNotNone(result_quest_obj)
        if result_quest_obj:
            self.assertEqual(result_quest_obj.name_i18n, expected_data_dict["name_i18n"])

    async def test_generate_quest_details_from_ai_openai_fails(self):
        guild_id = "gid_openai_fail"; quest_idea = "concept_openai_fail"
        self.mock_prompt_generator.generate_quest_prompt = AsyncMock(return_value={"system": "sys", "user": "usr"})
        self.mock_openai_service.generate_structured_multilingual_content = AsyncMock(return_value={"error": "OpenAI down"})
        # For this test, AI validator would not be called if OpenAI fails first.
        # If it were, it would return (None, [ValidationIssue(...)])
        self.mock_ai_validator.validate_ai_response = AsyncMock(return_value=(None, [ValidationIssue(type="openai_error", msg="OpenAI down", loc=())]))

        generation_context_arg = GenerationContext(guild_id=guild_id, main_language="en", target_languages=["en"], request_type="quest_idea", request_params={"idea": quest_idea}, game_rules_summary={}, lore_snippets=[], world_state={}, game_terms_dictionary=[], scaling_parameters=[], player_context=None, faction_data=[], relationship_data=[], active_quests_summary=[])
        result = await self.quest_manager.generate_quest_details_from_ai(guild_id, quest_idea, generation_context_arg)
        self.assertIsNone(result)

    async def test_generate_quest_details_from_ai_validator_fails(self):
        guild_id = "gid_validator_fail"; quest_idea = "concept_validator_fail"
        self.mock_prompt_generator.generate_quest_prompt = AsyncMock(return_value={"system": "sys", "user": "usr"})
        self.mock_openai_service.generate_structured_multilingual_content = AsyncMock(return_value={"json_string": "{}"}) # Valid JSON string from OpenAI

        # Validator returns (None data, List of issues) for failure
        validation_issues = [ValidationIssue(type="error", msg="failed validation", loc=())]
        self.mock_ai_validator.validate_ai_response = AsyncMock(return_value=(None, validation_issues))

        generation_context_arg = GenerationContext(guild_id=guild_id, main_language="en", target_languages=["en"], request_type="quest_idea", request_params={"idea": quest_idea}, game_rules_summary={}, lore_snippets=[], world_state={}, game_terms_dictionary=[], scaling_parameters=[], player_context=None, faction_data=[], relationship_data=[], active_quests_summary=[])
        result = await self.quest_manager.generate_quest_details_from_ai(guild_id, quest_idea, generation_context_arg)
        self.assertIsNone(result)

    async def test_generate_quest_details_from_ai_validator_requires_moderation(self):
        guild_id = "gid_validator_mod"; quest_idea = "concept_validator_mod"
        self.mock_prompt_generator.generate_quest_prompt = AsyncMock(return_value={"system": "sys", "user": "usr"})
        self.mock_openai_service.generate_structured_multilingual_content = AsyncMock(return_value={"json_string": "{}"}) # Valid JSON

        # For "requires_moderation", validator might return the data along with warning/info issues
        # Or the QuestManager's logic for requires_moderation is separate from strict validation failure.
        # Assuming here that if validator deems it needs moderation, it might still return data but with issues.
        # The QuestManager's internal logic then decides if this means "return None" for auto-start.
        # For this test, let's assume validate_ai_response returns (data, [issues_flagging_moderation])
        # and generate_quest_details_from_ai returns None if any issues exist, including moderation flags.
        moderation_issue = ValidationIssue(type="moderation_needed", msg="Content needs review", loc=(), severity="warning")
        # This data would be the parsed data if validation passed enough for that.
        parsed_data_for_moderation: Dict[str, Any] = {"name_i18n": {"en":"Needs Review"}, "steps": [], "id": str(uuid.uuid4()), "guild_id": guild_id}

        self.mock_ai_validator.validate_ai_response = AsyncMock(return_value=(parsed_data_for_moderation, [moderation_issue]))

        generation_context_arg = GenerationContext(guild_id=guild_id, main_language="en", target_languages=["en"], request_type="quest_idea", request_params={"idea": quest_idea}, game_rules_summary={}, lore_snippets=[], world_state={}, game_terms_dictionary=[], scaling_parameters=[], player_context=None, faction_data=[], relationship_data=[], active_quests_summary=[])
        result = await self.quest_manager.generate_quest_details_from_ai(guild_id, quest_idea, generation_context_arg)
        self.assertIsNone(result) # Should return None if moderation is required at this stage

    async def test_start_quest_from_moderated_data_success(self):
        guild_id = "test_guild_mod_quest"; character_id = "test_char_for_mod_quest"
        self.mock_character_manager.get_character = AsyncMock(return_value=MagicMock(id=character_id, name="TestChar"))
        moderated_quest_data: Dict[str, Any] = {
            "id": str(uuid.uuid4()), "name_i18n": {"en": "The Approved Adventure"},
            "description_i18n": {"en": "A quest vetted by the powers that be."},
            "steps": [{"id": "obj_approved_1", "title_i18n": {"en": "Retrieve"}, "description_i18n": {"en": "Retrieve the artifact."}}],
            "rewards_json_str": json.dumps({"items": [{"item_id": "gem_of_approval", "quantity": 1}]}),
            "template_id": "moderated_ai_quest_001", "giver_entity_id": "npc_quest_giver_approved",
            "guild_id": guild_id, "is_ai_generated": True
        }
        context_data: Dict[str, Any] = {"some_context_info": "value_for_quest", "bot_language": "en"}
        with patch.object(self.quest_manager, 'save_generated_quest', new_callable=AsyncMock) as mock_save_gen_quest:
            mock_save_gen_quest.return_value = True
            activated_quest_data = await self.quest_manager.start_quest_from_moderated_data(guild_id, character_id, moderated_quest_data, context_data)

        self.assertIsNotNone(activated_quest_data)
        self.assertIsInstance(activated_quest_data, dict)
        activated_quest_id = activated_quest_data.get("id")
        self.assertIsNotNone(activated_quest_id)
        self.assertEqual(activated_quest_data.get("character_id"), character_id)
        self.assertEqual(activated_quest_data.get("name_i18n", {}).get("en"), "The Approved Adventure")
        self.assertEqual(activated_quest_data.get("status"), "active")
        self.assertTrue(activated_quest_data.get("is_ai_generated"))

        # Check if quest_id is in the nested dictionary
        guild_quests = self.quest_manager._active_quests.get(guild_id, {})
        char_quests = guild_quests.get(character_id, {})
        self.assertIn(activated_quest_id, char_quests)

        self.assertIn(character_id, self.quest_manager._dirty_quests.get(guild_id, set()))
        mock_save_gen_quest.assert_called_once()
        saved_quest_obj_arg = mock_save_gen_quest.call_args[0][0]
        self.assertIsInstance(saved_quest_obj_arg, Quest)
        self.assertEqual(saved_quest_obj_arg.id, moderated_quest_data["id"])
        self.assertEqual(saved_quest_obj_arg.name_i18n["en"], "The Approved Adventure")

        # Assertions for services that should not be called for pre-moderated data
        self.mock_prompt_generator.generate_quest_prompt.assert_not_called()
        self.mock_openai_service.generate_structured_multilingual_content.assert_not_called()
        self.mock_ai_validator.validate_ai_response.assert_not_called()

        if "consequences_json_str" in moderated_quest_data and moderated_quest_data["consequences_json_str"]:
            try:
                consequences = json.loads(moderated_quest_data["consequences_json_str"])
                if isinstance(consequences, dict) and "on_start" in consequences:
                     self.mock_consequence_processor.process_consequences.assert_called_once()
                else:
                     self.mock_consequence_processor.process_consequences.assert_not_called()
            except json.JSONDecodeError:
                 self.mock_consequence_processor.process_consequences.assert_not_called()
        else:
            self.mock_consequence_processor.process_consequences.assert_not_called()

if __name__ == '__main__':
    unittest.main()
