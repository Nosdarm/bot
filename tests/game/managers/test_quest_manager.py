import unittest
from unittest.mock import AsyncMock, patch, MagicMock
import uuid
import json
import time

from bot.game.managers.quest_manager import QuestManager
from bot.game.models.quest import Quest, QuestStep # Import QuestStep
from bot.ai.ai_data_models import GenerationContext
from bot.database.models.player import Player # Corrected import
from bot.database.models.generated_quest import GeneratedQuest as DBGeneratedQuest # Corrected import
from bot.database.models.quest_step import QuestStepTable as DBQuestStepTable # Corrected import
from sqlalchemy.ext.asyncio import AsyncSession # For type hint

class TestQuestManager(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.mock_db_service = AsyncMock() # Changed to AsyncMock for DBService
        self.mock_db_service.adapter = AsyncMock()

        self.mock_settings = {
            "campaign_data": {"quest_templates": []},
            "default_language": "en"
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
        self.mock_notification_service = AsyncMock()
        self.mock_game_manager = AsyncMock() # Mock GameManager for QuestManager init

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
            game_manager=self.mock_game_manager # Pass GameManager
        )
        # Cannot assign to attribute "_status_manager" for class "QuestManager" (Pyright error) - Remove if not used or mock properly
        # self.quest_manager._status_manager = AsyncMock()

        self.mock_player_instance = MagicMock(spec=Player) # Use spec
        self.mock_player_instance.id = "test_char_id"
        self.mock_player_instance.name = "Test Character"
        self.mock_character_manager.get_character = AsyncMock(return_value=self.mock_player_instance) # Use AsyncMock for get_character


    async def test_start_quest_ai_pending_moderation(self):
        guild_id = "test_guild_q_ai_success"
        character_id = "test_char_id"
        quest_template_id = "AI:generate_epic_quest"
        user_id = "test_user_quest_mod"
        mock_validated_quest_data: Dict[str, Any] = { # Added type hint
            "name_i18n": {"en": "The Grand AI Quest"},
            "description_i18n": {"en": "An epic journey awaits."},
            "objectives": [{"id": "obj1", "description_i18n": {"en": "Slay the dragon"}}],
            "template_id": "AI_epic_quest_1"
        }

        self.quest_manager.generate_quest_details_from_ai = AsyncMock(return_value=mock_validated_quest_data) # type: ignore[method-assign]
        # self.mock_db_service.adapter.save_pending_moderation_request.return_value = None # This method is not on adapter

        self.mock_character_manager.get_character_by_discord_id = AsyncMock(return_value=self.mock_player_instance) # Use AsyncMock
        # self.quest_manager._status_manager = AsyncMock() # Already removed
        self.quest_manager._notification_service = self.mock_notification_service


        # expected_request_id_obj = uuid.uuid4() # Unused
        result = await self.quest_manager.start_quest(
            guild_id, character_id, quest_template_id, user_id=user_id
        )

        expected_request_id_str = "dummy_request_id"
        self.assertEqual(result, {"status": "pending_moderation", "request_id": expected_request_id_str, "quest_data_preview": {}})

        # self.mock_db_service.adapter.save_pending_moderation_request.assert_not_called() # Method doesn't exist on adapter

        self.mock_character_manager.get_character_by_discord_id.assert_called_once_with(guild_id, user_id)
        self.mock_notification_service.send_moderation_request_alert.assert_called_once()


    async def test_start_quest_ai_generation_fails(self):
        guild_id = "test_guild_q_ai_fail"
        character_id = "test_char_id"
        quest_template_id = "AI:generate_failed_quest"
        user_id = "test_user_q_fail"

        self.quest_manager.generate_quest_details_from_ai = AsyncMock(return_value=None) # type: ignore[method-assign]

        result = await self.quest_manager.start_quest(
            guild_id, character_id, quest_template_id, user_id=user_id
        )

        expected_response = {"status": "pending_moderation", "request_id": "dummy_request_id", "quest_data_preview": {}}
        self.assertEqual(result, expected_response)

    async def test_start_quest_ai_no_user_id(self):
        guild_id = "test_guild_q_ai_no_user"
        character_id = "test_char_id"
        quest_template_id = "AI:generate_quest_no_user"
        mock_validated_data: Dict[str, Any] = {"name_i18n": {"en": "Quest No User"}} # Added type hint
        self.quest_manager.generate_quest_details_from_ai = AsyncMock(return_value=mock_validated_data) # type: ignore[method-assign]

        result = await self.quest_manager.start_quest(
            guild_id, character_id, quest_template_id
        )
        expected_response = {"status": "pending_moderation", "request_id": "dummy_request_id", "quest_data_preview": {}}
        self.assertEqual(result, expected_response)

    # --- Tests for accept_quest ---
    async def test_accept_quest_success(self):
        guild_id = "guild_accept_q1"
        player_pk = "player_pk_for_accept"
        quest_db_id = "db_quest_to_accept_1"
        first_step_id = "step_1_of_db_quest_1"

        mock_player_db = MagicMock(spec=Player) # "Player" is not defined (Pyright error) - Fixed by importing Player from models
        mock_player_db.id = player_pk
        mock_player_db.guild_id = guild_id
        mock_player_db.level = 5
        mock_player_db.active_quests = None
        mock_player_db.selected_language = "en"

        mock_quest_to_accept_db = MagicMock(spec=DBGeneratedQuest) # "DBGeneratedQuest" is not defined (Pyright error) - Fixed by importing from models
        mock_quest_to_accept_db.id = quest_db_id
        mock_quest_to_accept_db.guild_id = guild_id
        mock_quest_to_accept_db.prerequisites_json = json.dumps({"min_level": 3})
        mock_quest_to_accept_db.title_i18n = {"en": "The Grand Test Quest"}
        mock_quest_to_accept_db.suggested_level = 1


        mock_first_step_db = MagicMock(spec=DBQuestStepTable) # "DBQuestStepTable" is not defined (Pyright error) - Fixed by importing from models
        mock_first_step_db.id = first_step_id
        mock_first_step_db.quest_id = quest_db_id
        mock_first_step_db.guild_id = guild_id
        mock_first_step_db.step_order = 0
        mock_first_step_db.title_i18n = {"en": "First Objective"}

        mock_session = AsyncMock(spec=AsyncSession) # "AsyncSession" is not defined (Pyright error) - Fixed by importing
        # Correct side_effect for session.get using a lambda
        async def mock_get_side_effect(model_class, pk_value):
            if model_class == Player and pk_value == player_pk: return mock_player_db
            if model_class == DBGeneratedQuest and pk_value == quest_db_id: return mock_quest_to_accept_db
            return None
        mock_session.get = AsyncMock(side_effect=mock_get_side_effect)


        mock_execute_result_for_steps = AsyncMock()
        mock_execute_result_for_steps.scalars.return_value.all.return_value = [mock_first_step_db]
        mock_session.execute.return_value = mock_execute_result_for_steps

        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        # Ensure get_session on the AsyncMock db_service returns a proper async context manager
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__.return_value = mock_session
        mock_session_cm.__aexit__.return_value = None
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
        active_quests_list = json.loads(mock_player_db.active_quests)
        self.assertEqual(len(active_quests_list), 1)
        self.assertEqual(active_quests_list[0]["quest_id"], quest_db_id)
        self.assertEqual(active_quests_list[0]["current_step_id"], first_step_id)
        self.assertEqual(active_quests_list[0]["status"], "in_progress")

        mock_session.commit.assert_awaited_once()
        self.mock_game_log_manager.log_event.assert_awaited_once()

    async def test_accept_quest_already_active(self):
        guild_id = "guild_accept_q_active"
        player_pk = "player_pk_active"
        quest_db_id = "db_quest_active_1"

        active_quest_entry = {"quest_id": quest_db_id, "status": "in_progress", "current_step_id": "s1"}
        mock_player_db = MagicMock(spec=Player) # "Player" is not defined - Fixed
        mock_player_db.id = player_pk; mock_player_db.guild_id = guild_id
        mock_player_db.active_quests = json.dumps([active_quest_entry])

        mock_quest_to_accept_db = MagicMock(spec=DBGeneratedQuest) # "DBGeneratedQuest" is not defined - Fixed
        mock_quest_to_accept_db.id = quest_db_id; mock_quest_to_accept_db.guild_id = guild_id

        mock_session = AsyncMock(spec=AsyncSession) # "AsyncSession" is not defined - Fixed
        async def mock_get_side_effect_active(model_class, pk_value): # Renamed side_effect function
            if model_class == Player: return mock_player_db
            if model_class == DBGeneratedQuest: return mock_quest_to_accept_db
            return None
        mock_session.get = AsyncMock(side_effect=mock_get_side_effect_active)

        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__.return_value = mock_session
        mock_session_cm.__aexit__.return_value = None
        self.mock_db_service.get_session = MagicMock(return_value=mock_session_cm)


        success, message = await self.quest_manager.accept_quest(guild_id, player_pk, quest_db_id)
        self.assertFalse(success)
        self.assertEqual(message, "You are already on this quest.")
        mock_session.commit.assert_not_called()

    # --- End of tests for accept_quest ---

    # --- Tests for handle_player_event_for_quest ---
    async def _setup_quest_for_event_handling(self, guild_id: str, char_id: str, quest_id: str, steps_data: list, initial_status: str = "active") -> Quest:
        pydantic_steps: List[QuestStep] = [] # "QuestStep" is not defined (Pyright error) - Fixed by importing QuestStep
        for i, step_d in enumerate(steps_data):
            step_d.setdefault("id", f"step_{quest_id}_{i}")
            step_d.setdefault("guild_id", guild_id)
            step_d.setdefault("quest_id", quest_id)
            step_d.setdefault("step_order", i)
            step_d.setdefault("status", "pending")
            pydantic_steps.append(QuestStep.from_dict(step_d))

        quest_obj = Quest(
            id=quest_id, guild_id=guild_id, name_i18n={"en": f"Test Quest {quest_id}"},
            description_i18n={"en": "A quest for testing events."}, steps=pydantic_steps,
            status=initial_status, is_ai_generated=False
        )
        self.quest_manager._all_quests.setdefault(guild_id, {})[quest_id] = quest_obj
        active_quest_dict_for_cache = quest_obj.model_dump() # Use model_dump for Pydantic V2
        active_quest_dict_for_cache.update({ "character_id": char_id, "start_time": time.time() })
        self.quest_manager._active_quests.setdefault(guild_id, {}).setdefault(char_id, {})[quest_id] = active_quest_dict_for_cache
        return quest_obj

    @patch('bot.game.managers.quest_manager.QuestManager._evaluate_abstract_goal', new_callable=AsyncMock)
    @patch('bot.game.managers.quest_manager.QuestManager._mark_step_complete', new_callable=AsyncMock)
    @patch('bot.game.managers.quest_manager.QuestManager.complete_quest', new_callable=AsyncMock)
    async def test_handle_event_completes_step_not_quest(
        self, mock_complete_quest: AsyncMock, mock_mark_step_complete: AsyncMock, mock_evaluate_goal: AsyncMock,
    ):
        guild_id = "event_guild1"; char_id = "event_char1"; quest_id = "event_quest_step_done"
        steps_data = [{"title_i18n": {"en": "Step 1"}, "abstract_goal_json": json.dumps({"type": "EVENT_A"})}, {"title_i18n": {"en": "Step 2"}, "abstract_goal_json": json.dumps({"type": "EVENT_B"})}]
        quest_obj = await self._setup_quest_for_event_handling(guild_id, char_id, quest_id, steps_data)
        mock_evaluate_goal.return_value = True
        mock_mark_step_complete.return_value = True
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
    async def test_handle_event_completes_last_step_and_quest(
        self, mock_complete_quest: AsyncMock, mock_mark_step_complete: AsyncMock, mock_evaluate_goal: AsyncMock,
    ):
        guild_id = "event_guild2"; char_id = "event_char2"; quest_id = "event_quest_all_done"
        steps_data = [{"title_i18n": {"en": "Final Step"}, "abstract_goal_json": json.dumps({"type": "FINAL_EVENT"})}]
        quest_obj = await self._setup_quest_for_event_handling(guild_id, char_id, quest_id, steps_data)
        mock_evaluate_goal.return_value = True
        mock_mark_step_complete.return_value = True
        with patch.object(self.quest_manager, '_are_all_objectives_complete', return_value=True) as mock_are_all_complete:
            event_data = {"event_type": "FINAL_EVENT_TRIGGER"}
            await self.quest_manager.handle_player_event_for_quest(guild_id, char_id, event_data)
            mock_evaluate_goal.assert_awaited_once_with(guild_id, char_id, quest_obj, quest_obj.steps[0], event_data)
            mock_mark_step_complete.assert_awaited_once_with(guild_id, char_id, quest_id, 0)
            mock_are_all_complete.assert_called_once_with(quest_obj)
            mock_complete_quest.assert_awaited_once_with(guild_id, char_id, quest_id)


    async def test_start_quest_non_ai_from_template(self):
        guild_id = "test_guild_q_template"; character_id = "test_char_id"; quest_template_id = "sample_quest_001"
        self.mock_character_manager.get_character = AsyncMock(return_value=MagicMock(id=character_id)) # Use AsyncMock for get_character

        template_data: Dict[str, Any] = { # Added type hint
            "id": quest_template_id, "name_i18n": {"en": "Sample Quest"}, "description_i18n": {"en": "A simple task."},
            "objectives": [{"id": "obj1", "description_i18n": {"en": "Do something."}}],
            "rewards_i18n": {}, "data": {}
        }
        self.quest_manager._quest_templates.setdefault(guild_id, {})[quest_template_id] = template_data
        result = await self.quest_manager.start_quest(guild_id, character_id, quest_template_id)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("status"), "active") # Use .get() for safer access
        self.assertEqual(result.get("template_id"), quest_template_id)
        self.assertEqual(result.get("character_id"), character_id)
        self.assertTrue(result.get("id") is not None)
        # self.mock_db_service.adapter.save_pending_moderation_request.assert_not_called() # Method doesn't exist
        self.assertIn(character_id, self.quest_manager._dirty_quests.get(guild_id, set()))


    async def test_generate_quest_details_from_ai_success(self):
        guild_id = "test_guild_gen_q_success"; quest_idea = "a quest about finding a lost cat"
        expected_data: Dict[str, Any] = {"name_i18n": {"en": "Find Mittens!"}, "objectives": []} # Added type hint
        self.mock_prompt_generator.generate_quest_prompt = AsyncMock(return_value={"system": "sys", "user": "usr"}) # Use AsyncMock
        self.mock_openai_service.generate_structured_multilingual_content = AsyncMock(return_value={"json_string": json.dumps(expected_data)})

        # Mock validate_ai_response to return a tuple (validated_data, None for issues)
        self.mock_ai_validator.validate_ai_response = AsyncMock(return_value=(expected_data, None)) # type: ignore[method-assign]

        dummy_player_context: Dict[str, Any] = {"player_level": 5, "current_location_name": "Town Square"} # Added type hint
        generation_context_arg = GenerationContext(
            guild_id=guild_id, main_language="en", target_languages=["en", "ru"], request_type="quest_idea",
            request_params={"idea_prompt": quest_idea, "difficulty": "medium"}, game_rules_summary={},
            lore_snippets=[], world_state={}, game_terms_dictionary=[], scaling_parameters=[],
            player_context=dummy_player_context, faction_data=[], relationship_data=[], active_quests_summary=[]
        )
        # generate_quest_details_from_ai is expected to return a Quest object or None
        result_quest_obj = await self.quest_manager.generate_quest_details_from_ai(guild_id, quest_idea, generation_context_arg)
        self.assertIsNotNone(result_quest_obj)
        if result_quest_obj: # Type guard
            self.assertEqual(result_quest_obj.name_i18n, expected_data["name_i18n"]) # Compare attributes of Quest object

    async def test_generate_quest_details_from_ai_openai_fails(self):
        guild_id = "gid_openai_fail"; quest_idea = "concept_openai_fail"
        self.mock_prompt_generator.generate_quest_prompt = AsyncMock(return_value={"system": "sys", "user": "usr"}) # Use AsyncMock
        self.mock_openai_service.generate_structured_multilingual_content = AsyncMock(return_value={"error": "OpenAI down"})
        generation_context_arg = GenerationContext(guild_id=guild_id, main_language="en", target_languages=["en"], request_type="quest_idea", request_params={"idea": quest_idea}, game_rules_summary={}, lore_snippets=[], world_state={}, game_terms_dictionary=[], scaling_parameters=[], player_context=None, faction_data=[], relationship_data=[], active_quests_summary=[])
        result = await self.quest_manager.generate_quest_details_from_ai(guild_id, quest_idea, generation_context_arg)
        self.assertIsNone(result)

    async def test_generate_quest_details_from_ai_validator_fails(self):
        guild_id = "gid_validator_fail"; quest_idea = "concept_validator_fail"
        self.mock_prompt_generator.generate_quest_prompt = AsyncMock(return_value={"system": "sys", "user": "usr"}) # Use AsyncMock
        self.mock_openai_service.generate_structured_multilingual_content = AsyncMock(return_value={"json_string": "{}"})

        # Mock validate_ai_response to return a result indicating failure
        mock_validation_result_fail = MagicMock()
        mock_validation_result_fail.overall_status = "error"
        mock_validation_result_fail.entities = []
        mock_validation_result_fail.global_errors = ["validation failed"]
        self.mock_ai_validator.validate_ai_response = AsyncMock(return_value=mock_validation_result_fail) # type: ignore[method-assign]

        generation_context_arg = GenerationContext(guild_id=guild_id, main_language="en", target_languages=["en"], request_type="quest_idea", request_params={"idea": quest_idea}, game_rules_summary={}, lore_snippets=[], world_state={}, game_terms_dictionary=[], scaling_parameters=[], player_context=None, faction_data=[], relationship_data=[], active_quests_summary=[])
        result = await self.quest_manager.generate_quest_details_from_ai(guild_id, quest_idea, generation_context_arg)
        self.assertIsNone(result)

    async def test_generate_quest_details_from_ai_validator_requires_moderation(self):
        guild_id = "gid_validator_mod"; quest_idea = "concept_validator_mod"
        self.mock_prompt_generator.generate_quest_prompt = AsyncMock(return_value={"system": "sys", "user": "usr"}) # Use AsyncMock
        self.mock_openai_service.generate_structured_multilingual_content = AsyncMock(return_value={"json_string": "{}"})

        mock_validation_result_mod = MagicMock()
        mock_validation_result_mod.overall_status = "requires_manual_review"
        mock_validation_result_mod.entities = [MagicMock(validated_data={"name":"Needs Review"}, requires_moderation=True)]
        self.mock_ai_validator.validate_ai_response = AsyncMock(return_value=mock_validation_result_mod) # type: ignore[method-assign]

        generation_context_arg = GenerationContext(guild_id=guild_id, main_language="en", target_languages=["en"], request_type="quest_idea", request_params={"idea": quest_idea}, game_rules_summary={}, lore_snippets=[], world_state={}, game_terms_dictionary=[], scaling_parameters=[], player_context=None, faction_data=[], relationship_data=[], active_quests_summary=[])
        result = await self.quest_manager.generate_quest_details_from_ai(guild_id, quest_idea, generation_context_arg)
        self.assertIsNone(result)

    async def test_start_quest_from_moderated_data_success(self):
        guild_id = "test_guild_mod_quest"; character_id = "test_char_for_mod_quest"
        self.mock_character_manager.get_character = AsyncMock(return_value=MagicMock(id=character_id, name="TestChar")) # Use AsyncMock
        moderated_quest_data: Dict[str, Any] = { # Added type hint
            "id": str(uuid.uuid4()), "name_i18n": {"en": "The Approved Adventure"},
            "description_i18n": {"en": "A quest vetted by the powers that be."},
            "steps": [{"id": "obj_approved_1", "title_i18n": {"en": "Retrieve"}, "description_i18n": {"en": "Retrieve the artifact."}}], # Ensure steps is a list of step-like dicts
            "rewards_json_str": json.dumps({"items": [{"item_id": "gem_of_approval", "quantity": 1}]}), # Use _json_str for Pydantic
            "template_id": "moderated_ai_quest_001", "giver_entity_id": "npc_quest_giver_approved",
            "guild_id": guild_id, "is_ai_generated": True
        }
        context_data: Dict[str, Any] = {"some_context_info": "value_for_quest", "bot_language": "en"} # Added type hint
        with patch.object(self.quest_manager, 'save_generated_quest', new_callable=AsyncMock) as mock_save_gen_quest:
            mock_save_gen_quest.return_value = True
            activated_quest_data = await self.quest_manager.start_quest_from_moderated_data(guild_id, character_id, moderated_quest_data, context_data)
        self.assertIsNotNone(activated_quest_data)
        self.assertIsInstance(activated_quest_data, dict)
        self.assertEqual(activated_quest_data.get("character_id"), character_id) # Use .get()
        self.assertEqual(activated_quest_data.get("name_i18n", {}).get("en"), "The Approved Adventure") # Use .get()
        self.assertEqual(activated_quest_data.get("status"), "active")
        self.assertTrue(activated_quest_data.get("is_ai_generated"))
        self.assertIn(activated_quest_data.get("id"), self.quest_manager._active_quests.get(guild_id, {}).get(character_id, {})) # Use .get()
        self.assertIn(character_id, self.quest_manager._dirty_quests.get(guild_id, set()))
        mock_save_gen_quest.assert_called_once()
        saved_quest_obj_arg = mock_save_gen_quest.call_args[0][0]
        self.assertIsInstance(saved_quest_obj_arg, Quest)
        self.assertEqual(saved_quest_obj_arg.id, moderated_quest_data["id"])
        self.assertEqual(saved_quest_obj_arg.name_i18n["en"], "The Approved Adventure")
        self.mock_prompt_generator.generate_quest_prompt.assert_not_called() # Use AsyncMock if this is async
        self.mock_openai_service.generate_structured_multilingual_content.assert_not_called() # Use AsyncMock
        self.mock_ai_validator.validate_ai_response.assert_not_called() # Use AsyncMock
        # self.mock_db_service.adapter.save_pending_moderation_request.assert_not_called() # Method does not exist
        # Consequence processing check
        if "consequences_json_str" in moderated_quest_data and moderated_quest_data["consequences_json_str"]: # Check if consequences_json_str exists
            # Assuming consequences_json_str is a valid JSON string with an "on_start" key
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
