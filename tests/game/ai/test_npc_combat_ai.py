import asyncio
import json
import unittest
from unittest.mock import MagicMock, AsyncMock

from bot.game.ai.npc_combat_ai import NpcCombatAI
from bot.game.models.npc import NPC as NpcModel
from bot.game.models.character import Character as CharacterModel
from bot.game.models.combat import Combat, CombatParticipant
# NpcBehaviorRules, TargetingRule, ActionSelectionRule removed
from bot.ai.rules_schema import CoreGameRulesConfig

class TestNpcCombatAI(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.mock_npc_self = NpcModel(id="npc_ai_1", template_id="t_npc_self", name_i18n={"en": "AI NPC"}, guild_id="guild1", stats={"strength": 10, "dexterity": 12}, health=60, max_health=60)
        setattr(self.mock_npc_self, 'available_actions', [
            {"action_type": "attack", "name": "Basic Attack", "weapon_id": "claws"},
            {"action_type": "spell", "name": "Mini Heal", "spell_id": "heal_self_lvl1", "target_type": "self", "hp_threshold_self": 0.5}
        ])

        self.npc_ai = NpcCombatAI(self.mock_npc_self)

        self.mock_target_char1 = CharacterModel(id="char1", name="Hero", guild_id="guild1", hp=50, max_health=100, stats={"constitution": 10})
        self.mock_target_char2 = CharacterModel(id="char2", name="Sidekick", guild_id="guild1", hp=30, max_health=80, stats={"constitution": 8})
        self.mock_target_npc1 = NpcModel(id="npc_ally1", template_id="t_npc_ally1", name_i18n={"en":"Friendly Goblin"}, guild_id="guild1", health=40, max_health=40, stats={"constitution": 9})


        self.mock_combat_instance = Combat(
            id="combat_test_1", guild_id="guild1", location_id="loc_test", is_active=True,
            participants=[
                CombatParticipant(entity_id="npc_ai_1", entity_type="NPC", hp=60, max_hp=60),
                CombatParticipant(entity_id="char1", entity_type="Character", hp=50, max_hp=100),
                CombatParticipant(entity_id="char2", entity_type="Character", hp=30, max_hp=80),
                CombatParticipant(entity_id="npc_ally1", entity_type="NPC", hp=40, max_hp=40)
            ],
            turn_order=["npc_ai_1", "char1", "char2", "npc_ally1"], current_turn_index=0,
            combat_log=[]
        )

        self.rules_config = CoreGameRulesConfig(
            base_stats={}, equipment_slots={}, checks={}, damage_types={},
            # item_definitions={}, # Assuming ItemDefinition was removed or moved from CoreGameRulesConfig based on other errors
            status_effects={}, xp_rules=None, loot_tables={},
            action_conflicts=[], location_interactions={},
            # npc_behavior_rules field is removed from CoreGameRulesConfig or set to None if optional
            # For this test, assuming the NpcBehaviorRules structure is now directly part of CoreGameRulesConfig
            # or NpcCombatAI is adapted not to need it directly from CoreGameRulesConfig.
            # If NpcCombatAI expects these rules, they should be mocked as direct attributes of CoreGameRulesConfig
            # or passed differently. The error was "cannot import name 'NpcBehaviorRules'",
            # implying it's not used as a type hint for a field in CoreGameRulesConfig anymore,
            # or the field itself was removed.
            # If CoreGameRulesConfig itself is expected to have targeting_rules etc., mock them directly:
            # TargetingRule and ActionSelectionRule are removed, so their instantiations are removed.
            # If NpcCombatAI still needs these, the tests will fail later, requiring updates to NpcCombatAI or mocks.
            targeting_rules=[],
            action_selection_rules=[],
            # scaling_rules=[] # Assuming this might also be a direct field or handled differently
        )

        self.mock_context = {
            "guild_id": "guild1",
            "rule_engine": AsyncMock(),
            "rules_config": self.rules_config,
            "character_manager": AsyncMock(),
            "npc_manager": AsyncMock(),
            "party_manager": AsyncMock(),
            "relationship_manager": AsyncMock(),
            "actor_effective_stats": {"strength": 10, "dexterity": 12, "current_hp": 60, "max_hp": 60},
            "targets_effective_stats": {
                "char1": {"constitution": 10, "current_hp": 50, "max_hp": 100, "_is_hostile_to_actor": True},
                "char2": {"constitution": 8, "current_hp": 30, "max_hp": 80, "_is_hostile_to_actor": True},
                "npc_ally1": {"constitution": 9, "current_hp": 40, "max_hp": 40, "_is_hostile_to_actor": False}
            }
        }

        async def mock_is_hostile_side_effect(actor_entity, target_entity_obj, guild_id):
            # This more closely matches the expected signature if RelationshipManager.is_hostile is used.
            # For this test, we rely on a pre-populated "_is_hostile_to_actor" in targets_effective_stats.
            target_stats = self.mock_context["targets_effective_stats"].get(target_entity_obj.id)
            if target_stats:
                return target_stats.get("_is_hostile_to_actor", False)
            return False

        if self.mock_context["relationship_manager"]:
             # Assuming RelationshipManager might have a method like is_hostile(actor, target, guild_id)
             # The AI code itself uses: relationship_manager.is_hostile(self.npc, target_entity_obj, context.get('guild_id'))
             self.mock_context["relationship_manager"].is_hostile = AsyncMock(side_effect=mock_is_hostile_side_effect)


    def test_no_valid_targets(self): # Changed to sync as get_npc_combat_action is sync
        action = self.npc_ai.get_npc_combat_action(
            combat_instance=self.mock_combat_instance,
            potential_targets=[],
            context=self.mock_context
        )
        self.assertEqual(action["type"], "wait")
        self.assertEqual(action["reason"], "no_valid_target")

    def test_target_lowest_hp_amongst_hostiles(self): # Changed to sync
        potential_targets_list = [self.mock_target_char1, self.mock_target_char2, self.mock_target_npc1]

        # Mock combat_instance.get_participant_data to return HP for sorting
        def get_hp_for_target(entity_id):
            if entity_id == "char1": return MagicMock(hp=50)
            if entity_id == "char2": return MagicMock(hp=30)
            if entity_id == "npc_ally1": return MagicMock(hp=40)
            return MagicMock(hp=0)
        self.mock_combat_instance.get_participant_data = MagicMock(side_effect=get_hp_for_target)

        action = self.npc_ai.get_npc_combat_action(
            combat_instance=self.mock_combat_instance,
            potential_targets=potential_targets_list,
            context=self.mock_context
        )
        self.assertEqual(action["type"], "attack")
        self.assertEqual(action["target_id"], "char2")

    def test_action_selection_heal_if_low_hp(self): # Changed to sync
        self.mock_context["actor_effective_stats"]["current_hp"] = 25
        self.mock_combat_instance.get_participant_data("npc_ai_1").hp = 25

        # Mock get_participant_data for target as well for sorting
        self.mock_combat_instance.get_participant_data = MagicMock(side_effect=lambda entity_id: MagicMock(hp=50) if entity_id == "char1" else MagicMock(hp=25))


        potential_targets_list = [self.mock_target_char1]
        action = self.npc_ai.get_npc_combat_action(
            combat_instance=self.mock_combat_instance,
            potential_targets=potential_targets_list,
            context=self.mock_context
        )
        self.assertEqual(action["type"], "cast_spell")
        self.assertEqual(action["spell_id"], "heal_self_lvl1")
        self.assertEqual(action["target_id"], "npc_ai_1")

    def test_action_selection_default_attack(self): # Changed to sync
        self.mock_context["actor_effective_stats"]["current_hp"] = 60
        self.mock_combat_instance.get_participant_data("npc_ai_1").hp = 60

        # Mock get_participant_data for target as well for sorting
        self.mock_combat_instance.get_participant_data = MagicMock(side_effect=lambda entity_id: MagicMock(hp=50) if entity_id == "char1" else MagicMock(hp=60))

        potential_targets_list = [self.mock_target_char1]
        action = self.npc_ai.get_npc_combat_action(
            combat_instance=self.mock_combat_instance,
            potential_targets=potential_targets_list,
            context=self.mock_context
        )
        self.assertEqual(action["type"], "attack")
        self.assertEqual(action["weapon_id"], "claws")
        self.assertEqual(action["target_id"], "char1")

    def test_no_available_actions_defaults_to_basic_attack(self): # Changed to sync
        setattr(self.mock_npc_self, 'available_actions', [])
        npc_ai_no_actions = NpcCombatAI(self.mock_npc_self)

        # Mock get_participant_data for target as well for sorting
        self.mock_combat_instance.get_participant_data = MagicMock(return_value=MagicMock(hp=50))

        potential_targets_list = [self.mock_target_char1]
        action = npc_ai_no_actions.get_npc_combat_action(
            combat_instance=self.mock_combat_instance,
            potential_targets=potential_targets_list,
            context=self.mock_context
        )
        self.assertEqual(action["type"], "attack")
        self.assertEqual(action.get("weapon_id", "default_npc_weapon"), "default_npc_weapon")
        self.assertEqual(action["target_id"], "char1")

if __name__ == '__main__':
    unittest.main()
