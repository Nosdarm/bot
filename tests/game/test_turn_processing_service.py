import asyncio
import unittest
import json
from unittest.mock import MagicMock, AsyncMock, patch

from typing import Dict, Any, List, Optional

from bot.game.turn_processing_service import TurnProcessingService
from bot.ai.rules_schema import CoreGameRulesConfig, ActionConflictDefinition # For rules_config
# For mocking player data - can use MagicMock configured to look like Player model
# from bot.database.models import Player

class MockPlayer:
    def __init__(self, player_id: str, guild_id: str, collected_actions_json_str: Optional[str] = None, current_game_status: str = "processing"):
        self.id = player_id
        self.guild_id = guild_id
        self.collected_actions_json = collected_actions_json_str
        self.current_game_status = current_game_status
        # Add other attributes as needed by TurnProcessingService or its callees
        self.name = f"Player_{player_id}"
        self.selected_language = "en"

    def clear_collected_actions(self): # As used in TPS
        self.collected_actions_json = None


class TestTurnProcessingService(unittest.TestCase):

    def setUp(self):
        self.mock_character_manager = AsyncMock()
        self.mock_conflict_resolver = AsyncMock()
        self.mock_rule_engine = MagicMock() # RuleEngine might not have async methods directly used by TPS init
        self.mock_game_manager = AsyncMock()
        self.mock_game_log_manager = AsyncMock()
        self.mock_character_action_processor = AsyncMock()
        self.mock_location_interaction_service = AsyncMock() # Added
        self.mock_combat_manager = AsyncMock() # Added as it's a TPS dependency
        self.mock_location_manager = MagicMock() # Added as it's a TPS dependency

        # Mock services accessed via game_manager
        self.mock_db_service = AsyncMock()
        self.mock_game_manager.db_service = self.mock_db_service

        # Mock settings for TPS
        self.mock_settings = {"turn_processing_action_read_delay": 0.01} # Small delay for tests

        # Setup mock CoreGameRulesConfig on rule_engine
        self.sample_rules_config = CoreGameRulesConfig(
            action_conflicts=[
                ActionConflictDefinition(
                    type="TEST_MANUAL_CONFLICT",
                    description="A test manual conflict",
                    involved_intent_pattern=["TEST_INTENT_A", "TEST_INTENT_B"],
                    resolution_type="manual_resolve",
                    manual_resolution_options=["Option1", "Option2"]
                )
            ]
            # Populate other rule sections if needed for specific tests
        )
        self.mock_rule_engine.rules_config_data = self.sample_rules_config


        self.tps = TurnProcessingService(
            character_manager=self.mock_character_manager,
            conflict_resolver=self.mock_conflict_resolver,
            rule_engine=self.mock_rule_engine,
            game_manager=self.mock_game_manager,
            game_log_manager=self.mock_game_log_manager,
            character_action_processor=self.mock_character_action_processor,
            combat_manager=self.mock_combat_manager, # Pass mock
            location_manager=self.mock_location_manager, # Pass mock
            location_interaction_service=self.mock_location_interaction_service, # Pass mock
            settings=self.mock_settings
        )

    def test_process_player_turns_action_loading_and_clearing(self):
        player_1_actions = [{"intent": "MOVE", "entities": [{"type": "direction", "value": "north"}]}]
        mock_player_1 = MockPlayer("player_1", "test_guild", json.dumps(player_1_actions))

        self.mock_character_manager.get_character.return_value = mock_player_1
        self.mock_conflict_resolver.analyze_actions_for_conflicts.return_value = {
            "actions_to_execute": [{"character_id": "player_1", "action_data": player_1_actions[0]}],
            "pending_conflict_details": [],
            "auto_resolution_outcomes": [],
            "requires_manual_resolution": False
        }
        # Mock the specific action handler called if actions_to_execute is processed
        self.mock_character_action_processor.handle_move_action.return_value = {"success": True, "message": "Moved.", "state_changed": True}

        asyncio.run(self.tps.process_player_turns(player_ids=["player_1"], guild_id="test_guild"))

        # Assert that collected_actions_json was cleared on the mock_player_1 object
        self.assertIsNone(mock_player_1.collected_actions_json)
        # Assert that mark_character_dirty was called for clearing (and potentially for status update at end)
        self.mock_character_manager.mark_character_dirty.assert_any_call("test_guild", "player_1")


    @patch('bot.game.turn_processing_service.PendingConflict') # Mock the PendingConflict class
    def test_process_player_turns_manual_conflict_path(self, MockPendingConflictClass: MagicMock):
        mock_player_A = MockPlayer("player_A", "test_guild", json.dumps([{"intent": "TEST_INTENT_A", "action_id": "actionA1"}]))
        mock_player_B = MockPlayer("player_B", "test_guild", json.dumps([{"intent": "TEST_INTENT_B", "action_id": "actionB1"}]))

        def get_char_side_effect(guild_id, char_id):
            if char_id == "player_A": return mock_player_A
            if char_id == "player_B": return mock_player_B
            return None
        self.mock_character_manager.get_character.side_effect = get_char_side_effect

        conflict_detail_for_db = {
            "conflict_type_id": "TEST_MANUAL_CONFLICT",
            "description_for_gm": "A test manual conflict",
            "involved_actions_data": [mock_player_A.collected_actions_json, mock_player_B.collected_actions_json], # Simplified
            "involved_player_ids": ["player_A", "player_B"],
            "manual_resolution_options": ["Option1", "Option2"],
            "guild_id": "test_guild"
        }
        self.mock_conflict_resolver.analyze_actions_for_conflicts.return_value = {
            "actions_to_execute": [],
            "pending_conflict_details": [conflict_detail_for_db],
            "auto_resolution_outcomes": [],
            "requires_manual_resolution": True
        }

        mock_pending_conflict_instance = MagicMock()
        MockPendingConflictClass.return_value = mock_pending_conflict_instance
        self.mock_db_service.add_entity = AsyncMock() # Ensure add_entity is an AsyncMock for await

        asyncio.run(self.tps.process_player_turns(player_ids=["player_A", "player_B"], guild_id="test_guild"))

        self.mock_db_service.add_entity.assert_called_once_with(mock_pending_conflict_instance)
        args, _ = MockPendingConflictClass.call_args
        self.assertEqual(args[0]['guild_id'], "test_guild")
        self.assertEqual(args[0]['status'], "pending_gm_resolution")
        saved_conflict_data = json.loads(args[0]['conflict_data_json'])
        self.assertEqual(saved_conflict_data['conflict_type_id'], "TEST_MANUAL_CONFLICT")
        self.assertCountEqual(saved_conflict_data['involved_player_ids'], ["player_A", "player_B"])

        # Ensure no action handlers were called
        self.mock_character_action_processor.handle_move_action.assert_not_called()
        self.mock_character_action_processor.handle_skill_use_action.assert_not_called()


    def test_process_player_turns_transactional_dispatch_commit(self):
        mock_player_1 = MockPlayer("player_1", "test_guild", json.dumps([{"intent": "MOVE", "action_id": "actionMove1"}]))
        self.mock_character_manager.get_character.return_value = mock_player_1
        self.mock_conflict_resolver.analyze_actions_for_conflicts.return_value = {
            "actions_to_execute": [{"character_id": "player_1", "action_data": json.loads(mock_player_1.collected_actions_json)[0]}],
            "pending_conflict_details": [], "auto_resolution_outcomes": [], "requires_manual_resolution": False
        }
        self.mock_character_action_processor.handle_move_action = AsyncMock(return_value={"success": True, "state_changed": True, "message": "Moved."})

        asyncio.run(self.tps.process_player_turns(player_ids=["player_1"], guild_id="test_guild"))

        self.mock_db_service.begin_transaction.assert_called_once()
        self.mock_character_action_processor.handle_move_action.assert_called_once()
        self.mock_db_service.commit_transaction.assert_called_once()
        self.mock_db_service.rollback_transaction.assert_not_called()

    def test_process_player_turns_transactional_dispatch_rollback_on_failure_with_state_change(self):
        mock_player_1 = MockPlayer("player_1", "test_guild", json.dumps([{"intent": "MOVE", "action_id": "actionMoveFail"}]))
        self.mock_character_manager.get_character.return_value = mock_player_1
        self.mock_conflict_resolver.analyze_actions_for_conflicts.return_value = {
            "actions_to_execute": [{"character_id": "player_1", "action_data": json.loads(mock_player_1.collected_actions_json)[0]}],
            "pending_conflict_details": [], "auto_resolution_outcomes": [], "requires_manual_resolution": False
        }
        self.mock_character_action_processor.handle_move_action = AsyncMock(return_value={"success": False, "state_changed": True, "message": "Failed to move but tried."})

        asyncio.run(self.tps.process_player_turns(player_ids=["player_1"], guild_id="test_guild"))

        self.mock_db_service.begin_transaction.assert_called_once()
        self.mock_character_action_processor.handle_move_action.assert_called_once()
        self.mock_db_service.commit_transaction.assert_not_called()
        self.mock_db_service.rollback_transaction.assert_called_once()

    def test_process_player_turns_transactional_dispatch_rollback_on_exception(self):
        mock_player_1 = MockPlayer("player_1", "test_guild", json.dumps([{"intent": "MOVE", "action_id": "actionMoveEx"}]))
        self.mock_character_manager.get_character.return_value = mock_player_1
        self.mock_conflict_resolver.analyze_actions_for_conflicts.return_value = {
            "actions_to_execute": [{"character_id": "player_1", "action_data": json.loads(mock_player_1.collected_actions_json)[0]}],
            "pending_conflict_details": [], "auto_resolution_outcomes": [], "requires_manual_resolution": False
        }
        self.mock_character_action_processor.handle_move_action = AsyncMock(side_effect=Exception("Handler error!"))

        asyncio.run(self.tps.process_player_turns(player_ids=["player_1"], guild_id="test_guild"))

        self.mock_db_service.begin_transaction.assert_called_once()
        self.mock_character_action_processor.handle_move_action.assert_called_once()
        self.mock_db_service.commit_transaction.assert_not_called()
        self.mock_db_service.rollback_transaction.assert_called_once()

if __name__ == '__main__':
    unittest.main()
