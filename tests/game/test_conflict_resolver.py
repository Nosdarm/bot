import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import uuid
# import json # Unused
from typing import Dict, List, Any, Optional

from bot.game.conflict_resolver import ConflictResolver, ActionWrapper, ActionStatus
from bot.ai.rules_schema import CoreGameRulesConfig, ActionConflictDefinition

class MockCharacter:
    def __init__(self, id: str, name: str, guild_id: str, location_id: str = "loc1", party_id: str = "party1"):
        self.id = id
        self.name = name
        self.guild_id = guild_id
        self.location_id = location_id
        self.party_id = party_id

class TestConflictResolver(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.mock_rule_engine = AsyncMock()
        self.mock_rule_engine.resolve_action_conflict = AsyncMock()

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
            auto_resolution_check_type="pickup_priority_check"
        )
        self.attack_conflict_def_auto = ActionConflictDefinition(
            name="Simultaneous Attack (Auto)",
            type="simultaneous_attack_on_target",
            involved_intent_pattern=["ATTACK"],
            description="Multiple players attacking the same target.",
            resolution_type="auto",
            priority=1,
            auto_resolution_check_type="attack_priority_check"
        )
        self.move_conflict_def_auto = ActionConflictDefinition(
            name="Simultaneous Move to Limited Space",
            type="simultaneous_move_to_limited_slot",
            involved_intent_pattern=["MOVE"],
            description="Two entities attempt to move into the same space that can only occupy one.",
            resolution_type="auto",
            priority=1,
            auto_resolution_check_type="move_priority_check"
        )

        # Simplified CoreGameRulesConfig for tests, ensure all *required* fields are present or have defaults
        # If XPRules is a Pydantic model, it needs to be instantiated or properly mocked.
        # Assuming XPRules might have default values or can be a simple MagicMock for these tests.
        mock_xp_rules = MagicMock() # Or instantiate XPRules if it's simple enough

        self.rules_config = CoreGameRulesConfig(
            checks={}, damage_types={}, xp_rules=mock_xp_rules, loot_tables={},
            action_conflicts=[
                self.pickup_conflict_def_manual,
                self.pickup_conflict_def_auto,
                self.attack_conflict_def_auto,
                self.move_conflict_def_auto,
            ],
            location_interactions={}, base_stats={}, equipment_slots={}, item_effects={}, status_effects={},
            relation_rules=[], relationship_influence_rules=[]
        )

        self.mock_notification_service = AsyncMock()
        self.mock_game_log_manager = AsyncMock()
        self.mock_db_service = AsyncMock()

        self.resolver = ConflictResolver(
            rule_engine=self.mock_rule_engine,
            notification_service=self.mock_notification_service,
            db_service=self.mock_db_service,
            game_log_manager=self.mock_game_log_manager
        )
        self.mock_characters: Dict[str, MockCharacter] = { # Added type hint
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
        action_data: Dict[str, Any] = {"intent": intent, "entities": entities or [], "action_id": act_id} # Added type hint

        # For tests, directly creating a MagicMock that mimics ActionWrapper is often simpler
        # if ActionWrapper itself is complex or has many dependencies.
        # However, if ActionWrapper is a simple Pydantic model or dataclass, instantiating it might be better.
        # Given ActionWrapper is imported, let's assume it can be mocked effectively.
        wrapper = MagicMock(spec=ActionWrapper)
        wrapper.player_id = player_id
        wrapper.action_data = action_data
        wrapper.action_id = act_id
        wrapper.original_intent = intent
        wrapper._status = status # Store status in a private attribute for the property
        wrapper.participated_in_conflict_resolution = False
        wrapper.is_resolved = False
        wrapper.guild_id = "test_guild" # Assuming a default or it's passed in

        # Define status as a property to mimic ActionWrapper's behavior
        def get_status(self_mock) -> ActionStatus: # Added type hint for return
            return self_mock._status
        def set_status(self_mock, value: ActionStatus): # Added type hint for value
            self_mock._status = value

        type(wrapper).status = property(fget=get_status, fset=set_status)


        return wrapper

    async def test_no_conflicts(self):
        """Test that actions with no conflicts are passed through."""
        action1_wrapper = self._create_action_wrapper("player1", "MOVE", entities=[{"type": "location", "id": "loc_A"}])
        action2_wrapper = self._create_action_wrapper("player2", "SEARCH_AREA", entities=[])

        player_actions_map: Dict[str, List[ActionWrapper]] = { # Value is List[ActionWrapper]
            "player1": [action1_wrapper],
            "player2": [action2_wrapper]
        }
        # Simplified CoreGameRulesConfig for this test
        mock_xp_rules = MagicMock()
        test_rules_config = CoreGameRulesConfig(checks={}, damage_types={}, xp_rules=mock_xp_rules, loot_tables={}, action_conflicts=[], location_interactions={}, base_stats={}, equipment_slots={}, item_effects={}, status_effects={}, relation_rules=[], relationship_influence_rules=[])

        # analyze_actions_for_conflicts now expects List[ActionWrapper] not List[Dict]
        result = await self.resolver.analyze_actions_for_conflicts(player_actions_map=player_actions_map, guild_id="guild1", rules_config=test_rules_config)

        self.assertFalse(result["requires_manual_resolution"])
        self.assertEqual(len(result["pending_conflict_details"]), 0)
        self.assertEqual(len(result["auto_resolution_outcomes"]), 0)
        self.assertEqual(len(result["actions_to_execute"]), 2)

        # actions_to_execute contains ActionWrapper instances
        executed_action_wrappers = result["actions_to_execute"]
        self.assertIn(action1_wrapper, executed_action_wrappers)
        self.assertIn(action2_wrapper, executed_action_wrappers)
        self.assertEqual(action1_wrapper.status, ActionStatus.READY_TO_EXECUTE)
        self.assertEqual(action2_wrapper.status, ActionStatus.READY_TO_EXECUTE)


    async def test_contested_item_pickup_manual_resolution(self):
        """Test contested unique item pickup requiring manual resolution."""
        item_id_contested = "unique_sword_1"
        actionA_wrapper = self._create_action_wrapper("playerA", "PICKUP", entities=[{"type": "item", "id": item_id_contested, "name": "Unique Sword"}])
        actionB_wrapper = self._create_action_wrapper("playerB", "PICKUP", entities=[{"type": "item", "id": item_id_contested, "name": "Unique Sword"}])

        player_actions_map: Dict[str, List[ActionWrapper]] = {
            "playerA": [actionA_wrapper],
            "playerB": [actionB_wrapper]
        }
        mock_xp_rules = MagicMock()
        current_rules_config = CoreGameRulesConfig(
            checks={}, damage_types={}, xp_rules=mock_xp_rules, loot_tables={},
            action_conflicts=[self.pickup_conflict_def_manual], # Only manual conflict rule
            location_interactions={}, base_stats={}, equipment_slots={}, item_effects={}, status_effects={},
            relation_rules=[], relationship_influence_rules=[]
        )

        result = await self.resolver.analyze_actions_for_conflicts(player_actions_map=player_actions_map, guild_id="guild_test", rules_config=current_rules_config)

        self.assertTrue(result["requires_manual_resolution"])
        self.assertEqual(len(result["pending_conflict_details"]), 1)
        self.assertEqual(len(result["auto_resolution_outcomes"]), 0)
        self.assertEqual(len(result["actions_to_execute"]), 0)
        self.assertEqual(actionA_wrapper.status, ActionStatus.PENDING_MANUAL_RESOLUTION)
        self.assertEqual(actionB_wrapper.status, ActionStatus.PENDING_MANUAL_RESOLUTION)


    async def test_contested_item_pickup_automatic_resolution_one_winner(self):
        """Test contested item pickup with automatic resolution, one winner."""
        item_id_contested = "unique_gem_1"
        actionC_wrapper = self._create_action_wrapper("playerC", "PICKUP", entities=[{"type": "item", "id": item_id_contested, "name": "Unique Gem"}])
        actionD_wrapper = self._create_action_wrapper("playerD", "PICKUP", entities=[{"type": "item", "id": item_id_contested, "name": "Unique Gem"}])

        player_actions_map: Dict[str, List[ActionWrapper]] = {
            "playerC": [actionC_wrapper],
            "playerD": [actionD_wrapper]
        }
        mock_xp_rules = MagicMock()
        current_rules_config = CoreGameRulesConfig(
            checks={}, damage_types={}, xp_rules=mock_xp_rules, loot_tables={},
            action_conflicts=[self.pickup_conflict_def_auto], # Only auto conflict rule
            location_interactions={}, base_stats={}, equipment_slots={}, item_effects={}, status_effects={},
            relation_rules=[], relationship_influence_rules=[]
        )

        self.mock_rule_engine.resolve_action_conflict.return_value = {
            "winning_action_ids": [actionC_wrapper.action_id],
            "losing_action_ids": [actionD_wrapper.action_id],
            "resolution_details": "Player C had higher priority."
        }

        result = await self.resolver.analyze_actions_for_conflicts(player_actions_map=player_actions_map, guild_id="guild_item_auto", rules_config=current_rules_config)

        self.mock_rule_engine.resolve_action_conflict.assert_called_once()
        self.assertFalse(result["requires_manual_resolution"])
        self.assertEqual(len(result["pending_conflict_details"]), 0)
        self.assertEqual(len(result["auto_resolution_outcomes"]), 1)

        self.assertEqual(len(result["actions_to_execute"]), 1)
        executed_action_wrapper = result["actions_to_execute"][0]
        self.assertEqual(executed_action_wrapper.action_id, actionC_wrapper.action_id)
        self.assertEqual(actionC_wrapper.status, ActionStatus.AUTO_RESOLVED_PROCEED)
        self.assertEqual(actionD_wrapper.status, ActionStatus.AUTO_RESOLVED_FAILED_CONFLICT)

        outcome = result["auto_resolution_outcomes"][0]
        self.assertIn(actionC_wrapper.action_id, outcome["outcome"]["winning_action_ids"])
        self.assertIn(actionD_wrapper.action_id, outcome["outcome"]["losing_action_ids"])


    async def test_simultaneous_attack_auto_resolution_no_winner(self):
        """Test simultaneous attack, auto resolution, no clear winner (e.g., both miss or a tie)."""
        npc_target_id = "goblin_1"
        action_atk1_wrapper = self._create_action_wrapper("playerA", "ATTACK", entities=[{"type": "npc", "id": npc_target_id, "name": "Goblin"}])
        action_atk2_wrapper = self._create_action_wrapper("playerB", "ATTACK", entities=[{"type": "npc", "id": npc_target_id, "name": "Goblin"}])

        player_actions_map: Dict[str, List[ActionWrapper]] = {
            "playerA": [action_atk1_wrapper],
            "playerB": [action_atk2_wrapper]
        }
        mock_xp_rules = MagicMock()
        current_rules_config = CoreGameRulesConfig(
            checks={}, damage_types={}, xp_rules=mock_xp_rules, loot_tables={},
            action_conflicts=[self.attack_conflict_def_auto],
            location_interactions={}, base_stats={}, equipment_slots={}, item_effects={}, status_effects={},
            relation_rules=[], relationship_influence_rules=[]
        )

        self.mock_rule_engine.resolve_action_conflict.return_value = {
            "winning_action_ids": [],
            "losing_action_ids": [action_atk1_wrapper.action_id, action_atk2_wrapper.action_id],
            "resolution_details": "Both attacks failed or tied."
        }

        result = await self.resolver.analyze_actions_for_conflicts(player_actions_map=player_actions_map, guild_id="guild_test", rules_config=current_rules_config)

        self.mock_rule_engine.resolve_action_conflict.assert_called_once()
        self.assertEqual(len(result["actions_to_execute"]), 0)
        self.assertEqual(len(result["auto_resolution_outcomes"]), 1)
        self.assertEqual(len(result["auto_resolution_outcomes"][0]["outcome"]["winning_action_ids"]), 0)
        self.assertIn(action_atk1_wrapper.action_id, result["auto_resolution_outcomes"][0]["outcome"]["losing_action_ids"])
        self.assertIn(action_atk2_wrapper.action_id, result["auto_resolution_outcomes"][0]["outcome"]["losing_action_ids"])
        self.assertEqual(action_atk1_wrapper.status, ActionStatus.AUTO_RESOLVED_FAILED_CONFLICT)
        self.assertEqual(action_atk2_wrapper.status, ActionStatus.AUTO_RESOLVED_FAILED_CONFLICT)


    async def test_action_not_double_conflicted(self):
        """Ensure an action, once part of a resolved/pending conflict, isn't re-evaluated."""
        item_id = "relic_xyz"
        action_pickup_p1_wrapper = self._create_action_wrapper("player1", "PICKUP", entities=[{"type": "item", "id": item_id}])
        action_pickup_p2_wrapper = self._create_action_wrapper("player2", "PICKUP", entities=[{"type": "item", "id": item_id}])

        another_pickup_conflict_def = ActionConflictDefinition(
            name="Generic Pickup Conflict",
            type="generic_pickup_conflict",
            involved_intent_pattern=["PICKUP", "TAKE"],
            description="Any pickup action might conflict.",
            resolution_type="manual",
            priority=0
        )
        mock_xp_rules = MagicMock()
        current_rules_config = CoreGameRulesConfig(
            checks={}, damage_types={}, xp_rules=mock_xp_rules, loot_tables={},
            action_conflicts=[
                self.pickup_conflict_def_manual, # Higher priority
                another_pickup_conflict_def
            ],
            location_interactions={}, base_stats={}, equipment_slots={}, item_effects={}, status_effects={},
            relation_rules=[], relationship_influence_rules=[]
        )

        player_actions_map: Dict[str, List[ActionWrapper]] = {
            action_pickup_p1_wrapper.player_id: [action_pickup_p1_wrapper],
            action_pickup_p2_wrapper.player_id: [action_pickup_p2_wrapper]
        }
        result = await self.resolver.analyze_actions_for_conflicts(player_actions_map=player_actions_map, guild_id="guild1", rules_config=current_rules_config)

        self.assertTrue(result["requires_manual_resolution"])
        self.assertEqual(len(result["pending_conflict_details"]), 1)
        self.assertEqual(result["pending_conflict_details"][0]["conflict_type"], self.pickup_conflict_def_manual.type)
        # Check statuses of original wrappers
        self.assertEqual(action_pickup_p1_wrapper.status, ActionStatus.PENDING_MANUAL_RESOLUTION)
        self.assertEqual(action_pickup_p2_wrapper.status, ActionStatus.PENDING_MANUAL_RESOLUTION)


    async def test_non_conflicting_action_passes_through(self):
        """A non-conflicting action should pass through alongside a conflict."""
        item_id_contested = "map_scroll"
        actionP1_pickup_wrapper = self._create_action_wrapper("playerA", "PICKUP", entities=[{"type": "item", "id": item_id_contested}])
        actionP2_pickup_wrapper = self._create_action_wrapper("playerB", "PICKUP", entities=[{"type": "item", "id": item_id_contested}])
        actionP1_move_wrapper = self._create_action_wrapper("playerA", "MOVE", entities=[{"type": "location", "id": "exit_A"}])

        player_actions_map: Dict[str, List[ActionWrapper]] = {
            actionP1_pickup_wrapper.player_id: [actionP1_pickup_wrapper, actionP1_move_wrapper], # playerA has two actions
            actionP2_pickup_wrapper.player_id: [actionP2_pickup_wrapper]
        }
        mock_xp_rules = MagicMock()
        current_rules_config = CoreGameRulesConfig(
            checks={}, damage_types={}, xp_rules=mock_xp_rules, loot_tables={},
            action_conflicts=[self.pickup_conflict_def_manual],
            location_interactions={}, base_stats={}, equipment_slots={}, item_effects={}, status_effects={},
            relation_rules=[], relationship_influence_rules=[]
        )
        result = await self.resolver.analyze_actions_for_conflicts(player_actions_map=player_actions_map, guild_id="guild_test", rules_config=current_rules_config)

        self.assertTrue(result["requires_manual_resolution"])
        self.assertEqual(len(result["pending_conflict_details"]), 1) # The pickup conflict
        self.assertEqual(len(result["actions_to_execute"]), 1) # The MOVE action

        self.assertIn(actionP1_move_wrapper, result["actions_to_execute"])
        self.assertEqual(actionP1_pickup_wrapper.status, ActionStatus.PENDING_MANUAL_RESOLUTION)
        self.assertEqual(actionP2_pickup_wrapper.status, ActionStatus.PENDING_MANUAL_RESOLUTION)
        self.assertEqual(actionP1_move_wrapper.status, ActionStatus.READY_TO_EXECUTE)

if __name__ == '__main__':
    unittest.main()
