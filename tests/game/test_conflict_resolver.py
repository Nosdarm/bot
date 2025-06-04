import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import uuid
import json

from bot.game.conflict_resolver import ConflictResolver
# Assuming models might be needed for constructing action context entities if not fully mocked
# from bot.game.models.character import Character
# from bot.game.models.item import Item

class TestConflictResolver(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.mock_rule_engine = AsyncMock() # RuleEngine methods are async
        self.mock_rules_config_data = {
            "conflict_definitions": {
                "simultaneous_move_to_limited_space": { # Existing example, make it auto for testing
                    "type": "automatic",
                    "description": "Two entities attempt to move into the same space that can only occupy one.",
                    "resolution_check_type": "move_priority_check", # Mocked check
                    "automatic_resolution": { # Ensure this structure is present if type is auto
                        "check_type": "move_priority_check", # Passed to RuleEngine
                        "outcome_rules": {"higher_wins": True, "tie_breaker_rule": "random"}
                    }
                },
                "contested_item_pickup": {
                    "type": "manual", # Test manual path first
                    "description": "Multiple players are trying to pick up the same unique item.",
                    "resolution_check_type": "pickup_contest_roll",
                    "notification_format": {
                        "message": "Conflict: {entity_ids_str} dispute item {item_id}."
                    }
                },
                "contested_item_pickup_auto": { # For testing auto resolution of this type
                    "type": "automatic",
                    "description": "Multiple players are trying to pick up the same unique item (auto).",
                    "resolution_check_type": "pickup_priority_check",
                     "automatic_resolution": {
                        "check_type": "pickup_priority_check",
                        "outcome_rules": {"higher_wins": True}
                    }
                },
                "opposed_stealth_vs_perception": {
                    "type": "automatic",
                    "description": "Player attempting stealth opposed by another's perception/search.",
                    "resolution_check_type": "stealth_vs_perception_roll",
                    "automatic_resolution": {
                        "check_type": "stealth_vs_perception_roll", # This is the check type for RuleEngine
                         "actor_check_details": {"skill_or_stat_to_use": "stealth_skill_value"}, # Example
                         "target_check_details": {"skill_or_stat_to_use": "perception_skill_value"}, # Example
                        "outcome_rules": {
                            "higher_wins": True, # Actor wins if their roll > target's roll
                            "tie_breaker_rule": "stealth_wins_on_tie", # Example tie-breaker
                             "outcomes": { # Detailed outcomes (optional, depends on RuleEngine output)
                                "actor_wins": {"description": "Stealth successful."},
                                "target_wins": {"description": "Stealth failed, detected."}
                            }
                        }
                    }
                }
            }
        }
        self.mock_notification_service = AsyncMock()
        self.mock_db_adapter = AsyncMock()
        self.mock_db_adapter.save_pending_conflict = AsyncMock()
        self.mock_db_adapter.get_pending_conflict = AsyncMock() # For process_master_resolution, not directly tested here
        self.mock_db_adapter.delete_pending_conflict = AsyncMock() # For process_master_resolution

        self.mock_game_log_manager = AsyncMock()

        self.resolver = ConflictResolver(
            rule_engine=self.mock_rule_engine,
            rules_config_data=self.mock_rules_config_data,
            notification_service=self.mock_notification_service,
            db_adapter=self.mock_db_adapter,
            game_log_manager=self.mock_game_log_manager
        )

        # Mock RuleEngine's resolve_check behavior for automatic resolution
        # This can be customized per test.
        self.mock_rule_engine.resolve_check = AsyncMock(return_value={"outcome": "SUCCESS", "total_roll_value": 15})
        # Mock get_game_time if resolve_conflict_automatically uses it
        self.mock_rule_engine.get_game_time = AsyncMock(return_value=12345.0)


    def _create_action_context(self, player_id: str, action_data: Dict,
                               location_id: str = "loc1", party_id: str = "party1",
                               action_id: Optional[str] = None) -> Dict:
        # Ensure action_data has an action_id, generate if not provided
        if 'action_id' not in action_data:
            action_data['action_id'] = f"action_{uuid.uuid4().hex[:8]}"

        # The structure of action_ctx should match what analyze_actions_for_conflicts expects
        # all_submitted_actions_with_context.append({
        #             "character_id": player_id,
        #             "action_data": action_data
        # ... and it seems ConflictResolver adds location_id/party_id from context if available
        # For tests, it's easier to ensure they are part of the action_ctx if the conflict logic uses them.
        # The ConflictResolver implementation itself doesn't seem to add location/party to action_ctx,
        # it expects them to be there if needed (e.g. for stealth conflict).
        # So, let's include them in the action_ctx for clarity in tests.
        return {
            "character_id": player_id,
            "action_data": action_data, # This is the NLU output like dict
            "location_id": location_id, # Assuming this context is added by PartyActionProcessor or similar
            "party_id": party_id,       # Assuming this context is added
            # Potentially other context like character object, but not strictly needed for conflict detection if IDs are primary
        }

    async def test_no_conflicts(self):
        """Test that actions with no conflicts are passed through."""
        actions_map = {
            "player1": [self._create_action_context("player1", {"intent_type": "move", "target_id": "loc_A"})['action_data']],
            "player2": [self._create_action_context("player2", {"intent_type": "search"})['action_data']],
        }
        # The resolver expects a list of action_data dicts per player

        result = await self.resolver.analyze_actions_for_conflicts(actions_map, "guild1")

        self.assertFalse(result["requires_manual_resolution"])
        self.assertEqual(len(result["pending_conflict_details"]), 0)
        self.assertEqual(len(result["auto_resolution_outcomes"]), 0)
        self.assertEqual(len(result["actions_to_execute"]), 2)
        # Ensure original action contexts are preserved
        self.assertEqual(result["actions_to_execute"][0]["character_id"], "player1")
        self.assertEqual(result["actions_to_execute"][0]["action_data"]["intent_type"], "move")
        self.assertEqual(result["actions_to_execute"][1]["character_id"], "player2")
        self.assertEqual(result["actions_to_execute"][1]["action_data"]["intent_type"], "search")

    async def test_contested_unique_item_pickup_manual_resolution(self):
        """Test contested unique item pickup requiring manual resolution."""
        item_id_contested = "unique_sword_1"
        action1_data = {"intent_type": "pickup", "action_id": "act1", "entities": [{"id": item_id_contested, "type": "item", "is_unique": True}]}
        action2_data = {"intent_type": "pickup", "action_id": "act2", "entities": [{"id": item_id_contested, "type": "item", "is_unique": True}]}

        actions_map = {
            "playerA": [action1_data],
            "playerB": [action2_data],
        }
        # Override rules_config for this test if needed, but setUp has it as manual
        self.resolver.rules_config["conflict_definitions"]["contested_item_pickup"]["type"] = "manual"


        result = await self.resolver.analyze_actions_for_conflicts(actions_map, "guild_item_test")

        self.assertTrue(result["requires_manual_resolution"])
        self.assertEqual(len(result["pending_conflict_details"]), 1)
        self.assertEqual(len(result["auto_resolution_outcomes"]), 0)
        self.assertEqual(len(result["actions_to_execute"]), 0) # Actions go to manual resolution

        conflict_detail = result["pending_conflict_details"][0]
        # This detail is from prepare_for_manual_resolution, check its structure
        self.assertEqual(conflict_detail["status"], "awaiting_manual_resolution")
        self.assertIn("conflict_id", conflict_detail)
        self.assertIn(f"dispute item {item_id_contested}", conflict_detail["details_for_master"])

        self.mock_db_adapter.save_pending_conflict.assert_called_once()
        call_args = self.mock_db_adapter.save_pending_conflict.call_args[0]
        self.assertEqual(call_args[0], conflict_detail["conflict_id"]) # conflict_id
        self.assertEqual(call_args[1], "guild_item_test") # guild_id
        saved_conflict_data = json.loads(call_args[2]) # conflict_data (JSON string)
        self.assertEqual(saved_conflict_data["type"], "contested_item_pickup")
        self.assertEqual(saved_conflict_data["details"]["item_id"], item_id_contested)
        self.assertEqual(len(saved_conflict_data["involved_actions"]), 2)


    async def test_contested_unique_item_pickup_automatic_resolution(self):
        """Test contested unique item pickup with automatic resolution."""
        item_id_contested = "unique_gem_1"
        # Ensure actions have unique IDs
        action1_ctx = self._create_action_context("playerC", {"intent_type": "pickup", "entities": [{"id": item_id_contested, "type": "item", "is_unique": True}]})
        action2_ctx = self._create_action_context("playerD", {"intent_type": "pickup", "entities": [{"id": item_id_contested, "type": "item", "is_unique": True}]})

        actions_map = {
            "playerC": [action1_ctx['action_data']],
            "playerD": [action2_ctx['action_data']],
        }
        # Use the _auto version of the rule
        self.resolver.rules_config["conflict_definitions"]["contested_item_pickup"] = self.resolver.rules_config["conflict_definitions"]["contested_item_pickup_auto"]

        # Mock RuleEngine to declare playerC the winner
        # resolve_conflict_automatically will call rule_engine.resolve_check
        # The outcome from resolve_check is less important than the final outcome structure from resolve_conflict_automatically
        async def mock_resolve_auto_outcome(conflict_details, context):
            # This mock simulates the behavior of self.resolver.resolve_conflict_automatically
            # including how it might determine a winner and structure its return.
            winner_id = conflict_details["involved_entities"][0]["id"] # Assume first entity (playerC) wins
            winning_action = conflict_details["involved_actions"][0] # playerC's action

            return {
                "conflict_id": conflict_details["conflict_id"],
                "status": "resolved_automatically",
                "outcome": {
                    "winner_id": winner_id,
                    "winning_action_id": winning_action['action_data']['action_id'], # Important for resolver
                    "description": f"{winner_id} wins the {item_id_contested}.",
                    "effects": []
                }
            }

        with patch.object(self.resolver, 'resolve_conflict_automatically', side_effect=mock_resolve_auto_outcome) as mock_auto_resolve:
            result = await self.resolver.analyze_actions_for_conflicts(actions_map, "guild_item_auto")

            mock_auto_resolve.assert_called_once()
            self.assertFalse(result["requires_manual_resolution"])
            self.assertEqual(len(result["pending_conflict_details"]), 0)
            self.assertEqual(len(result["auto_resolution_outcomes"]), 1)

            # Check that only the winner's action is in actions_to_execute
            self.assertEqual(len(result["actions_to_execute"]), 1)
            executed_action_ctx = result["actions_to_execute"][0]
            self.assertEqual(executed_action_ctx["character_id"], "playerC")
            self.assertEqual(executed_action_ctx["action_data"]["action_id"], action1_ctx['action_data']['action_id'])

            outcome = result["auto_resolution_outcomes"][0]
            self.assertEqual(outcome["status"], "resolved_automatically")
            self.assertEqual(outcome["outcome"]["winner_id"], "playerC")


    async def test_opposed_stealth_vs_search_automatic_resolution(self):
        """Test opposed stealth vs. search with automatic resolution."""
        stealth_action_ctx = self._create_action_context(
            "playerStealthy",
            {"intent_type": "stealth", "skill_id": "stealth"}, # Can be intent or skill_usage
            location_id="dungeon_hall", party_id="partyA"
        )
        search_action_ctx = self._create_action_context(
            "playerSearcher",
            {"intent_type": "search"}, # Could also be skill_id: perception
            location_id="dungeon_hall", party_id="partyA" # Same location
        )
        non_involved_action_ctx = self._create_action_context(
            "playerElse",
            {"intent_type": "move", "target_id": "exit"},
            location_id="dungeon_hall", party_id="partyA"
        )

        actions_map = {
            "playerStealthy": [stealth_action_ctx['action_data']],
            "playerSearcher": [search_action_ctx['action_data']],
            "playerElse": [non_involved_action_ctx['action_data']],
        }

        # Mock RuleEngine or resolve_conflict_automatically to determine outcome
        # Let's say stealth wins
        async def mock_resolve_stealth_outcome(conflict_details, context):
            stealth_action = next(a for a in conflict_details["involved_actions"] if a["character_id"] == "playerStealthy")
            return {
                "conflict_id": conflict_details["conflict_id"],
                "status": "resolved_automatically",
                "outcome": {
                    "winner_id": "playerStealthy", # Stealth player wins
                     # RuleEngine should ideally return list of action_ids that proceed
                    "winning_action_ids": [stealth_action['action_data']['action_id']],
                    "description": "Stealth successful!",
                }
            }

        with patch.object(self.resolver, 'resolve_conflict_automatically', side_effect=mock_resolve_stealth_outcome) as mock_auto_resolve:
            result = await self.resolver.analyze_actions_for_conflicts(actions_map, "guild_stealth")

            mock_auto_resolve.assert_called_once() # One conflict (stealth vs search)
            self.assertFalse(result["requires_manual_resolution"])
            self.assertEqual(len(result["pending_conflict_details"]), 0)
            self.assertEqual(len(result["auto_resolution_outcomes"]), 1)

            # Expected: stealth action + non_involved_action
            self.assertEqual(len(result["actions_to_execute"]), 2)

            action_ids_to_execute = {a['action_data']['action_id'] for a in result["actions_to_execute"]}
            self.assertIn(stealth_action_ctx['action_data']['action_id'], action_ids_to_execute)
            self.assertIn(non_involved_action_ctx['action_data']['action_id'], action_ids_to_execute)
            self.assertNotIn(search_action_ctx['action_data']['action_id'], action_ids_to_execute) # Searcher's action doesn't proceed if stealth won

    async def test_mixed_conflicting_and_non_conflicting_actions(self):
        """Test a mix of actions, some conflicting, some not."""
        # Conflict: playerA and playerB pickup same unique item
        item_id_contested = "idol_of_yendor"
        pickup_a_data = {"intent_type": "pickup", "action_id": "act_pick_a", "entities": [{"id": item_id_contested, "type": "item", "is_unique": True}]}
        pickup_b_data = {"intent_type": "pickup", "action_id": "act_pick_b", "entities": [{"id": item_id_contested, "type": "item", "is_unique": True}]}

        # Non-conflicting action
        move_c_data = {"intent_type": "move", "action_id": "act_move_c", "target_id": "market"}

        actions_map = {
            "playerA": [pickup_a_data],
            "playerB": [pickup_b_data],
            "playerC": [move_c_data],
        }
        self.resolver.rules_config["conflict_definitions"]["contested_item_pickup"]["type"] = "manual" # Set to manual

        result = await self.resolver.analyze_actions_for_conflicts(actions_map, "guild_mixed")

        self.assertTrue(result["requires_manual_resolution"])
        self.assertEqual(len(result["pending_conflict_details"]), 1) # The pickup conflict
        self.assertEqual(len(result["auto_resolution_outcomes"]), 0)

        # Only playerC's move action should be directly executable
        self.assertEqual(len(result["actions_to_execute"]), 1)
        self.assertEqual(result["actions_to_execute"][0]["character_id"], "playerC")
        self.assertEqual(result["actions_to_execute"][0]["action_data"]["action_id"], "act_move_c")

        # Verify the manual conflict details
        manual_conflict = result["pending_conflict_details"][0]
        self.assertIn(item_id_contested, manual_conflict["details_for_master"])


if __name__ == '__main__':
    unittest.main()
