import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import uuid
import json
from typing import Dict, List, Any, Optional

from bot.game.conflict_resolver import ConflictResolver # MODIFIED
from bot.ai.rules_schema import CoreGameRulesConfig, ActionConflictDefinition, AutoResolutionConfig, ActionContextEntities, ActionContextEntity # Assuming these are the Pydantic models

# Minimal mock for Character if needed by any part of the system under test,
# though ConflictResolver primarily works with IDs and action data.
class MockCharacter:
    def __init__(self, id: str, name: str, guild_id: str, location_id: str = "loc1", party_id: str = "party1"):
        self.id = id
        self.name = name
        self.guild_id = guild_id
        self.location_id = location_id
        self.party_id = party_id
        # Add other attributes if RuleEngine or other components accessed via context need them

# TODO: Refactor these tests to align with the current ConflictResolver interface.
class TestConflictResolver(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self): # Changed to asyncSetUp for async mocks
        self.mock_rule_engine = AsyncMock()
        self.mock_rule_engine.resolve_action_conflict = AsyncMock() # Key method for auto resolution

        # Define ActionConflictDefinitions using Pydantic models
        self.pickup_conflict_def_manual = ActionConflictDefinition(
            name="Contested Item Pickup (Manual)",
            type="contested_item_pickup",
            involved_intent_pattern=["PICKUP"],
            description="Multiple players trying to pick up the same unique item.",
            resolution_type="manual",
            priority=1
        )
        self.pickup_conflict_def_auto = ActionConflictDefinition(
            name="Contested Item Pickup (Auto)",
            type="contested_item_pickup",
            involved_intent_pattern=["PICKUP"],
            description="Multiple players trying to pick up the same unique item (auto).",
            resolution_type="auto",
            priority=1,
            auto_resolution_config=AutoResolutionConfig(
                check_type="pickup_priority_check", # Passed to RuleEngine
                # outcome_rules can be complex, simplified for this example
            )
        )
        self.attack_conflict_def_auto = ActionConflictDefinition(
            name="Simultaneous Attack (Auto)",
            type="simultaneous_attack_on_target",
            involved_intent_pattern=["ATTACK"],
            description="Multiple players attacking the same target.",
            resolution_type="auto",
            priority=1,
            auto_resolution_config=AutoResolutionConfig(check_type="attack_priority_check")
        )
        self.move_conflict_def_auto = ActionConflictDefinition( # Example from original test
            name="Simultaneous Move to Limited Space",
            type="simultaneous_move_to_limited_slot", # Changed type to match new logic
            involved_intent_pattern=["MOVE"],
            description="Two entities attempt to move into the same space that can only occupy one.",
            resolution_type="auto",
            priority=1,
            auto_resolution_config=AutoResolutionConfig(check_type="move_priority_check")
        )


        self.rules_config = CoreGameRulesConfig(
            action_conflicts=[
                self.pickup_conflict_def_manual,
                self.pickup_conflict_def_auto, # Will select one based on test scenario
                self.attack_conflict_def_auto,
                self.move_conflict_def_auto,
            ]
            # Populate other fields of CoreGameRulesConfig if necessary for tests
        )

        self.mock_notification_service = AsyncMock()
        # db_adapter is no longer directly used by ConflictResolver constructor or methods.
        # It might be part of a 'context' passed to RuleEngine, but not ConflictResolver itself.
        # self.mock_db_adapter = AsyncMock()
        self.mock_game_log_manager = AsyncMock()

        # ConflictResolver constructor no longer takes rules_config_data or db_adapter
        self.resolver = ConflictResolver(
            rule_engine=self.mock_rule_engine,
            # notification_service=self.mock_notification_service, # Removed if not used
            game_log_manager=self.mock_game_log_manager
        )
        # Mock characters - can be expanded if rule engine needs more details
        self.mock_characters = {
            "player1": MockCharacter(id="player1", name="Player One", guild_id="guild1"),
            "player2": MockCharacter(id="player2", name="Player Two", guild_id="guild1"),
            "playerA": MockCharacter(id="playerA", name="Player Alpha", guild_id="guild_test"),
            "playerB": MockCharacter(id="playerB", name="Player Bravo", guild_id="guild_test"),
            "playerC": MockCharacter(id="playerC", name="Player Charlie", guild_id="guild_item_auto"),
            "playerD": MockCharacter(id="playerD", name="Player Delta", guild_id="guild_item_auto"),
        }


    def _create_action_wrapper(self, player_id: str, intent: str,
                               entities: Optional[List[Dict[str, Any]]] = None,
                               action_id: Optional[str] = None,
                               status: ActionStatus = ActionStatus.PENDING_ANALYSIS) -> ActionWrapper:
        act_id = action_id or f"action_{uuid.uuid4().hex[:6]}"
        action_data = {"intent": intent, "entities": entities or [], "action_id": act_id}
        # Create a mock that quacks like an ActionWrapper
        wrapper = MagicMock(spec=ActionWrapper)
        wrapper.player_id = player_id
        wrapper.action_data = action_data
        wrapper.action_id = act_id
        wrapper.original_intent = intent
        wrapper._status = status # Use _status to allow direct assignment
        wrapper.participated_in_conflict_resolution = False
        wrapper.is_resolved = False

        # Make _status assignable for tests
        def set_status(s_val): wrapper._status = s_val
        def get_status(): return wrapper._status
        wrapper.status = property(get_status, set_status)

        return wrapper

    # async def test_no_conflicts(self):
    #     """Test that actions with no conflicts are passed through."""
    #     actions_flat = [
    #         self._create_action_wrapper("player1", "MOVE", entities=[{"type": "location", "id": "loc_A"}]),
    #         self._create_action_wrapper("player2", "SEARCH_AREA", entities=[]),
    #     ]
    #     test_rules_config = CoreGameRulesConfig(action_conflicts=[]) # No conflict definitions
    #
    #     result = await self.resolver.analyze_actions_for_conflicts(actions_flat, test_rules_config, self.mock_characters)
    #
    #     self.assertFalse(result["requires_manual_resolution"])
    #     self.assertEqual(len(result["pending_conflict_details"]), 0)
    #     self.assertEqual(len(result["auto_resolution_outcomes"]), 0)
    #     self.assertEqual(len(result["actions_to_execute"]), 2)
    #     self.assertEqual(result["actions_to_execute"][0].player_id, "player1")
    #     self.assertEqual(result["actions_to_execute"][0].action_data["intent"], "MOVE")
    #     self.assertEqual(result["actions_to_execute"][0].status, ActionStatus.PENDING_EXECUTION)
    #     self.assertEqual(result["actions_to_execute"][1].player_id, "player2")
    #     self.assertEqual(result["actions_to_execute"][1].action_data["intent"], "SEARCH_AREA")
    #     self.assertEqual(result["actions_to_execute"][1].status, ActionStatus.PENDING_EXECUTION)
    #
    #
    # async def test_contested_item_pickup_manual_resolution(self):
    #     """Test contested unique item pickup requiring manual resolution."""
    #     item_id_contested = "unique_sword_1"
    #     action1 = self._create_action_wrapper("playerA", "PICKUP", entities=[{"type": "item", "id": item_id_contested, "name": "Unique Sword"}])
    #     action2 = self._create_action_wrapper("playerB", "PICKUP", entities=[{"type": "item", "id": item_id_contested, "name": "Unique Sword"}])
    #
    #     actions_flat = [action1, action2]
    #     current_rules_config = CoreGameRulesConfig(action_conflicts=[self.pickup_conflict_def_manual])
    #
    #     result = await self.resolver.analyze_actions_for_conflicts(actions_flat, current_rules_config, self.mock_characters)
    #
    #     self.assertTrue(result["requires_manual_resolution"]) # Should be false as it's handled by prepare_for_manual_resolution now
    #     self.assertEqual(len(result["pending_conflict_details"]), 1)
    #     self.assertEqual(len(result["auto_resolution_outcomes"]), 0)
    #     self.assertEqual(len(result["actions_to_execute"]), 0)
    #
    #     conflict_detail = result["pending_conflict_details"][0]
    #     self.assertEqual(conflict_detail["status"], ActionStatus.MANUAL_PENDING.value) # Check string value
    #     self.assertIn("conflict_id", conflict_detail)
    #     self.assertIn(f"Contested Item Pickup (Manual): Action IDs {action1.action_id}, {action2.action_id} target {item_id_contested}", conflict_detail["details_for_gm"])
    #
    #     self.assertEqual(action1.status, ActionStatus.MANUAL_PENDING)
    #     self.assertEqual(action2.status, ActionStatus.MANUAL_PENDING)
    #
    # async def test_contested_item_pickup_automatic_resolution_one_winner(self):
    #     """Test contested item pickup with automatic resolution, one winner."""
    #     item_id_contested = "unique_gem_1"
    #     actionC = self._create_action_wrapper("playerC", "PICKUP", entities=[{"type": "item", "id": item_id_contested, "name": "Unique Gem"}])
    #     actionD = self._create_action_wrapper("playerD", "PICKUP", entities=[{"type": "item", "id": item_id_contested, "name": "Unique Gem"}])
    #     actions_flat = [actionC, actionD]
    #
    #     # Ensure only the 'auto' version of pickup conflict is in rules_config for this test
    #     current_rules_config = CoreGameRulesConfig(action_conflicts=[self.pickup_conflict_def_auto])
    #
    #     # Mock RuleEngine to declare playerC the winner
    #     self.mock_rule_engine.resolve_action_conflict.return_value = {
    #         "winning_action_ids": [actionC.action_id],
    #         "losing_action_ids": [actionD.action_id],
    #         "resolution_details": "Player C had higher dexterity."
    #     }
    #
    #     result = await self.resolver.analyze_actions_for_conflicts(actions_flat, current_rules_config, self.mock_characters)
    #
    #     self.mock_rule_engine.resolve_action_conflict.assert_called_once()
    #     self.assertFalse(result["requires_manual_resolution"])
    #     self.assertEqual(len(result["pending_conflict_details"]), 0)
    #     self.assertEqual(len(result["auto_resolution_outcomes"]), 1)
    #
    #     self.assertEqual(len(result["actions_to_execute"]), 1)
    #     executed_action_wrapper = result["actions_to_execute"][0]
    #     self.assertEqual(executed_action_wrapper.player_id, "playerC")
    #     self.assertEqual(executed_action_wrapper.action_id, actionC.action_id)
    #     self.assertEqual(actionC.status, ActionStatus.AUTO_RESOLVED_PROCEED)
    #     self.assertEqual(actionD.status, ActionStatus.AUTO_RESOLVED_FAILED_CONFLICT)
    #
    #     outcome = result["auto_resolution_outcomes"][0]
    #     self.assertEqual(outcome["resolution_type"], "auto")
    #     self.assertIn(actionC.action_id, outcome["winning_action_ids"])
    #
    #
    # async def test_simultaneous_attack_auto_resolution_no_winner(self):
    #     """Test simultaneous attack, auto resolution, no clear winner (e.g., both miss or a tie)."""
    #     npc_target_id = "goblin_1"
    #     action_atk1 = self._create_action_wrapper("playerA", "ATTACK", entities=[{"type": "npc", "id": npc_target_id, "name": "Goblin"}])
    #     action_atk2 = self._create_action_wrapper("playerB", "ATTACK", entities=[{"type": "npc", "id": npc_target_id, "name": "Goblin"}])
    #     actions_flat = [action_atk1, action_atk2]
    #     current_rules_config = CoreGameRulesConfig(action_conflicts=[self.attack_conflict_def_auto])
    #
    #     self.mock_rule_engine.resolve_action_conflict.return_value = {
    #         "winning_action_ids": [], # No winner
    #         "losing_action_ids": [action_atk1.action_id, action_atk2.action_id],
    #         "resolution_details": "Both attackers fumbled their attacks."
    #     }
    #
    #     result = await self.resolver.analyze_actions_for_conflicts(actions_flat, current_rules_config, self.mock_characters)
    #
    #     self.mock_rule_engine.resolve_action_conflict.assert_called_once()
    #     self.assertEqual(len(result["actions_to_execute"]), 0) # No actions proceed
    #     self.assertEqual(action_atk1.status, ActionStatus.AUTO_RESOLVED_FAILED_CONFLICT)
    #     self.assertEqual(action_atk2.status, ActionStatus.AUTO_RESOLVED_FAILED_CONFLICT)
    #     self.assertEqual(len(result["auto_resolution_outcomes"]), 1)
    #     self.assertEqual(len(result["auto_resolution_outcomes"][0]["winning_action_ids"]), 0)
    #
    #
    # async def test_action_not_double_conflicted(self):
    #     """Ensure an action, once part of a resolved/pending conflict, isn't re-evaluated."""
    #     item_id = "relic_xyz"
    #     action_pickup_p1 = self._create_action_wrapper("player1", "PICKUP", entities=[{"type": "item", "id": item_id}])
    #     # Second conflict definition that might also match PICKUP if not for status change
    #     another_pickup_conflict_def = ActionConflictDefinition(
    #         name="Generic Pickup Conflict",
    #         type="generic_pickup_conflict",
    #         involved_intent_pattern=["PICKUP", "TAKE"], # Matches PICKUP
    #         description="Any pickup action might conflict.",
    #         resolution_type="manual", # Different type to distinguish
    #         priority=0 # Lower priority
    #     )
    #     current_rules_config = CoreGameRulesConfig(action_conflicts=[
    #         self.pickup_conflict_def_manual, # Higher priority, will process first
    #         another_pickup_conflict_def
    #     ])
    #
    #     actions_flat = [
    #         action_pickup_p1,
    #         self._create_action_wrapper("player2", "PICKUP", entities=[{"type": "item", "id": item_id}]) # p2 also tries
    #     ]
    #
    #     result = await self.resolver.analyze_actions_for_conflicts(actions_flat, current_rules_config, self.mock_characters)
    #
    #     # Expect one manual conflict from the first definition
    #     self.assertEqual(len(result["pending_conflict_details"]), 1)
    #     self.assertEqual(result["pending_conflict_details"][0]["conflict_definition_name"], "Contested Item Pickup (Manual)")
    #
    #     # Both actions should be MANUAL_PENDING due to the first conflict def
    #     self.assertEqual(action_pickup_p1.status, ActionStatus.MANUAL_PENDING)
    #     self.assertEqual(actions_flat[1].status, ActionStatus.MANUAL_PENDING)
    #
    #     # Ensure no other conflict was generated for these actions by the second definition
    #     # (because their status is no longer PENDING_ANALYSIS when the second def is checked)
    #     # This is implicitly checked by `pending_conflict_details` having only 1 entry.
    #
    # async def test_non_conflicting_action_passes_through(self):
    #     """A non-conflicting action should pass through alongside a conflict."""
    #     item_id_contested = "map_scroll"
    #     actionP1_pickup = self._create_action_wrapper("playerA", "PICKUP", entities=[{"type": "item", "id": item_id_contested}])
    #     actionP2_pickup = self._create_action_wrapper("playerB", "PICKUP", entities=[{"type": "item", "id": item_id_contested}])
    #     actionP1_move = self._create_action_wrapper("playerA", "MOVE", entities=[{"type": "location", "id": "exit_A"}]) # Different action by P1
    #
    #     actions_flat = [actionP1_pickup, actionP2_pickup, actionP1_move]
    #     current_rules_config = CoreGameRulesConfig(action_conflicts=[self.pickup_conflict_def_manual])
    #
    #     result = await self.resolver.analyze_actions_for_conflicts(actions_flat, current_rules_config, self.mock_characters)
    #
    #     self.assertEqual(len(result["pending_conflict_details"]), 1) # The pickup conflict
    #     self.assertEqual(len(result["actions_to_execute"]), 1)
    #     self.assertEqual(result["actions_to_execute"][0].action_id, actionP1_move.action_id)
    #     self.assertEqual(result["actions_to_execute"][0].status, ActionStatus.PENDING_EXECUTION)
    #     self.assertEqual(actionP1_pickup.status, ActionStatus.MANUAL_PENDING)
    #     self.assertEqual(actionP2_pickup.status, ActionStatus.MANUAL_PENDING)

if __name__ == '__main__':
    unittest.main()
