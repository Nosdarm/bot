import unittest
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
import uuid
from typing import Dict, List, Any, Optional, Callable


from bot.game.conflict_resolver import ConflictResolver # ActionWrapper, ActionStatus are not exported
from bot.ai.rules_schema import CoreGameRulesConfig, ActionConflictDefinition, XPRule # Assuming XPRules is a simple model or mockable

# Mocking ActionStatus Enum as it's not directly importable or its definition is unclear
class MockActionStatus:
    PENDING_ANALYSIS = "pending_analysis"
    PENDING_MANUAL_RESOLUTION = "pending_manual_resolution"
    AUTO_RESOLVED_PROCEED = "auto_resolved_proceed"
    AUTO_RESOLVED_FAILED_CONFLICT = "auto_resolved_failed_conflict"
    READY_TO_EXECUTE = "ready_to_execute"
    RESOLVED_PROCEED = "resolved_proceed"
    RESOLVED_FAILED_CONFLICT = "resolved_failed_conflict"


class MockCharacter:
    def __init__(self, id: str, name: str, guild_id: str, location_id: str = "loc1", party_id: Optional[str] = "party1"):
        self.id = id
        self.name = name
        self.guild_id = guild_id
        self.location_id = location_id
        self.party_id = party_id

# Define a mock ActionWrapper class for type hinting and spec if ActionWrapper is not available
# Or, if ActionWrapper is a Pydantic model from elsewhere, import it.
# For now, we'll rely on MagicMock(spec=...) if ActionWrapper cannot be imported.
# If it's a simple structure, we can define a mock class.
class MockActionWrapper:
    def __init__(self, player_id: str, action_data: Dict[str, Any], action_id: str, original_intent: str, status: str, guild_id: str):
        self.player_id = player_id
        self.action_data = action_data
        self.action_id = action_id
        self.original_intent = original_intent
        self._status = status
        self.guild_id = guild_id
        self.participated_in_conflict_resolution = False
        self.is_resolved = False

    @property
    def status(self) -> str:
        return self._status

    @status.setter
    def status(self, value: str):
        self._status = value


class TestConflictResolver(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.mock_rule_engine = AsyncMock()
        self.mock_rule_engine.resolve_action_conflict = AsyncMock()

        # Corrected ActionConflictDefinition instantiation
        self.pickup_conflict_def_manual = ActionConflictDefinition(
            type="contested_item_pickup_manual", # Use 'type' instead of 'name'
            involved_intent_pattern=["PICKUP"],
            description="Multiple players trying to pick up the same unique item.",
            resolution_type="manual",
            # priority removed
            manual_resolution_options=["option1", "option2"] # Example options
        )
        self.pickup_conflict_def_auto = ActionConflictDefinition(
            type="contested_item_pickup_auto",
            involved_intent_pattern=["PICKUP"],
            description="Multiple players trying to pick up the same unique item (auto).",
            resolution_type="auto",
            # priority removed
            auto_resolution_check_type="pickup_priority_check"
        )
        self.attack_conflict_def_auto = ActionConflictDefinition(
            type="simultaneous_attack_on_target_auto",
            involved_intent_pattern=["ATTACK"],
            description="Multiple players attacking the same target.",
            resolution_type="auto",
            # priority removed
            auto_resolution_check_type="attack_priority_check"
        )
        self.move_conflict_def_auto = ActionConflictDefinition(
            type="simultaneous_move_to_limited_slot_auto",
            involved_intent_pattern=["MOVE"],
            description="Two entities attempt to move into the same space that can only occupy one.",
            resolution_type="auto",
            # priority removed
            auto_resolution_check_type="move_priority_check"
        )

        mock_xp_rules = MagicMock(spec=XPRule)
        if not isinstance(mock_xp_rules, XPRule) and XPRule is not MagicMock: # Ensure it's a valid XPRule or mock
            mock_xp_rules = XPRule(level_difference_modifier={}, base_xp_per_challenge={})


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
        self.mock_characters: Dict[str, MockCharacter] = {
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
                               status: str = MockActionStatus.PENDING_ANALYSIS, # Use MockActionStatus
                               guild_id: str = "test_guild") -> MockActionWrapper: # Return MockActionWrapper
        act_id = action_id or f"action_{uuid.uuid4().hex[:6]}"
        action_data: Dict[str, Any] = {"intent": intent, "entities": entities or [], "action_id": act_id}

        # Using the locally defined MockActionWrapper
        wrapper = MockActionWrapper(
            player_id=player_id,
            action_data=action_data,
            action_id=act_id,
            original_intent=intent,
            status=status,
            guild_id=guild_id
        )
        return wrapper

    async def test_no_conflicts(self):
        action1_wrapper = self._create_action_wrapper("player1", "MOVE", entities=[{"type": "location", "id": "loc_A"}])
        action2_wrapper = self._create_action_wrapper("player2", "SEARCH_AREA", entities=[])

        player_actions_map: Dict[str, List[MockActionWrapper]] = {
            "player1": [action1_wrapper],
            "player2": [action2_wrapper]
        }
        mock_xp_rules = MagicMock(spec=XPRule)
        if not isinstance(mock_xp_rules, XPRule) and XPRule is not MagicMock:
            mock_xp_rules = XPRule(level_difference_modifier={}, base_xp_per_challenge={})

        test_rules_config = CoreGameRulesConfig(checks={}, damage_types={}, xp_rules=mock_xp_rules, loot_tables={}, action_conflicts=[], location_interactions={}, base_stats={}, equipment_slots={}, item_effects={}, status_effects={}, relation_rules=[], relationship_influence_rules=[])

        result = await self.resolver.analyze_actions_for_conflicts(player_actions_map=player_actions_map, guild_id="guild1", rules_config=test_rules_config)

        self.assertFalse(result["requires_manual_resolution"])
        self.assertEqual(len(result["pending_conflict_details"]), 0)
        self.assertEqual(len(result["auto_resolution_outcomes"]), 0)
        self.assertEqual(len(result["actions_to_execute"]), 2)
        executed_action_wrappers = result["actions_to_execute"]
        self.assertIn(action1_wrapper, executed_action_wrappers)
        self.assertIn(action2_wrapper, executed_action_wrappers)
        self.assertEqual(action1_wrapper.status, MockActionStatus.READY_TO_EXECUTE)
        self.assertEqual(action2_wrapper.status, MockActionStatus.READY_TO_EXECUTE)

    async def test_contested_item_pickup_manual_resolution(self):
        item_id_contested = "unique_sword_1"
        actionA_wrapper = self._create_action_wrapper("playerA", "PICKUP", entities=[{"type": "item", "id": item_id_contested, "name": "Unique Sword"}])
        actionB_wrapper = self._create_action_wrapper("playerB", "PICKUP", entities=[{"type": "item", "id": item_id_contested, "name": "Unique Sword"}])

        player_actions_map: Dict[str, List[MockActionWrapper]] = {
            "playerA": [actionA_wrapper],
            "playerB": [actionB_wrapper]
        }
        mock_xp_rules = MagicMock(spec=XPRule)
        if not isinstance(mock_xp_rules, XPRule) and XPRule is not MagicMock:
             mock_xp_rules = XPRule(level_difference_modifier={}, base_xp_per_challenge={})
        current_rules_config = CoreGameRulesConfig(
            checks={}, damage_types={}, xp_rules=mock_xp_rules, loot_tables={},
            action_conflicts=[self.pickup_conflict_def_manual],
            location_interactions={}, base_stats={}, equipment_slots={}, item_effects={}, status_effects={},
            relation_rules=[], relationship_influence_rules=[]
        )
        result = await self.resolver.analyze_actions_for_conflicts(player_actions_map=player_actions_map, guild_id="guild_test", rules_config=current_rules_config)
        self.assertTrue(result["requires_manual_resolution"])
        self.assertEqual(len(result["pending_conflict_details"]), 1)
        self.assertEqual(len(result["auto_resolution_outcomes"]), 0)
        self.assertEqual(len(result["actions_to_execute"]), 0)
        self.assertEqual(actionA_wrapper.status, MockActionStatus.PENDING_MANUAL_RESOLUTION)
        self.assertEqual(actionB_wrapper.status, MockActionStatus.PENDING_MANUAL_RESOLUTION)

    async def test_contested_item_pickup_automatic_resolution_one_winner(self):
        item_id_contested = "unique_gem_1"
        actionC_wrapper = self._create_action_wrapper("playerC", "PICKUP", entities=[{"type": "item", "id": item_id_contested, "name": "Unique Gem"}])
        actionD_wrapper = self._create_action_wrapper("playerD", "PICKUP", entities=[{"type": "item", "id": item_id_contested, "name": "Unique Gem"}])
        player_actions_map: Dict[str, List[MockActionWrapper]] = {
            "playerC": [actionC_wrapper],
            "playerD": [actionD_wrapper]
        }
        mock_xp_rules = MagicMock(spec=XPRule)
        if not isinstance(mock_xp_rules, XPRule) and XPRule is not MagicMock:
            mock_xp_rules = XPRule(level_difference_modifier={}, base_xp_per_challenge={})
        current_rules_config = CoreGameRulesConfig(
            checks={}, damage_types={}, xp_rules=mock_xp_rules, loot_tables={},
            action_conflicts=[self.pickup_conflict_def_auto],
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
        self.assertEqual(actionC_wrapper.status, MockActionStatus.AUTO_RESOLVED_PROCEED)
        self.assertEqual(actionD_wrapper.status, MockActionStatus.AUTO_RESOLVED_FAILED_CONFLICT)
        outcome = result["auto_resolution_outcomes"][0]
        self.assertIn(actionC_wrapper.action_id, outcome["outcome"]["winning_action_ids"])
        self.assertIn(actionD_wrapper.action_id, outcome["outcome"]["losing_action_ids"])

    async def test_simultaneous_attack_auto_resolution_no_winner(self):
        npc_target_id = "goblin_1"
        action_atk1_wrapper = self._create_action_wrapper("playerA", "ATTACK", entities=[{"type": "npc", "id": npc_target_id, "name": "Goblin"}])
        action_atk2_wrapper = self._create_action_wrapper("playerB", "ATTACK", entities=[{"type": "npc", "id": npc_target_id, "name": "Goblin"}])
        player_actions_map: Dict[str, List[MockActionWrapper]] = {
            "playerA": [action_atk1_wrapper],
            "playerB": [action_atk2_wrapper]
        }
        mock_xp_rules = MagicMock(spec=XPRule)
        if not isinstance(mock_xp_rules, XPRule) and XPRule is not MagicMock:
            mock_xp_rules = XPRule(level_difference_modifier={}, base_xp_per_challenge={})
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
        self.assertEqual(action_atk1_wrapper.status, MockActionStatus.AUTO_RESOLVED_FAILED_CONFLICT)
        self.assertEqual(action_atk2_wrapper.status, MockActionStatus.AUTO_RESOLVED_FAILED_CONFLICT)

    async def test_action_not_double_conflicted(self):
        item_id = "relic_xyz"
        action_pickup_p1_wrapper = self._create_action_wrapper("player1", "PICKUP", entities=[{"type": "item", "id": item_id}])
        action_pickup_p2_wrapper = self._create_action_wrapper("player2", "PICKUP", entities=[{"type": "item", "id": item_id}])
        another_pickup_conflict_def = ActionConflictDefinition(
            type="generic_pickup_conflict", # Use type
            involved_intent_pattern=["PICKUP", "TAKE"],
            description="Any pickup action might conflict.",
            resolution_type="manual",
            # priority removed
            manual_resolution_options=["option_generic"]
        )
        mock_xp_rules = MagicMock(spec=XPRule)
        if not isinstance(mock_xp_rules, XPRule) and XPRule is not MagicMock:
            mock_xp_rules = XPRule(level_difference_modifier={}, base_xp_per_challenge={})
        current_rules_config = CoreGameRulesConfig(
            checks={}, damage_types={}, xp_rules=mock_xp_rules, loot_tables={},
            action_conflicts=[self.pickup_conflict_def_manual, another_pickup_conflict_def],
            location_interactions={}, base_stats={}, equipment_slots={}, item_effects={}, status_effects={},
            relation_rules=[], relationship_influence_rules=[]
        )
        player_actions_map: Dict[str, List[MockActionWrapper]] = {
            action_pickup_p1_wrapper.player_id: [action_pickup_p1_wrapper],
            action_pickup_p2_wrapper.player_id: [action_pickup_p2_wrapper]
        }
        result = await self.resolver.analyze_actions_for_conflicts(player_actions_map=player_actions_map, guild_id="guild1", rules_config=current_rules_config)
        self.assertTrue(result["requires_manual_resolution"])
        self.assertEqual(len(result["pending_conflict_details"]), 1)
        self.assertEqual(result["pending_conflict_details"][0]["conflict_type"], self.pickup_conflict_def_manual.type)
        self.assertEqual(action_pickup_p1_wrapper.status, MockActionStatus.PENDING_MANUAL_RESOLUTION)
        self.assertEqual(action_pickup_p2_wrapper.status, MockActionStatus.PENDING_MANUAL_RESOLUTION)

    async def test_non_conflicting_action_passes_through(self):
        item_id_contested = "map_scroll"
        actionP1_pickup_wrapper = self._create_action_wrapper("playerA", "PICKUP", entities=[{"type": "item", "id": item_id_contested}])
        actionP2_pickup_wrapper = self._create_action_wrapper("playerB", "PICKUP", entities=[{"type": "item", "id": item_id_contested}])
        actionP1_move_wrapper = self._create_action_wrapper("playerA", "MOVE", entities=[{"type": "location", "id": "exit_A"}])
        player_actions_map: Dict[str, List[MockActionWrapper]] = {
            actionP1_pickup_wrapper.player_id: [actionP1_pickup_wrapper, actionP1_move_wrapper],
            actionP2_pickup_wrapper.player_id: [actionP2_pickup_wrapper]
        }
        mock_xp_rules = MagicMock(spec=XPRule)
        if not isinstance(mock_xp_rules, XPRule) and XPRule is not MagicMock:
            mock_xp_rules = XPRule(level_difference_modifier={}, base_xp_per_challenge={})
        current_rules_config = CoreGameRulesConfig(
            checks={}, damage_types={}, xp_rules=mock_xp_rules, loot_tables={},
            action_conflicts=[self.pickup_conflict_def_manual],
            location_interactions={}, base_stats={}, equipment_slots={}, item_effects={}, status_effects={},
            relation_rules=[], relationship_influence_rules=[]
        )
        result = await self.resolver.analyze_actions_for_conflicts(player_actions_map=player_actions_map, guild_id="guild_test", rules_config=current_rules_config)
        self.assertTrue(result["requires_manual_resolution"])
        self.assertEqual(len(result["pending_conflict_details"]), 1)
        self.assertEqual(len(result["actions_to_execute"]), 1)
        self.assertIn(actionP1_move_wrapper, result["actions_to_execute"])
        self.assertEqual(actionP1_pickup_wrapper.status, MockActionStatus.PENDING_MANUAL_RESOLUTION)
        self.assertEqual(actionP2_pickup_wrapper.status, MockActionStatus.PENDING_MANUAL_RESOLUTION)
        self.assertEqual(actionP1_move_wrapper.status, MockActionStatus.READY_TO_EXECUTE)

if __name__ == '__main__':
    unittest.main()
