import unittest
import asyncio
import uuid
from typing import Dict, Any, Optional, List
from unittest.mock import MagicMock, AsyncMock # AsyncMock might be needed if log_event is called by tested methods

from bot.game.managers.quest_manager import QuestManager
# No direct model usage if revert methods operate on dicts in cache,
# but good to have if data structures from models are referenced.
# from bot.game.models.quest import Quest

class TestQuestManagerRevertLogic(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.guild_id = "test_guild_quest_revert"
        self.character_id = "test_char_quest_revert"

        # Mock dependencies for QuestManager
        self.mock_db_service = MagicMock()
        self.mock_settings = {} # Basic settings
        self.mock_npc_manager = MagicMock()
        self.mock_character_manager = MagicMock()
        self.mock_item_manager = MagicMock()
        self.mock_rule_engine = MagicMock()
        self.mock_relationship_manager = MagicMock()
        self.mock_consequence_processor = MagicMock()
        self.mock_game_log_manager = AsyncMock() # Methods being tested might call log_event
        self.mock_multilingual_prompt_generator = MagicMock()
        self.mock_openai_service = MagicMock()
        self.mock_ai_validator = MagicMock()
        self.mock_notification_service = MagicMock()

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
            multilingual_prompt_generator=self.mock_multilingual_prompt_generator,
            openai_service=self.mock_openai_service,
            ai_validator=self.mock_ai_validator,
            notification_service=self.mock_notification_service
        )

        self.quest_id_active = str(uuid.uuid4())
        self.active_quest_data = {
            "id": self.quest_id_active,
            "template_id": "q_template_1",
            "status": "active",
            "progress": {"obj1": 0, "obj2": 1},
            "character_id": self.character_id # Important for some internal logic if quest data needs it
        }

        # Initialize caches for the test guild and character
        # Ensure guild_id and character_id keys exist before trying to add the quest
        self.quest_manager._active_quests.setdefault(self.guild_id, {}).setdefault(self.character_id, {})[self.quest_id_active] = self.active_quest_data.copy()
        self.quest_manager._completed_quests.setdefault(self.guild_id, {}).setdefault(self.character_id, [])
        self.quest_manager._dirty_quests.setdefault(self.guild_id, set())

        # Clear dirty set specifically for this character for isolated test runs
        if self.character_id in self.quest_manager._dirty_quests.get(self.guild_id, {}):
            self.quest_manager._dirty_quests[self.guild_id].remove(self.character_id)


    async def test_revert_quest_start(self):
        # Ensure the quest is active before reverting
        self.assertIn(self.quest_id_active, self.quest_manager._active_quests.get(self.guild_id, {}).get(self.character_id, {}))

        result = await self.quest_manager.revert_quest_start(self.guild_id, self.character_id, self.quest_id_active)

        self.assertTrue(result, "revert_quest_start should return True on success.")

        # Assert quest is removed from active quests
        self.assertNotIn(self.quest_id_active,
                         self.quest_manager._active_quests.get(self.guild_id, {}).get(self.character_id, {}),
                         "Quest should be removed from active quests after reverting start.")

        # Assert character's quest data is marked dirty
        self.assertIn(self.character_id,
                      self.quest_manager._dirty_quests.get(self.guild_id, set()),
                      "Character should be marked as dirty after reverting quest start.")

    async def test_revert_quest_status_change_to_active(self):
        # Simulate quest was completed
        self.quest_manager._active_quests.get(self.guild_id, {}).get(self.character_id, {}).pop(self.quest_id_active, None)
        self.quest_manager._completed_quests.setdefault(self.guild_id, {}).setdefault(self.character_id, []).append(self.quest_id_active)

        # This is the state of the quest *before* it was completed (i.e., when it was active)
        old_quest_data_when_active = self.active_quest_data.copy()
        old_quest_data_when_active["status"] = "active" # Ensure old status was active

        result = await self.quest_manager.revert_quest_status_change(
            self.guild_id, self.character_id, self.quest_id_active,
            old_status="active",
            old_quest_data=old_quest_data_when_active
        )
        self.assertTrue(result, "revert_quest_status_change should return True.")

        # Assert quest is back in active_quests
        active_quests_char = self.quest_manager._active_quests.get(self.guild_id, {}).get(self.character_id, {})
        self.assertIn(self.quest_id_active, active_quests_char)
        self.assertEqual(active_quests_char[self.quest_id_active]["status"], "active")
        self.assertEqual(active_quests_char[self.quest_id_active]["progress"], old_quest_data_when_active["progress"]) # Check if progress restored

        # Assert quest is removed from completed_quests
        self.assertNotIn(self.quest_id_active, self.quest_manager._completed_quests.get(self.guild_id, {}).get(self.character_id, []))

        self.assertIn(self.character_id, self.quest_manager._dirty_quests.get(self.guild_id, set()))

    async def test_revert_quest_status_change_active_to_failed(self):
        # Quest is initially active (from setUp)
        self.assertIn(self.quest_id_active, self.quest_manager._active_quests.get(self.guild_id, {}).get(self.character_id, {}))

        # This is the state we want to revert TO (e.g. it was 'failed')
        # For this specific revert, old_quest_data might not be strictly necessary if only status changes.
        # However, the method expects it.
        old_quest_data_as_failed = self.active_quest_data.copy()
        old_quest_data_as_failed["status"] = "failed"

        # Simulate the current state is 'active' and we want to make it 'failed' by reverting
        # This test case is a bit conceptual for "revert". Usually, you revert *from* a state.
        # Let's assume the quest was 'failed', then wrongly set to 'active', and we revert to 'failed'.
        # So, current state in cache is self.active_quest_data (status: "active")

        result = await self.quest_manager.revert_quest_status_change(
            self.guild_id, self.character_id, self.quest_id_active,
            old_status="failed", # The status we are reverting TO
            old_quest_data=old_quest_data_as_failed # The full data of the quest when it was 'failed'
        )
        self.assertTrue(result, "revert_quest_status_change should return True.")

        # Assert quest is no longer in active_quests (because it's now 'failed')
        self.assertNotIn(self.quest_id_active, self.quest_manager._active_quests.get(self.guild_id, {}).get(self.character_id, {}))

        # If there was a _failed_quests list, we would check it here.
        # For now, the method just removes from active if old_status is not 'active'.

        self.assertIn(self.character_id, self.quest_manager._dirty_quests.get(self.guild_id, set()))


    async def test_revert_quest_progress_update(self):
        # Ensure quest is active and has some initial progress
        initial_progress = {"obj1": 1, "obj2": 0}
        self.active_quest_data["progress"] = initial_progress.copy()
        self.quest_manager._active_quests.setdefault(self.guild_id, {}).setdefault(self.character_id, {})[self.quest_id_active] = self.active_quest_data.copy()

        # Simulate that objective "obj1" was updated to 2
        # We want to revert it back to its "old_progress" which was 1
        objective_id_to_revert = "obj1"
        current_progress_in_cache = self.quest_manager._active_quests[self.guild_id][self.character_id][self.quest_id_active]["progress"]
        current_progress_in_cache[objective_id_to_revert] = 2 # This is the "new" state we are undoing

        old_progress_value_for_revert = 1 # The value we expect it to be after revert

        result = await self.quest_manager.revert_quest_progress_update(
            self.guild_id, self.character_id, self.quest_id_active,
            objective_id_to_revert,
            old_progress_value_for_revert
        )
        self.assertTrue(result, "revert_quest_progress_update should return True.")

        updated_quest_data = self.quest_manager._active_quests.get(self.guild_id, {}).get(self.character_id, {}).get(self.quest_id_active, {})
        self.assertEqual(updated_quest_data.get("progress", {}).get(objective_id_to_revert), old_progress_value_for_revert)

        self.assertIn(self.character_id, self.quest_manager._dirty_quests.get(self.guild_id, set()))

if __name__ == '__main__':
    asyncio.run(unittest.main())
