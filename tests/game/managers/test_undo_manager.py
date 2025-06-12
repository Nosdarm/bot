import unittest
import asyncio
import json
import uuid
from typing import Optional, Dict, Any, List
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game.managers.undo_manager import UndoManager
from bot.game.managers.game_log_manager import GameLogManager
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.item_manager import ItemManager
from bot.game.managers.quest_manager import QuestManager
from bot.game.managers.party_manager import PartyManager
from bot.game.managers.npc_manager import NpcManager # Added
from bot.game.managers.location_manager import LocationManager # Added
class TestUndoManager(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.guild_id = "test_guild_undo"
        self.player_id = "test_player_undo"
        self.log_id = str(uuid.uuid4())

        # Create mock instances for all dependent managers
        self.game_log_mgr_mock = AsyncMock(spec=GameLogManager)
        self.char_mgr_mock = AsyncMock(spec=CharacterManager)
        self.item_mgr_mock = AsyncMock(spec=ItemManager)
        self.quest_mgr_mock = AsyncMock(spec=QuestManager)
        self.party_mgr_mock = AsyncMock(spec=PartyManager)
        self.npc_mgr_mock = AsyncMock(spec=NpcManager) # Added
        self.loc_mgr_mock = AsyncMock(spec=LocationManager) # Added


        # db_service is not directly used by UndoManager's core logic being tested here,
        # but passed to managers it initializes (which are mocked here).
        self.mock_db_service = MagicMock()

        self.undo_manager = UndoManager(
            db_service=self.mock_db_service, # Can be None if UndoManager doesn't use it directly
            game_log_manager=self.game_log_mgr_mock,
            character_manager=self.char_mgr_mock,
            item_manager=self.item_mgr_mock,
            quest_manager=self.quest_mgr_mock,
            party_manager=self.party_mgr_mock,
            npc_manager=self.npc_mgr_mock, # Added
            location_manager=self.loc_mgr_mock # Added
        )

    async def test_process_log_revert_player_move_success(self):
        revert_data = {"old_location_id": "loc_previous"}
        # Simulate how PLAYER_ACTION_COMPLETED might log a MOVE action's revert_data
        log_details = {
            "completed_action_details": { # Assuming this structure based on UndoManager
                "type": "move", # Or "action_type": "MOVE"
                "revert_data": revert_data
            }
        }
        mock_log_entry = {
            "id": self.log_id,
            "guild_id": self.guild_id,
            "player_id": self.player_id,
            "event_type": "PLAYER_ACTION_COMPLETED",
            "details": json.dumps(log_details) # Details must be JSON string as per _process_log_entry_for_revert
        }

        self.char_mgr_mock.revert_location_change.return_value = True

        result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, mock_log_entry)

        self.assertTrue(result)
        self.char_mgr_mock.revert_location_change.assert_called_once_with(
            self.guild_id, self.player_id, "loc_previous"
        )

    async def test_process_log_revert_hp_change_success(self):
        # This tests a direct PLAYER_HEALTH_CHANGE event, not one nested in PLAYER_ACTION_COMPLETED
        revert_data = {"old_hp": 80.0, "old_is_alive": True}
        log_details = { # Details for PLAYER_HEALTH_CHANGE (not nested under completed_action_details)
            "action_type": "HEALTH_UPDATE", # This is what CharacterManager.update_health logs
            "revert_data": revert_data
        }
        mock_log_entry = {
            "id": self.log_id,
            "guild_id": self.guild_id,
            "player_id": self.player_id,
            "event_type": "PLAYER_HEALTH_CHANGE", # Specific event type from CharacterManager
            "details": json.dumps(log_details)
        }

        self.char_mgr_mock.revert_hp_change.return_value = True

        result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, mock_log_entry)

        self.assertTrue(result)
        self.char_mgr_mock.revert_hp_change.assert_called_once_with(
            self.guild_id, self.player_id, 80.0, True
        )

    async def test_process_log_revert_unsupported_event_type(self):
        mock_log_entry = {
            "id": self.log_id,
            "guild_id": self.guild_id,
            "player_id": self.player_id,
            "event_type": "UNSUPPORTED_EVENT_XYZ",
            "details": json.dumps({"some_data": "value"})
        }

        result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, mock_log_entry)

        self.assertFalse(result)
        self.char_mgr_mock.revert_location_change.assert_not_called()
        self.char_mgr_mock.revert_hp_change.assert_not_called()
        self.item_mgr_mock.revert_item_creation.assert_not_called()
        self.item_mgr_mock.revert_item_deletion.assert_not_called()
        self.item_mgr_mock.revert_item_update.assert_not_called()
        self.quest_mgr_mock.revert_quest_start.assert_not_called()
        self.quest_mgr_mock.revert_quest_status_change.assert_not_called()
        self.quest_mgr_mock.revert_quest_progress_update.assert_not_called()
        # Add more assert_not_called for other manager revert methods as they are added

    async def test_process_log_revert_stat_changes_success(self):
        stat_changes_payload = [{"stat": "xp", "old_value": 100}]
        log_details = {
            "completed_action_details": { # Assuming logged by a player action
                "action_type": "GENERIC_ACTION_THAT_CHANGED_STATS",
                "revert_data": {"stat_changes": stat_changes_payload}
            }
        }
        mock_log_entry = {
            "id": self.log_id, "guild_id": self.guild_id, "player_id": self.player_id,
            "event_type": "PLAYER_ACTION_COMPLETED", "details": json.dumps(log_details)
        }
        self.char_mgr_mock.revert_stat_changes.return_value = True
        result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, mock_log_entry)
        self.assertTrue(result)
        self.char_mgr_mock.revert_stat_changes.assert_called_once_with(
            self.guild_id, self.player_id, stat_changes_payload
        )

    async def test_process_log_revert_inventory_changes_success(self):
        inventory_changes_payload = [{"action": "added", "item_id": "potion", "quantity": 1}]
        log_details = {
            "completed_action_details": {
                "action_type": "PICKUP_ITEM_ACTION",
                "revert_data": {"inventory_changes": inventory_changes_payload}
            }
        }
        mock_log_entry = {
            "id": self.log_id, "guild_id": self.guild_id, "player_id": self.player_id,
            "event_type": "PLAYER_ACTION_COMPLETED", "details": json.dumps(log_details)
        }
        self.char_mgr_mock.revert_inventory_changes.return_value = True
        result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, mock_log_entry)
        self.assertTrue(result)
        self.char_mgr_mock.revert_inventory_changes.assert_called_once_with(
            self.guild_id, self.player_id, inventory_changes_payload
        )

    async def test_process_log_revert_status_effect_change_success(self):
        status_change_payload = {"action_taken": "gained", "status_effect_id": "eff_burn"}
        log_details = {
            "completed_action_details": {
                "action_type": "ABILITY_HIT_TARGET",
                "revert_data": {"status_effect_change": status_change_payload}
            }
        }
        mock_log_entry = {
            "id": self.log_id, "guild_id": self.guild_id, "player_id": self.player_id,
            "event_type": "PLAYER_ACTION_COMPLETED", "details": json.dumps(log_details)
        }
        self.char_mgr_mock.revert_status_effect_change.return_value = True
        result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, mock_log_entry)
        self.assertTrue(result)
        self.char_mgr_mock.revert_status_effect_change.assert_called_once_with(
            self.guild_id, self.player_id, "gained", "eff_burn", None
        )

    async def test_process_log_revert_entity_death_player_success(self):
        revert_data = {"previous_hp": 5.0, "previous_is_alive_status": True}
        # Note: For ENTITY_DEATH, details usually come from the event itself, not nested in completed_action_details
        log_details = {
            "deceased_entity_id": self.player_id,
            "deceased_entity_type": "Player",
            "revert_data": revert_data
        }
        mock_log_entry = {
            "id": self.log_id, "guild_id": self.guild_id,
            # player_id might be the killer, or system, deceased_entity_id is the one to revert
            "event_type": "ENTITY_DEATH", "details": json.dumps(log_details)
        }
        self.char_mgr_mock.revert_hp_change.return_value = True
        result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, mock_log_entry)
        self.assertTrue(result)
        self.char_mgr_mock.revert_hp_change.assert_called_once_with(
            self.guild_id, self.player_id, 5.0, True # player_id from log_entry used here
        )

    async def test_process_log_revert_item_created_success(self):
        item_id = "item_abc"
        log_details = {"item_id": item_id} # Direct details for ITEM_CREATED
        mock_log_entry = {
            "id": self.log_id, "guild_id": self.guild_id, "player_id": self.player_id,
            "event_type": "ITEM_CREATED", "details": json.dumps(log_details)
        }
        self.item_mgr_mock.revert_item_creation.return_value = True
        result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, mock_log_entry)
        self.assertTrue(result)
        self.item_mgr_mock.revert_item_creation.assert_called_once_with(self.guild_id, item_id)

    async def test_process_log_revert_item_deleted_success(self):
        original_item_data = {"id": "item_def", "template_id": "tpl_potion", "quantity": 1}
        log_details = {"revert_data": {"original_item_data": original_item_data}} # ITEM_DELETED logs revert_data
        mock_log_entry = {
            "id": self.log_id, "guild_id": self.guild_id, "player_id": self.player_id,
            "event_type": "ITEM_DELETED", "details": json.dumps(log_details)
        }
        self.item_mgr_mock.revert_item_deletion.return_value = True
        result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, mock_log_entry)
        self.assertTrue(result)
        self.item_mgr_mock.revert_item_deletion.assert_called_once_with(self.guild_id, original_item_data)

    async def test_process_log_revert_item_updated_success(self):
        item_id = "item_ghi"
        old_field_values = {"quantity": 5}
        log_details = {"item_id": item_id, "revert_data": {"old_field_values": old_field_values}}
        mock_log_entry = {
            "id": self.log_id, "guild_id": self.guild_id, "player_id": self.player_id,
            "event_type": "ITEM_UPDATED", "details": json.dumps(log_details)
        }
        self.item_mgr_mock.revert_item_update.return_value = True
        result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, mock_log_entry)
        self.assertTrue(result)
        self.item_mgr_mock.revert_item_update.assert_called_once_with(self.guild_id, item_id, old_field_values)

    async def test_process_log_revert_quest_started_success(self):
        quest_id = "q_start"
        log_details = {"quest_id": quest_id}
        mock_log_entry = {
            "id": self.log_id, "guild_id": self.guild_id, "player_id": self.player_id,
            "event_type": "QUEST_STARTED", "details": json.dumps(log_details)
        }
        self.quest_mgr_mock.revert_quest_start.return_value = True
        result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, mock_log_entry)
        self.assertTrue(result)
        self.quest_mgr_mock.revert_quest_start.assert_called_once_with(self.guild_id, self.player_id, quest_id)

    async def test_process_log_revert_quest_status_changed_success(self):
        quest_id = "q_status"
        old_status = "active"
        old_quest_data = {"id": quest_id, "status": "active", "progress": {}}
        log_details = {"quest_id": quest_id, "revert_data": {"old_status": old_status, "old_quest_data": old_quest_data}}
        mock_log_entry = {
            "id": self.log_id, "guild_id": self.guild_id, "player_id": self.player_id,
            "event_type": "QUEST_STATUS_CHANGED", "details": json.dumps(log_details)
        }
        self.quest_mgr_mock.revert_quest_status_change.return_value = True
        result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, mock_log_entry)
        self.assertTrue(result)
        self.quest_mgr_mock.revert_quest_status_change.assert_called_once_with(
            self.guild_id, self.player_id, quest_id, old_status, old_quest_data
        )

    async def test_process_log_revert_quest_progress_updated_success(self):
        quest_id = "q_progress"
        objective_id = "obj1"
        old_progress = 0
        log_details = {"quest_id": quest_id, "objective_id": objective_id, "revert_data": {"old_progress": old_progress}}
        mock_log_entry = {
            "id": self.log_id, "guild_id": self.guild_id, "player_id": self.player_id,
            "event_type": "QUEST_PROGRESS_UPDATED", "details": json.dumps(log_details)
        }
        self.quest_mgr_mock.revert_quest_progress_update.return_value = True
        result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, mock_log_entry)
        self.assertTrue(result)
        self.quest_mgr_mock.revert_quest_progress_update.assert_called_once_with(
            self.guild_id, self.player_id, quest_id, objective_id, old_progress
        )

    async def test_process_log_revert_gm_action_delete_character(self):
        char_id_deleted = "char_deleted_by_gm"
        original_char_data = {"id": char_id_deleted, "name": "Old Name"} # Simplified
        log_details = {"character_id": char_id_deleted, "revert_data": {"original_character_data": original_char_data}}
        mock_log_entry = {
            "id": self.log_id, "guild_id": self.guild_id,
            "event_type": "GM_ACTION_DELETE_CHARACTER", "details": json.dumps(log_details)
            # player_id might be the GM's ID or None for this log type
        }
        # We expect this to return True but log a warning, and not call a recreate method yet
        result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, mock_log_entry)
        self.assertTrue(result, "Revert of GM character deletion should allow other undos to proceed.")
        self.char_mgr_mock.recreate_character_from_data.assert_not_called() # Assuming this method name if it existed

    # --- Tests for undo_last_player_event ---
    async def test_undo_last_player_event_success_one_step(self):
        self.game_log_mgr_mock.get_logs_by_guild.return_value = [
            {"id": "log1", "player_id": self.player_id, "details": json.dumps({"revert_data": {}})}
        ]
        with patch.object(self.undo_manager, '_process_log_entry_for_revert', new_callable=AsyncMock) as mock_process:
            mock_process.return_value = True
            self.game_log_mgr_mock.delete_log_entry.return_value = True

            result = await self.undo_manager.undo_last_player_event(self.guild_id, self.player_id, num_steps=1)

            self.assertTrue(result)
            self.game_log_mgr_mock.get_logs_by_guild.assert_called_once_with(
                self.guild_id, limit=1, player_id_filter=self.player_id
            )
            mock_process.assert_called_once_with(self.guild_id, self.game_log_mgr_mock.get_logs_by_guild.return_value[0])
            self.game_log_mgr_mock.delete_log_entry.assert_called_once_with("log1", self.guild_id)

    async def test_undo_last_player_event_revert_fails(self):
        self.game_log_mgr_mock.get_logs_by_guild.return_value = [
            {"id": "log1", "player_id": self.player_id, "details": json.dumps({"revert_data": {}})}
        ]
        with patch.object(self.undo_manager, '_process_log_entry_for_revert', new_callable=AsyncMock) as mock_process:
            mock_process.return_value = False # Simulate revert failure

            result = await self.undo_manager.undo_last_player_event(self.guild_id, self.player_id, num_steps=1)

            self.assertFalse(result)
            mock_process.assert_called_once()
            self.game_log_mgr_mock.delete_log_entry.assert_not_called()

    async def test_undo_last_player_event_no_logs(self):
        self.game_log_mgr_mock.get_logs_by_guild.return_value = []
        with patch.object(self.undo_manager, '_process_log_entry_for_revert', new_callable=AsyncMock) as mock_process:
            result = await self.undo_manager.undo_last_player_event(self.guild_id, self.player_id, num_steps=1)

            self.assertTrue(result) # Nothing to undo is a success
            mock_process.assert_not_called()
            self.game_log_mgr_mock.delete_log_entry.assert_not_called()

    # --- Tests for undo_last_party_event ---
    async def test_undo_last_party_event_success(self):
        party_id_test = "test_party_1"
        mock_log_for_party = {"id": "log_party1", "party_id": party_id_test, "details": json.dumps({"revert_data": {}})}
        self.game_log_mgr_mock.get_logs_by_guild.return_value = [mock_log_for_party]

        with patch.object(self.undo_manager, '_process_log_entry_for_revert', new_callable=AsyncMock) as mock_process:
            mock_process.return_value = True
            self.game_log_mgr_mock.delete_log_entry.return_value = True

            result = await self.undo_manager.undo_last_party_event(self.guild_id, party_id_test, num_steps=1)

            self.assertTrue(result)
            self.game_log_mgr_mock.get_logs_by_guild.assert_called_once_with(
                self.guild_id, limit=1, party_id_filter=party_id_test
            )
            mock_process.assert_called_once_with(self.guild_id, mock_log_for_party)
            self.game_log_mgr_mock.delete_log_entry.assert_called_once_with("log_party1", self.guild_id)

    # --- Tests for undo_to_log_entry ---
    async def test_undo_to_log_entry_success(self):
        logs_in_db = [
            {"id": "log5_newest", "player_id": self.player_id, "details": json.dumps({})},
            {"id": "log4", "player_id": self.player_id, "details": json.dumps({})},
            {"id": "log3_target_becomes_this", "player_id": self.player_id, "details": json.dumps({})},
            {"id": "log2_older", "player_id": self.player_id, "details": json.dumps({})},
            {"id": "log1_oldest", "player_id": self.player_id, "details": json.dumps({})}
        ]
        self.game_log_mgr_mock.get_logs_by_guild.return_value = logs_in_db

        with patch.object(self.undo_manager, '_process_log_entry_for_revert', new_callable=AsyncMock) as mock_process:
            mock_process.return_value = True
            self.game_log_mgr_mock.delete_log_entry.return_value = True

            target_log_id = "log3_target_becomes_this"
            result = await self.undo_manager.undo_to_log_entry(self.guild_id, target_log_id)

            self.assertTrue(result)
            self.game_log_mgr_mock.get_logs_by_guild.assert_called_once_with(self.guild_id, limit=10000)

            # Should process log5 and log4
            self.assertEqual(mock_process.call_count, 2)
            mock_process.assert_any_call(self.guild_id, logs_in_db[0]) # log5
            mock_process.assert_any_call(self.guild_id, logs_in_db[1]) # log4

            self.assertEqual(self.game_log_mgr_mock.delete_log_entry.call_count, 2)
            self.game_log_mgr_mock.delete_log_entry.assert_any_call("log5_newest", self.guild_id)
            self.game_log_mgr_mock.delete_log_entry.assert_any_call("log4", self.guild_id)

    async def test_undo_to_log_entry_target_not_found(self):
        self.game_log_mgr_mock.get_logs_by_guild.return_value = [{"id": "log1"}, {"id": "log2"}]

        result = await self.undo_manager.undo_to_log_entry(self.guild_id, "log_not_in_db")
        self.assertFalse(result)
        self.game_log_mgr_mock.get_logs_by_guild.assert_called_once_with(self.guild_id, limit=10000)

    async def test_undo_to_log_entry_with_player_filter(self):
        other_player_id = "other_player"
        logs_in_db = [
            {"id": "logA_p1", "player_id": self.player_id, "details": json.dumps({})},      # Revert
            {"id": "logB_p2", "player_id": other_player_id, "details": json.dumps({})},   # Skip
            {"id": "logC_p1_target", "player_id": self.player_id, "details": json.dumps({})}, # Target
            {"id": "logD_p1_older", "player_id": self.player_id, "details": json.dumps({})}    # Older, not reverted
        ]
        self.game_log_mgr_mock.get_logs_by_guild.return_value = logs_in_db

        with patch.object(self.undo_manager, '_process_log_entry_for_revert', new_callable=AsyncMock) as mock_process:
            mock_process.return_value = True
            self.game_log_mgr_mock.delete_log_entry.return_value = True

            target_log_id = "logC_p1_target"
            result = await self.undo_manager.undo_to_log_entry(
                self.guild_id, target_log_id, player_or_party_id=self.player_id, entity_type="player"
            )
            self.assertTrue(result)
            mock_process.assert_called_once_with(self.guild_id, logs_in_db[0]) # Only logA_p1
            self.game_log_mgr_mock.delete_log_entry.assert_called_once_with("logA_p1", self.guild_id)

    async def test_undo_specific_log_entry_success(self):
        # 1. Setup: Mock GameLogManager.get_log_by_id to return a sample log
        #    sample_log_id = "specific_log_to_undo"
        #    mock_log_entry = {
        #        "id": sample_log_id, "guild_id": self.guild_id, "player_id": self.player_id,
        #        "event_type": "PLAYER_XP_CHANGED", # Example event type
        #        "details": json.dumps({"revert_data": {"old_xp": 10, "old_level": 1, "old_unspent_xp": 0}})
        #    }
        #    self.game_log_mgr_mock.get_log_by_id.return_value = mock_log_entry
        #
        #    # Mock _process_log_entry_for_revert to return True
        #    with patch.object(self.undo_manager, '_process_log_entry_for_revert', new_callable=AsyncMock) as mock_process_revert:
        #        mock_process_revert.return_value = True
        #        # Mock delete_log_entry to return True
        #        self.game_log_mgr_mock.delete_log_entry.return_value = True
        #
        #        # 2. Action: Call undo_specific_log_entry
        #        result = await self.undo_manager.undo_specific_log_entry(self.guild_id, sample_log_id)
        #
        #        # 3. Assert: Check success, and that methods were called
        #        self.assertTrue(result)
        #        self.game_log_mgr_mock.get_log_by_id.assert_called_once_with(sample_log_id, self.guild_id)
        #        mock_process_revert.assert_called_once_with(self.guild_id, mock_log_entry)
        #        self.game_log_mgr_mock.delete_log_entry.assert_called_once_with(sample_log_id)
        pass

    async def test_undo_specific_log_entry_log_not_found(self):
        # 1. Setup: Mock GameLogManager.get_log_by_id to return None
        #    sample_log_id = "non_existent_log"
        #    self.game_log_mgr_mock.get_log_by_id.return_value = None
        #
        #    with patch.object(self.undo_manager, '_process_log_entry_for_revert', new_callable=AsyncMock) as mock_process_revert:
        #        # 2. Action
        #        result = await self.undo_manager.undo_specific_log_entry(self.guild_id, sample_log_id)
        #
        #        # 3. Assert
        #        self.assertFalse(result)
        #        self.game_log_mgr_mock.get_log_by_id.assert_called_once_with(sample_log_id, self.guild_id)
        #        mock_process_revert.assert_not_called()
        #        self.game_log_mgr_mock.delete_log_entry.assert_not_called()
        pass

    async def test_undo_specific_log_entry_revert_fails(self):
        # 1. Setup
        #    sample_log_id = "log_revert_fail"
        #    mock_log_entry = {"id": sample_log_id, "details": json.dumps({})}
        #    self.game_log_mgr_mock.get_log_by_id.return_value = mock_log_entry
        #    with patch.object(self.undo_manager, '_process_log_entry_for_revert', new_callable=AsyncMock) as mock_process_revert:
        #        mock_process_revert.return_value = False # Simulate revert failure
        #
        #        # 2. Action
        #        result = await self.undo_manager.undo_specific_log_entry(self.guild_id, sample_log_id)
        #
        #        # 3. Assert
        #        self.assertFalse(result)
        #        mock_process_revert.assert_called_once()
        #        self.game_log_mgr_mock.delete_log_entry.assert_not_called() # Should not delete if revert fails
        pass

# Separate class for detailed _process_log_entry_for_revert cases
class TestUndoManagerProcessLogEntryRevertCases(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.guild_id = "test_guild_process_revert"
        self.player_id = "test_player_process_revert"
        self.log_id_counter = 0

        self.game_log_mgr_mock = AsyncMock(spec=GameLogManager)
        self.char_mgr_mock = AsyncMock(spec=CharacterManager)
        self.item_mgr_mock = AsyncMock(spec=ItemManager)
        self.quest_mgr_mock = AsyncMock(spec=QuestManager)
        self.party_mgr_mock = AsyncMock(spec=PartyManager)
        self.npc_mgr_mock = AsyncMock(spec=NpcManager)
        self.loc_mgr_mock = AsyncMock(spec=LocationManager)

        self.undo_manager = UndoManager(
            game_log_manager=self.game_log_mgr_mock,
            character_manager=self.char_mgr_mock,
            item_manager=self.item_mgr_mock,
            quest_manager=self.quest_mgr_mock,
            party_manager=self.party_mgr_mock,
            npc_manager=self.npc_mgr_mock,
            location_manager=self.loc_mgr_mock
        )

    def _create_mock_log_entry(self, event_type: str, details: Dict[str, Any], entity_id: Optional[str] = None, entity_key: str = "player_id") -> Dict[str, Any]:
        self.log_id_counter += 1
        log_entry = {
            "id": f"log_{self.log_id_counter}",
            "guild_id": self.guild_id,
            "event_type": event_type,
            "details": json.dumps(details) # Details must be JSON string
        }
        if entity_id:
            log_entry[entity_key] = entity_id
        elif entity_key == "player_id": # Default player_id if no entity_id given for player events
             log_entry[entity_key] = self.player_id
        return log_entry

    # --- CharacterManager Event Tests ---
    async def test_process_revert_PLAYER_XP_CHANGED(self):
        #    details = {"revert_data": {"old_xp": 10, "old_level": 1, "old_unspent_xp": 5}}
        #    log_entry = self._create_mock_log_entry("PLAYER_XP_CHANGED", details)
        #    self.char_mgr_mock.revert_xp_change.return_value = True
        #    result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, log_entry)
        #    self.assertTrue(result)
        #    self.char_mgr_mock.revert_xp_change.assert_called_once_with(self.guild_id, self.player_id, 10, 1, 5)
        pass

    async def test_process_revert_PLAYER_GOLD_CHANGED(self):
        #    details = {"revert_data": {"old_gold": 100}}
        #    log_entry = self._create_mock_log_entry("PLAYER_GOLD_CHANGED", details)
        #    self.char_mgr_mock.revert_gold_change.return_value = True
        #    result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, log_entry)
        #    self.assertTrue(result)
        #    self.char_mgr_mock.revert_gold_change.assert_called_once_with(self.guild_id, self.player_id, 100)
        pass

    async def test_process_revert_PLAYER_ACTION_QUEUE_CHANGED(self):
        #    old_json = json.dumps([{"action": "test"}])
        #    details = {"revert_data": {"old_action_queue_json": old_json}}
        #    log_entry = self._create_mock_log_entry("PLAYER_ACTION_QUEUE_CHANGED", details)
        #    self.char_mgr_mock.revert_action_queue_change.return_value = True
        #    result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, log_entry)
        #    self.assertTrue(result)
        #    self.char_mgr_mock.revert_action_queue_change.assert_called_once_with(self.guild_id, self.player_id, old_json)
        pass

    async def test_process_revert_PLAYER_COLLECTED_ACTIONS_CHANGED(self):
        #    old_json = json.dumps({"action": "test_collected"})
        #    details = {"revert_data": {"old_collected_actions_json": old_json}}
        #    log_entry = self._create_mock_log_entry("PLAYER_COLLECTED_ACTIONS_CHANGED", details)
        #    self.char_mgr_mock.revert_collected_actions_change.return_value = True
        #    result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, log_entry)
        #    self.assertTrue(result)
        #    self.char_mgr_mock.revert_collected_actions_change.assert_called_once_with(self.guild_id, self.player_id, old_json)
        pass

    async def test_process_revert_PLAYER_CREATED(self):
        #    # player_id from log entry is used as character_id
        #    log_entry = self._create_mock_log_entry("PLAYER_CREATED", {}, entity_id=self.player_id)
        #    self.char_mgr_mock.revert_character_creation.return_value = True
        #    result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, log_entry)
        #    self.assertTrue(result)
        #    self.char_mgr_mock.revert_character_creation.assert_called_once_with(self.guild_id, self.player_id)
        pass

    async def test_process_revert_GM_CHARACTER_RECREATED(self):
        #    char_id_recreated = "char_recreated_xyz"
        #    details = {"character_id": char_id_recreated}
        #    log_entry = self._create_mock_log_entry("GM_CHARACTER_RECREATED", details) # player_id might be GM
        #    self.char_mgr_mock.revert_character_creation.return_value = True
        #    result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, log_entry)
        #    self.assertTrue(result)
        #    self.char_mgr_mock.revert_character_creation.assert_called_once_with(self.guild_id, char_id_recreated)
        pass

    # --- NPCManager Event Tests ---
    async def test_process_revert_NPC_SPAWNED(self):
        #    npc_id = "npc_spawned_1"
        #    details = {"npc_id": npc_id}
        #    log_entry = self._create_mock_log_entry("NPC_SPAWNED", details, entity_key="npc_id", entity_id=npc_id)
        #    self.npc_mgr_mock.revert_npc_spawn.return_value = True
        #    result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, log_entry)
        #    self.assertTrue(result)
        #    self.npc_mgr_mock.revert_npc_spawn.assert_called_once_with(self.guild_id, npc_id)
        pass

    async def test_process_revert_NPC_LOCATION_CHANGED(self):
        #    npc_id = "npc_loc_change_1"
        #    old_loc = "old_npc_loc"
        #    details = {"npc_id": npc_id, "revert_data": {"old_location_id": old_loc}}
        #    log_entry = self._create_mock_log_entry("NPC_LOCATION_CHANGED", details, entity_key="npc_id", entity_id=npc_id)
        #    self.npc_mgr_mock.revert_npc_location_change.return_value = True
        #    result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, log_entry)
        #    self.assertTrue(result)
        #    self.npc_mgr_mock.revert_npc_location_change.assert_called_once_with(self.guild_id, npc_id, old_loc)
        pass

    async def test_process_revert_NPC_HP_CHANGED(self):
        #    npc_id = "npc_hp_change_1"
        #    details = {"npc_id": npc_id, "revert_data": {"old_hp": 30.0, "old_is_alive": True}}
        #    log_entry = self._create_mock_log_entry("NPC_HP_CHANGED", details, entity_key="npc_id", entity_id=npc_id)
        #    self.npc_mgr_mock.revert_npc_hp_change.return_value = True
        #    result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, log_entry)
        #    self.assertTrue(result)
        #    self.npc_mgr_mock.revert_npc_hp_change.assert_called_once_with(self.guild_id, npc_id, 30.0, True)
        pass

    async def test_process_revert_NPC_STATS_UPDATED(self):
        #    npc_id = "npc_stats_upd"
        #    changes = [{"stat": "str", "old_value": 8}]
        #    details = {"npc_id": npc_id, "revert_data": {"stat_changes": changes}}
        #    log_entry = self._create_mock_log_entry("NPC_STATS_UPDATED", details, entity_key="npc_id", entity_id=npc_id)
        #    self.npc_mgr_mock.revert_npc_stat_changes.return_value = True
        #    result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, log_entry)
        #    self.assertTrue(result)
        #    self.npc_mgr_mock.revert_npc_stat_changes.assert_called_once_with(self.guild_id, npc_id, changes)
        pass

    async def test_process_revert_NPC_INVENTORY_CHANGED(self):
        #    npc_id = "npc_inv_change"
        #    changes = [{"action": "added", "item_id": "sword", "quantity": 1}]
        #    details = {"npc_id": npc_id, "revert_data": {"inventory_changes": changes}}
        #    log_entry = self._create_mock_log_entry("NPC_INVENTORY_CHANGED", details, entity_key="npc_id", entity_id=npc_id)
        #    self.npc_mgr_mock.revert_npc_inventory_changes.return_value = True
        #    result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, log_entry)
        #    self.assertTrue(result)
        #    self.npc_mgr_mock.revert_npc_inventory_changes.assert_called_once_with(self.guild_id, npc_id, changes)
        pass

    async def test_process_revert_NPC_PARTY_CHANGED(self):
        #    npc_id = "npc_pty_change"
        #    old_party = "party_old_id"
        #    details = {"npc_id": npc_id, "revert_data": {"old_party_id": old_party}}
        #    log_entry = self._create_mock_log_entry("NPC_PARTY_CHANGED", details, entity_key="npc_id", entity_id=npc_id)
        #    self.npc_mgr_mock.revert_npc_party_change.return_value = True
        #    result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, log_entry)
        #    self.assertTrue(result)
        #    self.npc_mgr_mock.revert_npc_party_change.assert_called_once_with(self.guild_id, npc_id, old_party)
        pass

    async def test_process_revert_NPC_STATE_VARIABLES_CHANGED(self):
        #    npc_id = "npc_stvar_change"
        #    old_json = json.dumps({"mood": "calm"})
        #    details = {"npc_id": npc_id, "revert_data": {"old_state_variables_json": old_json}}
        #    log_entry = self._create_mock_log_entry("NPC_STATE_VARIABLES_CHANGED", details, entity_key="npc_id", entity_id=npc_id)
        #    self.npc_mgr_mock.revert_npc_state_variables_change.return_value = True
        #    result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, log_entry)
        #    self.assertTrue(result)
        #    self.npc_mgr_mock.revert_npc_state_variables_change.assert_called_once_with(self.guild_id, npc_id, old_json)
        pass

    async def test_process_revert_GM_NPC_RECREATED(self):
        #    npc_id_recreated = "npc_recreated_xyz"
        #    details = {"npc_id": npc_id_recreated}
        #    log_entry = self._create_mock_log_entry("GM_NPC_RECREATED", details, entity_key="npc_id", entity_id=npc_id_recreated)
        #    self.npc_mgr_mock.revert_npc_spawn.return_value = True # Revert is to spawn (delete)
        #    result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, log_entry)
        #    self.assertTrue(result)
        #    self.npc_mgr_mock.revert_npc_spawn.assert_called_once_with(self.guild_id, npc_id_recreated)
        pass

    # --- ItemManager Event Tests ---
    async def test_process_revert_ITEM_OWNER_CHANGED(self):
        #    item_id = "item_owner_change_1"
        #    revert_data = {"old_owner_id": "owner_A", "old_owner_type": "Character", "old_location_id_if_unowned": "loc_A"}
        #    details = {"item_id": item_id, "revert_data": revert_data}
        #    log_entry = self._create_mock_log_entry("ITEM_OWNER_CHANGED", details) # player_id from log_entry is not used here
        #    self.item_mgr_mock.revert_item_owner_change.return_value = True
        #    result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, log_entry)
        #    self.assertTrue(result)
        #    self.item_mgr_mock.revert_item_owner_change.assert_called_once_with(self.guild_id, item_id, "owner_A", "Character", "loc_A")
        pass

    async def test_process_revert_ITEM_QUANTITY_CHANGED(self):
        #    item_id = "item_qty_change_1"
        #    details = {"item_id": item_id, "revert_data": {"old_quantity": 5.0}}
        #    log_entry = self._create_mock_log_entry("ITEM_QUANTITY_CHANGED", details)
        #    self.item_mgr_mock.revert_item_quantity_change.return_value = True
        #    result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, log_entry)
        #    self.assertTrue(result)
        #    self.item_mgr_mock.revert_item_quantity_change.assert_called_once_with(self.guild_id, item_id, 5.0)
        pass

    # --- LocationManager Event Tests ---
    async def test_process_revert_LOCATION_STATE_VARIABLE_CHANGED(self):
        #    loc_id = "loc_stvar_change"
        #    var_name = "is_lit"
        #    old_val = True
        #    details = {"location_id": loc_id, "variable_name": var_name, "revert_data": {"old_value": old_val}}
        #    log_entry = self._create_mock_log_entry("LOCATION_STATE_VARIABLE_CHANGED", details)
        #    self.loc_mgr_mock.revert_location_state_variable_change.return_value = True
        #    result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, log_entry)
        #    self.assertTrue(result)
        #    self.loc_mgr_mock.revert_location_state_variable_change.assert_called_once_with(self.guild_id, loc_id, var_name, old_val)
        pass

    async def test_process_revert_LOCATION_INVENTORY_CHANGED(self):
        #    loc_id = "loc_inv_change"
        #    revert_details = {
        #        "location_id": loc_id, "item_template_id": "rock", "item_instance_id": "rock1",
        #        "change_action": "added", "quantity_changed": 1,
        #        "revert_data": {"original_item_data": None} # Or some data if action was 'removed'
        #    }
        #    log_entry = self._create_mock_log_entry("LOCATION_INVENTORY_CHANGED", revert_details)
        #    self.loc_mgr_mock.revert_location_inventory_change.return_value = True
        #    result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, log_entry)
        #    self.assertTrue(result)
        #    self.loc_mgr_mock.revert_location_inventory_change.assert_called_once_with(
        #        self.guild_id, loc_id, "rock", "rock1", "added", 1, None
        #    )
        pass

    async def test_process_revert_LOCATION_EXIT_CHANGED(self):
        #    loc_id = "loc_exit_change"
        #    direction = "north"
        #    old_target = "loc_B"
        #    details = {"location_id": loc_id, "exit_direction": direction, "revert_data": {"old_target_location_id": old_target}}
        #    log_entry = self._create_mock_log_entry("LOCATION_EXIT_CHANGED", details)
        #    self.loc_mgr_mock.revert_location_exit_change.return_value = True
        #    result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, log_entry)
        #    self.assertTrue(result)
        #    self.loc_mgr_mock.revert_location_exit_change.assert_called_once_with(self.guild_id, loc_id, direction, old_target)
        pass

    async def test_process_revert_LOCATION_ACTIVATION_STATUS_CHANGED(self):
        #    loc_id = "loc_active_change"
        #    old_status = False
        #    details = {"location_id": loc_id, "revert_data": {"old_is_active_status": old_status}}
        #    log_entry = self._create_mock_log_entry("LOCATION_ACTIVATION_STATUS_CHANGED", details)
        #    self.loc_mgr_mock.revert_location_activation_status.return_value = True
        #    result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, log_entry)
        #    self.assertTrue(result)
        #    self.loc_mgr_mock.revert_location_activation_status.assert_called_once_with(self.guild_id, loc_id, old_status)
        pass

    # --- PartyManager Event Tests ---
    async def test_process_revert_PARTY_CREATED(self):
        #    party_id_created = "party_xyz"
        #    # Log entry's party_id field or details.party_id
        #    log_entry = self._create_mock_log_entry("PARTY_CREATED", {"party_id": party_id_created}, entity_key="party_id", entity_id=party_id_created)
        #    self.party_mgr_mock.revert_party_creation.return_value = True
        #    result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, log_entry)
        #    self.assertTrue(result)
        #    self.party_mgr_mock.revert_party_creation.assert_called_once_with(self.guild_id, party_id_created)
        pass

    async def test_process_revert_PARTY_MEMBER_ADDED(self):
        #    party_id = "party_abc"
        #    member_id = "char_123"
        #    details = {"party_id": party_id, "member_id": member_id}
        #    # Log entry might have party_id and player_id (as member_id)
        #    log_entry = self._create_mock_log_entry("PARTY_MEMBER_ADDED", details, entity_id=member_id, entity_key="player_id")
        #    log_entry['party_id'] = party_id # Ensure party_id is also in log_entry directly if needed
        #    self.party_mgr_mock.revert_party_member_add.return_value = True
        #    result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, log_entry)
        #    self.assertTrue(result)
        #    self.party_mgr_mock.revert_party_member_add.assert_called_once_with(self.guild_id, party_id, member_id)
        pass

    async def test_process_revert_PARTY_MEMBER_REMOVED(self):
        #    party_id = "party_def"
        #    member_id = "char_456"
        #    old_leader_id = "leader_old"
        #    details = {"party_id": party_id, "member_id": member_id, "revert_data": {"old_leader_id_if_changed": old_leader_id}}
        #    log_entry = self._create_mock_log_entry("PARTY_MEMBER_REMOVED", details, entity_id=member_id, entity_key="player_id")
        #    log_entry['party_id'] = party_id
        #    self.party_mgr_mock.revert_party_member_remove.return_value = True
        #    result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, log_entry)
        #    self.assertTrue(result)
        #    self.party_mgr_mock.revert_party_member_remove.assert_called_once_with(self.guild_id, party_id, member_id, old_leader_id)
        pass

    async def test_process_revert_PARTY_LEADER_CHANGED(self):
        #    party_id_leader = "party_leader_change"
        #    old_leader = "old_leader_char"
        #    details = {"party_id": party_id_leader, "revert_data": {"old_leader_id": old_leader}}
        #    log_entry = self._create_mock_log_entry("PARTY_LEADER_CHANGED", details, entity_key="party_id", entity_id=party_id_leader)
        #    self.party_mgr_mock.revert_party_leader_change.return_value = True
        #    result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, log_entry)
        #    self.assertTrue(result)
        #    self.party_mgr_mock.revert_party_leader_change.assert_called_once_with(self.guild_id, party_id_leader, old_leader)
        pass

    async def test_process_revert_PARTY_LOCATION_CHANGED(self):
        #    party_id_loc = "party_loc_change"
        #    old_loc = "loc_old_party"
        #    details = {"party_id": party_id_loc, "revert_data": {"old_location_id": old_loc}}
        #    log_entry = self._create_mock_log_entry("PARTY_LOCATION_CHANGED", details, entity_key="party_id", entity_id=party_id_loc)
        #    self.party_mgr_mock.revert_party_location_change.return_value = True
        #    result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, log_entry)
        #    self.assertTrue(result)
        #    self.party_mgr_mock.revert_party_location_change.assert_called_once_with(self.guild_id, party_id_loc, old_loc)
        pass

    async def test_process_revert_PARTY_TURN_STATUS_CHANGED(self):
        #    party_id_turn = "party_turn_change"
        #    old_status = "pending"
        #    details = {"party_id": party_id_turn, "revert_data": {"old_turn_status": old_status}}
        #    log_entry = self._create_mock_log_entry("PARTY_TURN_STATUS_CHANGED", details, entity_key="party_id", entity_id=party_id_turn)
        #    self.party_mgr_mock.revert_party_turn_status_change.return_value = True
        #    result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, log_entry)
        #    self.assertTrue(result)
        #    self.party_mgr_mock.revert_party_turn_status_change.assert_called_once_with(self.guild_id, party_id_turn, old_status)
        pass

    async def test_process_revert_GM_PARTY_RECREATED(self):
        #    party_id_recreated = "party_recreated_xyz"
        #    details = {"party_id": party_id_recreated}
        #    log_entry = self._create_mock_log_entry("GM_PARTY_RECREATED", details, entity_key="party_id", entity_id=party_id_recreated)
        #    self.party_mgr_mock.revert_party_creation.return_value = True # Revert is to delete
        #    result = await self.undo_manager._process_log_entry_for_revert(self.guild_id, log_entry)
        #    self.assertTrue(result)
        #    self.party_mgr_mock.revert_party_creation.assert_called_once_with(self.guild_id, party_id_recreated)
        pass


if __name__ == '__main__':
    asyncio.run(unittest.main())
