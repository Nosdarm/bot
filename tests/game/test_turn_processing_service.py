import asyncio
import unittest
import json
from unittest.mock import MagicMock, AsyncMock, patch
import uuid # For generating action_ids in helpers

from typing import Dict, Any, List, Optional

from bot.game.turn_processing_service import TurnProcessingService
from bot.ai.rules_schema import CoreGameRulesConfig, ActionConflictDefinition
# from bot.game.conflict_resolver import ActionWrapper, ActionStatus # MODIFIED: Removed import

# For mocking player data
class MockPlayer:
    def __init__(self, player_id: str, guild_id: str, collected_actions_json_str: Optional[str] = None, current_game_status: str = "processing"):
        self.id = player_id
        self.guild_id = guild_id
        self.collected_actions_json = collected_actions_json_str
        self.current_game_status = current_game_status
        self.name = f"Player_{player_id}"
        self.selected_language = "en"
        self.location_id = "start_location" # Default location for tests

    def clear_collected_actions(self):
        self.collected_actions_json = None

class TestTurnProcessingService(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.mock_character_manager = AsyncMock()
        self.mock_conflict_resolver = AsyncMock()
        self.mock_rule_engine = AsyncMock()
        self.mock_game_manager = AsyncMock()
        self.mock_game_log_manager = AsyncMock()
        self.mock_character_action_processor = AsyncMock()

        self.mock_item_manager = AsyncMock()
        self.mock_inventory_manager = AsyncMock() # TPS now takes InventoryManager for USE_ITEM if CAP doesn't handle it
        self.mock_equipment_manager = AsyncMock()
        self.mock_dialogue_manager = AsyncMock()
        self.mock_location_interaction_service = AsyncMock()
        self.mock_combat_manager = AsyncMock()
        self.mock_location_manager = AsyncMock()

        self.mock_db_service = AsyncMock()
        self.mock_db_service.begin_transaction = AsyncMock()
        self.mock_db_service.commit_transaction = AsyncMock()
        self.mock_db_service.rollback_transaction = AsyncMock()
        self.mock_db_service.is_transaction_active = MagicMock(return_value=False)

        self.mock_game_manager.db_service = self.mock_db_service
        self.mock_settings = {"turn_processing_action_read_delay": 0.0}

        self.sample_rules_config = CoreGameRulesConfig(action_conflicts=[])
        self.mock_rule_engine.rules_config_data = self.sample_rules_config

        self.tps = TurnProcessingService(
            character_manager=self.mock_character_manager,
            conflict_resolver=self.mock_conflict_resolver,
            rule_engine=self.mock_rule_engine,
            game_manager=self.mock_game_manager,
            game_log_manager=self.mock_game_log_manager,
            character_action_processor=self.mock_character_action_processor,
            combat_manager=self.mock_combat_manager,
            location_manager=self.mock_location_manager,
            location_interaction_service=self.mock_location_interaction_service,
            dialogue_manager=self.mock_dialogue_manager,
            inventory_manager=self.mock_inventory_manager,
            equipment_manager=self.mock_equipment_manager,
            item_manager=self.mock_item_manager,
            settings=self.mock_settings
        )

    async def _setup_intent_test(self, player_id: str, guild_id: str, action_data: Dict[str, Any]):
        action_data_with_id = {**action_data, "action_id": action_data.get("action_id", f"action_{uuid.uuid4().hex[:6]}")}
        mock_player = MockPlayer(player_id, guild_id, json.dumps([action_data_with_id]))

        self.mock_character_manager.get_character.return_value = mock_player

        self.mock_db_service.begin_transaction.reset_mock()
        self.mock_db_service.commit_transaction.reset_mock()
        self.mock_db_service.rollback_transaction.reset_mock()
        self.mock_game_manager.save_game_state_after_action.reset_mock()

        self.mock_conflict_resolver.analyze_actions_for_conflicts.return_value = {
            "actions_to_execute": [{"character_id": player_id, "action_data": action_data_with_id}],
            "pending_conflict_details": [], "auto_resolution_outcomes": [], "requires_manual_resolution": False
        }
        return mock_player, action_data_with_id

    async def test_intent_look_success_no_state_change(self):
        action_data = {"intent": "LOOK", "entities": []}
        mock_player, processed_action_data = await self._setup_intent_test("p_look", "g_look", action_data)
        self.mock_character_action_processor.handle_explore_action.return_value = {"success": True, "message": "You see a room.", "state_changed": False}
        result = await self.tps.process_player_turns(player_ids=["p_look"], guild_id="g_look")
        self.mock_character_action_processor.handle_explore_action.assert_called_once_with(character=mock_player, guild_id="g_look", action_params={'entities': []})
        self.mock_db_service.begin_transaction.assert_not_called()
        self.mock_db_service.commit_transaction.assert_not_called()
        self.mock_game_manager.save_game_state_after_action.assert_called_with("g_look", reason="End of turn processing cycle")
        self.assertEqual(mock_player.current_game_status, "turn_processed")
        self.assertIn("You see a room.", result["feedback_per_player"]["p_look"])

    async def test_intent_attack_success_state_changed(self):
        action_data = {"intent": "ATTACK", "entities": [{"type": "npc", "id": "goblin1"}]}
        mock_player, processed_action_data = await self._setup_intent_test("p_attack", "g_attack", action_data)
        self.mock_character_action_processor.handle_attack_action.return_value = {"success": True, "message": "Hit Goblin for 5 damage.", "state_changed": True}
        await self.tps.process_player_turns(player_ids=["p_attack"], guild_id="g_attack")
        self.mock_character_action_processor.handle_attack_action.assert_called_once_with(character_attacker=mock_player, guild_id="g_attack", action_data=processed_action_data, rules_config=self.sample_rules_config)
        self.mock_db_service.begin_transaction.assert_called_once()
        self.mock_db_service.commit_transaction.assert_called_once()
        self.mock_db_service.rollback_transaction.assert_not_called()
        self.mock_game_manager.save_game_state_after_action.assert_any_call("g_attack", reason="Post-action: ATTACK")

    async def test_intent_attack_handler_failure_state_changed(self):
        action_data = {"intent": "ATTACK", "entities": [{"type": "npc", "id": "goblin1"}]}
        mock_player, processed_action_data = await self._setup_intent_test("p_attack_fail", "g_attack_fail", action_data)
        self.mock_character_action_processor.handle_attack_action.return_value = {"success": False, "message": "Target not found.", "state_changed": True}
        result = await self.tps.process_player_turns(player_ids=["p_attack_fail"], guild_id="g_attack_fail")
        self.mock_db_service.begin_transaction.assert_called_once()
        self.mock_db_service.commit_transaction.assert_not_called()
        self.mock_db_service.rollback_transaction.assert_called_once()
        self.assertIn("Target not found.", result["feedback_per_player"]["p_attack_fail"])

    async def test_intent_equip_success_state_changed(self):
        action_data = {"intent": "EQUIP", "entities": [{"type": "item_instance_id", "id": "sword_inst_123"}]}
        mock_player, processed_action_data = await self._setup_intent_test("p_equip", "g_equip", action_data)
        self.mock_character_action_processor.handle_equip_item_action.return_value = {"success": True, "message": "Sword equipped.", "state_changed": True}
        await self.tps.process_player_turns(player_ids=["p_equip"], guild_id="g_equip")
        self.mock_character_action_processor.handle_equip_item_action.assert_called_once_with(character=mock_player, guild_id="g_equip", action_data=processed_action_data, rules_config=self.sample_rules_config)
        self.mock_db_service.begin_transaction.assert_called_once()
        self.mock_db_service.commit_transaction.assert_called_once()

    async def test_intent_unequip_success_state_changed(self):
        action_data = {"intent": "UNEQUIP", "entities": [{"type": "equipment_slot", "id": "main_hand"}]}
        mock_player, processed_action_data = await self._setup_intent_test("p_unequip", "g_unequip", action_data)
        self.mock_character_action_processor.handle_unequip_item_action.return_value = {"success": True, "message": "Sword unequipped.", "state_changed": True}
        await self.tps.process_player_turns(player_ids=["p_unequip"], guild_id="g_unequip")
        self.mock_character_action_processor.handle_unequip_item_action.assert_called_once_with(character=mock_player, guild_id="g_unequip", action_data=processed_action_data, rules_config=self.sample_rules_config)
        self.mock_db_service.begin_transaction.assert_called_once()
        self.mock_db_service.commit_transaction.assert_called_once()

    async def test_intent_drop_item_success_state_changed(self):
        action_data = {"intent": "DROP_ITEM", "entities": [{"type": "item_instance_id", "id": "potion_inst_456"}]}
        mock_player, processed_action_data = await self._setup_intent_test("p_drop", "g_drop", action_data)
        self.mock_character_action_processor.handle_drop_item_action.return_value = {"success": True, "message": "Potion dropped.", "state_changed": True}
        await self.tps.process_player_turns(player_ids=["p_drop"], guild_id="g_drop")
        self.mock_character_action_processor.handle_drop_item_action.assert_called_once_with(character=mock_player, guild_id="g_drop", action_data=processed_action_data, rules_config=self.sample_rules_config)
        self.mock_db_service.begin_transaction.assert_called_once()
        self.mock_db_service.commit_transaction.assert_called_once()

    async def test_intent_use_item_success_state_changed(self):
        action_data = {"intent": "USE_ITEM", "entities": [{"type": "item_template_id", "id": "health_potion_tpl"}]} # NLU gives template_id for "use"
        mock_player, processed_action_data = await self._setup_intent_test("p_use", "g_use", action_data)
        self.mock_item_manager.use_item.return_value = {"success": True, "message": "Used Health Potion.", "state_changed": True}
        await self.tps.process_player_turns(player_ids=["p_use"], guild_id="g_use")
        self.mock_item_manager.use_item.assert_called_once()
        args, kwargs = self.mock_item_manager.use_item.call_args
        self.assertEqual(kwargs.get("guild_id"), "g_use")
        self.assertEqual(kwargs.get("character_user"), mock_player)
        self.assertEqual(kwargs.get("item_template_id"), "health_potion_tpl")
        self.assertEqual(kwargs.get("rules_config"), self.sample_rules_config)
        self.mock_db_service.begin_transaction.assert_called_once()
        self.mock_db_service.commit_transaction.assert_called_once()

    async def test_intent_talk_success_no_state_change(self):
        action_data = {"intent": "TALK", "entities": [{"type": "npc", "id": "shopkeeper"}]}
        mock_player, processed_action_data = await self._setup_intent_test("p_talk", "g_talk", action_data)
        self.mock_dialogue_manager.handle_talk_action.return_value = {"success": True, "message": "Shopkeeper says hello.", "state_changed": False}
        await self.tps.process_player_turns(player_ids=["p_talk"], guild_id="g_talk")
        self.mock_dialogue_manager.handle_talk_action.assert_called_once_with(character_speaker=mock_player, guild_id="g_talk", action_data=processed_action_data, rules_config=self.sample_rules_config)
        self.mock_db_service.commit_transaction.assert_not_called()

    def test_process_player_turns_action_loading_and_clearing(self):
        player_1_actions = [{"intent": "MOVE", "entities": [{"type": "direction", "value": "north"}]}]
        mock_player_1 = MockPlayer("player_1", "test_guild", json.dumps(player_1_actions))
        self.mock_character_manager.get_character.return_value = mock_player_1
        self.mock_conflict_resolver.analyze_actions_for_conflicts.return_value = {
            "actions_to_execute": [{"character_id": "player_1", "action_data": player_1_actions[0]}],
            "pending_conflict_details": [], "auto_resolution_outcomes": [], "requires_manual_resolution": False
        }
        self.mock_character_action_processor.handle_move_action.return_value = {"success": True, "message": "Moved.", "state_changed": True}
        asyncio.run(self.tps.process_player_turns(player_ids=["player_1"], guild_id="test_guild"))
        self.assertIsNone(mock_player_1.collected_actions_json)
        self.mock_character_manager.mark_character_dirty.assert_any_call("test_guild", "player_1")

    @patch('bot.game.turn_processing_service.PendingConflict')
    def test_process_player_turns_manual_conflict_path(self, MockPendingConflictClass: MagicMock):
        mock_player_A = MockPlayer("player_A", "test_guild_manual", json.dumps([{"intent": "TEST_INTENT_A", "action_id": "actionA1"}]))
        mock_player_B = MockPlayer("player_B", "test_guild_manual", json.dumps([{"intent": "TEST_INTENT_B", "action_id": "actionB1"}]))
        def get_char_side_effect(guild_id, char_id):
            if guild_id == "test_guild_manual":
                if char_id == "player_A": return mock_player_A
                if char_id == "player_B": return mock_player_B
            return None
        self.mock_character_manager.get_character.side_effect = get_char_side_effect
        conflict_detail_for_db = {
            "conflict_id": "conf_123", "conflict_definition_name": "TEST_MANUAL_CONFLICT",
            "involved_actions": [
                {"character_id": "player_A", "action_id": "actionA1", "action_data": json.loads(mock_player_A.collected_actions_json)[0]},
                {"character_id": "player_B", "action_id": "actionB1", "action_data": json.loads(mock_player_B.collected_actions_json)[0]},
            ], "details_for_gm": "Test conflict for GM", "status": "manual_pending", # MODIFIED: Direct string value
        }
        self.mock_conflict_resolver.analyze_actions_for_conflicts.return_value = {
            "actions_to_execute": [], "pending_conflict_details": [conflict_detail_for_db],
            "auto_resolution_outcomes": [], "requires_manual_resolution": True
        }
        result = asyncio.run(self.tps.process_player_turns(player_ids=["player_A", "player_B"], guild_id="test_guild_manual"))
        self.assertTrue(result["feedback_per_player"]["player_A"][0].startswith("Ваше действие ожидает"))
        self.assertTrue(result["feedback_per_player"]["player_B"][0].startswith("Ваше действие ожидает"))
        self.assertEqual(mock_player_A.current_game_status, "awaiting_gm_resolution")
        self.assertEqual(mock_player_B.current_game_status, "awaiting_gm_resolution")

    async def test_process_player_turns_no_rules_config(self):
        """Tests that processing aborts if rules_config is not available."""
        action_data = {"intent": "MOVE", "entities": [{"type": "direction", "value": "north"}]}
        mock_player, _ = await self._setup_intent_test("p_no_rules", "g_no_rules", action_data)

        self.mock_rule_engine.rules_config_data = None # Simulate rules_config not being loaded

        result = await self.tps.process_player_turns(player_ids=["p_no_rules"], guild_id="g_no_rules")

        self.assertEqual(result["status"], "error_no_rules_config")
        self.assertIn("Критическая ошибка: правила игры не загружены.", result["feedback_per_player"]["p_no_rules"])
        self.assertEqual(mock_player.current_game_status, "ожидание_обработки") # Status should be reverted
        self.mock_character_action_processor.handle_move_action.assert_not_called() # No action processing should occur
        self.mock_db_service.begin_transaction.assert_not_called()


if __name__ == '__main__':
    unittest.main()
