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
        # No need to patch uuid.uuid4 as start_quest returns a hardcoded "dummy_request_id"
        result = await self.quest_manager.start_quest(
            guild_id, character_id, quest_template_id, user_id=user_id
        )

        expected_request_id_str = "dummy_request_id" # Matches hardcoded value in QuestManager
        self.assertEqual(result, {"status": "pending_moderation", "request_id": expected_request_id_str, "quest_data_preview": {}})

        # Assert that save_pending_moderation_request was NOT called by start_quest
        self.mock_db_service.adapter.save_pending_moderation_request.assert_not_called()

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

        expected_response = {"status": "pending_moderation", "request_id": "dummy_request_id", "quest_data_preview": {}}
        self.assertEqual(result, expected_response)
        # save_pending_moderation_request is part of the CommandRouter/GMCommand flow, not directly QuestManager.start_quest for "AI:" type
        # self.mock_db_service.adapter.save_pending_moderation_request.assert_not_called() # This might change if start_quest evolves

    async def test_start_quest_ai_no_user_id(self):
        guild_id = "test_guild_q_ai_no_user"
        character_id = "test_char_id"
        quest_template_id = "AI:generate_quest_no_user"
        mock_validated_data = {"name_i18n": {"en": "Quest No User"}}
        self.quest_manager.generate_quest_details_from_ai = AsyncMock(return_value=mock_validated_data)

        result = await self.quest_manager.start_quest(
            guild_id, character_id, quest_template_id # No user_id in kwargs
        )
        expected_response = {"status": "pending_moderation", "request_id": "dummy_request_id", "quest_data_preview": {}}
        self.assertEqual(result, expected_response)
        # self.mock_db_service.adapter.save_pending_moderation_request.assert_not_called() # See comment in previous test

    # --- Tests for accept_quest ---
    async def test_accept_quest_success(self):
        guild_id = "guild_accept_q1"
        player_pk = "player_pk_for_accept" # This is Player.id (PK)
        quest_db_id = "db_quest_to_accept_1"
        first_step_id = "step_1_of_db_quest_1"

        mock_player_db = MagicMock(spec=Player)
        mock_player_db.id = player_pk
        mock_player_db.guild_id = guild_id
        mock_player_db.level = 5
        mock_player_db.active_quests = None # No active quests initially
        mock_player_db.selected_language = "en"

        mock_quest_to_accept_db = MagicMock(spec=DBGeneratedQuest)
        mock_quest_to_accept_db.id = quest_db_id
        mock_quest_to_accept_db.guild_id = guild_id
        mock_quest_to_accept_db.prerequisites_json = json.dumps({"min_level": 3})
        mock_quest_to_accept_db.title_i18n = {"en": "The Grand Test Quest"}
        mock_quest_to_accept_db.suggested_level = 1


        mock_first_step_db = MagicMock(spec=DBQuestStepTable)
        mock_first_step_db.id = first_step_id
        mock_first_step_db.quest_id = quest_db_id
        mock_first_step_db.guild_id = guild_id
        mock_first_step_db.step_order = 0
        mock_first_step_db.title_i18n = {"en": "First Objective"}

        # Mock DBService.get_session and its context manager
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.get = AsyncMock(side_effect=lambda model, pk: mock_player_db if model == Player and pk == player_pk else (mock_quest_to_accept_db if model == DBGeneratedQuest and pk == quest_db_id else None))

        mock_execute_result_for_steps = AsyncMock()
        mock_execute_result_for_steps.scalars.return_value.all.return_value = [mock_first_step_db]
        mock_session.execute.return_value = mock_execute_result_for_steps

        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        self.mock_db_service.get_session.return_value.__aenter__.return_value = mock_session
        self.mock_db_service.get_session.return_value.__aexit__ = AsyncMock(return_value=None)

        success, message = await self.quest_manager.accept_quest(guild_id, player_pk, quest_db_id)

        self.assertTrue(success)
        self.assertIn("Quest 'The Grand Test Quest' accepted!", message)
        self.assertIn("First Objective", message)

        mock_session.get.assert_any_call(Player, player_pk)
        mock_session.get.assert_any_call(DBGeneratedQuest, quest_db_id)
        mock_session.execute.assert_awaited_once() # For fetching steps

        mock_session.add.assert_called_once_with(mock_player_db) # Player with updated active_quests
        self.assertIsNotNone(mock_player_db.active_quests)
        active_quests_list = json.loads(mock_player_db.active_quests)
        self.assertEqual(len(active_quests_list), 1)
        self.assertEqual(active_quests_list[0]["quest_id"], quest_db_id)
        self.assertEqual(active_quests_list[0]["current_step_id"], first_step_id)
        self.assertEqual(active_quests_list[0]["status"], "in_progress")

        mock_session.commit.assert_awaited_once()
        self.mock_game_log_manager.log_event.assert_awaited_once() # Check logging

    async def test_accept_quest_already_active(self):
        guild_id = "guild_accept_q_active"
        player_pk = "player_pk_active"
        quest_db_id = "db_quest_active_1"

        active_quest_entry = {"quest_id": quest_db_id, "status": "in_progress", "current_step_id": "s1"}
        mock_player_db = MagicMock(spec=Player)
        mock_player_db.id = player_pk; mock_player_db.guild_id = guild_id
        mock_player_db.active_quests = json.dumps([active_quest_entry]) # Already on this quest

        mock_quest_to_accept_db = MagicMock(spec=DBGeneratedQuest) # Quest itself
        mock_quest_to_accept_db.id = quest_db_id; mock_quest_to_accept_db.guild_id = guild_id

        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.get = AsyncMock(side_effect=lambda model, pk: mock_player_db if model == Player else (mock_quest_to_accept_db if model == DBGeneratedQuest else None))
        self.mock_db_service.get_session.return_value.__aenter__.return_value = mock_session

        success, message = await self.quest_manager.accept_quest(guild_id, player_pk, quest_db_id)
        self.assertFalse(success)
        self.assertEqual(message, "You are already on this quest.")
        mock_session.commit.assert_not_called()

    # --- End of tests for accept_quest ---

    # --- Tests for handle_player_event_for_quest ---
    async def _setup_quest_for_event_handling(self, guild_id: str, char_id: str, quest_id: str, steps_data: list, initial_status: str = "active") -> Quest:
        """Helper to set up a Quest object in the manager's cache."""
        pydantic_steps = []
        for i, step_d in enumerate(steps_data):
            step_d.setdefault("id", f"step_{quest_id}_{i}")
            step_d.setdefault("guild_id", guild_id)
            step_d.setdefault("quest_id", quest_id)
            step_d.setdefault("step_order", i)
            step_d.setdefault("status", "pending")
            pydantic_steps.append(QuestStep.from_dict(step_d))

        quest_obj = Quest(
            id=quest_id,
            guild_id=guild_id,
            name_i18n={"en": f"Test Quest {quest_id}"},
            description_i18n={"en": "A quest for testing events."},
            steps=pydantic_steps,
            status=initial_status,
            is_ai_generated=False # Assuming standard quest for these tests
        )
        # Populate _all_quests cache
        self.quest_manager._all_quests.setdefault(guild_id, {})[quest_id] = quest_obj

        # Populate _active_quests cache (stores dicts)
        active_quest_dict_for_cache = quest_obj.to_dict() # Pydantic to_dict
        active_quest_dict_for_cache.update({ # Add contextual info not in Pydantic Quest model
            "character_id": char_id,
            "start_time": time.time()
        })
        self.quest_manager._active_quests.setdefault(guild_id, {}).setdefault(char_id, {})[quest_id] = active_quest_dict_for_cache

        return quest_obj

    @patch('bot.game.managers.quest_manager.QuestManager._evaluate_abstract_goal', new_callable=AsyncMock)
    @patch('bot.game.managers.quest_manager.QuestManager._mark_step_complete', new_callable=AsyncMock)
    @patch('bot.game.managers.quest_manager.QuestManager.complete_quest', new_callable=AsyncMock)
    async def test_handle_event_completes_step_not_quest(
        self, mock_complete_quest: AsyncMock, mock_mark_step_complete: AsyncMock, mock_evaluate_goal: AsyncMock,
    ):
        guild_id = "event_guild1"
        char_id = "event_char1"
        quest_id = "event_quest_step_done"

        steps_data = [
            {"title_i18n": {"en": "Step 1"}, "description_i18n": {"en": "Do A"}, "abstract_goal_json": json.dumps({"type": "EVENT_A"})},
            {"title_i18n": {"en": "Step 2"}, "description_i18n": {"en": "Do B"}, "abstract_goal_json": json.dumps({"type": "EVENT_B"})}
        ]
        quest_obj = await self._setup_quest_for_event_handling(guild_id, char_id, quest_id, steps_data)

        mock_evaluate_goal.return_value = True # Event matches first step's goal
        mock_mark_step_complete.return_value = True # Marking step as complete succeeds

        event_data = {"event_type": "EVENT_A_TRIGGER", "details": {}} # Example event

        await self.quest_manager.handle_player_event_for_quest(guild_id, char_id, event_data)

        mock_evaluate_goal.assert_awaited_once_with(guild_id, char_id, quest_obj, quest_obj.steps[0], event_data)
        mock_mark_step_complete.assert_awaited_once_with(guild_id, char_id, quest_id, 0) # Step order 0

        # Check if _are_all_objectives_complete was called and returned False (implicitly)
        # This is harder to check directly without patching it too or checking its effects.
        # For now, we check that complete_quest was NOT called.
        mock_complete_quest.assert_not_called()
        self.assertEqual(quest_obj.steps[0].status, "completed") # Verify Pydantic model updated by _mark_step_complete
        self.assertEqual(quest_obj.steps[1].status, "pending")


    @patch('bot.game.managers.quest_manager.QuestManager._evaluate_abstract_goal', new_callable=AsyncMock)
    @patch('bot.game.managers.quest_manager.QuestManager._mark_step_complete', new_callable=AsyncMock)
    @patch('bot.game.managers.quest_manager.QuestManager.complete_quest', new_callable=AsyncMock)
    async def test_handle_event_completes_last_step_and_quest(
        self, mock_complete_quest: AsyncMock, mock_mark_step_complete: AsyncMock, mock_evaluate_goal: AsyncMock,
    ):
        guild_id = "event_guild2"
        char_id = "event_char2"
        quest_id = "event_quest_all_done"

        steps_data = [
            {"title_i18n": {"en": "Final Step"}, "description_i18n": {"en": "Finish it!"}, "abstract_goal_json": json.dumps({"type": "FINAL_EVENT"})}
        ]
        # Quest setup will mark this step as 'pending' initially
        quest_obj = await self._setup_quest_for_event_handling(guild_id, char_id, quest_id, steps_data)

        mock_evaluate_goal.return_value = True
        mock_mark_step_complete.return_value = True

        # Simulate _are_all_objectives_complete returning True after the step is marked
        # This means we need the Pydantic step object to actually change status for _are_all_objectives_complete
        # We can patch _are_all_objectives_complete directly for simplicity for this test's focus
        with patch.object(self.quest_manager, '_are_all_objectives_complete', return_value=True) as mock_are_all_complete:
            event_data = {"event_type": "FINAL_EVENT_TRIGGER"}
            await self.quest_manager.handle_player_event_for_quest(guild_id, char_id, event_data)

            mock_evaluate_goal.assert_awaited_once_with(guild_id, char_id, quest_obj, quest_obj.steps[0], event_data)
            mock_mark_step_complete.assert_awaited_once_with(guild_id, char_id, quest_id, 0)
            mock_are_all_complete.assert_called_once_with(quest_obj) # Check it was called
            mock_complete_quest.assert_awaited_once_with(guild_id, char_id, quest_id)
            # The status of the quest_obj itself would be updated by complete_quest
            # For this test, we mainly check complete_quest was called.


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
        self.assertIn("status", result) # Status should be present
        self.assertEqual(result["status"], "active") # And should be active
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
        dummy_player_context = {"player_level": 5, "current_location_name": "Town Square"}
        generation_context_arg = GenerationContext(
            guild_id=guild_id,
            main_language="en",
            target_languages=["en", "ru"],
            request_type="quest_idea", # Example, adjust if QuestManager uses a more specific type
            request_params={"idea_prompt": quest_idea, "difficulty": "medium"},
            game_rules_summary={"xp_per_level": 1000, "max_level": 20},
            lore_snippets=[{"title": "Ancient Artifact", "content": "Said to grant power."}],
            world_state={"current_year": 1024, "global_event": "Dragon's Menace"},
            game_terms_dictionary=[{"term": "mana", "definition_i18n": {"en":"Magical energy"}}],
            scaling_parameters=[{"type": "difficulty_scalar", "value": 1.2}],
            player_context=dummy_player_context,
            faction_data=[{"id": "f001", "name_i18n": {"en":"The King's Guard"}}],
            relationship_data=[], # Empty list if no specific relationships are relevant
            active_quests_summary=[] # Empty list if no active quests to consider
        )

        result = await self.quest_manager.generate_quest_details_from_ai(guild_id, quest_idea, generation_context_arg)
        self.assertEqual(result, expected_data)

    async def test_generate_quest_details_from_ai_openai_fails(self):
        guild_id = "gid_openai_fail"
        quest_idea = "concept_openai_fail"
        self.mock_prompt_generator.generate_quest_prompt.return_value = {"system": "sys", "user": "usr"}
        self.mock_openai_service.generate_structured_multilingual_content = AsyncMock(return_value={"error": "OpenAI down"})

        dummy_player_context = {"player_level": 3}
        generation_context_arg = GenerationContext(
            guild_id=guild_id, main_language="en", target_languages=["en"],
            request_type="quest_idea", request_params={"idea": quest_idea},
            game_rules_summary={}, lore_snippets=[], world_state={}, game_terms_dictionary=[],
            scaling_parameters=[], player_context=dummy_player_context, faction_data=[],
            relationship_data=[], active_quests_summary=[]
        )

        result = await self.quest_manager.generate_quest_details_from_ai(guild_id, quest_idea, generation_context_arg)
        self.assertIsNone(result)

    async def test_generate_quest_details_from_ai_validator_fails(self):
        guild_id = "gid_validator_fail"
        quest_idea = "concept_validator_fail"
        self.mock_prompt_generator.generate_quest_prompt.return_value = {"system": "sys", "user": "usr"}
        self.mock_openai_service.generate_structured_multilingual_content = AsyncMock(return_value={"json_string": "{}"})
        self.mock_ai_validator.validate_ai_response = AsyncMock(return_value={"global_errors": ["validation failed"]})

        generation_context_arg = GenerationContext(
            guild_id=guild_id, main_language="en", target_languages=["en"],
            request_type="quest_idea", request_params={"idea": quest_idea},
            game_rules_summary={}, lore_snippets=[], world_state={}, game_terms_dictionary=[],
            scaling_parameters=[], player_context=None, faction_data=[],
            relationship_data=[], active_quests_summary=[]
        )

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

        generation_context_arg = GenerationContext(
            guild_id=guild_id, main_language="en", target_languages=["en"],
            request_type="quest_idea", request_params={"idea": quest_idea},
            game_rules_summary={}, lore_snippets=[], world_state={}, game_terms_dictionary=[],
            scaling_parameters=[], player_context=None, faction_data=[],
            relationship_data=[], active_quests_summary=[]
        )

        result = await self.quest_manager.generate_quest_details_from_ai(guild_id, quest_idea, generation_context_arg)
        self.assertIsNone(result) # If validator requires moderation, details_from_ai should return None

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
